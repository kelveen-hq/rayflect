"""La végétation qui fait de l'ombre : arbres, pergolas végétalisées, plantes grimpantes sur les murs.

UN FEUILLAGE SE DÉCRIT PAR CE QUI SE MESURE. Sa densité est son indice foliaire : la surface de feuilles
au-dessus d'un mètre carré de sol, qui se relève sur le terrain (photographie hémisphérique, capteur de
lumière). La part de soleil qui le traverse en découle par la loi de Beer-Lambert appliquée aux couverts
végétaux [S : Monsi et Saeki, 1953] :

    transparence = exp(− k × indice)        k = 0,7 : la valeur des couverts mesurés en plein soleil

Les branches comptent aussi : un arbre sans feuilles garde un « indice de bois », et c'est lui qui règle
l'ombre d'hiver. Le calendrier dit quand les feuilles sortent et quand elles tombent, et en combien de jours.

Trois objets portent un feuillage :
  - l'ARBRE, dont la couronne est un prisme à 8 pans ;
  - la PERGOLA, un plan horizontal au-dessus des baies ;
  - la plante GRIMPANTE, un plan devant les murs pleins.

LA COURONNE D'UN ARBRE est fermée dessus et dessous. Un rayon qui la traverse coupe 2 de ses faces, et le
moteur multiplie les transparences des faces traversées (vérifié : 2 écrans à 50 % l'un derrière l'autre
laissent passer autant qu'un écran à 25 %). Chaque face reçoit donc la RACINE CARRÉE de la transparence de
la couronne. Une pergola ou une plante grimpante est un seul plan : il porte la transparence entière.

LA CROISSANCE. Une plante se décrit à un âge : `a_l_age` rend la même plante à l'âge demandé, compté depuis la
plantation. Un arbre suit la courbe de son ESSENCE (hauteur et couronne selon l'âge, voir ESSENCES) ; une plante
grimpante monte le long du mur à la vitesse de la sienne (voir GRIMPANTES) et ne couvre que le bas du mur tant
qu'elle n'est pas arrivée en haut. Le calcul reste celui d'UNE année, la plante figée à cet âge : comparer
plusieurs âges, c'est jouer plusieurs scénarios.

Pour les arbres, les pergolas et les grimpantes, seule l'ombre est modélisée, pas la fraîcheur par évaporation. Le
mur végétalisé, lui, compte l'eau que ses modules évaporent (rayflect.evaporation).

À SAVOIR : la méthode rapide de calcul des ombres d'EnergyPlus (par la carte graphique) traite tout masque
comme opaque. Avec de la végétation, `environnement.regler_le_calcul_des_ombres` garde la méthode géométrique.
"""

from __future__ import annotations

import math
from pathlib import Path
from dataclasses import dataclass, replace
from typing import List, Optional, Sequence, Tuple

from rayflect import geometrie

PANS = 8
# LE COEFFICIENT D'EXTINCTION. Pour des feuilles orientées en tous sens, la théorie donne 0,5 divisé par le
# sinus de la hauteur du soleil : 0,5 soleil au zénith, 0,71 à 45°, 1,0 à 30°. Les couverts mesurés en plein
# soleil tournent autour de 0,7 [S : Hirose 2005, Annals of Botany 95, sur la théorie de Monsi et Saeki ;
# 0,3 à 0,5 pour des feuilles dressées, 0,7 à 1,0 pour des feuilles horizontales]. Les façades végétales
# mesurées donnent 0,78 [S : Convertino et al. 2022, cité]. On retient 0,7, sans le faire varier dans la journée.
EXTINCTION = 0.7
JOURS_AVANT_LE_MOIS = (0, 31, 59, 90, 120, 151, 181, 212, 243, 273, 304, 334)


def transparence_depuis_l_indice(indice: float, extinction: float = EXTINCTION) -> float:
    """La part du soleil qui traverse un feuillage d'indice foliaire donné."""
    return math.exp(-extinction * max(0.0, indice))


@dataclass(frozen=True)
class Feuillage:
    nom: str
    indice_foliaire: float                          # surface de feuilles par mètre carré, en pleine feuille
    indice_de_bois: float = 0.0                     # branches et rameaux : ce qui reste l'hiver
    persistant: bool = False
    debut_des_feuilles: Tuple[int, int] = (4, 15)   # [S] forêts françaises : débourrement du 11 au 22 avril...
    fin_des_feuilles: Tuple[int, int] = (10, 31)    # [H] ...jaunissement fini mi-octobre, chute 2 semaines après
    jours_de_feuillaison: int = 21                  # [H] durée de la sortie des feuilles
    jours_de_chute: int = 30                        # [H] durée de la chute

    def __post_init__(self) -> None:
        if self.indice_foliaire < 0 or self.indice_de_bois < 0:
            raise ValueError("un indice foliaire ou de bois ne peut pas être négatif")

    @property
    def transparence_en_feuilles(self) -> float:
        return transparence_depuis_l_indice(self.indice_foliaire + self.indice_de_bois)

    @property
    def transparence_sans_feuilles(self) -> float:
        return transparence_depuis_l_indice(self.indice_de_bois)

    def transparences_de_l_annee(self) -> List[float]:
        """La transparence pour chacun des 365 jours : les feuilles sortent et tombent progressivement."""
        if self.persistant:
            return [self.transparence_en_feuilles] * 365
        debut = JOURS_AVANT_LE_MOIS[self.debut_des_feuilles[0] - 1] + self.debut_des_feuilles[1] - 1
        fin = JOURS_AVANT_LE_MOIS[self.fin_des_feuilles[0] - 1] + self.fin_des_feuilles[1] - 1
        annee = []
        for jour in range(365):
            if jour < debut or jour > fin:
                part = 0.0
            elif jour < debut + self.jours_de_feuillaison:
                part = (jour - debut + 1) / max(1, self.jours_de_feuillaison)
            elif jour > fin - self.jours_de_chute:
                part = (fin - jour) / max(1, self.jours_de_chute)
            else:
                part = 1.0
            annee.append(transparence_depuis_l_indice(self.indice_de_bois + part * self.indice_foliaire))
        return annee


