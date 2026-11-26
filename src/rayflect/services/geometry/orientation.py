# -*- coding: utf-8 -*-
"""L'orientation des façades du bâtiment : une seule règle de secteur, et les azimuts réels.

Les façades de l'enveloppe sont calculées à leur azimut réel, et non ramenées au point cardinal le plus proche.

UNE SEULE RÈGLE DE SECTEUR. `secteur` range tout azimut dans un quart de ciel de 90°, à bornes demi-ouvertes. Tout
le code qui range une façade, un vitrage ou un mur par orientation passe par cette fonction : une façade à 45 ou
225° pile est ainsi rangée au même endroit partout.

LE VOCABULAIRE. Les clés "south"/"north"/"east"/"west" de la requête (`windows_by_orientation`,
`party_wall_orientations`, murs d'une zone) et les noms "Sud"/"Nord"/"Est"/"Ouest" de l'enveloppe nomment un SECTEUR
de 90°, pas un angle. Le secteur est un libellé (la table du vitrage n'existe que par secteur) ; l'angle porté par
chaque face du modèle est réel (`azimuts_facades`).
"""
from __future__ import annotations

import math
from typing import Dict, Iterable, Optional, Tuple

# L'azimut qui centre chaque secteur (0 = nord, sens horaire). L'ordre est celui dans lequel les façades de
# l'enveloppe sont énumérées.
CENTRES_DEG: Dict[str, float] = {"south": 180.0, "north": 0.0, "east": 90.0, "west": 270.0}

_PAR_QUART = ("north", "east", "south", "west")


