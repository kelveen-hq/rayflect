"""Ce qui entoure le bâtiment : les bâtiments voisins, pris dans les données ouvertes, deviennent des masques.

La source : la BD TOPO de l'IGN, servie par la Géoplateforme (licence ouverte Etalab 2.0). Chaque bâtiment y
porte son emprise au sol et sa hauteur. On en fait un prisme (ses murs et son toit), que le moteur de calcul
traite comme n'importe quel masque : il ombre le bâtiment étudié heure par heure.

Le relief lointain n'est pas ici : l'année météo type de PVGIS tient déjà compte de l'horizon du terrain.
Les arbres ne sont pas dans la BD TOPO bâtiment ; ils restent à saisir.

Repère : des mètres vers l'est (x) et vers le nord (y), comptés depuis la position du site. Sur quelques
centaines de mètres, la Terre est prise pour plate.
"""

from __future__ import annotations

import json
import math
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import List, Optional, Sequence, Tuple

from shapely.geometry import Polygon

from rayflect import geometrie

SERVICE = "https://data.geopf.fr/wfs/ows"
COUCHE = "BDTOPO_V3:batiment"
RAYON_TERRE_M = 6_371_000.0
HAUTEUR_PAR_ETAGE_M = 3.0           # [H] quand la hauteur manque mais que le nombre d'étages est donné
ANGLE_MINIMAL_DEG = 5.0             # [H] un voisin vu sous moins de 5° au-dessus de l'horizon est écarté


@dataclass(frozen=True)
class Voisin:
    identifiant: str
    contour_m: Tuple[Tuple[float, float], ...]      # points (est, nord) en mètres depuis le site
    hauteur_m: float
    hauteur_supposee: bool = False                  # vraie si elle vient du nombre d'étages
    sol_m: Optional[float] = None                   # altitude du sol au pied du bâtiment, si elle est connue

    @property
    def distance_m(self) -> float:
        return Polygon(self.contour_m).distance(Polygon([(-0.01, -0.01), (0.01, -0.01), (0.0, 0.01)]))


def vers_metres(latitude: float, longitude: float, latitude_site: float, longitude_site: float) -> Tuple[float, float]:
    est = math.radians(longitude - longitude_site) * RAYON_TERRE_M * math.cos(math.radians(latitude_site))
    nord = math.radians(latitude - latitude_site) * RAYON_TERRE_M
    return est, nord


def _emprise_en_degres(latitude: float, longitude: float, rayon_m: float) -> Tuple[float, float, float, float]:
    d_lat = math.degrees(rayon_m / RAYON_TERRE_M)
    d_lon = d_lat / math.cos(math.radians(latitude))
    return latitude - d_lat, longitude - d_lon, latitude + d_lat, longitude + d_lon


def telecharger(latitude: float, longitude: float, rayon_m: float = 150.0, delai_s: float = 60.0) -> dict:
    """Les bâtiments de la BD TOPO dans le carré de côté 2 × rayon autour du point, au format GeoJSON."""
    sud, ouest, nord, est = _emprise_en_degres(latitude, longitude, rayon_m)
    requete = urllib.parse.urlencode({
        "SERVICE": "WFS", "VERSION": "2.0.0", "REQUEST": "GetFeature", "TYPENAMES": COUCHE,
        "OUTPUTFORMAT": "application/json", "SRSNAME": "EPSG:4326", "COUNT": "2000",
        "BBOX": f"{sud:.6f},{ouest:.6f},{nord:.6f},{est:.6f},urn:ogc:def:crs:EPSG::4326"})
    with urllib.request.urlopen(f"{SERVICE}?{requete}", timeout=delai_s) as reponse:
        return json.loads(reponse.read().decode("utf-8"))


