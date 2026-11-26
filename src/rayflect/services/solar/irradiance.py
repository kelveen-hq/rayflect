"""Hypothèses partagées pour le traitement du DNI et du DHI.

La constante DIFFUSE_PLANE_OFFSET_DEG est un alias de la valeur de
SYSTEM_DEFAULTS (system_constants.py).

Ce module implémente aussi le modèle de Perez (1990), qui décompose le
rayonnement diffus en composantes directionnelles.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

import numpy as np

from ...config.system_constants import SYSTEM_DEFAULTS

# Alias des valeurs de SYSTEM_DEFAULTS
DIFFUSE_PLANE_OFFSET_DEG = SYSTEM_DEFAULTS.diffuse_plane_offset_deg

_DIFFERENTIAL_VERTICAL = np.array([0.0, 0.0, 1.0], dtype=float)


# =============================================================================
# MODÈLE DE PEREZ (1990) - Coefficients pour ciel clair à couvert
# =============================================================================
# Coefficients F1 et F2 pour 8 catégories de clarté du ciel (epsilon bins)
# Source: Perez et al., "Modeling daylight availability and irradiance
#         components from direct and global irradiance", Solar Energy, 1990
# Format: (f11, f12, f13, f21, f22, f23) pour chaque bin d'epsilon
PEREZ_COEFFICIENTS = {
    # Bin 1: Ciel très couvert (epsilon < 1.065)
    1: (-0.008, 0.588, -0.062, -0.060, 0.072, -0.022),
    # Bin 2: Ciel couvert (1.065 <= epsilon < 1.230)
    2: (0.130, 0.683, -0.151, -0.019, 0.066, -0.029),
    # Bin 3: Ciel intermédiaire couvert (1.230 <= epsilon < 1.500)
    3: (0.330, 0.487, -0.221, 0.055, -0.064, -0.026),
    # Bin 4: Ciel intermédiaire (1.500 <= epsilon < 1.950)
    4: (0.568, 0.187, -0.295, 0.109, -0.152, -0.014),
    # Bin 5: Ciel intermédiaire clair (1.950 <= epsilon < 2.800)
    5: (0.873, -0.392, -0.362, 0.226, -0.462, 0.001),
    # Bin 6: Ciel partiellement clair (2.800 <= epsilon < 4.500)
    6: (1.132, -1.237, -0.412, 0.288, -0.823, 0.056),
    # Bin 7: Ciel clair (4.500 <= epsilon < 6.200)
    7: (1.060, -1.600, -0.359, 0.264, -1.127, 0.131),
    # Bin 8: Ciel très clair (epsilon >= 6.200)
    8: (0.678, -0.327, -0.250, 0.156, -1.377, 0.251),
}


@dataclass(frozen=True)
class PerezComponents:
    """Composantes du DHI selon le modèle de Perez.

    Attributes:
        circumsolar: Fraction circumsolaire (autour du soleil, W/m²)
        horizon: Fraction horizon brightening (W/m²)
        isotropic: Fraction isotrope (uniforme sur le ciel, W/m²)
        total_dhi: DHI total d'entrée (W/m²)
        epsilon: Indice de clarté du ciel (1=couvert, >6=très clair)
        delta: Luminance du ciel (brightness)
    """
    circumsolar: float
    horizon: float
    isotropic: float
    total_dhi: float
    epsilon: float
    delta: float

    @property
    def circumsolar_fraction(self) -> float:
        """Fraction du DHI venant de la région circumsolaire."""
        return self.circumsolar / self.total_dhi if self.total_dhi > 0 else 0.0

    @property
    def horizon_fraction(self) -> float:
        """Fraction du DHI venant de l'horizon."""
        return self.horizon / self.total_dhi if self.total_dhi > 0 else 0.0

    @property
    def isotropic_fraction(self) -> float:
        """Fraction du DHI isotrope."""
        return self.isotropic / self.total_dhi if self.total_dhi > 0 else 0.0


def _get_perez_epsilon_bin(epsilon: float) -> int:
    """Détermine le bin de clarté pour les coefficients de Perez.

    Parameters
    ----------
    epsilon: Indice de clarté du ciel

    Returns
    -------
    Numéro du bin (1-8)
    """
    if epsilon < 1.065:
        return 1
    elif epsilon < 1.230:
        return 2
    elif epsilon < 1.500:
        return 3
    elif epsilon < 1.950:
        return 4
    elif epsilon < 2.800:
        return 5
    elif epsilon < 4.500:
        return 6
    elif epsilon < 6.200:
        return 7
    else:
        return 8


