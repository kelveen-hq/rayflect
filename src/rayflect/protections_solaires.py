"""Les protections solaires, paramétrables, à poser sur un modèle Honeybee.

Chaque protection est une petite fiche de paramètres avec des valeurs par défaut, et dit sur quelles
orientations elle se pose. `poser(modele, protection)` l'applique à toutes les baies concernées.

Les valeurs par défaut sont des points de départ raisonnables, marqués [H] quand elles ne viennent d'aucune
source : elles sont faites pour être changées.

Protections fixes : Casquette, Joues, LamesHorizontales, LamesVerticales.
Protections à 2 positions selon la saison : LamesSaisonnieres (de grandes lames motorisées qu'on efface ou
qu'on réoriente l'hiver pour laisser entrer le soleil).
Protections pilotées sur le besoin : LamesPilotees, les mêmes grandes lames, en place quand la pièce est
chaude et effacées sinon. EnergyPlus prend la décision à chaque pas de temps, sur la température que la
pièce a réellement avec ses lames.
Protections mobiles devant la vitre : BSO, avec 4 pilotages.

Limite du moteur : EnergyPlus ne déplace pas une géométrie pendant le calcul. Une protection à 2 positions
est donc décrite 2 fois, chaque jeu de lames n'existant que pendant sa saison.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Tuple, Union

from honeybee_energy.construction.shade import ShadeConstruction
from honeybee_energy.construction.windowshade import WindowConstructionShade
from honeybee_energy.material.shade import EnergyWindowMaterialBlind
from honeybee_energy.schedule.day import ScheduleDay
from honeybee_energy.schedule.rule import ScheduleRule
from honeybee_energy.schedule.ruleset import ScheduleRuleset
import honeybee_energy.lib.scheduletypelimits as limites
from ladybug.dt import Date
from ladybug_geometry.geometry2d import Vector2D

SECTEURS = ("N", "NE", "E", "SE", "S", "SO", "O", "NO")
TOUTES = None
COTE_SOLEIL = ("E", "SE", "S", "SO", "O")
SUD = ("SE", "S", "SO")
EST_OUEST = ("NE", "E", "SE", "SO", "O", "NO")


def secteur(azimut_deg: float) -> str:
    return SECTEURS[int(((azimut_deg + 22.5) % 360.0) // 45.0)]


@dataclass(frozen=True)
class Casquette:
    """Un débord horizontal au-dessus de la baie."""
    profondeur_m: float = 0.8           # [H] environ la moitié de la hauteur d'une baie courante
    inclinaison_deg: float = 0.0        # positif : la casquette penche vers le bas
    orientations: Optional[Tuple[str, ...]] = SUD


@dataclass(frozen=True)
class Joues:
    """Deux retours verticaux, de chaque côté de la baie."""
    profondeur_m: float = 0.5           # [H]
    orientations: Optional[Tuple[str, ...]] = EST_OUEST


@dataclass(frozen=True)
class LamesHorizontales:
    """Des lames horizontales fixes devant la baie, du linteau à l'appui."""
    profondeur_m: float = 0.30          # [H]
    entraxe_m: float = 0.30             # [H] autant de vide que de lame : coupe le soleil au-dessus de 45°
    inclinaison_deg: float = 0.0        # positif : la lame penche vers le bas
    ecart_a_la_vitre_m: float = 0.10
    orientations: Optional[Tuple[str, ...]] = SUD


@dataclass(frozen=True)
class LamesVerticales:
    """Des lames verticales fixes devant la baie : le brise-soleil des façades est et ouest."""
    profondeur_m: float = 0.40          # [H]
    entraxe_m: float = 0.40             # [H]
    angle_deg: float = 0.0              # 0 : perpendiculaires à la façade
    ecart_a_la_vitre_m: float = 0.10
    orientations: Optional[Tuple[str, ...]] = EST_OUEST