# LE CATALOGUE. Chaque feuillage dit d'où viennent ses indices. [S] lu dans la source, [C] cité par une autre
# source, [H] hypothèse faute de mesure trouvée.
#
# Arbres isolés, mesurés sous la couronne [S : Deak Sjöman et al. 2021, Arboriculture and Urban Forestry
# 47(6), 63 feuillus de 15 à 20 ans, Danemark] : indice de surface végétale en été de 1,93 à 8,15 selon
# l'essence (tilleuls 5,85, poiriers 2,74) ; indice de bois en hiver de 0,32 à 1,94, moyenne 0,91.
# Recoupement par la transparence mesurée [S : Konarska et al. 2014, 5 arbres de rue à Göteborg] : 1,3 à
# 5,3 % du soleil direct en feuilles, 40 à 52 % sans feuilles ; marronnier, tilleul et bouleau nus : 0,56 à
# 0,59 du rayonnement global [S : Larsson 2011]. Avec 0,7 d'extinction, le tilleul du catalogue donne 1,7 %
# et 53 %. Les dates de feuillaison viennent d'essences forestières [S : Lebourgeois et al. 2002, réseau
# RENECOFOR : chêne sessile du 11 avril au 14 octobre, hêtre du 22 avril au 19 octobre] ; aucune date
# trouvée pour les essences de rue.
ARBRE_CADUC_DENSE = Feuillage("arbre caduc à feuillage dense (tilleul, érable)", 4.9, 0.9)             # [S]
ARBRE_CADUC_CLAIR = Feuillage("arbre caduc à feuillage clair (poirier, févier, robinier)", 1.8, 0.9)   # [S]
# Pin noir : 0,22 du rayonnement global toute l'année [S : Larsson 2011], soit un indice de 2,2.
ARBRE_PERSISTANT = Feuillage("arbre persistant (pin noir)", 2.2, 0.0, persistant=True)                # [S]
# Vigne vierge en façade : indice de 3,5 à 4 en été [S : Pérez et al. 2017, Applied Energy 187], 0,9 en
# hiver [C : Pérez et al. 2022].
VIGNE_VIERGE = Feuillage("vigne vierge sur un mur", 2.8, 0.9, debut_des_feuilles=(4, 25))             # [S] et [C]
# Vigne ou glycine sur treille, lierre : aucune mesure trouvée. Valeurs posées par analogie.
VIGNE_OU_GLYCINE = Feuillage("vigne ou glycine sur treille", 3.0, 0.5, debut_des_feuilles=(4, 25))    # [H]
# Platane de rue : indice de 2,0 à 2,7 selon l'âge, par photographie hémisphérique [S : Cailliau 2016, mémoire
# de master, Université de Bayreuth, tableau 8, 103 platanes] ; 2,5 à 2,7 par la surface de feuilles rapportée
# à la couronne [S : Peper et al. 2001, tableau 4, calculé]. Le bois : la moyenne des feuillus mesurés.
# À SAVOIR : la même méthode donne 2,8 au tilleul, là où la mesure sous couronne retenue plus haut donne 5,85.
# Les 2 méthodes ne se recoupent pas ; l'écart entre essences est plus sûr que la valeur de chacune.
PLATANE = Feuillage("platane", 2.3, 0.9)                                                              # [S]
LIERRE = Feuillage("lierre sur un mur", 3.5, 0.0, persistant=True)                                    # [H]
CATALOGUE = (ARBRE_CADUC_DENSE, ARBRE_CADUC_CLAIR, ARBRE_PERSISTANT, PLATANE, VIGNE_OU_GLYCINE, VIGNE_VIERGE,
             LIERRE)


def _entre(points: Tuple[Tuple[float, float], ...], age: float) -> float:
    """La valeur à l'âge donné, entre les points (âge, valeur) d'une courbe. Hors de la courbe : son bord."""
    if age <= points[0][0]:
        return points[0][1]
    for (a0, v0), (a1, v1) in zip(points, points[1:]):
        if age <= a1:
            return v0 + (v1 - v0) * (age - a0) / (a1 - a0)
    return points[-1][1]