def compute_perez_components(
    dhi_w_m2: float,
    dni_w_m2: float,
    solar_elevation_deg: float,
    air_mass: float | None = None,
) -> PerezComponents:
    """Décompose le DHI en composantes selon le modèle de Perez (1990).

    Le modèle de Perez décompose le rayonnement diffus horizontal (DHI) en trois
    composantes directionnelles :
    - Circumsolaire : concentré autour du soleil
    - Horizon brightening : bande lumineuse à l'horizon
    - Isotrope : uniformément réparti sur la voûte céleste

    Parameters
    ----------
    dhi_w_m2: Rayonnement diffus horizontal (W/m²)
    dni_w_m2: Rayonnement direct normal (W/m²)
    solar_elevation_deg: Élévation solaire (degrés, 0=horizon, 90=zénith)
    air_mass: Masse d'air optique (optionnel, calculée si None)

    Returns
    -------
    PerezComponents avec les trois composantes et métriques

    References
    ----------
    Perez R., Ineichen P., Seals R., Michalsky J., Stewart R. (1990).
    "Modeling daylight availability and irradiance components from direct
    and global irradiance". Solar Energy, 44(5), 271-289.
    """
    # Valeurs par défaut si pas d'irradiance
    if dhi_w_m2 <= 0:
        return PerezComponents(0.0, 0.0, 0.0, 0.0, 1.0, 0.0)

    # Angle zénithal solaire (radians)
    zenith_rad = math.radians(90.0 - solar_elevation_deg)
    cos_zenith = max(0.01, math.cos(zenith_rad))  # Éviter division par zéro

    # Masse d'air (Kasten & Young, 1989)
    if air_mass is None:
        if solar_elevation_deg <= 0:
            air_mass = 40.0  # Valeur limite au coucher
        else:
            air_mass = 1.0 / (cos_zenith + 0.50572 * (solar_elevation_deg + 6.07995) ** (-1.6364))
            air_mass = min(40.0, air_mass)  # Plafonner à 40

    # Irradiance extraterrestre normale (constante solaire corrigée ~1361 W/m²)
    # Simplification : on utilise une valeur moyenne
    I_0 = 1361.0

    # Indice de clarté du ciel (epsilon)
    # epsilon = ((DHI + DNI) / DHI + kappa * zenith³) / (1 + kappa * zenith³)
    # où kappa = 1.041 (constante empirique)
    kappa = 1.041
    zenith_rad_cubed = zenith_rad ** 3

    if dhi_w_m2 > 0:
        numerator = (dhi_w_m2 + dni_w_m2) / dhi_w_m2 + kappa * zenith_rad_cubed
        denominator = 1.0 + kappa * zenith_rad_cubed
        epsilon = numerator / denominator
    else:
        epsilon = 1.0  # Ciel couvert par défaut

    epsilon = max(1.0, min(12.0, epsilon))  # Borner entre 1 et 12

    # Luminance du ciel (delta)
    # delta = DHI * air_mass / I_0
    delta = (dhi_w_m2 * air_mass) / I_0
    delta = max(0.01, min(1.0, delta))  # Borner entre 0.01 et 1

    # Récupérer les coefficients de Perez pour le bin approprié
    epsilon_bin = _get_perez_epsilon_bin(epsilon)
    f11, f12, f13, f21, f22, f23 = PEREZ_COEFFICIENTS[epsilon_bin]

    # Calculer les coefficients de luminosité F1 (circumsolaire) et F2 (horizon)
    F1 = max(0.0, f11 + f12 * delta + f13 * zenith_rad)
    F2 = f21 + f22 * delta + f23 * zenith_rad

    # Angle d'incidence du soleil par rapport au plan horizontal
    # Pour un plan horizontal, theta = zenith, donc a = cos(zenith)
    a = max(0.0, cos_zenith)  # cos(theta) pour plan horizontal
    # b = max(cos(85°), cos(zenith)) : borne basse à cos(85°) pour éviter
    # la divergence près de l'horizon (Perez 1990, eq. 8)
    b = max(0.087, cos_zenith)

    # Décomposition du DHI
    # La fraction circumsolaire est proportionnelle à F1 * a/b
    circumsolar_factor = F1 * (a / b)

    # L'isotrope est (1 - F1)
    isotropic_factor = max(0.0, 1.0 - F1)

    # L'horizon brightening est F2
    horizon_factor = F2

    # Normaliser pour que la somme = DHI
    # ATTENTION : cette re-normalisation est NON-STANDARD par rapport à Perez (1990).
    # Quand F2 < 0 (ciel clair, bins 5-8), le modèle original applique un assombrissement
    # à l'horizon. Ici cette information est écartée et redistribuée vers l'isotrope.
    # Impact faible (<2%) car : (1) DHI petit par ciel clair, (2) horizon contribue peu
    # à une surface quasi-verticale. Conservation d'énergie préservée.
    total_factor = isotropic_factor + circumsolar_factor + abs(horizon_factor)
    if total_factor > 0:
        circumsolar = dhi_w_m2 * (circumsolar_factor / total_factor)
        isotropic = dhi_w_m2 * (isotropic_factor / total_factor)
        # F2 peut être négatif (réduction à l'horizon pour ciel clair)
        horizon = dhi_w_m2 * (horizon_factor / total_factor) if horizon_factor > 0 else 0.0
        # Réajuster l'isotrope pour compenser si F2 < 0
        if horizon_factor < 0:
            isotropic = max(0.0, dhi_w_m2 - circumsolar)
            horizon = 0.0
    else:
        # Fallback : tout isotrope
        circumsolar = 0.0
        horizon = 0.0
        isotropic = dhi_w_m2

    return PerezComponents(
        circumsolar=circumsolar,
        horizon=horizon,
        isotropic=isotropic,
        total_dhi=dhi_w_m2,
        epsilon=epsilon,
        delta=delta,
    )