@dataclass(frozen=True)
class LamesSaisonnieres:
    """De grandes lames motorisées à 2 positions : une pour la saison chaude, une pour la saison froide.

    `hiver` None : les lames sont effacées l'hiver (relevées, ou tournées dans le fil du soleil).
    """
    ete: Union[LamesHorizontales, LamesVerticales] = LamesHorizontales(0.60, 0.60)
    hiver: Optional[Union[LamesHorizontales, LamesVerticales]] = None
    debut_saison_chaude: Tuple[int, int] = (5, 1)       # [H] du 1er mai...
    fin_saison_chaude: Tuple[int, int] = (9, 30)        # [H] ...au 30 septembre
    orientations: Optional[Tuple[str, ...]] = COTE_SOLEIL


@dataclass(frozen=True)
class LamesPilotees:
    """De grandes lames motorisées, en place quand la pièce est chaude, effacées sinon.

    Elles sont décrites à EnergyPlus comme un store à lames posé devant la vitre, avec de grandes lames :
    c'est sa façon native de décrire une protection qui se manœuvre, et c'est lui qui la commande à chaque
    pas de temps sur la température réelle de la pièce. Les lames sont supposées couvrir toute la baie.
    Limites d'EnergyPlus : lame de 1 m au plus, à 1 m de la vitre au plus, pas d'hystérésis.
    """
    lames: Union[LamesHorizontales, LamesVerticales] = LamesHorizontales(0.60, 0.60)
    seuil_chaleur_c: float = 24.0       # [H] au-dessus, les lames se mettent en place
    reflexion_lames: float = 0.3        # [H] la même que les lames fixes
    orientations: Optional[Tuple[str, ...]] = COTE_SOLEIL


@dataclass(frozen=True)
class BSO:
    """Un brise-soleil orientable extérieur, devant la vitre.

    pilotage :
      « chaleur »  baissé quand la pièce dépasse `seuil_chaleur_c` (défaut : ne prive pas du soleil d'hiver) ;
      « soleil »   baissé quand le soleil sur la vitre dépasse `seuil_soleil_w_m2`, été comme hiver ;
      « toujours » toujours baissé ;
      « occupants » manœuvré à la main : voir `rayflect.bso_occupants`.
    """
    pilotage: str = "chaleur"
    seuil_chaleur_c: float = 24.0       # [H]
    seuil_soleil_w_m2: float = 150.0    # [S] EN 15232, gestion technique de classe B
    angle_lames_deg: float = 45.0       # [S] EN 14501, position d'essai lames à 45°
    reflexion_lames: float = 0.5        # [H] lames de teinte moyenne
    orientations: Optional[Tuple[str, ...]] = COTE_SOLEIL


PILOTAGES_BSO = {"chaleur": "OnIfHighZoneAirTemperature", "soleil": "OnIfHighSolarOnWindow", "toujours": "AlwaysOn"}
OPAQUE = ShadeConstruction("lame_opaque", 0.3, 0.3)     # [H] lame qui renvoie 30 % du soleil


def _concernees(modele, orientations):
    for baie in modele.apertures:
        if orientations is None or secteur(baie.azimuth) in orientations:
            yield baie


def _saison(nom: str, debut, fin, pendant: float, hors: float) -> ScheduleRuleset:
    """Un calendrier de transparence : `pendant` entre les 2 dates, `hors` le reste de l'année."""
    jour_pendant = ScheduleDay(f"{nom}_pendant", [pendant])
    regle = ScheduleRule(jour_pendant, start_date=Date(*debut), end_date=Date(*fin))
    regle.apply_all = True
    return ScheduleRuleset(nom, ScheduleDay(f"{nom}_hors", [hors]), [regle], limites.fractional)