def lire(geojson: dict, latitude_site: float, longitude_site: float) -> Tuple[List[Voisin], List[str]]:
    """(voisins, manques). Un bâtiment sans hauteur ni nombre d'étages est écarté, et compté dans les manques."""
    voisins, sans_hauteur = [], 0
    for element in geojson.get("features", []):
        proprietes = element.get("properties") or {}
        geometrie = element.get("geometry") or {}
        hauteur, supposee = proprietes.get("hauteur"), False
        if not hauteur:
            etages = proprietes.get("nombre_d_etages")
            if not etages:
                sans_hauteur += 1
                continue
            hauteur, supposee = float(etages) * HAUTEUR_PAR_ETAGE_M, True
        polygones = geometrie.get("coordinates") or []
        if geometrie.get("type") == "Polygon":
            polygones = [polygones]
        for rang, polygone in enumerate(polygones):
            if not polygone:
                continue
            contour = tuple(vers_metres(p[1], p[0], latitude_site, longitude_site) for p in polygone[0][:-1])
            if len(contour) >= 3 and Polygon(contour).area > 1.0:
                voisins.append(Voisin(f"{element.get('id', 'batiment')}_{rang}", contour, float(hauteur), supposee,
                                      proprietes.get("altitude_minimale_sol")))
    manques = []
    if sans_hauteur:
        manques.append(f"{sans_hauteur} bâtiment(s) voisin(s) sans hauteur connue : non repris comme masques")
    supposes = sum(1 for v in voisins if v.hauteur_supposee)
    if supposes:
        manques.append(f"{supposes} voisin(s) dont la hauteur est déduite du nombre d'étages")
    return voisins, manques


def filtrer(voisins: Sequence[Voisin], emprise_etudiee_m: Optional[Sequence[Tuple[float, float]]] = None,
            hauteur_des_baies_m: float = 1.5, angle_minimal_deg: float = ANGLE_MINIMAL_DEG) -> Tuple[List[Voisin], dict]:
    """Écarte le bâtiment étudié lui-même, puis les voisins trop bas ou trop loin pour ombrer.

    `emprise_etudiee_m` : le contour du bâtiment étudié, dans le même repère. Tout bâtiment de la carte qui
    le recouvre est le bâtiment lui-même (ou un morceau), pas un voisin.
    """
    etudie = Polygon(emprise_etudiee_m) if emprise_etudiee_m else None
    gardes, bilan = [], {"lui_meme": 0, "trop_bas_ou_loin": 0}
    for voisin in voisins:
        forme = Polygon(voisin.contour_m)
        if not forme.is_valid:
            forme = forme.buffer(0)
        if etudie is not None and forme.intersection(etudie).area > 0.2 * min(forme.area, etudie.area):
            bilan["lui_meme"] += 1
            continue
        distance = forme.distance(etudie) if etudie is not None else voisin.distance_m
        hauteur_vue = voisin.hauteur_m - hauteur_des_baies_m
        if hauteur_vue <= 0 or math.degrees(math.atan2(hauteur_vue, max(distance, 0.5))) < angle_minimal_deg:
            bilan["trop_bas_ou_loin"] += 1
            continue
        gardes.append(voisin)
    bilan["gardes"] = len(gardes)
    return gardes, bilan


def altitude_du_site(voisins: Sequence[Voisin]) -> Optional[float]:
    """L'altitude du sol au pied du bâtiment le plus proche du site : la meilleure estimation disponible."""
    connus = [v for v in voisins if v.sol_m is not None]
    return min(connus, key=lambda v: v.distance_m).sol_m if connus else None