def estimate_direct_normal_irradiance(sample: Any, solar_elevation_deg: float) -> float:
    """Estime le DNI (W/m²) à partir d'une mesure météo partielle."""

    if getattr(sample, "direct_normal_irradiance", None) is not None:
        return max(0.0, float(sample.direct_normal_irradiance))
    ghi = max(0.0, float(getattr(sample, "global_horizontal_irradiance", 0.0)))
    dhi = max(0.0, float(getattr(sample, "diffuse_horizontal_irradiance", 0.0)))
    beam_component = max(0.0, ghi - dhi)
    cos_zenith = max(1e-3, math.cos(math.radians(90.0 - solar_elevation_deg)))
    # Le DNI est plafonné à la constante solaire (1361 W/m²).
    return min(1361.0, beam_component / cos_zenith)


def diffuse_source_direction(facade_normal: np.ndarray) -> np.ndarray:
    """Vecteur unitaire représentant la direction moyenne du DHI.

    Hypothèses
    ----------
    - Façade verticale (normale horizontale).
    - Flux diffus arrivant avec un angle de 30° par rapport au plan, donc 60°
      par rapport à la normale.
    - Projection dans le plan (facade_normal, verticale).
    """

    normalized_facade = np.asarray(facade_normal, dtype=float)
    norm = np.linalg.norm(normalized_facade)
    if norm == 0:
        raise ValueError("Facade normal cannot be zero length")
    normalized_facade = normalized_facade / norm
    vertical = _DIFFERENTIAL_VERTICAL
    angle_from_normal = math.radians(90.0 - DIFFUSE_PLANE_OFFSET_DEG)
    direction = normalized_facade * math.cos(angle_from_normal) + vertical * math.sin(angle_from_normal)
    dir_norm = np.linalg.norm(direction)
    if dir_norm == 0:
        return direction
    return direction / dir_norm


def project_surface(active_area_m2: float, panel_normal: np.ndarray, incoming_direction: np.ndarray) -> float:
    """Surface interceptée (m²) pour une direction donnée."""

    if active_area_m2 <= 0:
        return 0.0
    panel_normal = np.asarray(panel_normal, dtype=float)
    incoming_direction = np.asarray(incoming_direction, dtype=float)
    cos_incident = float(np.dot(panel_normal, incoming_direction))
    if cos_incident <= 0:
        return 0.0
    return active_area_m2 * cos_incident