def _lames(baie, fiche, calendrier=None, suffixe: str = ""):
    verticales = isinstance(fiche, LamesVerticales)
    angle = fiche.angle_deg if verticales else -fiche.inclinaison_deg
    avant = set(id(o) for o in baie.outdoor_shades)
    baie.louvers_by_distance_between(
        fiche.entraxe_m, fiche.profondeur_m, fiche.ecart_a_la_vitre_m, angle,
        Vector2D(1, 0) if verticales else Vector2D(0, 1),
        base_name=f"{baie.identifier}_lame{suffixe}")
    for ombre in baie.outdoor_shades:
        if id(ombre) not in avant:
            ombre.properties.energy.construction = OPAQUE
            if calendrier is not None:
                ombre.properties.energy.transmittance_schedule = calendrier


def poser(modele, protection, contexte: Optional[dict] = None) -> int:
    """Pose la protection sur les baies des orientations qu'elle vise. Rend le nombre de baies équipées."""
    if isinstance(protection, (Balcon, Toit, PhotovoltaiqueEnToiture)):
        return _poser_sur_l_enveloppe(modele, protection)
    if not isinstance(protection, (Casquette, Joues, LamesHorizontales, LamesVerticales, LamesSaisonnieres,
                                   LamesPilotees, BSO)):
        raise TypeError(f"protection inconnue : {type(protection).__name__}")
    baies = list(_concernees(modele, protection.orientations))
    if isinstance(protection, Casquette):
        for baie in baies:
            baie.overhang(protection.profondeur_m, protection.inclinaison_deg)
    elif isinstance(protection, Joues):
        for baie in baies:
            baie.left_fin(protection.profondeur_m)
            baie.right_fin(protection.profondeur_m)
    elif isinstance(protection, (LamesHorizontales, LamesVerticales)):
        for baie in baies:
            _lames(baie, protection)
    elif isinstance(protection, LamesSaisonnieres):
        chaud = _saison("lames_saison_chaude", protection.debut_saison_chaude, protection.fin_saison_chaude, 0.0, 1.0)
        froid = _saison("lames_saison_froide", protection.debut_saison_chaude, protection.fin_saison_chaude, 1.0, 0.0)
        for baie in baies:
            _lames(baie, protection.ete, chaud, "_ete")
            if protection.hiver is not None:
                _lames(baie, protection.hiver, froid, "_hiver")
    elif isinstance(protection, LamesPilotees):
        fiche = protection.lames
        verticales = isinstance(fiche, LamesVerticales)
        tourne = fiche.angle_deg if verticales else fiche.inclinaison_deg
        lames = EnergyWindowMaterialBlind(
            f"grandes_lames_{id(protection)}", "Vertical" if verticales else "Horizontal",
            slat_width=min(fiche.profondeur_m, 1.0), slat_separation=min(fiche.entraxe_m, 1.0),
            slat_thickness=0.005, slat_angle=90.0 - tourne,
            solar_reflectance=protection.reflexion_lames, visible_reflectance=protection.reflexion_lames,
            distance_to_glass=min(1.0, fiche.ecart_a_la_vitre_m + fiche.profondeur_m / 2.0))
        construit = {}
        for baie in baies:
            vitrage = baie.properties.energy.construction
            if vitrage.identifier not in construit:
                construit[vitrage.identifier] = WindowConstructionShade(
                    f"{vitrage.identifier}_grandes_lames", vitrage, lames, "Exterior",
                    "OnIfHighZoneAirTemperature", protection.seuil_chaleur_c)
            baie.properties.energy.construction = construit[vitrage.identifier]
    elif isinstance(protection, BSO):
        if protection.pilotage == "occupants":
            from . import bso_occupants, hypotheses
            contexte = contexte or {}
            usage = hypotheses.USAGES[contexte.get("usage", "bureau")]
            contexte["bilan_bso_manuels"] = bso_occupants.poser(
                modele, contexte["epw"], usage, usage.nom == "logement", contexte.get("temperatures"),
                orientations=protection.orientations)
            return len(baies)
        lames = EnergyWindowMaterialBlind(
            "lames_bso", slat_angle=protection.angle_lames_deg,
            solar_reflectance=protection.reflexion_lames, visible_reflectance=protection.reflexion_lames)
        seuil = {"chaleur": protection.seuil_chaleur_c, "soleil": protection.seuil_soleil_w_m2,
                 "toujours": None}[protection.pilotage]
        construit = {}
        for baie in baies:
            vitrage = baie.properties.energy.construction
            if vitrage.identifier not in construit:
                construit[vitrage.identifier] = WindowConstructionShade(
                    f"{vitrage.identifier}_bso", vitrage, lames, "Exterior",
                    PILOTAGES_BSO[protection.pilotage], seuil)
            baie.properties.energy.construction = construit[vitrage.identifier]
    else:
        raise TypeError(f"protection inconnue : {type(protection).__name__}")
    return len(baies)


