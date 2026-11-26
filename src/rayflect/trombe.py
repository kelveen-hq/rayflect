"""Le mur Trombe : un mur lourd et sombre derrière une vitre, qui rend le soir le soleil de la journée.

Le soleil traverse la vitre et chauffe le mur ; la chaleur arrive dans la pièce quelques heures plus tard, par
conduction. Un scénario porte un élément `mur_trombe` : sur les façades visées, la bande de mur sous les
fenêtres (l'allège) devient ce mur, sur toute la longueur de la façade. Une façade sans fenêtre peut être prise
sur une plus grande hauteur, jusqu'à 10 cm du haut du mur. Un seul élément par scénario.

CE QUE CALCULE ENERGYPLUS. Il n'a pas d'objet « mur Trombe ». La lame d'air entre la vitre et le mur est une
zone très étroite, dont la convection est réglée sur l'algorithme `TrombeWall` (lame verticale fermée, norme
ISO 15099). Le soleil doit être suivi jusqu'au mur (`FullInteriorAndExterior`, avec ou sans reflets selon le
réglage de l'étude) : dès qu'un scénario de l'étude porte un mur Trombe, tous ses scénarios sont calculés ainsi,
pour rester comparables.

CE QUI NE DOIT PAS CHANGER AVEC LE MUR. La pièce garde son volume et ses fuites d'air : le mur d'origine n'est
raccourci que dans le fichier d'EnergyPlus (`retoucher`), et le débit de fuite par mètre carré de paroi est
relevé d'autant que l'allège quitte la pièce. Sans cela, le mur Trombe se verrait créditer d'une baisse des
fuites qu'il ne cause pas. Les petits côtés de la lame et le cadre de la vitre sont un isolant sans masse.

CE QUI N'EST PAS MODÉLISÉ. La lame ventilée vers la pièce (thermocirculation par des orifices haut et bas) :
EnergyPlus n'a pas de convection validée pour elle. Les ponts thermiques du cadre. Un store ou un isolant de
nuit devant la vitre. Le mur est en béton plein sans isolant ; l'isolant du mur d'origine est donc retiré sur
l'allège, ce qui coûte du chauffage les jours sans soleil : le résultat compte les 2 effets ensemble.

L'ÉTÉ, la vitre chauffe autant. 2 parades se règlent ici : une tablette en saillie au-dessus de la vitre, qui
coupe le soleil haut, et l'ouverture de la lame sur le dehors au-dessus d'une température.

PREUVE. `verification/trombe_los_alamos.py` rejoue une cellule d'essai mesurée à Los Alamos en février 1982
(mur de béton de 0,40 m derrière un double vitrage, lame fermée), avec la lame écrite par ce module, et compare
aux températures mesurées des 2 faces du mur. Les mesures ne sont pas dans le dépôt : l'essai se joue quand on
lui donne le texte de la thèse qui les publie. Le banc écrit lui-même les parois de sa cellule : il prouve la
lame, la vitre et les 2 faces du mur, pas les couches de béton choisies ici ni la retouche du mur d'origine.

Chaque valeur porte son origine : [S] lue dans une source, [C] citée sans relecture, [D] déduite, [H] hypothèse.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence, Tuple

from rayflect import extensions, hypotheses as hyp
from rayflect.aeration import combien
from rayflect.io.releve import secteur

NOM = "mur_trombe"
PREFIXE = "trombe_"                 # le début du nom de tout ce que ce module écrit dans le fichier
VITRAGES = ("du_batiment", "simple")
SOLEIL_SUIVI_DEDANS = "FullInteriorAndExteriorWithReflections"     # ce que devient le réglage courant
RESTE_DE_MUR_M = 0.10                               # le mur d'origine garde au moins cela au-dessus
RESISTANCE_DES_BORDS = 2.5                          # [H] m².K/W : le cadre et les petits côtés de la lame
CONDUCTION = "Surface Inside Face Conduction Heat Transfer Energy"
TEMPERATURE_DE_L_AIR = "Zone Mean Air Temperature"
SAISON_DE_CHAUFFE = (10, 11, 12, 1, 2, 3, 4)        # [H] d'octobre à avril
# Le béton plein des parois lourdes de rayflect.hypotheses ([S] règles Th-bât, Matériaux).
BETON_K, BETON_RHO, BETON_CP = hyp.BETON["k"], hyp.BETON["rho"], hyp.BETON["cp"]
PEAU_SOMBRE_M = 0.02                                # la face au soleil : les 2 premiers centimètres, peints
VERRE_SIMPLE = (5.7, 0.85)                          # [C] simple vitrage clair : U en W/m².K, facteur solaire
MARGE_SOUS_LA_BAIE_M = 0.05
HAUTEUR_MINIMALE_M = 0.30
OUVERTURE_VOL_H = 100.0                             # [H] la lame ouverte se renouvelle 100 fois par heure


@dataclass(frozen=True)
class MurTrombe:
    orientations: Optional[Tuple[str, ...]] = ("S",)
    hauteur_m: float = 0.85                 # [H] une allège courante ; réduite si une baie descend plus bas
    epaisseur_m: float = 0.25               # [H] le béton, peau sombre comprise
    lame_m: float = 0.15                    # [H] entre la vitre et le mur
    absorption: float = 0.9                 # [H] une peinture sombre et mate
    vitrage: str = "du_batiment"            # du_batiment ou simple
    cadre_m: float = 0.03                   # [H] largeur du cadre autour de la vitre
    tablette_m: float = 0.0                 # saillie d'une tablette pleine au-dessus de la vitre ; 0 : aucune
    ouverture_d_ete_c: Optional[float] = None       # la lame s'ouvre sur le dehors au-dessus de cette température
    niveaux: Optional[Tuple[int, ...]] = None       # les rangs des niveaux équipés ; None : tous

    def __post_init__(self) -> None:
        if self.vitrage not in VITRAGES:
            raise ValueError(f"vitrage : « {self.vitrage} » n'est pas dans {', '.join(VITRAGES)}")
        bornes = {"hauteur_m": (HAUTEUR_MINIMALE_M, 6.0), "epaisseur_m": (0.08, 0.60), "lame_m": (0.02, 0.30),
                  "absorption": (0.3, 0.98), "cadre_m": (0.01, 0.15), "tablette_m": (0.0, 1.5)}
        for cle, (mini, maxi) in bornes.items():
            valeur = getattr(self, cle)
            if isinstance(valeur, bool) or not isinstance(valeur, (int, float)) or not mini <= valeur <= maxi:
                raise ValueError(f"{cle} = {valeur} : attendu de {mini:g} à {maxi:g}")
        if self.ouverture_d_ete_c is not None and not 15.0 <= self.ouverture_d_ete_c <= 60.0:
            raise ValueError("ouverture_d_ete_c : une température de la lame, de 15 à 60 °C")
        if self.niveaux is not None and any(isinstance(n, bool) or not isinstance(n, int) or n < 0 for n in self.niveaux):
            raise ValueError("niveaux : des rangs de niveau, 0 pour le plus bas")


Point = Tuple[float, float, float]


def _plat(points: Sequence[Point]) -> str:
    return ",\n  ".join(f"{x:.4f}, {y:.4f}, {z:.4f}" for x, y, z in points)


def _paroi(nom: str, genre: str, construction: str, zone: str, limite: str, objet: str, au_soleil: bool,
           points: Sequence[Point]) -> str:
    return (f"BuildingSurface:Detailed,\n  {nom}, {genre}, {construction}, {zone}, , {limite}, {objet}, "
            f"{'SunExposed, WindExposed' if au_soleil else 'NoSun, NoWind'}, Autocalculate, {len(points)},\n  "
            f"{_plat(points)};\n\n")


def lame(nom: str, zone_de_la_piece: str, gauche: Point, droite: Point, hauteur_m: float, vers_dehors: Point,
         lame_m: float, mur_cote_piece: str, mur_cote_lame: str, bord: str, vitrage: str,
         cadre: Tuple[float, float, float, float], tablette_m: float = 0.0,
         ouverture_d_ete_c: Optional[float] = None, convection: str = "TrombeWall") -> Tuple[str, str]:
    """Le texte d'EnergyPlus d'un mur Trombe : sa face côté pièce, la lame d'air, la vitre.

    `gauche`, `droite` : les 2 pieds du mur, vus du dehors. `vers_dehors` : la normale horizontale, de norme 1.
    `mur_cote_piece`, `mur_cote_lame` : la même construction dans les 2 sens. `bord` : la construction des
    petits côtés de la lame, sans échange. `cadre` : ce que le cadre prend à gauche, à droite, en bas, en haut.
    Rend (le texte, le nom de la face du mur côté pièce).
    """
    def monte(point: Point, de: float) -> Point:
        return (point[0], point[1], point[2] + de)

    def avance(point: Point, de: float = lame_m) -> Point:
        return (point[0] + de * vers_dehors[0], point[1] + de * vers_dehors[1], point[2])

    a, b = gauche, droite
    a1, b1 = avance(a), avance(b)
    longueur = ((b[0] - a[0]) ** 2 + (b[1] - a[1]) ** 2) ** 0.5
    le_long = ((b[0] - a[0]) / longueur, (b[1] - a[1]) / longueur)
    zone, face = f"{nom}_lame", f"{nom}_cote_piece"
    h = hauteur_m
    texte = (f"Zone,\n  {zone}, , , , , , 1, {h:.3f}, {longueur * lame_m * h:.4f}, {longueur * lame_m:.4f}, "
             f"{convection}, , No;\n\n")
    texte += _paroi(face, "Wall", mur_cote_piece, zone_de_la_piece, "Surface", f"{nom}_cote_lame", False,
                    [monte(a, h), a, b, monte(b, h)])
    texte += _paroi(f"{nom}_cote_lame", "Wall", mur_cote_lame, zone, "Surface", face, False,
                    [monte(b, h), b, a, monte(a, h)])
    texte += _paroi(f"{nom}_devant", "Wall", bord, zone, "Outdoors", "", True, [monte(a1, h), a1, b1, monte(b1, h)])
    texte += _paroi(f"{nom}_a_droite", "Wall", bord, zone, "Adiabatic", "", False, [monte(b1, h), b1, b, monte(b, h)])
    texte += _paroi(f"{nom}_a_gauche", "Wall", bord, zone, "Adiabatic", "", False, [monte(a, h), a, a1, monte(a1, h)])
    texte += _paroi(f"{nom}_en_bas", "Floor", bord, zone, "Adiabatic", "", False, [b, b1, a1, a])
    texte += _paroi(f"{nom}_en_haut", "Ceiling", bord, zone, "Adiabatic", "", False,
                    [monte(a1, h), monte(b1, h), monte(b, h), monte(a, h)])

    def sur_la_vitre(le_long_m: float, en_haut_m: float) -> Point:
        return (a1[0] + le_long_m * le_long[0], a1[1] + le_long_m * le_long[1], a1[2] + en_haut_m)

    a_gauche, a_droite, en_bas, en_haut = cadre
    texte += (f"FenestrationSurface:Detailed,\n  {nom}_vitre, Window, {vitrage}, {nom}_devant, , Autocalculate, , 1, 4,\n  "
              + _plat([sur_la_vitre(a_gauche, h - en_haut), sur_la_vitre(a_gauche, en_bas),
                       sur_la_vitre(longueur - a_droite, en_bas), sur_la_vitre(longueur - a_droite, h - en_haut)])
              + ";\n\n")
    if tablette_m > 0:
        texte += (f"Shading:Zone:Detailed,\n  {nom}_tablette, {nom}_devant, , 4,\n  "
                  + _plat([avance(monte(a, h), lame_m + tablette_m), avance(monte(b, h), lame_m + tablette_m),
                           monte(b1, h), monte(a1, h)]) + ";\n\n")
    if ouverture_d_ete_c is not None:
        texte += (f"ZoneVentilation:DesignFlowRate,\n  {nom}_ouverte, {zone}, trombe_hors_saison_de_chauffe, "
                  f"AirChanges/Hour, , , , {OUVERTURE_VOL_H:g}, Natural, , , 1, 0, 0, 0, {ouverture_d_ete_c:g}, , 100, , 1;\n\n")
    return texte, face


def constructions(fiche: MurTrombe) -> str:
    """Le béton du mur, dans les 2 sens, et le verre simple. Les noms commencent par « trombe_ »."""
    def beton(nom: str, epaisseur: float, absorption: float) -> str:
        return (f"Material,\n  {nom}, MediumRough, {epaisseur:.4f}, {BETON_K:g}, {BETON_RHO:g}, {BETON_CP:g}, 0.9, "
                f"{absorption:g}, {absorption:g};\n\n")

    return (beton("trombe_peau_sombre", PEAU_SOMBRE_M, fiche.absorption)
            + beton("trombe_beton", fiche.epaisseur_m - PEAU_SOMBRE_M, 0.7)
            + "Construction,\n  trombe_mur_cote_piece, trombe_peau_sombre, trombe_beton;\n\n"
            "Construction,\n  trombe_mur_cote_lame, trombe_beton, trombe_peau_sombre;\n\n"
            # Le cadre de la vitre et les petits côtés de la lame : un isolant sans masse.
            f"Material:NoMass,\n  trombe_isolant_de_bord, MediumRough, {RESISTANCE_DES_BORDS:g}, 0.9, 0.5, 0.5;\n\n"
            "Construction,\n  trombe_bord, trombe_isolant_de_bord;\n\n"
            f"WindowMaterial:SimpleGlazingSystem,\n  trombe_verre_simple, {VERRE_SIMPLE[0]:g}, {VERRE_SIMPLE[1]:g};\n\n"
            "Construction,\n  trombe_vitre_simple, trombe_verre_simple;\n\n"
            # L'ouverture de la lame sur le dehors : de mai à septembre seulement, sinon elle viderait le mur l'hiver.
            "Schedule:Compact,\n  trombe_hors_saison_de_chauffe, , Through: 4/30, For: AllDays, Until: 24:00, 0, "
            "Through: 9/30, For: AllDays, Until: 24:00, 1, Through: 12/31, For: AllDays, Until: 24:00, 0;\n\n")


def _mur_a_equiper(face, hauteur_m: float) -> Optional[Tuple[Point, Point, Point, float]]:
    """(pied gauche, pied droit, normale vers le dehors, hauteur) d'un mur droit, ou None s'il ne s'y prête pas."""
    sommets = [(p.x, p.y, p.z) for p in face.geometry.boundary]
    normale = face.normal
    if len(sommets) != 4 or abs(normale.z) > 1e-6:
        return None
    bas = min(p[2] for p in sommets)
    pieds = [p for p in sommets if abs(p[2] - bas) < 1e-6]
    if len(pieds) != 2 or len({round(p[2], 6) for p in sommets}) != 2:
        return None
    seuils = [baie.geometry.min.z for baie in face.apertures] + [door.geometry.min.z for door in face.doors]
    hauteur = min([hauteur_m, max(p[2] for p in sommets) - bas - RESTE_DE_MUR_M]
                  + [s - bas - MARGE_SOUS_LA_BAIE_M for s in seuils])
    if hauteur < HAUTEUR_MINIMALE_M:
        return None
    # Vu du dehors, la gauche est du côté de (normale x verticale).
    vers_la_gauche = (normale.y, -normale.x)
    pieds.sort(key=lambda p: -(p[0] * vers_la_gauche[0] + p[1] * vers_la_gauche[1]))
    return pieds[0], pieds[1], (normale.x, normale.y, 0.0), hauteur


