"""Le relevé d'une maquette IFC : ce qu'il faut pour étudier le soleil sur un bâtiment.

On ne lit pas tout le bâtiment. On relève : où il est, où est le nord, ses niveaux, et chaque baie avec sa
taille, son niveau, son orientation et le mur qui la porte. Tout ce qui manque ou paraît douteux est noté
dans `manques`, pour être demandé à l'utilisateur au lieu d'être deviné en silence.

L'orientation d'une baie se mesure sur sa GÉOMÉTRIE (le plan de la fenêtre dans l'espace), pas sur les
conventions d'axes du logiciel qui a exporté le fichier : elles varient d'un logiciel à l'autre.

Usage :
    python -m rayflect.io.lecture_ifc maquette.ifc [releve.json]
"""

from __future__ import annotations

import json
import math
import sys
from dataclasses import asdict
from pathlib import Path
from typing import Optional

import numpy as np
from shapely.geometry import Polygon
from shapely.ops import unary_union

import ifcopenshell
import ifcopenshell.geom
import ifcopenshell.util.element
import ifcopenshell.util.placement
import ifcopenshell.util.unit

from .releve import Baie, Niveau, Releve, SECTEURS, _azimut, resume, secteur  # noqa: F401

class FormatNonLu(ValueError):
    """La maquette est dans une version d'IFC que la bibliothèque ne lit pas."""


def _degres(compose) -> Optional[float]:
    """Une latitude IFC s'écrit (degrés, minutes, secondes, millionièmes de seconde)."""
    if not compose:
        return None
    d, m, s, *reste = list(compose) + [0, 0, 0]
    micro = reste[0] if reste else 0
    signe = -1.0 if any(v < 0 for v in (d, m, s, micro)) else 1.0
    return signe * (abs(d) + abs(m) / 60.0 + (abs(s) + abs(micro) / 1e6) / 3600.0)


def _nord(modele) -> tuple:
    """Le vecteur du nord dans le plan de la maquette. Par défaut, l'axe Y."""
    for contexte in modele.by_type("IfcGeometricRepresentationContext"):
        if contexte.is_a("IfcGeometricRepresentationSubContext"):
            continue
        direction = getattr(contexte, "TrueNorth", None)
        if direction is not None:
            x, y = direction.DirectionRatios[:2]
            n = math.hypot(x, y)
            if n > 0:
                return (x / n, y / n)
    return (0.0, 1.0)


def _plan(sommets: np.ndarray):
    """Centre, normale et étendues d'un nuage de points à peu près plan (une fenêtre)."""
    centre = (sommets.min(axis=0) + sommets.max(axis=0)) / 2.0
    _valeurs, vecteurs = np.linalg.eigh(np.cov((sommets - sommets.mean(axis=0)).T))
    normale = vecteurs[:, 0]                       # la direction la plus mince
    return centre, normale


_RAYON = np.array([0.5257311, 0.3249197, 0.7861514])     # direction quelconque, hors des axes


def _dans_le_volume(point, triangles) -> bool:
    """Le point est-il dans le volume fermé ? Un rayon qui en sort traverse sa peau un nombre impair de fois."""
    a, b, c = triangles[:, 0], triangles[:, 1], triangles[:, 2]
    e1, e2 = b - a, c - a
    h = np.cross(_RAYON, e2)
    det = np.einsum("ij,ij->i", e1, h)
    ok = np.abs(det) > 1e-12
    inv = np.where(ok, 1.0 / np.where(ok, det, 1.0), 0.0)
    t0 = point - a
    u = np.einsum("ij,ij->i", t0, h) * inv
    q = np.cross(t0, e1)
    v = (q @ _RAYON) * inv
    t = np.einsum("ij,ij->i", e2, q) * inv
    touche = ok & (u >= 0) & (v >= 0) & (u + v <= 1) & (t > 1e-9)
    return int(touche.sum()) % 2 == 1


def _mur_porteur(baie):
    for remplissage in getattr(baie, "FillsVoids", None) or []:
        ouverture = remplissage.RelatingOpeningElement
        for percement in getattr(ouverture, "VoidsElements", None) or []:
            return percement.RelatingBuildingElement
    return None