# ─────────────────────────────── L'enveloppe : balcons, toit, photovoltaïque ───────────────────────────────

@dataclass(frozen=True)
class Balcon:
    """Un balcon filant : la dalle de l'étage du dessus déborde de la façade et ombre les baies du dessous."""
    profondeur_m: float = 1.5           # [H]
    orientations: Optional[Tuple[str, ...]] = COTE_SOLEIL


# L'absorption solaire d'une toiture : la part du soleil qu'elle transforme en chaleur (1 − réflectance).
# Valeurs par défaut réglementaires françaises [S : règles Th-Bât, fascicule Parois opaques, tableau XIV] :
# clair 0,4 ; moyen 0,6 ; sombre 0,8 ; noir 1,0.
# Matériaux mesurés, en réflectance [S : California Air Resources Board, comparatif de toitures] : membrane
# ou revêtement noir 0,05 ; bitume à surface minérale 0,10 à 0,20 ; tuile terre cuite rouge 0,40 à 0,50 ;
# membrane ou revêtement blanc neuf 0,70 à 0,85. Ardoise et zinc : aucune mesure trouvée.
# Vieillissement [S : Sleiman et al. 2011, Solar Energy Materials and Solar Cells 95] : après 3 ans,
# réflectance = 0,20 + β × (réflectance neuve − 0,20), β = 0,76 pour un revêtement appliqué sur chantier,
# 0,79 à 0,82 pour une membrane. En ville en Europe, la perte est atteinte en 1 à 2 ans [S : Paolini et al.,
# membrane à 0,85 neuve tombée à 0,62 après 1 an à Milan].
TOIT_NOIR = 0.95                        # [S] membrane ou revêtement noir
TOIT_SOMBRE = 0.80                      # [S] Th-Bât, couleur sombre
TOIT_COURANT = 0.60                     # [S] Th-Bât, couleur moyenne
TOIT_CLAIR_VIEILLI = 0.35               # [S] revêtement blanc de 0,80 neuf, après 3 ans (formule de Sleiman)
TOIT_CLAIR_NEUF = 0.20                  # [S] revêtement ou membrane blanc neuf


def absorption_apres_3_ans(absorption_neuve: float, beta: float = 0.76) -> float:
    """L'absorption d'un revêtement de toit après 3 ans d'encrassement, d'après la formule de Sleiman."""
    return 1.0 - (0.20 + beta * ((1.0 - absorption_neuve) - 0.20))


@dataclass(frozen=True)
class Toit:
    """La couleur du toit. Un toit clair chauffe moins l'été, et capte moins de soleil l'hiver."""
    absorption_solaire: float = TOIT_CLAIR_VIEILLI

    def __post_init__(self) -> None:
        if not 0.0 < self.absorption_solaire <= 1.0:
            raise ValueError("l'absorption solaire est une part, entre 0 et 1")