def suivre_le_soleil_dedans(reglages) -> None:
    """Fait suivre le soleil jusqu'aux parois intérieures, en gardant le choix de l'étude sur les reflets."""
    ombres = reglages.shadow_calculation
    if ombres.solar_distribution.startswith("FullExterior"):
        ombres.solar_distribution = ombres.solar_distribution.replace("FullExterior", "FullInteriorAndExterior", 1)


def poser(modele, fiche: MurTrombe, contexte: dict) -> str:
    """Remplace l'allège des façades visées par un mur Trombe. Rend le texte à ajouter au fichier d'EnergyPlus.

    Le modèle Honeybee garde ses murs entiers : c'est `retoucher` qui raccourcit le mur d'origine dans le fichier.
    """
    from honeybee_energy.load.infiltration import Infiltration

    suivre_le_soleil_dedans(contexte["reglages"])
    etiquettes = getattr(contexte.get("rendu"), "etiquettes", {})
    vitrage = "trombe_vitre_simple"
    if fiche.vitrage == "du_batiment":
        des_baies = [baie.properties.energy.construction.identifier for baie in modele.apertures]
        if not des_baies:
            raise ValueError("mur Trombe : le bâtiment n'a pas de vitrage à reprendre ; demander vitrage = \"simple\"")
        vitrage = des_baies[0]
    texte, poses, ecartes = constructions(fiche), [], 0
    for piece in modele.rooms:
        rang = etiquettes.get(piece.identifier, (None,))[0]
        if fiche.niveaux is not None and rang not in fiche.niveaux:
            continue
        for face in piece.faces:
            if face.type.name != "Wall" or face.boundary_condition.name != "Outdoors":
                continue
            if fiche.orientations is not None and secteur(face.azimuth) not in fiche.orientations:
                continue
            mur = _mur_a_equiper(face, fiche.hauteur_m)
            if mur is None:
                ecartes += 1
                continue
            gauche, droite, normale, hauteur = mur
            longueur = ((droite[0] - gauche[0]) ** 2 + (droite[1] - gauche[1]) ** 2) ** 0.5
            if longueur <= 2 * fiche.cadre_m + 0.1:
                ecartes += 1
                continue
            nom = f"{PREFIXE}{len(poses)}"
            du_mur, cote_piece = lame(
                nom, piece.identifier, gauche, droite, hauteur, normale, fiche.lame_m, "trombe_mur_cote_piece",
                "trombe_mur_cote_lame", "trombe_bord", vitrage, (fiche.cadre_m,) * 4, fiche.tablette_m,
                fiche.ouverture_d_ete_c)
            texte += du_mur + (f"Output:Variable,\n  {cote_piece}, {CONDUCTION}, Hourly;\n\n"
                               f"Output:Variable,\n  {nom}_lame, {TEMPERATURE_DE_L_AIR}, Hourly;\n\n")
            poses.append({"face": cote_piece, "aire_m2": longueur * hauteur, "piece": piece.identifier,
                          "mur": face.identifier, "bas": gauche[2], "haut": gauche[2] + hauteur})
    ou = "toutes les façades" if fiche.orientations is None else "façades " + ", ".join(fiche.orientations)
    if not poses:
        raise ValueError(f"mur Trombe : aucun mur droit avec au moins {HAUTEUR_MINIMALE_M:g} m d'allège libre sur les "
                         f"{ou}")
    aire = sum(p["aire_m2"] for p in poses)
    # Les fuites d'air s'écrivent par mètre carré de paroi extérieure. L'allège ne sera plus une paroi extérieure
    # de la pièce : le débit par mètre carré est relevé pour que la pièce garde les mêmes fuites.
    for piece in modele.rooms:
        retiree = sum(p["aire_m2"] for p in poses if p["piece"] == piece.identifier)
        fuites = piece.properties.energy.infiltration
        if retiree and fuites is not None and piece.exposed_area > retiree:
            piece.properties.energy.infiltration = Infiltration(
                f"infiltration_{piece.identifier}",
                fuites.flow_per_exterior_area * piece.exposed_area / (piece.exposed_area - retiree), fuites.schedule)
    contexte.setdefault("trombe", {})[contexte.get("scenario")] = poses
    dire = contexte.setdefault("a_dire", [])
    dire.append(
        f"mur Trombe sur les {ou} : {combien(len(poses), 'allège', 'allèges')}, {aire:.1f} m², béton de "
        f"{fiche.epaisseur_m:g} m sans isolant derrière un vitrage "
        f"{'simple' if fiche.vitrage == 'simple' else 'du bâtiment'}, lame fermée de {fiche.lame_m:g} m"
        + (f", tablette de {fiche.tablette_m:g} m" if fiche.tablette_m else "")
        + (f", lame ouverte sur le dehors de mai à septembre au-dessus de {fiche.ouverture_d_ete_c:g} °C"
           if fiche.ouverture_d_ete_c else ""))
    dire.append("mur Trombe : la lame ventilée vers la pièce n'est pas modélisée ; l'isolant du mur est retiré sur "
                "l'allège")
    if ecartes:
        dire.append(f"mur Trombe : {combien(ecartes, 'mur laissé tel quel', 'murs laissés tels quels')} (pas droit, ou une baie "
                    f"descend trop bas)")
    return texte


