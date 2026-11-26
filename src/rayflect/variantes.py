"""Les variantes de conception : changer le bâtiment lui-même, pour mesurer ce que le choix change.

Une protection solaire s'ajoute à un bâtiment donné. Une variante modifie ce bâtiment : agrandir les baies
d'une façade, la passer en bandeau vitré ou en tout vitré, la fermer. Elle se compare à la maquette telle
qu'elle est, sur les mêmes sorties : chauffage, froid, heures chaudes, lumière du jour.

Une variante de façade s'écrit de 2 façons, au choix :
  - `baies_fois` : l'aire de chaque baie existante est multipliée, la baie restant centrée où elle est ;
  - `part_vitree` : la part du mur qui est en verre, de 0 (mur plein) à 0,95 (tout vitré). Les baies de la
    maquette sont alors remplacées par un vitrage de cette aire, centré sur chaque mur.

CE QUI N'EST PAS MODÉLISÉ. Le vitrage d'une variante garde le vitrage de l'étude : un mur-rideau a en réalité
ses propres cadres et ses propres ponts thermiques, qui ne sont pas comptés. La structure n'est pas vérifiée :
l'outil dit ce qu'une façade vitrée fait à la thermique, pas si elle tient debout.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

SECTEURS = ("N", "NE", "E", "SE", "S", "SO", "O", "NO")
PART_VITREE_MAX = 0.95          # au-delà, il ne reste plus de mur pour porter le vitrage dans le modèle
MARGE_M = 0.05                  # une baie ne touche pas le bord de son mur
ACCORD_DES_AIRES = 0.02         # une baie agrandie à moins de 2 % de l'aire visée est tenue pour juste


@dataclass(frozen=True)
class Facade:
    """Le vitrage d'une ou de plusieurs façades, changé. `orientations` : None pour toutes."""
    orientations: Optional[Tuple[str, ...]] = None
    baies_fois: Optional[float] = None
    part_vitree: Optional[float] = None

    def __post_init__(self) -> None:
        if (self.baies_fois is None) == (self.part_vitree is None):
            raise ValueError("donner baies_fois ou part_vitree, l'un des 2")
        if self.baies_fois is not None and self.baies_fois <= 0:
            raise ValueError("baies_fois doit être positif ; pour fermer une façade : part_vitree = 0")
        if self.part_vitree is not None and not 0.0 <= self.part_vitree <= PART_VITREE_MAX:
            raise ValueError(f"part_vitree va de 0 à {PART_VITREE_MAX}")
        inconnues = [o for o in (self.orientations or ()) if o not in SECTEURS]
        if inconnues:
            raise ValueError(f"orientation inconnue : {', '.join(inconnues)}. Connues : {', '.join(SECTEURS)}")


