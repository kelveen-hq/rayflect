"""Des formes de plateau tirées au hasard, pour éprouver le découpage en zones.

Le tirage est reproductible : une graine donne toujours les mêmes formes. Les familles couvrent ce qu'on
rencontre en plan : rectangles, équerres, U, T, croix, plateaux à décrochés, polygones quelconques convexes,
le tout tourné d'un angle quelconque.
"""

from __future__ import annotations

import math
import random
from typing import List, Tuple

Contour = List[Tuple[float, float]]


def _tourner(points: Contour, angle_deg: float) -> Contour:
    a = math.radians(angle_deg)
    return [(round(x * math.cos(a) - y * math.sin(a), 4), round(x * math.sin(a) + y * math.cos(a), 4))
            for x, y in points]


def rectangle(h: random.Random) -> Contour:
    largeur, profondeur = h.uniform(12, 70), h.uniform(10, 40)
    return [(0, 0), (largeur, 0), (largeur, profondeur), (0, profondeur)]


def equerre(h: random.Random) -> Contour:
    a, b = h.uniform(25, 60), h.uniform(25, 60)
    e1, e2 = h.uniform(11, 18), h.uniform(11, 18)
    return [(0, 0), (a, 0), (a, e1), (e2, e1), (e2, b), (0, b)]


def en_u(h: random.Random) -> Contour:
    a, b, e, c = h.uniform(40, 70), h.uniform(30, 50), h.uniform(11, 16), h.uniform(12, 20)
    return [(0, 0), (a, 0), (a, b), (a - e, b), (a - e, c), (e, c), (e, b), (0, b)]


def en_t(h: random.Random) -> Contour:
    a, e, b, f = h.uniform(40, 70), h.uniform(11, 16), h.uniform(25, 45), h.uniform(12, 18)
    g = (a - f) / 2.0
    return [(0, 0), (a, 0), (a, e), (g + f, e), (g + f, b), (g, b), (g, e), (0, e)]


def en_croix(h: random.Random) -> Contour:
    a, e = h.uniform(40, 60), h.uniform(12, 18)
    g = (a - e) / 2.0
    return [(g, 0), (g + e, 0), (g + e, g), (a, g), (a, g + e), (g + e, g + e), (g + e, a), (g, a),
            (g, g + e), (0, g + e), (0, g), (g, g)]


def a_decroches(h: random.Random) -> Contour:
    """Un rectangle dont un long côté porte 1 à 3 petits décrochés, comme une façade à redents."""
    largeur, profondeur = h.uniform(30, 70), h.uniform(14, 30)
    points: Contour = [(0, 0)]
    x = 0.0
    for _ in range(h.randint(1, 3)):
        pas = h.uniform(4, largeur / 4)
        retrait = h.uniform(0.3, 2.5)
        if x + 2 * pas >= largeur - 1:
            break
        points += [(x + pas, 0), (x + pas, retrait), (x + 2 * pas, retrait), (x + 2 * pas, 0)]
        x += 2 * pas + h.uniform(1, 4)
        if x >= largeur - 1:
            break
        points.append((x, 0))
    points += [(largeur, 0), (largeur, profondeur), (0, profondeur)]
    propre = [points[0]]
    for p in points[1:]:
        if math.hypot(p[0] - propre[-1][0], p[1] - propre[-1][1]) > 0.05:
            propre.append(p)
    return propre


def convexe(h: random.Random) -> Contour:
    n = h.randint(5, 9)
    angles = sorted(h.uniform(0, 2 * math.pi) for _ in range(n))
    rx, ry = h.uniform(15, 35), h.uniform(12, 30)
    points = [(rx * math.cos(a), ry * math.sin(a)) for a in angles]
    propre = [points[0]]
    for p in points[1:]:
        if math.hypot(p[0] - propre[-1][0], p[1] - propre[-1][1]) > 2.0:
            propre.append(p)
    return propre


FAMILLES = {"rectangle": rectangle, "équerre": equerre, "U": en_u, "T": en_t, "croix": en_croix,
            "décrochés": a_decroches, "convexe": convexe}


def tirer(n: int, graine: int = 2026) -> List[Tuple[str, Contour]]:
    """n formes : (famille, contour). Les familles tournent à tour de rôle ; chaque forme a son angle."""
    hasard = random.Random(graine)
    noms = list(FAMILLES)
    formes = []
    for k in range(n):
        famille = noms[k % len(noms)]
        contour = FAMILLES[famille](hasard)
        formes.append((famille, _tourner(contour, hasard.uniform(0, 360))))
    return formes