@dataclass(frozen=True)
class Essence:
    """Une essence d'arbre : son feuillage, et sa taille selon l'âge depuis la plantation.

    Les courbes sont des points (âge en années, mètres), reliés par des droites. Au-delà du dernier point,
    l'arbre garde sa taille : la courbe ne dit rien de plus que sa source.
    """
    nom: str
    feuillage: Feuillage
    hauteur_m: Tuple[Tuple[float, float], ...]
    couronne_m: Tuple[Tuple[float, float], ...]     # diamètre de la couronne
    source: str

    def __post_init__(self) -> None:
        for courbe in (self.hauteur_m, self.couronne_m):
            ages = [a for a, _v in courbe]
            if len(courbe) < 2 or ages != sorted(set(ages)) or ages[0] != 0 or any(v <= 0 for _a, v in courbe):
                raise ValueError(f"{self.nom} : une courbe part de l'âge 0, à âges croissants et tailles positives")

    @property
    def age_connu_ans(self) -> float:
        return min(self.hauteur_m[-1][0], self.couronne_m[-1][0])


# LES ESSENCES ET LES GRIMPANTES. Remplies plus bas, après les classes qui s'en servent.
ESSENCES: dict = {}
# La base de la couronne des tilleuls de Copenhague est à 20 à 23 % de leur hauteur, de 20 à 100 ans
# [S : Larsen et Kristoffersen 2002, tableau 3, rapport de leurs 2 équations]. Appliqué à toutes les essences [H].
PART_DU_TRONC = 0.22
TRONC_MAX_M = 4.5                       # [H] au-delà, un arbre de rue est élagué à cette hauteur libre


@dataclass(frozen=True)
class Arbre:
    est_m: float                        # position du tronc, en mètres depuis le site
    nord_m: float
    hauteur_m: float = 10.0             # [H] un arbre d'alignement adulte
    diametre_m: float = 6.0             # [H] diamètre de la couronne
    tronc_m: float = 2.5                # [H] hauteur sous couronne
    feuillage: Feuillage = ARBRE_CADUC_DENSE
    essence: Optional[str] = None       # clé de ESSENCES : la taille et le feuillage suivent alors l'âge
    age_ans: Optional[float] = None     # depuis la plantation ; None avec une essence : l'arbre adulte

    def __post_init__(self) -> None:
        if self.age_ans is not None and self.essence is None:
            raise ValueError("un âge sans essence : donner essence, ou la taille de l'arbre à cet âge")
        if self.essence is not None:
            if self.essence not in ESSENCES:
                raise ValueError(f"essence inconnue : « {self.essence} ». Connues : {', '.join(ESSENCES)}")
            if self.age_ans is not None and self.age_ans < 0:
                raise ValueError("un âge ne peut pas être négatif")
            fiche = ESSENCES[self.essence]
            age = fiche.age_connu_ans if self.age_ans is None else self.age_ans
            hauteur = _entre(fiche.hauteur_m, age)
            object.__setattr__(self, "hauteur_m", round(hauteur, 2))
            object.__setattr__(self, "diametre_m", round(_entre(fiche.couronne_m, age), 2))
            object.__setattr__(self, "tronc_m", round(min(TRONC_MAX_M, PART_DU_TRONC * hauteur), 2))
            object.__setattr__(self, "feuillage", fiche.feuillage)
        if not 0.0 < self.tronc_m < self.hauteur_m:
            raise ValueError("la hauteur du tronc doit être entre 0 et la hauteur de l'arbre")
        if self.diametre_m <= 0:
            raise ValueError("le diamètre de la couronne doit être positif")


@dataclass(frozen=True)
class Pergola:
    """Une treille horizontale au-dessus des baies, couverte d'une plante."""
    profondeur_m: float = 3.0           # [H]
    debord_m: float = 0.5               # dépassement de chaque côté de la baie
    feuillage: Feuillage = VIGNE_OU_GLYCINE
    orientations: Optional[Tuple[str, ...]] = ("SE", "S", "SO")


@dataclass(frozen=True)
class Montee:
    """La montée d'une plante grimpante le long d'un mur."""
    vitesse_m_an: float
    hauteur_max_m: float
    source: str


GRIMPANTES: dict = {}                   # par nom de feuillage, rempli plus bas


@dataclass(frozen=True)
class Grimpante:
    """Une plante qui couvre les murs pleins. Les baies restent dégagées."""
    ecart_au_mur_m: float = 0.15        # [H] épaisseur du treillage ou du feuillage
    feuillage: Feuillage = VIGNE_VIERGE
    orientations: Optional[Tuple[str, ...]] = None      # tous les murs
    age_ans: Optional[float] = None     # depuis la plantation ; None : le mur est couvert jusqu'en haut
    hauteur_couverte_m: Optional[float] = None          # depuis le sol ; calculée depuis l'âge si elle est vide

    def __post_init__(self) -> None:
        if self.age_ans is not None:
            if self.age_ans < 0:
                raise ValueError("un âge ne peut pas être négatif")
            if self.hauteur_couverte_m is None:
                montee = GRIMPANTES.get(self.feuillage.nom)
                if montee is None:
                    raise ValueError(f"aucune vitesse de croissance connue pour « {self.feuillage.nom} » : "
                                     f"donner hauteur_couverte_m")
                object.__setattr__(self, "hauteur_couverte_m",
                                   round(min(montee.hauteur_max_m, montee.vitesse_m_an * self.age_ans), 2))