def masques(voisins: Sequence[Voisin], altitude_site_m: Optional[float] = None, finesse_m: float = 1.0) -> list:
    """Les murs et le toit de chaque voisin, en masques Honeybee détachés du bâtiment étudié.

    `altitude_site_m` : l'altitude du sol du bâtiment étudié. Un voisin plus haut sur la pente ombre davantage.
    `finesse_m` : les contours sont simplifiés à cette précision, pour ne pas noyer le calcul de petites faces.
    """
    from honeybee.shade import Shade
    from ladybug_geometry.geometry3d import Face3D, Point3D

    ombres = []
    for rang, voisin in enumerate(voisins):
        forme = Polygon(voisin.contour_m).simplify(finesse_m)
        if forme.is_empty or forme.geom_type != "Polygon" or forme.area < 1.0:
            continue
        contour = list(forme.exterior.coords)[:-1]
        if forme.exterior.is_ccw is False:
            contour.reverse()
        decalage = (voisin.sol_m - altitude_site_m) if (voisin.sol_m is not None and altitude_site_m is not None) else 0.0
        bas, haut = min(0.0, decalage), decalage + voisin.hauteur_m
        if haut <= 0.5:
            continue
        for k, (a, b) in enumerate(zip(contour, contour[1:] + contour[:1])):
            if math.hypot(b[0] - a[0], b[1] - a[1]) < 0.05:
                continue
            mur = Face3D([Point3D(a[0], a[1], bas), Point3D(b[0], b[1], bas),
                          Point3D(b[0], b[1], haut), Point3D(a[0], a[1], haut)])
            ombres.append(Shade(f"voisin_{rang}_mur_{k}", mur, is_detached=True))
        # Un toit en L n'est pas convexe : EnergyPlus ne l'ombrerait pas juste (voir geometrie.convexes).
        toit = geometrie.convexes(Face3D([Point3D(x, y, haut) for x, y in contour]))
        for k, morceau in enumerate(toit):
            nom = f"voisin_{rang}_toit" if len(toit) == 1 else f"voisin_{rang}_toit_{k}"
            ombres.append(Shade(nom, morceau, is_detached=True))
    return ombres


def a_des_masques_transparents(modele) -> bool:
    """Le modèle porte-t-il un masque qui laisse passer une part du soleil (feuillage, lames de saison) ?"""
    return any(ombre.properties.energy.transmittance_schedule is not None for ombre in modele.shades)


def regler_le_calcul_des_ombres(parametres, modele=None) -> str:
    """Règle EnergyPlus pour un bâtiment entouré de nombreux masques. Rend la méthode retenue.

    Mesuré sur une salle entourée de 539 faces de voisins : le calcul par défaut prend 179 s ; sans les
    reflets du soleil sur les voisins, 76 s ; en comptant les ombres par la carte graphique, 28 s, pour le
    même résultat. Ce qu'on perd en renonçant aux reflets : moins de 2 % sur le chauffage.
    Sans carte graphique utilisable, EnergyPlus revient de lui-même à la méthode géométrique.

    PIÈGE MESURÉ : la méthode par la carte graphique traite tout masque comme opaque. Un écran transparent
    à 50 % y ombre autant qu'un mur. Dès qu'un masque du modèle est à demi transparent (un arbre, une lame
    effacée l'hiver), on garde donc la méthode géométrique, plus lente mais juste. Sans `modele`, la
    fonction ne peut pas le savoir et choisit la méthode rapide : à réserver aux masques tous opaques.
    """
    parametres.shadow_calculation.solar_distribution = "FullExterior"
    methode = "PolygonClipping" if (modele is not None and a_des_masques_transparents(modele)) else "PixelCounting"
    parametres.shadow_calculation.calculation_method = methode
    return methode


@dataclass(frozen=True)
class Calage:
    """Où la maquette se pose sur la carte : le décalage à lui appliquer, et la confiance qu'on peut y mettre."""
    decalage_m: Tuple[float, float]         # (est, nord) à ajouter aux points de la maquette pour tomber sur la carte
    recouvrement: float                     # part commune des 2 emprises, de 0 à 1
    batiment: Optional[str]                 # le bâtiment de la carte reconnu comme étant la maquette
    sur: bool                               # faux : position à faire confirmer


RECOUVREMENT_MINIMAL = 0.6      # [H] en dessous, on ne prétend pas avoir reconnu le bâtiment


def _recouvrement(a: Polygon, b: Polygon) -> float:
    reunion = a.union(b).area
    return a.intersection(b).area / reunion if reunion > 0 else 0.0


