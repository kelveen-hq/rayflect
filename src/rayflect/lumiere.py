"""La lumière du jour dans une pièce, lue dans le calcul d'EnergyPlus : assez de lumière, trop de lumière, l'éblouissement.

2 CAPTEURS par pièce vitrée, à hauteur de plan de travail :
  - au CENTRE de la pièce : la lumière qui manque au fond ;
  - en BORD DE BAIE, à 1 m du mur le plus vitré, en face de son milieu [H : le premier rang de bureaux] : la lumière
    qui déborde, là où une grande baie au sud se fait refuser. Le milieu du mur, pas celui d'une baie : le point ne
    bouge pas quand un scénario change les baies.
EnergyPlus y calcule l'éclairement naturel heure par heure, en tenant compte de toutes les protections : masques
fixes, lames, BSO baissés ou levés.

LES INDICATEURS, sur les heures d'occupation :
  - l'AUTONOMIE : la part des heures où la lumière naturelle atteint 300 lux sans allumer, le niveau visé par la
    norme NF EN 17037 [S] ; 100 lux, son niveau minimal [S] ;
  - l'EXCÈS : la part des heures au-dessus de 3 000 lux, la borne haute de la lumière utile. L'indicateur UDI de
    Mardaljevic et Nabil la plaçait d'abord à 2 000 lux [S : Nabil et Mardaljevic, « Useful daylight illuminances : a
    replacement for daylight factors », Energy and Buildings 38(7), 2006] ; ses révisions la placent à 3 000 lux
    [C : VELUX, Daylight, Energy and Indoor Climate Basic Book, §1.7]. Au-delà, la lumière éblouit et chauffe. Les 2 sont
    rendues ;
  - l'ÉBLOUISSEMENT : la part des heures où l'indice d'éblouissement d'EnergyPlus (DGI, la formule de Hopkinson dite
    de Cornell) dépasse 22, le maximum conseillé pour le travail de bureau [S : EnergyPlus 25.2, Energy+.idd,
    Daylighting:Controls, « The default is for general office work »]. Il se calcule pour un regard PARALLÈLE à la
    vitre la plus grande, comme à un poste de travail tourné le long de la façade [H] : un regard face à la vitre
    éblouirait davantage.

Limites de la méthode d'EnergyPlus (dite « split-flux ») : 2 points par pièce, une estimation simplifiée de la
lumière réfléchie par les parois, et un indice d'éblouissement qui ne voit que les baies, pas le soleil direct sur
une table. L'indice de Hopkinson est fait pour des sources petites : devant une très grande baie, la pièce entière
s'éclaire, le fond de la vue aussi, et l'indice BAISSE alors que la gêne augmente. Pour comparer des parts de vitrage,
lire l'excès de lumière ; l'éblouissement compare des protections sur un même vitrage (mesuré à Bordeaux le
23/11/2026 : façade sud passée de 24 à 80 % vitrée, excès de 55 à 71 % des heures, éblouissement de 50 à 24 %).
La méthode convient pour COMPARER des protections sur une même pièce, pas pour certifier : l'éblouissement de la
norme NF EN 17037 (la probabilité DGP) et un calcul point par point demandent Radiance.
"""

from __future__ import annotations

import math
import re
from typing import Dict, List, Optional, Sequence