_SOMMET = re.compile(r"^(\s*)(-?\d+(?:\.\d+)?),\s*(-?\d+(?:\.\d+)?),\s*(-?\d+(?:\.\d+)?)([,;])\s*$")


def retoucher(texte: str, fiche: MurTrombe, contexte: dict) -> str:
    """Raccourcit, dans le fichier d'EnergyPlus, chaque mur dont l'allège est devenue un mur Trombe."""
    for pose in contexte.get("trombe", {}).get(contexte.get("scenario"), []):
        entete = re.search(r"BuildingSurface:Detailed,\s*\n\s*" + re.escape(pose["mur"]) + r"\s*,", texte)
        if entete is None:
            raise ValueError(f"mur Trombe : le mur « {pose['mur']} » n'est pas dans le fichier d'EnergyPlus")
        fin = texte.index(";", entete.end()) + 1
        lignes, remontes = [], 0
        for ligne in texte[entete.start():fin].split("\n"):
            sommet = _SOMMET.match(ligne)
            if sommet and abs(float(sommet.group(4)) - pose["bas"]) < 1e-3:
                ligne = (f"{sommet.group(1)}{sommet.group(2)}, {sommet.group(3)}, {pose['haut']:.3f}"
                         f"{sommet.group(5)}")
                remontes += 1
            lignes.append(ligne)
        if remontes != 2:
            raise ValueError(f"mur Trombe : le mur « {pose['mur']} » n'a pas 2 sommets au pied, mais {remontes}")
        texte = texte[:entete.start()] + "\n".join(lignes) + texte[fin:]
    return texte


