"""Géométrie des masques : EnergyPlus ne sait ombrer juste qu'avec des faces convexes.

Devant une face qui projette une ombre et qui n'est pas convexe (un toit en L, un mur percé de baies),
EnergyPlus écrit une erreur grave : « casting surfaces [...] non-convex. Shadowing values may be inaccurate »
(Engineering Reference, « Shading Module » : le calcul des ombres par découpe de polygones suppose des
polygones convexes) [S]. Une telle face se découpe donc ici en morceaux convexes, de même aire au total.
"""

from __future__ import annotations

from typing import List

TOLERANCE_M = 0.001
AIRE_MINIMALE_M2 = 1e-4


def convexes(face) -> List:
    """La face (Face3D), découpée en morceaux convexes. Une face déjà convexe et sans trou est rendue telle quelle.

    La face est d'abord découpée en triangles, puis 2 morceaux voisins sont réunis tant que leur réunion reste
    convexe : un rectangle percé d'une baie donne ainsi quelques quadrilatères, pas des dizaines de triangles.
    """
    from ladybug_geometry.geometry2d import Point2D
    from ladybug_geometry.geometry3d import Face3D
    from shapely.geometry import Polygon
    from shapely.geometry.polygon import orient

    if not face.has_holes and face.is_convex:
        return [face]
    plan = face.plane
    maillage = face.triangulated_mesh3d
    morceaux = []
    for triangle in maillage.faces:
        points = [plan.xyz_to_xy(maillage.vertices[i]) for i in triangle]
        polygone = Polygon([(p.x, p.y) for p in points])
        if polygone.area > AIRE_MINIMALE_M2:
            morceaux.append(polygone)
    reuni = True
    while reuni:
        reuni = False
        for i in range(len(morceaux)):
            for j in range(i + 1, len(morceaux)):
                # 2 morceaux qui ne se touchent que par un point ne partagent pas de côté : on ne les réunit pas.
                if morceaux[i].intersection(morceaux[j]).length < TOLERANCE_M:
                    continue
                ensemble = morceaux[i].union(morceaux[j])
                if ensemble.geom_type != "Polygon" or ensemble.interiors:
                    continue
                enveloppe = ensemble.convex_hull
                if enveloppe.area - ensemble.area <= 1e-6 * max(ensemble.area, 1.0):
                    morceaux[i] = enveloppe            # l'enveloppe retire aussi les points alignés
                    del morceaux[j]
                    reuni = True
                    break
            if reuni:
                break
    faces = []
    for polygone in morceaux:
        contour = list(orient(polygone, 1.0).exterior.coords)[:-1]
        faces.append(Face3D([plan.xy_to_xyz(Point2D(x, y)) for x, y in contour]))
    return faces