ECLAIREMENT = "Daylighting Reference Point 1 Illuminance"
ECLAIREMENT_DU_BORD = "Daylighting Reference Point 2 Illuminance"
EBLOUISSEMENT = "Daylighting Reference Point 1 Glare Index"
EBLOUISSEMENT_DU_BORD = "Daylighting Reference Point 2 Glare Index"
SORTIES = (ECLAIREMENT, ECLAIREMENT_DU_BORD, EBLOUISSEMENT, EBLOUISSEMENT_DU_BORD)
SUFFIXE_DU_CAPTEUR = "_DAYLIGHTING"
HAUTEUR_DU_PLAN_DE_TRAVAIL_M = 0.8      # [H] hauteur d'un bureau
NIVEAU_VISE_LUX = 300.0                 # [S] NF EN 17037, niveau visé
NIVEAU_MINIMAL_LUX = 100.0              # [S] NF EN 17037, niveau minimal
UTILE_JUSQU_A_LUX = 2000.0              # [S] Nabil et Mardaljevic 2006
EXCES_LUX = 3000.0                      # [C] la borne révisée de la lumière utile
EBLOUISSEMENT_MAXIMAL = 22.0            # [S] EnergyPlus, maximum conseillé pour le travail de bureau
DISTANCE_DU_BORD_M = 1.0                # [H] le premier rang de bureaux


def poser_les_capteurs(modele, hauteur_m: float = HAUTEUR_DU_PLAN_DE_TRAVAIL_M) -> List[str]:
    """Pose un capteur au centre de chaque pièce qui a des baies. Rend le nom des pièces équipées.

    Le capteur du bord de baie et l'éblouissement s'ajoutent dans le fichier d'EnergyPlus (`retoucher`)."""
    equipees = []
    for piece in modele.rooms:
        if piece.exterior_aperture_area <= 0:
            continue
        if piece.properties.energy.add_daylight_control_to_center(hauteur_m, NIVEAU_VISE_LUX) is not None:
            equipees.append(piece.identifier)
    return equipees


def facade_principale(piece):
    """Le mur de la pièce qui porte le plus de vitrage, ou None sans baie."""
    murs = [f for f in piece.faces if f.apertures]
    return max(murs, key=lambda f: sum(b.area for b in f.apertures)) if murs else None


def point_du_bord(piece, hauteur_m: float = HAUTEUR_DU_PLAN_DE_TRAVAIL_M, distance_m: float = DISTANCE_DU_BORD_M):
    """Le point à `distance_m` du mur le plus vitré, en face de son milieu, à hauteur de plan de travail.

    Le milieu du mur, pas celui d'une baie : le point reste le même d'un scénario à l'autre quand les baies changent
    (une façade passée en tout vitré). None si ce point tombe hors de la pièce ; la distance est d'abord divisée par 2."""
    from ladybug_geometry.geometry3d import Point3D

    mur = facade_principale(piece)
    if mur is None:
        return None
    z = piece.geometry.min.z + hauteur_m
    centre, normale = mur.geometry.center, mur.normal
    for d in (distance_m, distance_m / 2.0):
        point = Point3D(centre.x - normale.x * d, centre.y - normale.y * d, z)
        if piece.geometry.is_point_inside(point):
            return point
    return None


def regard(piece) -> float:
    """La direction du regard, en degrés depuis l'axe y du bâtiment dans le sens horaire : le long du mur le plus vitré."""
    mur = facade_principale(piece)
    if mur is None:
        return 0.0
    azimut = math.degrees(math.atan2(mur.normal.x, mur.normal.y)) % 360.0
    return round((azimut + 90.0) % 360.0, 1)


def retoucher(texte: str, modele) -> str:
    """Le fichier d'EnergyPlus, où le capteur de chaque pièce gagne le capteur du bord de baie et l'éblouissement."""
    for piece in modele.rooms:
        controle = piece.properties.energy.daylighting_control
        if controle is None:
            continue
        nom, zone = f"{piece.identifier}_Daylighting", piece.identifier
        objet = re.compile(r"Daylighting:Controls,\s*\n\s*" + re.escape(nom) + r"\s*,.*?;", re.DOTALL)
        if not objet.search(texte):
            continue
        bord = point_du_bord(piece)
        points = f"  {zone}_Sensor, {controle.control_fraction}, {controle.illuminance_setpoint}"
        ajout = ""
        if bord is not None:
            points += f",\n  {zone}_Bord, 0.0, {controle.illuminance_setpoint}"
            ajout = (f"\nDaylighting:ReferencePoint,\n  {zone}_Bord, {zone}, {bord.x:.3f}, {bord.y:.3f}, {bord.z:.3f};\n")
        type_ = 'ContinuousOff' if controle.off_at_minimum else 'Continuous'
        nouveau = (f"Daylighting:Controls,\n  {nom}, {zone}, SplitFlux, , {type_}, "
                   f"{controle.min_power_input}, {controle.min_light_output}, , ,\n"
                   f"  {zone}_Sensor, {regard(piece)}, {EBLOUISSEMENT_MAXIMAL:g}, ,\n{points};\n" + ajout)
        texte = objet.sub(lambda _m, n=nouveau: n, texte, count=1)
    return texte


