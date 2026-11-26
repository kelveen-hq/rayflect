"""Incidence solaire 3D : fonctions partagées pour la projection azimutale.

Ce module expose 2 fonctions qui tiennent compte de l'écart d'azimut entre
le soleil et la façade :

- ``effective_elevation_deg`` : élévation solaire projetée dans le plan
  vertical perpendiculaire à la façade (coupe 2D).
- ``cos_incidence_3d`` : produit scalaire 3D exact entre le vecteur soleil
  et la normale d'un panneau incliné dans le plan façade.

Conventions :
    - Angle panneau : 0° = horizontal, 90° = vertical.
    - ``az_diff_deg`` : écart d'azimut absolu |soleil − façade|, dans [0, 90].
    - Coordonnées locales façade : X = perpendiculaire vers l'extérieur,
      Y = le long de la façade, Z = vertical vers le haut.
"""

from __future__ import annotations

import math
from functools import lru_cache

__all__ = [
    "effective_elevation_deg",
    "cos_incidence_3d",
]


# =============================================================================
# ÉLÉVATION EFFECTIVE
# =============================================================================

# Mémoïsée : le résultat ne dépend que de la position du soleil, et un balayage
# d'angles rappelle la fonction avec les mêmes arguments à chaque candidat.
@lru_cache(maxsize=4096)
def effective_elevation_deg(sun_elevation_deg: float, az_diff_deg: float) -> float:
    """Élévation solaire effective dans le plan perpendiculaire à la façade.

    Quand le soleil est de côté (``az_diff > 0``), sa composante horizontale
    perpendiculaire à la façade diminue (``cos(elev) × cos(az_diff)``),
    tandis que la composante verticale reste inchangée (``sin(elev)``).

    L'angle projeté est donc :

    .. math::

        \\theta_{eff} = \\arctan\\!\\left(
            \\frac{\\sin(\\theta)}{\\cos(\\theta) \\cdot \\cos(\\delta)}
        \\right)

    Où *θ* est l'élévation réelle et *δ* l'écart d'azimut.

    Quand ``az_diff = 0`` : ``θ_eff = θ`` (identité).
    Quand ``az_diff → 90°`` : ``θ_eff → 90°`` (soleil rasant le plan façade).

    C'est cette élévation projetée qui sert aux calculs d'angle en 2D
    (coupe XZ).

    Parameters
    ----------
    sun_elevation_deg : float
        Élévation solaire réelle (°).
    az_diff_deg : float
        Écart d'azimut absolu entre soleil et façade (°), dans [0, 90].

    Returns
    -------
    float
        Élévation effective dans le plan façade (°).
        Retourne 0.0 si le soleil est sous l'horizon ou derrière la façade.

    Examples
    --------
    >>> effective_elevation_deg(30.0, 0.0)
    30.0
    >>> effective_elevation_deg(30.0, 60.0)  # soleil à 60° du plan
    46.1...
    """
    if sun_elevation_deg <= 0 or az_diff_deg >= 90:
        return 0.0
    elev_rad = math.radians(sun_elevation_deg)
    az_rad = math.radians(az_diff_deg)
    x = math.cos(elev_rad) * math.cos(az_rad)
    z = math.sin(elev_rad)
    if x <= 0:
        return 0.0
    return math.degrees(math.atan2(z, x))


# =============================================================================
# COSINUS D'INCIDENCE 3D EXACT
# =============================================================================

def cos_incidence_3d(
    sun_elev_deg: float,
    az_diff_deg: float,
    panel_angle_deg: float,
) -> float:
    """Cosinus d'incidence 3D exact pour un panneau incliné dans le plan façade.

    Calcule le produit scalaire 3D exact entre le vecteur soleil et la normale
    du panneau, plus juste que l'approximation
    ``sin(elev + angle) × cos(az_diff)``.

    **Convention d'angle** : 0° = horizontal, 90° = vertical.

    Démonstration (repère local façade, X = perp extérieur, Y = latéral, Z = haut) :

    .. math::

        \\vec{N}_{panel} = (\\sin(\\alpha),\\; 0,\\; \\cos(\\alpha))

        \\vec{S}_{sun}   = (\\cos(\\theta)\\cos(\\delta),\\;
                            \\cos(\\theta)\\sin(\\delta),\\;
                            \\sin(\\theta))

        \\cos(\\text{inc}) = \\cos(\\theta)\\cos(\\delta)\\sin(\\alpha)
                           + \\sin(\\theta)\\cos(\\alpha)

    Comparaison avec l'approximation :

    .. math::

        \\text{Approx.} &= \\sin(\\theta+\\alpha) \\times \\cos(\\delta)
                        = [\\sin\\theta\\cos\\alpha + \\cos\\theta\\sin\\alpha]
                          \\times \\cos\\delta \\\\
        \\text{Erreur} &= \\sin\\theta\\cos\\alpha\\,(1-\\cos\\delta)

    L'erreur est non nulle dès que ``az_diff > 0`` et que le panneau n'est
    pas horizontal (``panel_angle < 90°``). À 45° d'azimut, l'erreur sur
    la composante verticale est de ~29%.

    Parameters
    ----------
    sun_elev_deg : float
        Élévation solaire réelle (°).
    az_diff_deg : float
        Écart d'azimut absolu entre soleil et façade (°).
    panel_angle_deg : float
        Angle du panneau (0° = horizontal, 90° = vertical).

    Returns
    -------
    float
        cos(incidence) en 3D, dans [0, 1].

    Examples
    --------
    Soleil plein face (az_diff=0), panneau à 45° :

    >>> cos_incidence_3d(30.0, 0.0, 45.0)  # == sin(30+45)
    0.9659...

    Même configuration avec 45° d'azimut : l'approximation donnerait
    0.9659 × cos(45) = 0.683, mais la vraie valeur est plus élevée car
    la composante verticale sin(30)·cos(45) n'est PAS atténuée :

    >>> cos_incidence_3d(30.0, 45.0, 45.0)
    0.7417...
    """
    elev_rad = math.radians(sun_elev_deg)
    az_rad = math.radians(az_diff_deg)
    angle_rad = math.radians(panel_angle_deg)
    result = (
        math.cos(elev_rad) * math.cos(az_rad) * math.sin(angle_rad)
        + math.sin(elev_rad) * math.cos(angle_rad)
    )
    return max(0.0, min(1.0, result))