def caler(emprise_m: Sequence[Tuple[float, float]], voisins: Sequence[Voisin], recherche_m: float = 40.0,
          pas_m: float = 0.5, affinage_m: float = 3.0) -> Calage:
    """Retrouve sur la carte le bâtiment dont l'emprise ressemble à celle de la maquette.

    La position écrite dans une maquette est souvent approchée, parfois fausse de dizaines de mètres. Pour
    chaque bâtiment de la carte à moins de `recherche_m`, on superpose les centres, puis on essaie de petits
    déplacements autour, et on garde la superposition qui recouvre le mieux.
    """
    from shapely.affinity import translate

    maquette = Polygon(emprise_m)
    if not maquette.is_valid:
        maquette = maquette.buffer(0)
    centre = maquette.centroid
    meilleur = Calage((0.0, 0.0), 0.0, None, False)
    n = int(round(affinage_m / pas_m))
    for voisin in voisins:
        carte = Polygon(voisin.contour_m)
        if not carte.is_valid:
            carte = carte.buffer(0)
        if carte.is_empty or carte.distance(centre) > recherche_m:
            continue
        if not 0.5 < carte.area / maquette.area < 2.0:
            continue
        dx0, dy0 = carte.centroid.x - centre.x, carte.centroid.y - centre.y
        for i in range(-n, n + 1):
            for j in range(-n, n + 1):
                dx, dy = dx0 + i * pas_m, dy0 + j * pas_m
                part = _recouvrement(translate(maquette, dx, dy), carte)
                if part > meilleur.recouvrement:
                    meilleur = Calage((round(dx, 2), round(dy, 2)), round(part, 3), voisin.identifiant, False)
    return Calage(meilleur.decalage_m, meilleur.recouvrement, meilleur.batiment,
                  meilleur.recouvrement >= RECOUVREMENT_MINIMAL)


def deplacer(voisins: Sequence[Voisin], est_m: float, nord_m: float) -> List[Voisin]:
    """Les mêmes voisins, déplacés : sert à ramener la carte dans le repère de la maquette."""
    return [Voisin(v.identifiant, tuple((x + est_m, y + nord_m) for x, y in v.contour_m), v.hauteur_m,
                   v.hauteur_supposee, v.sol_m) for v in voisins]


def entourer(modele, emprise_m: Sequence[Tuple[float, float]], latitude: float, longitude: float,
             rayon_m: float = 150.0, z_du_sol_m: float = 0.0, carte: Optional[dict] = None) -> dict:
    """Ajoute au modèle les bâtiments voisins, après avoir calé la maquette sur la carte.

    `emprise_m` : le contour au sol du bâtiment étudié, dans le repère du modèle (mètres, Y au nord).
    `carte` : un extrait déjà téléchargé ; sinon il est demandé à la Géoplateforme.
    Rend le compte rendu : calage, nombre de voisins, manques.
    """
    from ladybug_geometry.geometry3d import Vector3D

    carte = carte if carte is not None else telecharger(latitude, longitude, rayon_m + 50.0)
    tous, manques = lire(carte, latitude, longitude)
    calage = caler(emprise_m, tous)
    if calage.sur:
        # La carte est ramenée dans le repère de la maquette : on lui retire le décalage trouvé.
        tous = deplacer(tous, -calage.decalage_m[0], -calage.decalage_m[1])
    else:
        manques.append(
            f"la maquette n'a pas été reconnue sur la carte (meilleur recouvrement {calage.recouvrement:.0%}) : "
            f"sa position est prise telle qu'elle est écrite, à confirmer")
    gardes, bilan = filtrer(tous, emprise_m)
    ombres = masques(gardes, altitude_du_site(tous))
    if z_du_sol_m:
        for ombre in ombres:
            ombre.move(Vector3D(0, 0, z_du_sol_m))
    modele.add_shades(ombres)
    return {"calage": calage, "batiments_sur_la_carte": len(tous), "tri": bilan, "faces_de_masque": len(ombres),
            "manques": manques}