def autonomie(eclairement_lux: Sequence[float], occupe: Sequence[bool], niveau_lux: float = NIVEAU_VISE_LUX) -> float:
    """La part des heures d'occupation où l'éclairement naturel atteint le niveau, entre 0 et 1."""
    heures = [e for e, o in zip(eclairement_lux, occupe) if o]
    if not heures:
        return 0.0
    return sum(1 for e in heures if e >= niveau_lux) / len(heures)


def part_au_dessus(valeurs: Sequence[float], occupe: Sequence[bool], seuil: float) -> float:
    """La part des heures d'occupation où la valeur dépasse le seuil, entre 0 et 1."""
    heures = [v for v, o in zip(valeurs, occupe) if o]
    return sum(1 for v in heures if v > seuil) / len(heures) if heures else 0.0


def _par_piece(resultats, nom_de_sortie: str) -> Dict[str, list]:
    rendu = {}
    for serie in resultats.data_collections_by_output_name(nom_de_sortie):
        nom = str(serie.header.metadata.get("Zone", serie.header.metadata.get("System", "?")))
        if nom.upper().endswith(SUFFIXE_DU_CAPTEUR):       # EnergyPlus rend le nom du capteur, pas de la pièce
            nom = nom[:-len(SUFFIXE_DU_CAPTEUR)]
        rendu[nom] = list(serie.values)
    return rendu


def lire(resultats, occupe: Sequence[bool]) -> Dict[str, dict]:
    """Par pièce : l'autonomie, l'éclairement médian, l'excès et l'éblouissement, au centre et au bord de baie."""
    centre, bord = _par_piece(resultats, ECLAIREMENT), _par_piece(resultats, ECLAIREMENT_DU_BORD)
    dgi, dgi_bord = _par_piece(resultats, EBLOUISSEMENT), _par_piece(resultats, EBLOUISSEMENT_DU_BORD)
    bilan = {}
    for nom, valeurs in centre.items():
        heures = sorted(e for e, o in zip(valeurs, occupe) if o)

        def part(serie: Optional[list], seuil: float) -> Optional[float]:
            return None if serie is None else round(part_au_dessus(serie, occupe, seuil), 3)

        bilan[nom] = {
            "autonomie_300_lux": round(autonomie(valeurs, occupe, NIVEAU_VISE_LUX), 3),
            "autonomie_100_lux": round(autonomie(valeurs, occupe, NIVEAU_MINIMAL_LUX), 3),
            "eclairement_median_lux": round(heures[len(heures) // 2]) if heures else 0,
            "centre_plus_de_3000_lux": part(valeurs, EXCES_LUX),
            "bord_autonomie_300_lux": None if nom not in bord else round(autonomie(bord[nom], occupe, NIVEAU_VISE_LUX), 3),
            "bord_plus_de_2000_lux": part(bord.get(nom), UTILE_JUSQU_A_LUX),
            "bord_plus_de_3000_lux": part(bord.get(nom), EXCES_LUX),
            "eblouissement_centre": part(dgi.get(nom), EBLOUISSEMENT_MAXIMAL),
            "eblouissement_bord": part(dgi_bord.get(nom), EBLOUISSEMENT_MAXIMAL),
        }
    return bilan