def secteur(azimuth_deg: float) -> str:
    """Le secteur de 90° qui contient cet azimut, en vocabulaire de requête.

    [315, 45) nord ; [45, 135) est ; [135, 225) sud ; [225, 315) ouest.

    Bornes demi-ouvertes : une égalité (45, 135, 225, 315°) va au secteur suivant dans le sens horaire. La requête
    range le vitrage selon cette règle, le calcul le relit selon la même.
    """
    return _PAR_QUART[int(((float(azimuth_deg) + 45.0) % 360.0) // 90.0)]


def ecart_deg(azimuth_deg: float, reference_deg: float) -> float:
    """L'écart signé de `azimuth_deg` à `reference_deg`, dans [-180, 180)."""
    return (float(azimuth_deg) - float(reference_deg) + 180.0) % 360.0 - 180.0


def rotation_batiment_deg(equipees: Iterable[Tuple[float, float]]) -> float:
    """De combien le bâtiment est tourné par rapport aux points cardinaux, dans [-45, 45).

    `equipees` : couples (azimut, poids) des façades équipées. La rotation est celle de la façade de plus grand poids
    (la première à égalité), mesurée depuis le centre de son secteur. Sans façade équipée, zéro.
    """
    equipees = list(equipees)
    if not equipees:
        return 0.0
    azimut = max(equipees, key=lambda e: e[1])[0]
    return ecart_deg(azimut, CENTRES_DEG[secteur(azimut)])


def azimuts_facades(equipees: Iterable[Tuple[float, float]]) -> Dict[str, float]:
    """L'azimut réel de chacune des 4 faces de l'enveloppe, par secteur.

    Un secteur qui porte des façades équipées regarde où ELLES regardent : la moyenne circulaire de leurs azimuts,
    pondérée par leurs poids ; un seul azimut est rendu tel quel (sans trigonométrie), pour qu'une façade à 180°
    rende 180.0 et non 180.00000000000003.

    Un secteur sans façade équipée suit la rotation du bâtiment (`rotation_batiment_deg`) : l'enveloppe est un
    rectangle, ses murs sont à 90° les uns des autres. C'est une supposition (la requête ne dit que le vitrage de ces
    secteurs, pas leur angle), et la seule qui décrive un bâtiment : une façade sud-ouest dont les 3 autres resteraient
    à 0, 90 et 180° ferait un mur à 45° de son voisin.

    Un bâtiment à façades cardinales rend exactement 180/0/90/270.
    """
    equipees = [(float(a), float(n)) for a, n in equipees]
    delta = rotation_batiment_deg(equipees)
    azimuts = {o: (centre + delta) % 360.0 for o, centre in CENTRES_DEG.items()}
    groupes: Dict[str, list] = {}
    for azimut, n in equipees:
        groupes.setdefault(secteur(azimut), []).append((azimut, n))
    for o, groupe in groupes.items():
        if len({a % 360.0 for a, _ in groupe}) == 1:
            azimuts[o] = groupe[0][0] % 360.0
            continue
        poids = [max(0.0, n) for _, n in groupe]
        if sum(poids) <= 0:
            poids = [1.0] * len(groupe)
        x = math.fsum(p * math.cos(math.radians(a)) for p, (a, _) in zip(poids, groupe))
        y = math.fsum(p * math.sin(math.radians(a)) for p, (a, _) in zip(poids, groupe))
        azimuts[o] = math.degrees(math.atan2(y, x)) % 360.0
    return azimuts


# ── L'AZIMUT DE CHAQUE FACE, DONNÉ PAR LA REQUÊTE ───────────────────────────────────────────────────────────────
#
# L'appelant qui connaît le dessin du bâtiment peut donner l'azimut de CHAQUE face, équipée ou non, dans
# `azimuts_faces_deg` = {secteur: azimut}, les clés de `windows_by_orientation`. Une face donnée remplace la
# supposition du rectangle pour son secteur ; un secteur qui porte des façades équipées garde LEUR azimut, et la
# requête ne peut pas le contredire. Sans le champ, rien ne change.
ECART_FACE_EQUIPEE_MAX_DEG = 1.0


def valider_azimuts_faces(azimuts_faces: Optional[Dict[str, float]],
                          equipees: Iterable[Tuple[float, float]]) -> Optional[Dict[str, float]]:
    """Le champ `azimuts_faces_deg` relu, ou ValueError avec la raison, en français.

    Refusé : une clé hors de south, north, east, west ; un azimut non fini ou hors de [0, 360[ ; un azimut hors du
    secteur de sa clé (la règle `secteur`, 225° est à l'ouest) ; dans un secteur qui porte UNE seule façade équipée (un
    seul azimut), un azimut de face qui s'en écarte de plus de 1°. Un secteur à plusieurs façades équipées d'azimuts
    différents garde leur moyenne : la face donnée n'y est pas relue."""
    if azimuts_faces is None:
        return None
    if not isinstance(azimuts_faces, dict):
        raise ValueError("azimuts_faces_deg : un objet {secteur: azimut} est attendu, par exemple "
                         "{\"south\": 172.0, \"west\": 262.0}")
    out: Dict[str, float] = {}
    for cle, valeur in azimuts_faces.items():
        if cle not in CENTRES_DEG:
            raise ValueError(f"azimuts_faces_deg : secteur inconnu « {cle} » (attendu : south, north, east, west)")
        try:
            az = float(valeur)
        except (TypeError, ValueError):
            raise ValueError(f"azimuts_faces_deg[{cle}] : « {valeur} » n'est pas un azimut en degrés") from None
        if not math.isfinite(az) or not 0.0 <= az < 360.0:
            raise ValueError(f"azimuts_faces_deg[{cle}] : {valeur} hors de [0, 360[")
        if secteur(az) != cle:
            raise ValueError(f"azimuts_faces_deg[{cle}] : {az:g}° appartient au secteur « {secteur(az)} » "
                             "(bornes à 45, 135, 225 et 315°, l'égalité au secteur suivant dans le sens horaire)")
        out[cle] = az
    par_secteur: Dict[str, set] = {}
    for a, _n in equipees:
        par_secteur.setdefault(secteur(a), set()).add(float(a) % 360.0)
    for cle, az in out.items():
        vus = par_secteur.get(cle)
        if vus and len(vus) == 1:
            a = next(iter(vus))
            if abs(ecart_deg(az, a)) > ECART_FACE_EQUIPEE_MAX_DEG:
                raise ValueError(f"azimuts_faces_deg[{cle}] : {az:g}° contredit la façade équipée de ce secteur "
                                 f"({a:g}°) ; une face et ce qui l'équipe ont le même azimut")
    return out


def azimuts_enveloppe(equipees: Iterable[Tuple[float, float]],
                      azimuts_faces: Optional[Dict[str, float]] = None) -> Tuple[Dict[str, float], Dict[str, str]]:
    """(azimut de chaque face, d'où il vient) : les façades équipées, puis la requête, puis la rotation du bâtiment."""
    equipees = [(float(a), float(n)) for a, n in equipees]
    azimuts = azimuts_facades(equipees)
    equipes = {secteur(a) for a, _ in equipees}
    sources = {o: ("facades_equipees" if o in equipes else "rotation du bâtiment") for o in CENTRES_DEG}
    for cle, az in (azimuts_faces or {}).items():
        if cle not in equipes:
            azimuts[cle] = float(az) % 360.0
            sources[cle] = "requête (azimuts_faces_deg)"
    return azimuts, sources


def est_cardinal(azimuts: Dict[str, float]) -> bool:
    """Vrai quand chaque face regarde exactement le centre de son secteur."""
    return all(azimuts.get(o) == c for o, c in CENTRES_DEG.items())