def a_l_age(plante, age_ans: float):
    """La même plante, à l'âge donné depuis sa plantation. Lève ValueError si rien ne dit comment elle pousse."""
    if isinstance(plante, Arbre):
        if plante.essence is None:
            raise ValueError("un arbre sans essence ne grandit pas : donner essence (voir vegetation.ESSENCES)")
        return replace(plante, age_ans=age_ans)
    if isinstance(plante, Grimpante):
        return replace(plante, age_ans=age_ans, hauteur_couverte_m=None)
    raise ValueError(f"la croissance d'une {type(plante).__name__.lower()} n'est pas modélisée : "
                     f"la décrire à l'âge voulu par son feuillage")


def dire(plante) -> List[str]:
    """Ce qu'il faut dire d'une plante dont la taille vient de son âge, avec la source de sa courbe."""
    if isinstance(plante, Arbre) and plante.essence is not None:
        fiche = ESSENCES[plante.essence]
        age = "adulte" if plante.age_ans is None else f"à {plante.age_ans:g} an(s) de la plantation"
        dit = [f"{fiche.nom} {age} : {plante.hauteur_m:g} m de haut, couronne de {plante.diametre_m:g} m "
               f"({fiche.source})"]
        if plante.age_ans is not None and plante.age_ans > fiche.age_connu_ans:
            dit.append(f"{fiche.nom} : la courbe de croissance s'arrête à {fiche.age_connu_ans:g} ans ; au-delà, "
                       f"l'arbre garde la taille de cet âge")
        return dit
    if isinstance(plante, Grimpante) and plante.age_ans is not None:
        montee = GRIMPANTES.get(plante.feuillage.nom)
        source = f" ({montee.source})" if montee else ""
        return [f"{plante.feuillage.nom} à {plante.age_ans:g} an(s) : le mur est couvert jusqu'à "
                f"{plante.hauteur_couverte_m:g} m du sol{source}"]
    return []