def lire(annee, fiche: MurTrombe, contexte: dict) -> Dict[str, Any]:
    """Ce que les murs donnent à la pièce par conduction, en saison de chauffe et hors saison, et la lame au plus chaud."""
    poses = contexte.get("trombe", {}).get(contexte.get("scenario"), [])
    faces = {p["face"].upper() for p in poses}
    hiver = ete = 0.0
    for serie in annee.data_collections_by_output_name(CONDUCTION):
        if str(serie.header.metadata.get("Surface", "")).upper() not in faces:
            continue
        for instant, valeur in zip(serie.datetimes, serie.values):
            if instant.month in SAISON_DE_CHAUFFE:
                hiver += valeur
            else:
                ete += valeur
    lames: List[float] = [max(serie.values) for serie in annee.data_collections_by_output_name(TEMPERATURE_DE_L_AIR)
                          if str(serie.header.metadata.get("Zone", "")).upper().startswith(PREFIXE.upper())]
    return {"aire_m2": round(sum(p["aire_m2"] for p in poses), 1),
            "donne_a_la_piece_en_saison_de_chauffe_kwh": round(hiver),
            "donne_a_la_piece_hors_saison_kwh": round(ete),
            "lame_au_plus_chaud_c": round(max(lames), 1) if lames else None}


def dire(lu: Dict[str, Any]) -> List[str]:
    lignes = [f"{lu['aire_m2']:g} m² de mur : il donne à la pièce {lu['donne_a_la_piece_en_saison_de_chauffe_kwh']} kWh "
              f"d'octobre à avril, et {lu['donne_a_la_piece_hors_saison_kwh']} kWh de mai à septembre (négatif : il en "
              f"prend)"]
    if lu.get("lame_au_plus_chaud_c") is not None:
        lignes.append(f"la lame d'air monte à {lu['lame_au_plus_chaud_c']:g} °C au plus chaud")
    lignes.append("soleil suivi jusqu'au mur dans tous les scénarios de l'étude ; lame ventilée non modélisée")
    return lignes


def declarer() -> None:
    extensions.enregistrer(NOM, MurTrombe, poser, retoucher, lire)


declarer()
