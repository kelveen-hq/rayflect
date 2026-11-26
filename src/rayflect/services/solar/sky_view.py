"""Calcul du Sky View Factor (SVF) pour surfaces inclinées.

Le Sky View Factor (F_sky) représente la fraction du ciel visible depuis
une surface. C'est crucial pour le calcul du rayonnement diffus (DHI).

Ce module implémente 2 modèles de complexité croissante :
1. Modèle simple : F_sky = (1 + cos(β)) / 2  (surface inclinée isolée)
2. Modèle avec obstacle : prend en compte un obstacle au-dessus (balcon, auvent)

Il calcule aussi la part du rayonnement réfléchi par le sol et le DHI
effectif reçu par la surface.

Références:
- Perez et al. (1990) - Modèle de ciel anisotrope
- Tian et al. (2001) - SVF pour surfaces inclinées avec obstacles
- ISO 52010-1:2017 - Energy performance of buildings
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Tuple


# =============================================================================
# CONSTANTES
# =============================================================================

# Albédo typique du sol (réflexion au sol)
DEFAULT_GROUND_ALBEDO = 0.2


# =============================================================================
# STRUCTURES DE DONNÉES
# =============================================================================

@dataclass(frozen=True)
class SkyViewResult:
    """Résultat complet du calcul de Sky View Factor.

    Attributes
    ----------
    f_sky : float
        Facteur de vue du ciel (0-1). Fraction de l'hémisphère céleste visible.
    f_ground : float
        Facteur de vue du sol (0-1). Pour le calcul de la réflexion au sol.
    f_obstacle : float
        Facteur de vue des obstacles (0-1). Partie masquée par les obstacles.
    effective_tilt_deg : float
        Inclinaison effective de la surface (degrés).
    details : dict
        Détails du calcul pour debug/visualisation.
    """
    f_sky: float
    f_ground: float
    f_obstacle: float
    effective_tilt_deg: float
    details: dict


@dataclass(frozen=True)
class ObstacleConfig:
    """Configuration d'un obstacle horizontal (balcon, auvent).

    Attributes
    ----------
    depth_m : float
        Profondeur de l'obstacle (projection horizontale), en mètres.
    height_above_m : float
        Distance verticale entre la surface et le bas de l'obstacle, en mètres.
    width_m : float
        Largeur de l'obstacle (0 = infini = obstacle continu), en mètres.
    """
    depth_m: float
    height_above_m: float
    width_m: float = 0.0  # 0 = obstacle infini (balcon filant)



# =============================================================================
# MODÈLE SIMPLE : Surface inclinée sans obstacle
# =============================================================================

def compute_simple_svf(tilt_from_horizontal_deg: float) -> float:
    """Sky View Factor pour une surface inclinée sans obstacle.

    Formule classique pour ciel isotrope :
        F_sky = (1 + cos(β)) / 2

    où β est l'inclinaison depuis l'horizontal.

    Parameters
    ----------
    tilt_from_horizontal_deg : float
        Angle d'inclinaison depuis l'horizontal (degrés).
        - 0° = horizontal (voit tout le ciel) → F_sky = 1
        - 90° = vertical (voit la moitié du ciel) → F_sky = 0.5
        - 180° = face au sol → F_sky = 0

    Returns
    -------
    float
        Facteur de vue du ciel (0 à 1).

    Examples
    --------
    >>> compute_simple_svf(0)    # Horizontal
    1.0
    >>> compute_simple_svf(90)   # Vertical
    0.5
    >>> compute_simple_svf(45)   # 45°
    0.8535...
    """
    beta_rad = math.radians(tilt_from_horizontal_deg)
    return 0.5 * (1 + math.cos(beta_rad))


def compute_ground_view_factor(tilt_from_horizontal_deg: float) -> float:
    """Facteur de vue du sol pour une surface inclinée.

    Formule : F_ground = (1 - cos(β)) / 2

    Complémentaire au SVF : F_sky + F_ground = 1 (sans obstacles)

    Parameters
    ----------
    tilt_from_horizontal_deg : float
        Angle d'inclinaison depuis l'horizontal (degrés).

    Returns
    -------
    float
        Facteur de vue du sol (0 à 1).
    """
    beta_rad = math.radians(tilt_from_horizontal_deg)
    return 0.5 * (1 - math.cos(beta_rad))


# =============================================================================
# MODÈLE AVEC OBSTACLE HORIZONTAL
# =============================================================================

def compute_svf_with_obstacle(
    tilt_from_horizontal_deg: float,
    obstacle: ObstacleConfig,
) -> SkyViewResult:
    """Sky View Factor avec un obstacle horizontal au-dessus.

    Prend en compte un obstacle (balcon, auvent) qui masque une partie du ciel.

    L'obstacle crée un angle de masquage :
        α_mask = atan(depth / height_above)

    Parameters
    ----------
    tilt_from_horizontal_deg : float
        Inclinaison de la surface (degrés).
    obstacle : ObstacleConfig
        Configuration de l'obstacle horizontal.

    Returns
    -------
    SkyViewResult
        Résultat complet avec détails.

    Notes
    -----
    Pour une surface sous un balcon :
    - depth = profondeur du balcon
    - height_above = distance entre la surface et le balcon
    """
    # SVF de base sans obstacle
    f_sky_base = compute_simple_svf(tilt_from_horizontal_deg)
    f_ground_base = compute_ground_view_factor(tilt_from_horizontal_deg)

    if obstacle.depth_m <= 0 or obstacle.height_above_m <= 0:
        return SkyViewResult(
            f_sky=f_sky_base,
            f_ground=f_ground_base,
            f_obstacle=0.0,
            effective_tilt_deg=tilt_from_horizontal_deg,
            details={"method": "simple", "no_obstacle": True},
        )

    # Angle de masquage par l'obstacle
    mask_angle_rad = math.atan(obstacle.depth_m / obstacle.height_above_m)
    mask_angle_deg = math.degrees(mask_angle_rad)

    # Fraction du ciel masquée
    # Approximation : le masque coupe une calotte sphérique
    # Pour un obstacle horizontal au-dessus, il masque les angles > (90 - mask_angle)
    tilt_rad = math.radians(tilt_from_horizontal_deg)

    # L'obstacle masque la partie haute du ciel visible
    # Fraction masquée ≈ sin²(mask_angle/2) pour une surface inclinée
    f_obstacle = 0.5 * (1 - math.cos(mask_angle_rad)) * (1 + math.cos(tilt_rad))
    f_obstacle = min(f_obstacle, f_sky_base)  # Ne peut pas masquer plus que le ciel visible

    f_sky_effective = f_sky_base - f_obstacle

    return SkyViewResult(
        f_sky=max(0, f_sky_effective),
        f_ground=f_ground_base,
        f_obstacle=f_obstacle,
        effective_tilt_deg=tilt_from_horizontal_deg,
        details={
            "method": "obstacle",
            "mask_angle_deg": mask_angle_deg,
            "f_sky_base": f_sky_base,
            "obstacle_depth_m": obstacle.depth_m,
            "obstacle_height_m": obstacle.height_above_m,
        },
    )


# =============================================================================
# CONTRIBUTION DU SOL (RÉFLEXION)
# =============================================================================

def compute_ground_reflected_irradiance(
    ghi_w_m2: float,
    f_ground: float,
    ground_albedo: float = DEFAULT_GROUND_ALBEDO,
) -> float:
    """Calcule l'irradiance diffuse réfléchie par le sol.

    Formule : E_ground = GHI × ρ × F_ground

    où :
    - GHI = irradiance globale horizontale (W/m²)
    - ρ = albédo du sol (0.2 typique)
    - F_ground = facteur de vue du sol

    Parameters
    ----------
    ghi_w_m2 : float
        Irradiance globale horizontale (W/m²).
    f_ground : float
        Facteur de vue du sol (0-1).
    ground_albedo : float
        Albédo du sol (0-1). Valeurs typiques :
        - Herbe : 0.2
        - Béton : 0.3
        - Neige : 0.8
        - Asphalte : 0.1

    Returns
    -------
    float
        Irradiance réfléchie par le sol (W/m²).
    """
    return ghi_w_m2 * ground_albedo * f_ground


# =============================================================================
# FONCTION PRINCIPALE DE CALCUL DHI
# =============================================================================

def compute_effective_dhi(
    dhi_w_m2: float,
    ghi_w_m2: float,
    svf_result: SkyViewResult,
    ground_albedo: float = DEFAULT_GROUND_ALBEDO,
) -> Tuple[float, float, float]:
    """Calcule le DHI effectif reçu par une surface inclinée.

    Prend en compte :
    - DHI du ciel pondéré par F_sky
    - Réflexion du sol pondérée par F_ground

    Parameters
    ----------
    dhi_w_m2 : float
        Irradiance diffuse horizontale mesurée (W/m²).
    ghi_w_m2 : float
        Irradiance globale horizontale (W/m²).
    svf_result : SkyViewResult
        Résultat du calcul SVF.
    ground_albedo : float
        Albédo du sol.

    Returns
    -------
    tuple[float, float, float]
        (dhi_sky, dhi_ground, dhi_total) en W/m².
    """
    # DHI venant du ciel
    dhi_sky = dhi_w_m2 * svf_result.f_sky

    # DHI réfléchi par le sol
    dhi_ground = compute_ground_reflected_irradiance(ghi_w_m2, svf_result.f_ground, ground_albedo)

    # Total
    dhi_total = dhi_sky + dhi_ground

    return dhi_sky, dhi_ground, dhi_total