@dataclass(frozen=True)
class PhotovoltaiqueEnToiture:
    """Des panneaux posés au-dessus du toit. Ils produisent, et ils font de l'ombre au toit toute l'année."""
    couverture: float = 0.5             # part de la surface du toit couverte de panneaux [H]
    hauteur_m: float = 0.3              # lame d'air entre le toit et les panneaux [H]
    rendement: float = 0.20             # [H] module courant
    pertes_du_systeme: float = 0.14     # câbles, onduleur, salissure : la valeur par défaut de PVWatts [S]

    def __post_init__(self) -> None:
        if not 0.0 < self.couverture <= 1.0:
            raise ValueError("la couverture est une part du toit, entre 0 et 1")


PRODUCTION_PHOTOVOLTAIQUE = "Generator Produced DC Electricity Energy"


def _toits(modele):
    for piece in modele.rooms:
        for face in piece.faces:
            if face.type.name == "RoofCeiling" and face.boundary_condition.name == "Outdoors":
                yield face


def _poser_sur_l_enveloppe(modele, protection) -> int:
    from honeybee.shade import Shade
    from honeybee_energy.generator.pv import PVProperties
    from ladybug_geometry.geometry3d import Face3D, Point3D, Vector3D

    poses = 0
    if isinstance(protection, Balcon):
        for piece in modele.rooms:
            for face in piece.faces:
                if face.type.name != "Wall" or face.boundary_condition.name != "Outdoors" or not face.apertures:
                    continue
                if protection.orientations is not None and secteur(face.azimuth) not in protection.orientations:
                    continue
                haut = max(p.z for p in face.geometry.vertices)
                bord = sorted({(round(p.x, 4), round(p.y, 4)) for p in face.geometry.vertices if abs(p.z - haut) < 0.01})
                if len(bord) < 2:
                    continue
                (x1, y1), (x2, y2) = bord[0], bord[-1]
                n = face.normal
                dalle = Face3D([Point3D(x1, y1, haut), Point3D(x2, y2, haut),
                                Point3D(x2 + n.x * protection.profondeur_m, y2 + n.y * protection.profondeur_m, haut),
                                Point3D(x1 + n.x * protection.profondeur_m, y1 + n.y * protection.profondeur_m, haut)])
                ombre = Shade(f"{face.identifier}_balcon", dalle, is_detached=True)
                ombre.properties.energy.construction = OPAQUE
                modele.add_shade(ombre)
                poses += 1
    elif isinstance(protection, Toit):
        refaits = {}
        for face in _toits(modele):
            construction = face.properties.energy.construction
            if construction.identifier not in refaits:
                nouvelle = construction.duplicate()
                nouvelle.identifier = f"{construction.identifier}_absorption_{int(round(protection.absorption_solaire * 100))}"
                dehors = nouvelle.materials[0].duplicate()
                dehors.identifier = f"{dehors.identifier}_absorption_{int(round(protection.absorption_solaire * 100))}"
                dehors.solar_absorptance = protection.absorption_solaire
                nouvelle.materials = [dehors] + list(nouvelle.materials[1:])
                refaits[construction.identifier] = nouvelle
            face.properties.energy.construction = refaits[construction.identifier]
            poses += 1
    elif isinstance(protection, PhotovoltaiqueEnToiture):
        echelle = protection.couverture ** 0.5
        for rang, face in enumerate(_toits(modele)):
            panneau = face.geometry.scale(echelle, face.geometry.center).move(Vector3D(0, 0, protection.hauteur_m))
            if panneau.normal.z < 0:
                panneau = panneau.flip()
            ombre = Shade(f"photovoltaique_{rang}", panneau, is_detached=True)
            ombre.properties.energy.construction = ShadeConstruction("panneau_photovoltaique", 0.1, 0.1)
            ombre.properties.energy.pv_properties = PVProperties(
                f"photovoltaique_{rang}", protection.rendement, 0.9, "Standard", "FixedRoofMounted",
                protection.pertes_du_systeme)
            modele.add_shade(ombre)
            poses += 1
    return poses