def _est_exterieur(element) -> Optional[bool]:
    if element is None:
        return None
    for proprietes in ifcopenshell.util.element.get_psets(element).values():
        if "IsExternal" in proprietes and proprietes["IsExternal"] is not None:
            return bool(proprietes["IsExternal"])
    return None


def lire(chemin) -> Releve:
    chemin = Path(chemin)
    try:
        modele = ifcopenshell.open(str(chemin))
    except ifcopenshell.SchemaError as erreur:
        raise FormatNonLu(f"{chemin.name} : {erreur}. Réexporter la maquette en IFC2x3 ou en IFC4.") from erreur
    echelle = ifcopenshell.util.unit.calculate_unit_scale(modele)
    nord = _nord(modele)
    applis = modele.by_type("IfcApplication")
    sites = modele.by_type("IfcSite")
    site = sites[0] if sites else None
    releve = Releve(
        fichier=chemin.name, schema=modele.schema,
        logiciel=(applis[0].ApplicationFullName if applis else "inconnu"),
        latitude=_degres(getattr(site, "RefLatitude", None)) if site else None,
        longitude=_degres(getattr(site, "RefLongitude", None)) if site else None,
        altitude_m=(site.RefElevation * echelle if site and site.RefElevation is not None else None),
        nord_deg=round(math.degrees(math.atan2(nord[0], nord[1])) % 360.0, 2),
    )
    if releve.latitude is None or releve.longitude is None:
        releve.manques.append("position du site absente : latitude et longitude à demander")
    elif abs(releve.latitude) < 1e-6 and abs(releve.longitude) < 1e-6:
        releve.manques.append("position du site à (0, 0) : non renseignée, à demander")

    niveaux = {}
    # LE ZÉRO DU BÂTIMENT. L'altitude déclarée d'un niveau se compte depuis le zéro du bâtiment, alors que la
    # géométrie est placée à l'altitude du terrain : 14 m plus haut sur une maquette de logements, 29 m plus bas
    # sur une maquette de bureaux. On mesure ce décalage sur les niveaux eux-mêmes et on ramène toute la
    # géométrie au zéro du bâtiment : « enterré » veut alors dire sous le rez-de-chaussée.
    decalages = []
    for etage in modele.by_type("IfcBuildingStorey"):
        niveaux[etage.id()] = Niveau(etage.Name or f"niveau {etage.id()}", round((etage.Elevation or 0.0) * echelle, 3))
        try:
            pose = ifcopenshell.util.placement.get_local_placement(etage.ObjectPlacement)
            decalages.append(float(pose[2, 3]) * echelle - (etage.Elevation or 0.0) * echelle)
        except Exception:
            continue
    decalage_z = float(np.median(decalages)) if decalages else 0.0
    if abs(decalage_z) > 0.05:
        releve.altitude_du_zero_m = round(decalage_z, 3)
    if not niveaux:
        releve.manques.append("aucun niveau déclaré")

    espaces = modele.by_type("IfcSpace")
    murs = modele.by_type("IfcWall")
    releve.n_murs = len(murs)
    etats = [_est_exterieur(m) for m in murs]
    if murs and all(e is None for e in etats):
        if not espaces:
            releve.manques.append("ni mur déclaré extérieur ni local : impossible d'écarter les baies intérieures")
    else:
        releve.n_murs_exterieurs = sum(1 for e in etats if e)

    releve.n_espaces = len(espaces)
    if not espaces:
        releve.manques.append("aucun local déclaré : les pièces ne sont pas connues")
    releve.n_protections_solaires = len(modele.by_type("IfcShadingDevice")) if modele.schema != "IFC2X3" else 0
    releve.n_murs_rideaux = len(modele.by_type("IfcCurtainWall"))
    if releve.n_murs_rideaux:
        releve.manques.append(f"{releve.n_murs_rideaux} mur(s)-rideau(x) : vitrage non relevé, à saisir")

    reglages = ifcopenshell.geom.settings()
    reglages.set("use-world-coords", True)
    fenetres = modele.by_type("IfcWindow")
    if not fenetres:
        releve.manques.append("aucune fenêtre déclarée")
    formes = []
    for fenetre in fenetres:
        try:
            forme = ifcopenshell.geom.create_shape(reglages, fenetre)
            sommets = np.array(forme.geometry.verts, dtype=float).reshape(-1, 3)
            if len(sommets) < 3:
                raise ValueError("géométrie vide")
            sommets[:, 2] -= decalage_z
            formes.append((fenetre, sommets))
        except Exception as erreur:          # une baie illisible ne doit pas faire perdre les autres
            releve.manques.append(f"fenêtre {fenetre.GlobalId} illisible ({type(erreur).__name__})")
    # Le centre du bâtiment : celui de ses murs, plus sûr que celui de ses fenêtres quand elles sont
    # toutes du même côté.
    origines = []
    for mur in murs:
        try:
            origines.append(ifcopenshell.util.placement.get_local_placement(mur.ObjectPlacement)[:3, 3] * echelle)
        except Exception:
            continue
    if len(origines) >= 3:
        centre_batiment = np.mean(origines, axis=0)
    elif formes:
        centre_batiment = np.mean([s.mean(axis=0) for _f, s in formes], axis=0)
    else:
        centre_batiment = np.zeros(3)

    # LE DEHORS D'UNE BAIE : le côté où il n'y a pas de local. On teste un point à 60 cm de chaque côté du
    # plan de la baie contre le VOLUME de chaque local (pas sa boîte : un bâtiment tourné la fausse).
    # Un local des 2 côtés : baie intérieure. Aucun local d'aucun côté, ou la maquette n'a pas de locaux :
    # on retombe sur « à l'opposé du centre », et on le dit.
    boites = []
    for espace in espaces:
        try:
            geometrie = ifcopenshell.geom.create_shape(reglages, espace).geometry
            pts = np.array(geometrie.verts, dtype=float).reshape(-1, 3)
            pts[:, 2] -= decalage_z
            triangles = np.array(geometrie.faces, dtype=int).reshape(-1, 3)
            if len(pts) and len(triangles):
                boites.append((pts.min(axis=0), pts.max(axis=0), pts[triangles], espace))
        except Exception:
            continue

    def dans_un_local(point) -> bool:
        return any(bool(np.all(point >= bas) and np.all(point <= haut)) and _dans_le_volume(point, tri)
                   for bas, haut, tri, _espace in boites)

    sans_sens = 0
    for fenetre, sommets in formes:
        centre, normale = _plan(sommets)
        vers_dehors = centre - centre_batiment
        if float(np.dot(normale[:2], vers_dehors[:2])) < 0:
            normale = -normale
        sens_sur = False
        interieure = False
        if boites:
            devant, derriere = dans_un_local(centre + 0.6 * normale), dans_un_local(centre - 0.6 * normale)
            if devant and not derriere:
                normale, sens_sur = -normale, True
            elif derriere and not devant:
                sens_sur = True
            elif devant and derriere:
                interieure = True
        horizontale = math.hypot(normale[0], normale[1])
        inclinaison = math.degrees(math.atan2(horizontale, abs(normale[2])))
        if inclinaison <= 60.0:
            interieure = False      # une fenêtre de toit a un local dessous, pas derrière
        etendue = sommets.max(axis=0) - sommets.min(axis=0)
        if inclinaison > 30.0:
            le_long = np.array([-normale[1], normale[0], 0.0]) / horizontale
            projections = sommets @ le_long
            largeur, hauteur = float(projections.max() - projections.min()), float(etendue[2])
            azimut = _azimut((normale[0], normale[1]), nord)
            if not sens_sur and not interieure:
                sans_sens += 1
        else:
            largeur, hauteur = float(etendue[0]), float(etendue[1])
            azimut = None
        conteneur = ifcopenshell.util.element.get_container(fenetre)
        niveau = niveaux.get(conteneur.id()) if conteneur is not None else None
        mur = _mur_porteur(fenetre)
        declare = None
        if getattr(fenetre, "OverallWidth", None) and getattr(fenetre, "OverallHeight", None):
            declare = (round(fenetre.OverallWidth * echelle, 3), round(fenetre.OverallHeight * echelle, 3))
        if niveau:
            niveau.n_baies += 1
        releve.baies.append(Baie(
            identifiant=fenetre.GlobalId, nom=fenetre.Name or "", niveau=niveau.nom if niveau else None,
            largeur_m=round(largeur, 3), hauteur_m=round(hauteur, 3), aire_m2=round(largeur * hauteur, 3),
            allege_m=(round(float(sommets[:, 2].min()) - niveau.altitude_m, 3) if niveau else None),
            azimut_deg=(round(azimut, 1) if azimut is not None else None),
            secteur=(secteur(azimut) if azimut is not None else None),
            inclinaison_deg=round(inclinaison, 1),
            centre_m=tuple(round(float(v), 3) for v in centre),
            normale_xy=(round(float(normale[0]), 5), round(float(normale[1]), 5)),
            z_bas_m=round(float(sommets[:, 2].min()), 3), z_haut_m=round(float(sommets[:, 2].max()), 3),
            mur=(mur.GlobalId if mur is not None else None),
            mur_exterieur=(False if interieure else _est_exterieur(mur)),
            taille_declaree_m=declare,
        ))

    for etage_id, niveau in niveaux.items():
        aires = []
        for espace in espaces:
            conteneur = ifcopenshell.util.element.get_container(espace) or ifcopenshell.util.element.get_aggregate(espace)
            if conteneur is not None and conteneur.id() == etage_id:
                for quantites in ifcopenshell.util.element.get_psets(espace, qtos_only=True).values():
                    for cle in ("NetFloorArea", "GrossFloorArea"):
                        if quantites.get(cle):
                            aires.append(float(quantites[cle]))
                            break
                    else:
                        continue
                    break
        if aires:
            niveau.aire_espaces_m2 = round(sum(aires), 1)
    # L'EMPRISE D'UN NIVEAU : la réunion des locaux vus de dessus. On gonfle de 35 cm pour refermer l'épaisseur
    # des cloisons entre locaux, puis on dégonfle de 20 cm : le contour tombe à peu près à mi-épaisseur du mur
    # extérieur. Une cour intérieure est perdue, et signalée.
    cours = 0
    sans_locaux = 0
    for etage_id, niveau in niveaux.items():
        dessus, bas_z, haut_z = [], [], []
        for bas, haut, tri, espace in boites:
            conteneur = ifcopenshell.util.element.get_container(espace) or ifcopenshell.util.element.get_aggregate(espace)
            if conteneur is None or conteneur.id() != etage_id:
                continue
            bas_z.append(float(bas[2]))
            haut_z.append(float(haut[2]))
            for t in tri:
                polygone = Polygon(t[:, :2])
                if polygone.is_valid and polygone.area > 1e-6:
                    dessus.append(polygone)
        if not dessus:
            # SANS LOCAUX : beaucoup de maquettes d'architecte n'en ont pas. L'emprise vient alors des murs du
            # niveau, vus de dessus : on les réunit, on referme les angles, et on garde le contour extérieur.
            murs_du_niveau, hauts = [], []
            for mur in murs:
                conteneur = ifcopenshell.util.element.get_container(mur)
                if conteneur is None or conteneur.id() != etage_id:
                    continue
                try:
                    g = ifcopenshell.geom.create_shape(reglages, mur).geometry
                    pts = np.array(g.verts, dtype=float).reshape(-1, 3)
                    tris = np.array(g.faces, dtype=int).reshape(-1, 3)
                except Exception:
                    continue
                hauts.append(float(pts[:, 2].max()) - decalage_z)
                for t in pts[tris]:
                    polygone = Polygon(t[:, :2])
                    if polygone.is_valid and polygone.area > 1e-6:
                        murs_du_niveau.append(polygone)
            if len(murs_du_niveau) < 3:
                continue
            ferme = unary_union(murs_du_niveau).buffer(0.6, join_style=2)
            corps = max((ferme.geoms if hasattr(ferme, "geoms") else [ferme]), key=lambda m: Polygon(m.exterior).area)
            contour = Polygon(corps.exterior).buffer(-0.6 - 0.15, join_style=2).simplify(0.05)
            if contour.is_empty or contour.geom_type != "Polygon" or contour.area < 10.0:
                continue
            points = list(contour.exterior.coords)[:-1]
            if contour.exterior.is_ccw is False:
                points.reverse()
            niveau.emprise_m = [(round(x, 3), round(y, 3)) for x, y in points]
            niveau.aire_emprise_m2 = round(contour.area, 1)
            niveau.plancher_m, niveau.plafond_m = niveau.altitude_m, round(float(np.median(hauts)), 3)
            sans_locaux += 1
            continue
        reunion = unary_union(dessus).buffer(0.35, join_style=2).buffer(-0.20, join_style=2)
        morceaux = list(reunion.geoms) if hasattr(reunion, "geoms") else [reunion]
        principal = max(morceaux, key=lambda m: m.area)
        if len(morceaux) > 1:
            releve.manques.append(f"niveau {niveau.nom} : {len(morceaux)} corps séparés, seul le plus grand est gardé")
        cours += len(principal.interiors)
        contour = Polygon(principal.exterior).simplify(0.05)
        points = list(contour.exterior.coords)[:-1]
        if contour.exterior.is_ccw is False:
            points.reverse()
        niveau.emprise_m = [(round(x, 3), round(y, 3)) for x, y in points]
        niveau.aire_emprise_m2 = round(contour.area, 1)
        niveau.plancher_m = round(float(np.median(bas_z)), 3)
        niveau.plafond_m = round(float(np.median(haut_z)), 3)
    # UN NIVEAU QUI A DES BAIES MAIS PAS D'EMPRISE (ses murs ne ferment pas, et il n'a pas de locaux) : on lui
    # prête l'emprise du niveau le plus proche qui en a une, et on le dit.
    avec_emprise = [n for n in niveaux.values() if n.emprise_m]
    altitudes_triees = sorted(n.altitude_m for n in niveaux.values())
    for niveau in niveaux.values():
        if niveau.emprise_m or not niveau.n_baies or not avec_emprise:
            continue
        modele_du_niveau = min(avec_emprise, key=lambda n: abs(n.altitude_m - niveau.altitude_m))
        au_dessus = [a for a in altitudes_triees if a > niveau.altitude_m + 2.0]
        niveau.emprise_m = list(modele_du_niveau.emprise_m)
        niveau.aire_emprise_m2 = modele_du_niveau.aire_emprise_m2
        niveau.plancher_m = niveau.altitude_m
        niveau.plafond_m = round((au_dessus[0] if au_dessus else niveau.altitude_m + 3.0) - 0.3, 3)
        releve.manques.append(
            f"niveau {niveau.nom} : ni local ni murs fermés ; emprise reprise du niveau {modele_du_niveau.nom}, "
            f"à confirmer")
    if sans_locaux:
        releve.manques.append(f"{sans_locaux} niveau(x) sans local : emprise tirée des murs, à confirmer")
    if cours:
        releve.manques.append(f"{cours} cour(s) ou vide(s) intérieur(s) non repris dans l'emprise")
    releve.niveaux = sorted(niveaux.values(), key=lambda n: n.altitude_m)
    if espaces and all(n.aire_espaces_m2 is None for n in releve.niveaux):
        releve.manques.append("surface des locaux non exportée : à mesurer sur la géométrie ou à demander")

    sans_mur = sum(1 for b in releve.baies if b.mur is None)
    if sans_mur:
        releve.manques.append(f"{sans_mur} baie(s) sans mur porteur identifié")
    interieures = sum(1 for b in releve.baies if b.mur_exterieur is False)
    if interieures:
        releve.manques.append(f"{interieures} baie(s) dans un mur intérieur : à écarter du calcul solaire")
    if sans_sens:
        releve.manques.append(f"{sans_sens} baie(s) dont le côté extérieur n'a pas pu être établi : orientation à confirmer")
    ecarts = sum(1 for b in releve.baies if b.taille_declaree_m and (
        abs(b.taille_declaree_m[0] - b.largeur_m) > 0.10 or abs(b.taille_declaree_m[1] - b.hauteur_m) > 0.10))
    if ecarts:
        releve.manques.append(f"{ecarts} baie(s) dont la taille déclarée s'écarte de plus de 10 cm de la taille mesurée")
    if abs(releve.nord_deg) < 1e-9:
        releve.manques.append("nord sur l'axe Y de la maquette : valeur par défaut, à confirmer")
    return releve


def main(argv) -> int:
    if len(argv) < 2:
        print(__doc__)
        return 2
    try:
        releve = lire(argv[1])
    except FormatNonLu as erreur:
        print(erreur)
        return 1
    print(resume(releve))
    if len(argv) > 2:
        Path(argv[2]).write_text(json.dumps(asdict(releve), indent=2, ensure_ascii=False), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