def alignement(depart: Tuple[float, float], arrivee: Tuple[float, float], espacement_m: float = 8.0,
               modele: Arbre = Arbre(0.0, 0.0)) -> List[Arbre]:
    """Une rangée d'arbres identiques, de `depart` à `arrivee`, un tous les `espacement_m`."""
    longueur = math.hypot(arrivee[0] - depart[0], arrivee[1] - depart[1])
    n = max(1, int(longueur // espacement_m) + 1)
    pas = (0.0, 0.0) if n == 1 else ((arrivee[0] - depart[0]) / (n - 1), (arrivee[1] - depart[1]) / (n - 1))
    return [replace(modele, est_m=depart[0] + k * pas[0], nord_m=depart[1] + k * pas[1]) for k in range(n)]


def _date(jour: int):
    from ladybug.dt import Date
    mois = max(m for m in range(12) if JOURS_AVANT_LE_MOIS[m] <= jour)
    return Date(mois + 1, jour - JOURS_AVANT_LE_MOIS[mois] + 1)


def calendrier(feuillage: Feuillage, racine: bool, deja: dict):
    """Le calendrier de transparence d'un plan de feuillage, pour EnergyPlus.

    `racine` : vrai pour une face de couronne d'arbre, que le rayon traverse 2 fois. Les jours de même
    transparence, arrondie à 5 % près, sont regroupés en périodes.
    """
    from honeybee_energy.schedule.day import ScheduleDay
    from honeybee_energy.schedule.rule import ScheduleRule
    from honeybee_energy.schedule.ruleset import ScheduleRuleset
    import honeybee_energy.lib.scheduletypelimits as limites

    cle = (feuillage, racine)
    if cle in deja:
        return deja[cle]
    nom = f"feuillage_{len(deja)}"
    annee = [round((math.sqrt(t) if racine else t) * 20.0) / 20.0 for t in feuillage.transparences_de_l_annee()]
    hiver = annee[0]
    regles, debut = [], None
    for jour in range(366):
        valeur = annee[jour] if jour < 365 else None
        if debut is not None and valeur != annee[debut]:
            if annee[debut] != hiver:
                regle = ScheduleRule(ScheduleDay(f"{nom}_du_jour_{debut}", [annee[debut]]),
                                     start_date=_date(debut), end_date=_date(jour - 1))
                regle.apply_all = True
                regles.append(regle)
            debut = None
        if debut is None and valeur is not None:
            debut = jour
    deja[cle] = ScheduleRuleset(nom, ScheduleDay(f"{nom}_hors_saison", [hiver]), regles or None, limites.fractional)
    return deja[cle]


def masques(arbres: Sequence[Arbre], z_du_sol_m: float = 0.0) -> list:
    """La couronne de chaque arbre, en masques Honeybee détachés : 8 pans, un dessus, un dessous."""
    from honeybee.shade import Shade
    from ladybug_geometry.geometry3d import Face3D, Point3D

    ombres, calendriers = [], {}
    for rang, arbre in enumerate(arbres):
        planning = calendrier(arbre.feuillage, True, calendriers)
        rayon = arbre.diametre_m / 2.0
        bas, haut = z_du_sol_m + arbre.tronc_m, z_du_sol_m + arbre.hauteur_m
        tour = [(arbre.est_m + rayon * math.cos(2 * math.pi * k / PANS),
                 arbre.nord_m + rayon * math.sin(2 * math.pi * k / PANS)) for k in range(PANS)]
        faces = {}
        for k, (a, b) in enumerate(zip(tour, tour[1:] + tour[:1])):
            faces[f"pan_{k}"] = [(a[0], a[1], bas), (b[0], b[1], bas), (b[0], b[1], haut), (a[0], a[1], haut)]
        faces["dessus"] = [(x, y, haut) for x, y in tour]
        faces["dessous"] = [(x, y, bas) for x, y in reversed(tour)]
        for nom, points in faces.items():
            ombre = Shade(f"arbre_{rang}_{nom}", Face3D([Point3D(*p) for p in points]), is_detached=True)
            ombre.properties.energy.transmittance_schedule = planning
            ombres.append(ombre)
    return ombres


def _secteur(azimut_deg: float) -> str:
    return ("N", "NE", "E", "SE", "S", "SO", "O", "NO")[int(((azimut_deg + 22.5) % 360.0) // 45.0)]


def _sous(morceaux, z_max: float) -> list:
    """Les morceaux de mur, coupés à l'altitude donnée : ce qui est au-dessus n'est pas encore couvert."""
    from ladybug_geometry.geometry3d import Face3D, Plane, Point3D, Vector3D

    gardes = []
    for morceau in morceaux:
        if morceau.max.z <= z_max + 1e-6:
            gardes.append(morceau)
        elif morceau.min.z < z_max - 0.05:
            coupes = morceau.split_with_plane(Plane(Vector3D(0, 0, 1), Point3D(0, 0, z_max)), 0.01) or []
            gardes += [c for c in coupes if isinstance(c, Face3D) and c.center.z < z_max and c.area > 0.01]
    return gardes


def poser(modele, plante, niveau_le_plus_bas_seulement: bool = False) -> int:
    """Pose une pergola ou une plante grimpante sur le modèle. Rend le nombre de plans de feuillage créés."""
    from honeybee.shade import Shade
    from ladybug_geometry.geometry3d import Vector3D

    planning = calendrier(plante.feuillage, False, {})
    z_bas = min(piece.geometry.min.z for piece in modele.rooms)
    crees = 0
    for piece in modele.rooms:
        if niveau_le_plus_bas_seulement and piece.geometry.min.z > z_bas + 0.1:
            continue
        for face in piece.faces:
            if face.type.name != "Wall" or face.boundary_condition.name != "Outdoors":
                continue
            if plante.orientations is not None and _secteur(face.azimuth) not in plante.orientations:
                continue
            if isinstance(plante, Pergola):
                for baie in face.apertures:
                    avant = {id(o) for o in baie.outdoor_shades}
                    baie.overhang(plante.profondeur_m, base_name=f"{baie.identifier}_pergola")
                    for ombre in baie.outdoor_shades:
                        if id(ombre) not in avant:
                            ombre.properties.energy.transmittance_schedule = planning
                            crees += 1
            elif isinstance(plante, Grimpante):
                normale = face.normal
                decalage = Vector3D(normale.x, normale.y, normale.z) * plante.ecart_au_mur_m
                mur_plein = face.punched_geometry.move(decalage)
                morceaux = mur_plein.split_through_holes() if mur_plein.has_holes else [mur_plein]
                if plante.hauteur_couverte_m is not None:
                    morceaux = _sous(morceaux, z_bas + plante.hauteur_couverte_m)
                # Un mur coupé autour de ses baies donne des morceaux en U : EnergyPlus veut des masques convexes.
                morceaux = [convexe for morceau in morceaux for convexe in geometrie.convexes(morceau)]
                for k, morceau in enumerate(morceaux):
                    ombre = Shade(f"{face.identifier}_grimpante_{k}", morceau, is_detached=True)
                    ombre.properties.energy.transmittance_schedule = planning
                    modele.add_shade(ombre)
                    crees += 1
            else:
                raise TypeError(f"plante inconnue : {type(plante).__name__}")
    return crees


# LE MUR VÉGÉTALISÉ : des modules plantés (bacs, gabions, feutres) sur un support, posés devant le mur. Ce n'est pas
# une plante grimpante : le dos des modules est opaque, et il couvre tout le mur plein, même l'hiver quand les plantes
# perdent leurs feuilles. Tout vient de mesures [S : Weinläder, Reim, Ullerich, Körner et Weismann, « Thermal
# Characterization of Living Wall Systems », EuroSun 2024, ISES, doi 10.18086/eurosun.2024.01.13] :
#   - 4 systèmes en caisson chaud (gabion, bacs, 2 modulaires), tableau 1 : résistance ajoutée au mur de 0,13 à
#     0,18 m².K/W quand la lame d'air arrière est ventilée, comme d'ordinaire (l'équivalent de 4 à 7 mm de polystyrène),
#     de 0,24 à 0,52 m².K/W quand elle est fermée ;
#   - sur façade, les modules sont à 5 cm environ du mur, sans contact, ouverts au vent sur les côtés (§3.1) ;
#   - l'été, au sud, les gains de chaleur par le mur baissent de 38 à 48 % face à un enduit moyen (absorption 0,6),
#     de 5 à 17 % seulement face à un enduit clair (0,24), « surtout par l'ombre » des modules (§3.1, 3.2) ;
#   - l'hiver, les pertes baissent peu face à un enduit moyen, et montent de 16 % pour l'un des systèmes (§3.3) ;
#   - les fixations font des ponts thermiques qui peuvent effacer le gain, non mesurés ici (§4.2, d'après Tudiwer
#     et al. 2019).
# LE MODÈLE : une ombre opaque à 5 cm de chaque mur plein couvert, et la résistance mesurée ajoutée côté extérieur.
# DERRIÈRE LES MODULES, LE MUR NE VOIT PLUS LE CIEL : une ombre d'EnergyPlus arrête le soleil, pas l'échange de
# rayonnement avec le ciel froid des nuits claires, et le mur perdrait trop l'hiver. Chaque mur couvert voit donc le dos
# des modules (SurfaceProperty:SurroundingSurfaces, ciel et sol à 0, le dos des modules à 1), à LEUR TEMPÉRATURE, heure
# par heure : le soleil qu'ils absorbent les chauffe, l'eau qu'ils évaporent les refroidit (rayflect.evaporation, la
# méthode de Hoffmann et al. 2023 validée sur lysimètre). Sans arrosage, le soleil seul.
# CONFRONTÉ AU BANC DE WÜRZBURG (verification/mur_vegetal_wurzburg.py, 24/11/2026) : validé l'hiver, pas l'été, où ses
# gains de chaleur sont sans doute trop forts. Le compte rendu le dit.
# L'HIVER, sur un mur peu isolé et d'absorption 0,6, les pertes par le mur montent (mesuré le 23/11/2026 à Bordeaux,
# mur de U ≈ 0,8 : +51 %) : le mur ne reçoit plus le soleil d'hiver. Weinläder et al. mesurent de −4 à +16 % sur un mur
# très isolé (U = 0,2), où ce soleil compte peu. Les ponts thermiques des fixations ne sont pas comptés.
R_LAME_VENTILEE = 0.155                 # [S] moyenne des 4 systèmes, lame d'air ventilée (0,13 à 0,18)
R_LAME_FERMEE = 0.35                    # [S] moyenne des 4 systèmes, lame d'air fermée (0,24 à 0,52)
ECART_DU_MUR_VEGETAL_M = 0.05           # [S] environ 5 cm


@dataclass(frozen=True)
class MurVegetal:
    """Un mur végétalisé : des modules plantés posés devant les murs pleins des façades visées. Les baies restent."""
    orientations: Optional[Tuple[str, ...]] = None      # tous les murs
    lame_d_air: str = "ventilee"                        # ventilee (l'ordinaire) ou fermee
    systeme: str = "bacs"                               # bacs ou panneaux : le coefficient de l'évaporation
    kc: Optional[float] = None                          # celui d'un système mesuré, à la place
    arrose: bool = True                                 # arrosé d'avril à octobre ; sinon, aucune évaporation
    resistance_m2k_w: Optional[float] = None            # celle d'un système mesuré ; sinon la moyenne de la lame
    ecart_au_mur_m: float = ECART_DU_MUR_VEGETAL_M

    def __post_init__(self) -> None:
        if self.lame_d_air not in ("ventilee", "fermee"):
            raise ValueError("lame_d_air : ventilee ou fermee")
        if self.resistance_m2k_w is not None and not 0.0 < self.resistance_m2k_w <= 2.0:
            raise ValueError("resistance_m2k_w : entre 0 et 2 m².K/W")
        if not 0.0 < self.ecart_au_mur_m <= 0.5:
            raise ValueError("ecart_au_mur_m : entre 0 et 0,5 m")
        from rayflect import evaporation
        if self.systeme not in evaporation.KC:
            raise ValueError(f"systeme : {', '.join(evaporation.KC)}")
        if self.kc is not None and not 0.0 <= self.kc <= 3.0:
            raise ValueError("kc : entre 0 et 3")

    @property
    def coefficient(self) -> float:
        from rayflect import evaporation
        return self.kc if self.kc is not None else evaporation.KC[self.systeme]

    @property
    def resistance(self) -> float:
        if self.resistance_m2k_w is not None:
            return self.resistance_m2k_w
        return R_LAME_VENTILEE if self.lame_d_air == "ventilee" else R_LAME_FERMEE


def poser_le_mur_vegetal(modele, mur: MurVegetal) -> List[str]:
    """Couvre les murs pleins visés : une ombre opaque devant, la résistance des modules ajoutée. Rend ce qu'il faut dire."""
    from honeybee.shade import Shade
    from honeybee_energy.construction.opaque import OpaqueConstruction
    from honeybee_energy.material.opaque import EnergyMaterialNoMass
    from ladybug_geometry.geometry3d import Vector3D

    lame = EnergyMaterialNoMass(f"modules_vegetaux_{mur.resistance:g}", mur.resistance)
    couverte, faites = 0.0, {}
    for piece in modele.rooms:
        for face in piece.faces:
            if face.type.name != "Wall" or face.boundary_condition.name != "Outdoors":
                continue
            if mur.orientations is not None and _secteur(face.azimuth) not in mur.orientations:
                continue
            normale = face.normal
            plein = face.punched_geometry.move(Vector3D(normale.x, normale.y, normale.z) * mur.ecart_au_mur_m)
            morceaux = plein.split_through_holes() if plein.has_holes else [plein]
            for k, morceau in enumerate(convexe for m in morceaux for convexe in geometrie.convexes(m)):
                modele.add_shade(Shade(f"{face.identifier}_mur_vegetal_{k}", morceau, is_detached=True))
            couverte += face.punched_geometry.area
            face.user_data = {**(face.user_data or {}), "mur_vegetal": True, "kc": mur.coefficient, "arrose": mur.arrose}
            avant = face.properties.energy.construction
            if avant.identifier not in faites:
                faites[avant.identifier] = OpaqueConstruction(f"{avant.identifier}_mur_vegetal", [lame] + list(avant.materials))
            face.properties.energy.construction = faites[avant.identifier]
    lame_d_air = 'ventilée' if mur.lame_d_air == 'ventilee' else 'fermée'
    return [f"mur végétalisé : {couverte:.0f} m² de murs pleins couverts"
            + (f" ({', '.join(mur.orientations)})" if mur.orientations else "")
            + f", modules à {mur.ecart_au_mur_m * 100:g} cm du mur, lame d'air {lame_d_air}, "
            f"{mur.resistance:g} m².K/W ajoutés [S : Weinläder et al., EuroSun 2024, caisson chaud]",
            "mur végétalisé : ombre opaque des modules, toute l'année ; le mur voit leur dos, chauffé par le soleil et "
            + (f"refroidi par l'eau évaporée d'avril à octobre (coefficient {mur.coefficient:g}, {mur.systeme}) [S : Hoffmann "
               f"et al. 2023]" if mur.arrose else "sans arrosage, donc sans évaporation")
            + " ; les ponts thermiques des fixations ne sont pas comptés",
            "mur végétalisé, À SAVOIR : confronté au banc de Würzburg, le modèle tient l'hiver mais pas l'été, où il "
            "donne sans doute au mur plus de chaleur que les mesures (verification/mur_vegetal_wurzburg.py)"]


AIR_DEHORS = "rayflect_air_dehors"


def _modules_par_facade(modele, epw) -> dict:
    """Par (azimut arrondi, coefficient, arrosé) : la température des modules et l'eau évaporée, heure par heure."""
    from rayflect import evaporation

    rendu = {}
    for face in modele.faces:
        donnees = face.user_data or {}
        if not donnees.get("mur_vegetal"):
            continue
        cle = (round(face.azimuth) % 360, donnees.get("kc", 0.0), donnees.get("arrose", False))
        if cle not in rendu:
            rendu[cle] = evaporation.modules(epw, cle[0], cle[1], cle[2])
    return rendu


def texte_des_murs_vegetaux(modele, epw, dossier) -> str:
    """Pour EnergyPlus : chaque mur couvert de modules voit leur dos, à leur température, heure par heure.

    La température des modules (rayflect.evaporation) est écrite dans `dossier`, un fichier .csv par façade : EnergyPlus ne
    lit un calendrier que dans un fichier .csv. Rien si aucun mur n'est couvert."""
    par_facade = _modules_par_facade(modele, epw)
    if not par_facade:
        return ""
    texte, calendriers = "", {}
    for n, (cle, (temperatures, _eau)) in enumerate(par_facade.items()):
        fichier = Path(dossier) / f"modules_{n}.csv"
        fichier.write_text("\n".join(f"{t:.2f}" for t in temperatures) + "\n", encoding="ascii")
        calendriers[cle] = f"{AIR_DEHORS}_{n}"
        # Le nom seul : EnergyPlus cherche dans son dossier de travail, celui du scénario. Un chemin complet qui porte un
        # accent (« mur_végétal ») ne s'ouvre pas.
        texte += f"\nSchedule:File,\n  {calendriers[cle]}, , {fichier.name}, 1, 0, 8760, Comma, No, 60;\n"
    k = 0
    for face in modele.faces:
        donnees = face.user_data or {}
        if not donnees.get("mur_vegetal"):
            continue
        calendrier_ = calendriers[(round(face.azimuth) % 360, donnees.get("kc", 0.0), donnees.get("arrose", False))]
        texte += (f"\nSurfaceProperty:SurroundingSurfaces,\n  dos_des_modules_{k}, 0.0, , 0.0, , dos_des_modules, 1.0, "
                  f"{calendrier_};\n"
                  f"\nSurfaceProperty:LocalEnvironment,\n  modules_devant_{k}, {face.identifier}, , dos_des_modules_{k}, , ;\n")
        k += 1
    return texte


def dire_l_eau_des_murs(modele, epw) -> List[str]:
    """Ce que le compte rendu dit de l'eau évaporée, façade par façade."""
    from rayflect import evaporation

    lignes = []
    for (azimut, _kc, arrose), (_t, eau) in _modules_par_facade(modele, epw).items():
        if arrose:
            lignes.append(f"mur végétalisé, façade {_secteur(azimut)} : {evaporation.dire_l_eau(eau)}")
    return lignes


# LA CROISSANCE DES ARBRES DE VILLE.
#
# L'ÂGE SE COMPTE DEPUIS LA PLANTATION. Un arbre d'alignement est planté à 10 ans environ : une circonférence
# de tronc de 18 à 20 cm « correspond à 10 ans » [S : Larsen et Kristoffersen 2002, Journal of Arboriculture
# 28(5), 331 tilleuls de Copenhague, âges tirés des registres de plantation]. Les courbes des sources, données
# en âge de l'arbre, sont décalées de ces 10 ans.
AGE_A_LA_PLANTATION_ANS = 10

# Bavière : moyennes par classe d'âge de 10 à 100 ans, environ 2 000 arbres mesurés dans 6 villes [S : Rötzer,
# Reischl, Rahman, Pretzsch et Pauleit 2021, « Leitfaden zu Stadtbäumen in Bayern », TU München, tableau 6].
# RÉSERVE DE LA SOURCE : l'âge n'y est pas relevé, il est estimé depuis le diamètre du tronc.
_BAVIERE = "Rötzer et al. 2021, tableau 6, arbres de rue de 6 villes de Bavière ; âge estimé depuis le tronc"
_AGES = (0, 10, 20, 30, 40, 50, 70, 90)


def _courbe(valeurs):
    return tuple(zip(_AGES, valeurs))


def _copenhague(b1: float, b2: float, fois: float = 1.0):
    """Y = b1 × âge + b2 × âge², l'âge de l'arbre en années [S : Larsen et Kristoffersen 2002, tableau 3]."""
    return tuple((age, round(fois * (b1 * (age + AGE_A_LA_PLANTATION_ANS) + b2 * (age + AGE_A_LA_PLANTATION_ANS) ** 2), 2))
                 for age in _AGES)


ESSENCES.update({
    "tilleul": Essence(
        "tilleul à petites feuilles", ARBRE_CADUC_DENSE,
        _courbe((5.8, 8.6, 11.1, 13.3, 15.3, 17.2, 20.7, 23.9)),
        _courbe((3.3, 5.1, 6.9, 8.6, 10.3, 11.9, 15.0, 18.0)), _BAVIERE),
    # Le même tilleul pousse moins vite à Copenhague : 6,9 m à 20 ans d'arbre, contre 8,6 m en Bavière. Les 2
    # courbes encadrent ce qu'on peut attendre ; aucune des 2 ne vient de France.
    "tilleul_lent": Essence(
        "tilleul, croissance lente", ARBRE_CADUC_DENSE,
        _copenhague(0.3846, -0.0019), _copenhague(0.1257, -0.0005, fois=2.0),
        "Larsen et Kristoffersen 2002, tableau 3, tilleuls de Copenhague non ombrés, âges des registres"),
    "robinier": Essence(
        "robinier", ARBRE_CADUC_CLAIR,
        _courbe((9.3, 12.1, 14.2, 15.8, 17.3, 18.6, 20.9, 22.8)),
        _courbe((5.0, 7.0, 8.7, 10.2, 11.5, 12.7, 14.9, 16.9)), _BAVIERE),
    "platane": Essence(
        "platane", PLATANE,
        _courbe((8.6, 11.2, 14.4, 17.2, 19.5, 21.6, 22.2, 29.0)),
        _courbe((4.3, 7.3, 10.4, 12.3, 14.3, 15.7, 19.1, 20.4)), _BAVIERE),
})
# CE QUI N'EST PAS MODÉLISÉ. L'indice foliaire garde sa valeur à tout âge. Une seule mesure par classe d'âge a
# été trouvée [S : Cailliau 2016, tableau 8] : il double chez le tilleul entre moins de 20 ans et 60 à 80 ans
# (1,7 à 3,6), ne bouge pas chez le platane ni le marronnier, et l'autrice juge ses régressions très faibles.
# Un jeune tilleul fait donc sans doute une ombre moins dense que celle calculée ici.
# Érable, févier, pin : aucune courbe de croissance lue, ils ne sont pas au catalogue.

# LA MONTÉE DES PLANTES GRIMPANTES. Ce sont des ordres de grandeur d'horticulture, pas des mesures sur façade.
GRIMPANTES.update({
    # 1 à 2 m par an [S : fassadengruen.de, fiche de la vigne vierge de Veitch, source commerciale] ; plus de
    # 12 m en 5 à 10 ans [S : Royal Horticultural Society, fiche de l'espèce] ; 15 à 20 m [S : BUND 2024].
    VIGNE_VIERGE.nom: Montee(1.5, 15.0, "1 à 2 m par an, fassadengruen.de ; hauteur, RHS et BUND 2024"),
    # Aucune vitesse lue. 8 à 12 m atteints en 10 à 20 ans [S : Royal Horticultural Society], soit 0,4 à 1,2 m
    # par an : le milieu est retenu [C].
    LIERRE.nom: Montee(0.7, 12.0, "8 à 12 m en 10 à 20 ans, RHS ; vitesse déduite"),
    # Vigne : 8 à 10 m [S : BUND 2024], hauteur finale en 5 à 10 ans [S : Royal Horticultural Society], soit
    # 0,8 à 2 m par an : le milieu est retenu [C]. La glycine monte plus haut et plus vite ; non distinguée.
    VIGNE_OU_GLYCINE.nom: Montee(1.3, 10.0, "8 à 10 m, BUND 2024, en 5 à 10 ans, RHS ; vitesse déduite"),
})
