"""Le relevé d'un bâtiment : ce que le calcul a besoin de savoir, d'où que cela vienne.

Une maquette IFC ou des plans DXF donnent le même relevé : des niveaux avec leur contour et leurs altitudes,
des baies avec leur taille, leur position et le côté vers lequel elles regardent, et la liste de ce qui
manque, à demander. Toute la suite de la chaîne ne connaît que lui.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Dict, List, Optional

SECTEURS = ("N", "NE", "E", "SE", "S", "SO", "O", "NO")


@dataclass
class Baie:
    identifiant: str
    nom: str
    niveau: Optional[str]
    largeur_m: float
    hauteur_m: float
    aire_m2: float
    allege_m: Optional[float]           # au-dessus du plancher de son niveau
    azimut_deg: Optional[float]         # 0 = nord, 90 = est, 180 = sud ; None pour une baie de toit
    secteur: Optional[str]
    inclinaison_deg: float              # 90 = verticale, 0 = à plat
    centre_m: tuple
    normale_xy: tuple                   # vers le dehors, dans le repère de la maquette
    z_bas_m: float
    z_haut_m: float
    mur: Optional[str]
    mur_exterieur: Optional[bool]       # None : la maquette ne le dit pas
    taille_declaree_m: Optional[tuple]  # largeur et hauteur écrites dans la maquette, si elles y sont


@dataclass
class Niveau:
    nom: str
    altitude_m: float
    n_baies: int = 0
    aire_espaces_m2: Optional[float] = None
    emprise_m: Optional[list] = None    # contour extérieur du niveau, points (x, y) dans le repère de la maquette
    plancher_m: Optional[float] = None  # altitudes basse et haute des locaux du niveau
    plafond_m: Optional[float] = None
    aire_emprise_m2: Optional[float] = None
    chauffe: bool = True                # faux : un niveau que rien ne chauffe (atelier, stockage, garage)


@dataclass
class Releve:
    fichier: str
    schema: str
    logiciel: str
    latitude: Optional[float]
    longitude: Optional[float]
    altitude_m: Optional[float]
    nord_deg: float                     # angle du nord par rapport à l'axe Y de la maquette, sens horaire
    niveaux: List[Niveau] = field(default_factory=list)
    baies: List[Baie] = field(default_factory=list)
    n_murs: int = 0
    n_murs_exterieurs: Optional[int] = None
    n_espaces: int = 0
    n_protections_solaires: int = 0
    altitude_du_zero_m: float = 0.0     # altitude, dans la géométrie de la maquette, du zéro du bâtiment
    n_murs_rideaux: int = 0
    manques: List[str] = field(default_factory=list)
    # Les murs mitoyens : un segment ((x1, y1), (x2, y2)) par mur, dans le repère de la maquette. Le mur du
    # volume qui le suit n'échange pas avec le dehors : le voisin est supposé chauffé comme le bâtiment.
    mitoyens_m: List[tuple] = field(default_factory=list)
    provenances: Dict[str, str] = field(default_factory=dict)    # par champ lu : d'où vient sa valeur
    non_lus: List[str] = field(default_factory=list)             # ce que la source dit et que le calcul ne prend pas

    def vitrage_par_secteur(self) -> dict:
        """Aire vitrée par orientation, baies intérieures exclues."""
        aires: dict = {}
        for b in self.baies:
            if b.mur_exterieur is False:
                continue
            cle = b.secteur or "toit"
            aires[cle] = round(aires.get(cle, 0.0) + b.aire_m2, 2)
        return aires


def _azimut(normale_xy, nord) -> float:
    est = (nord[1], -nord[0])
    return math.degrees(math.atan2(normale_xy[0] * est[0] + normale_xy[1] * est[1],
                                   normale_xy[0] * nord[0] + normale_xy[1] * nord[1])) % 360.0


def secteur(azimut_deg: float) -> str:
    return SECTEURS[int(((azimut_deg + 22.5) % 360.0) // 45.0)]


def resume(r: Releve) -> str:
    lignes = [
        f"{r.fichier} ({r.schema}, {r.logiciel})",
        f"  site : latitude {r.latitude}, longitude {r.longitude}, nord à {r.nord_deg}° de l'axe Y",
        f"  {len(r.niveaux)} niveaux, {r.n_murs} murs dont {r.n_murs_exterieurs} extérieurs, "
        f"{r.n_espaces} locaux, {len(r.baies)} baies, {r.n_murs_rideaux} murs-rideaux, "
        f"{r.n_protections_solaires} protections solaires",
    ]
    for n in r.niveaux:
        lignes.append(f"    {n.nom:<28} altitude {n.altitude_m:>7.2f} m  {n.n_baies:>3} baies  locaux {n.aire_espaces_m2} m²"
                      f"  emprise {n.aire_emprise_m2} m² en {len(n.emprise_m or [])} points, de {n.plancher_m} à {n.plafond_m} m"
                      + ("" if n.chauffe else "  NON CHAUFFÉ"))
    lignes.append(f"  vitrage par orientation (m²) : {r.vitrage_par_secteur()}")
    if r.mitoyens_m:
        longueur = sum(math.hypot(b[0] - a[0], b[1] - a[1]) for a, b in r.mitoyens_m)
        lignes.append(f"  {len(r.mitoyens_m)} mur(s) mitoyen(s), {longueur:.1f} m de long")
    for m in r.manques:
        lignes.append(f"  À DEMANDER : {m}")
    for m in r.non_lus:
        lignes.append(f"  NON REPRIS : {m}")
    return "\n".join(lignes)