def secteur(azimut_deg: float) -> str:
    return SECTEURS[int(((azimut_deg + 22.5) % 360.0) // 45.0)]


def _murs(modele, orientations):
    for piece in modele.rooms:
        for face in piece.faces:
            if face.type.name != "Wall" or face.boundary_condition.name != "Outdoors":
                continue
            if orientations is None or secteur(face.azimuth) in orientations:
                yield face


def vitrage_par_secteur(modele) -> Dict[str, float]:
    """L'aire vitrée du modèle par orientation, en mètres carrés."""
    aires: Dict[str, float] = {}
    for face in _murs(modele, None):
        if face.apertures:
            cle = secteur(face.azimuth)
            aires[cle] = aires.get(cle, 0.0) + sum(b.area for b in face.apertures)
    return {cle: round(aire, 2) for cle, aire in sorted(aires.items(), key=lambda c: SECTEURS.index(c[0]))}


def _repere(face):
    """Le mur vu de dehors : (origine, vecteur le long du mur, étendue le long, étendue en hauteur)."""
    m = face.normal
    ux, uy = -m.y, m.x
    le_long = [v.x * ux + v.y * uy for v in face.geometry.vertices]
    hauts = [v.z for v in face.geometry.vertices]
    return (ux, uy), (min(le_long), max(le_long)), (min(hauts), max(hauts))


def _rectangle(baie, u):
    le_long = [v.x * u[0] + v.y * u[1] for v in baie.geometry.vertices]
    hauts = [v.z for v in baie.geometry.vertices]
    return [min(le_long), max(le_long), min(hauts), max(hauts)]


def _agrandir(face, fois: float) -> bool:
    """Multiplie l'aire de chaque baie du mur, en place. Faux quand la place manque : rien n'est alors changé."""
    from honeybee.aperture import Aperture
    from ladybug_geometry.geometry3d import Face3D, Point3D

    u, (gauche_mur, droite_mur), (bas_mur, haut_mur) = _repere(face)
    m, p0 = face.normal, face.geometry.vertices[0]
    base = p0.x * m.x + p0.y * m.y
    nouveaux = []
    for baie in face.apertures:
        if abs(baie.normal.z) > 0.01 or len(baie.geometry.vertices) != 4:
            return False
        g, d, b, h = _rectangle(baie, u)
        visee = (d - g) * (h - b) * fois
        echelle = math.sqrt(fois)
        centre, milieu = (g + d) / 2.0, (b + h) / 2.0
        demi_l, demi_h = (d - g) * echelle / 2.0, (h - b) * echelle / 2.0
        # La hauteur bute d'abord sur le plancher et le plafond : ce qui manque se reprend en largeur.
        b2, h2 = max(milieu - demi_h, bas_mur + MARGE_M), min(milieu + demi_h, haut_mur - MARGE_M)
        demi_l = max(demi_l, visee / max(h2 - b2, 1e-6) / 2.0)
        g2, d2 = max(centre - demi_l, gauche_mur + MARGE_M), min(centre + demi_l, droite_mur - MARGE_M)
        if abs((d2 - g2) * (h2 - b2) - visee) > ACCORD_DES_AIRES * visee:
            return False
        nouveaux.append((baie.identifier, g2, d2, b2, h2))
    for k, (_i, g, d, b, h) in enumerate(nouveaux):
        for _j, g3, d3, b3, h3 in nouveaux[k + 1:]:
            if g < d3 + MARGE_M and g3 < d + MARGE_M and b < h3 + MARGE_M and b3 < h + MARGE_M:
                return False                # 2 baies agrandies se recouvriraient

    def point(t, z):
        return Point3D(base * m.x + t * u[0], base * m.y + t * u[1], z)

    face.remove_apertures()
    for identifiant, g, d, b, h in nouveaux:
        face.add_aperture(Aperture(identifiant, Face3D([point(g, b), point(d, b), point(d, h), point(g, h)])))
    return True


def poser(modele, variante: Facade) -> List[str]:
    """Applique la variante au modèle. Rend ce qu'il faut dire à l'utilisateur de ce qui a été fait.

    À appeler avant de poser les parois, l'aération et les protections : celles-ci se règlent sur les baies.
    """
    murs = list(_murs(modele, variante.orientations))
    cotes = "toutes les façades" if variante.orientations is None else "façades " + ", ".join(variante.orientations)
    if not murs:
        return [f"variante sans effet : aucun mur extérieur sur {cotes}"]
    avant = sum(b.area for face in murs for b in face.apertures)
    redessines = 0
    for face in murs:
        if variante.part_vitree is not None:
            face.remove_apertures()
            if variante.part_vitree > 0:
                face.apertures_by_ratio(variante.part_vitree)
            continue
        if not face.apertures:
            continue
        part = min(PART_VITREE_MAX, face.aperture_ratio * variante.baies_fois)
        if not _agrandir(face, variante.baies_fois):
            face.remove_apertures()
            face.apertures_by_ratio(part)
            redessines += 1
    apres = sum(b.area for face in murs for b in face.apertures)
    dit = [f"{cotes} : {avant:.1f} m² de vitrage dans la maquette, {apres:.1f} m² dans la variante"]
    if variante.baies_fois is not None and avant > 0 and apres < avant * variante.baies_fois * (1 - ACCORD_DES_AIRES):
        dit.append(f"l'aire visée ({avant * variante.baies_fois:.1f} m²) dépasse ce que les murs peuvent porter : "
                   f"le vitrage est plafonné à {PART_VITREE_MAX:.0%} du mur")
    if redessines:
        dit.append(f"sur {redessines} mur(s), les baies agrandies se touchaient ou sortaient du mur : elles sont "
                   f"remplacées par un vitrage de même aire, centré sur le mur")
    return dit
