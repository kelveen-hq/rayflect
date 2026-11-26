"""
Modèle géométrique de casquette solaire (brise-soleil horizontal fixe).

Ce module calcule l'ombrage d'une casquette sur une fenêtre en fonction de
la géométrie (profondeur, position) et de la trajectoire solaire (altitude,
azimut).

Formule fondamentale :
    shadow_length = depth × tan(sun_altitude) / cos(azimuth_offset)

    où azimuth_offset = angle entre l'azimut du soleil et la normale à la façade.
    La casquette projette une ombre sur la fenêtre verticale en dessous.

Usage:
    from rayflect.services.analysis.casquette import (
        compute_casquette_shadow_fraction,
        compute_casquette_seasonal_factors,
    )
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from ...config.system_constants import SYSTEM_DEFAULTS


# ============================================================================
# CONSTANTES
# ============================================================================

# Aliasing depuis SYSTEM_DEFAULTS pour lisibilité
CASQUETTE_DEPTH_TYPICAL_M = SYSTEM_DEFAULTS.casquette_depth_typical_m
WINDOW_HEIGHT_STANDARD_M = SYSTEM_DEFAULTS.window_height_standard_m


# ============================================================================
# FONCTIONS GÉOMÉTRIQUES
# ============================================================================

def compute_casquette_shadow_fraction(
    depth_m: float,
    sun_altitude_deg: float,
    sun_azimuth_deg: float,
    facade_azimuth_deg: float,
    window_height_m: float,
) -> float:
    """Calcule la fraction de fenêtre ombrée par une casquette horizontale.

    La casquette est un brise-soleil horizontal fixé au sommet de la fenêtre.
    L'ombre projetée sur la fenêtre verticale dépend de l'altitude du soleil
    et de son azimut relatif à la façade.

    Formule:
        tan(angle de profil) = tan(sun_altitude) / cos(azimuth_offset)
        shadow_length = depth × tan(sun_altitude) / cos(azimuth_offset)
        shading_fraction = min(1.0, shadow_length / window_height)

    C'EST LA RAISON D'ÊTRE D'UNE CASQUETTE : l'ombre grandit avec la hauteur
    du soleil, donc elle protège l'été et laisse passer l'hiver.

    Args:
        depth_m: Profondeur de la casquette depuis la façade (m).
        sun_altitude_deg: Altitude du soleil au-dessus de l'horizon (°, 0–90).
        sun_azimuth_deg: Azimut du soleil (°, convention 0=Nord, 180=Sud).
        facade_azimuth_deg: Azimut de la normale à la façade (°, 180=façade Sud).
        window_height_m: Hauteur de la fenêtre (m).

    Returns:
        Fraction de la fenêtre ombrée (0.0–1.0).
        0.0 = pas d'ombre, 1.0 = fenêtre entièrement ombrée.

    Example:
        >>> # Soleil haut (été, midi, façade sud) : l'ombre descend loin
        >>> compute_casquette_shadow_fraction(0.40, 65.0, 180.0, 180.0, 1.80)
        0.48  # 0,40 × tan 65° = 0,86 m sur 1,80 m
        >>> # Soleil bas (hiver, midi, façade sud) : l'ombre reste en haut
        >>> compute_casquette_shadow_fraction(0.40, 25.0, 180.0, 180.0, 1.80)
        0.10  # 0,40 × tan 25° = 0,19 m sur 1,80 m
    """
    if depth_m <= 0 or window_height_m <= 0:
        return 0.0
    if sun_altitude_deg <= 0:
        return 0.0  # Soleil sous l'horizon

    # Angle azimutal entre le soleil et la normale à la façade
    azimuth_offset_deg = abs(sun_azimuth_deg - facade_azimuth_deg)
    if azimuth_offset_deg > 180:
        azimuth_offset_deg = 360 - azimuth_offset_deg

    # Si le soleil est derrière la façade, pas d'ombre
    if azimuth_offset_deg >= 90:
        return 0.0

    sun_alt_rad = math.radians(sun_altitude_deg)
    az_offset_rad = math.radians(azimuth_offset_deg)

    # Longueur de l'ombre projetée sur la fenêtre (vertical, sous la casquette)
    tan_alt = math.tan(sun_alt_rad)
    if tan_alt <= 0:
        return 0.0

    # L'ombre d'un débord tombe sous lui, et elle grandit avec la hauteur du
    # soleil : on MULTIPLIE par la tangente de l'altitude.
    #
    # L'obliquité se prend par l'ANGLE DE PROFIL, pas sur la longueur :
    #     tan(profil) = tan(altitude) / cos(écart d'azimut)
    cos_az = math.cos(az_offset_rad)
    if cos_az <= 1e-9:
        return 0.0
    shadow_length = depth_m * tan_alt / cos_az

    # Fraction de la fenêtre couverte
    fraction = min(1.0, max(0.0, shadow_length / window_height_m))
    return fraction


@dataclass(frozen=True)
class CasquetteSeasonalFactors:
    """Facteurs saisonniers d'ombrage de la casquette.

    Attributes:
        summer_shading_factor: Fraction moyenne du flux solaire bloqué en été (0–1).
        winter_blocking_factor: Fraction moyenne des gains solaires perdus en hiver (0–1).
        summer_avg_altitude_deg: Altitude solaire moyenne été utilisée.
        winter_avg_altitude_deg: Altitude solaire moyenne hiver utilisée.
    """
    summer_shading_factor: float
    winter_blocking_factor: float
    summer_avg_altitude_deg: float
    winter_avg_altitude_deg: float


def compute_casquette_seasonal_factors(
    depth_m: float,
    latitude_deg: float,
    window_height_m: float = WINDOW_HEIGHT_STANDARD_M,
    facade_azimuth_deg: float = 180.0,
) -> CasquetteSeasonalFactors:
    """Calcule les facteurs saisonniers d'ombrage pour une latitude donnée.

    Approximation basée sur les altitudes solaires typiques à midi :
    - Été (solstice) : altitude ≈ 90 - latitude + 23.45
    - Hiver (solstice) : altitude ≈ 90 - latitude - 23.45
    - Mi-saison : altitude ≈ 90 - latitude

    On calcule l'ombrage moyen pour plusieurs heures de la journée
    en pondérant par l'intensité solaire relative.

    Args:
        depth_m: Profondeur de la casquette (m).
        latitude_deg: Latitude du site (°).
        window_height_m: Hauteur de la fenêtre (m).
        facade_azimuth_deg: Azimut de la façade (° ; 180 = façade Sud).

    Returns:
        CasquetteSeasonalFactors avec les facteurs calculés.

    Example:
        >>> factors = compute_casquette_seasonal_factors(0.40, 45.0)
        >>> factors.summer_shading_factor   # l'été est protégé
        >>> factors.winter_blocking_factor  # l'hiver passe presque entier
    """
    # Altitude solaire à midi aux solstices/équinoxes
    summer_noon_alt = min(90.0, 90.0 - latitude_deg + 23.45)
    winter_noon_alt = max(5.0, 90.0 - latitude_deg - 23.45)
    equinox_noon_alt = max(5.0, 90.0 - latitude_deg)

    # Calcul de l'ombrage pour des heures types de la journée
    # Poids : midi a le plus d'irradiance solaire, matin/soir moins
    # On simule 5 points : 9h, 10h30, 12h, 13h30, 15h
    # Altitude approximative : alt_noon × facteur(heure)
    # Azimut approximatif par rapport au sud
    #
    # IMPORTANT: Pour une façade non-Sud, les heures de pic solaire
    # changent. On décale les azimuts pour que le poids maximal (0.30)
    # corresponde au moment où le soleil fait face à la façade :
    # - Façade Sud (180°) : pic à midi (azimut solaire ~180°)
    # - Façade Est (90°)  : pic le matin (azimut solaire ~90°)
    # - Façade Ouest (270°): pic l'après-midi (azimut solaire ~270°)
    #
    # On calcule le décalage azimutal entre la façade et le Sud,
    # puis on décale l'azimut solaire des heures simulées.
    facade_vs_south_offset = facade_azimuth_deg - 180.0  # >0 pour Ouest, <0 pour Est

    hour_configs = [
        # (altitude_fraction, azimuth_offset_deg, weight)
        (0.70, 45.0 + facade_vs_south_offset, 0.15),   # matin
        (0.88, 22.0 + facade_vs_south_offset, 0.20),   # milieu matin
        (1.00, 0.0 + facade_vs_south_offset, 0.30),    # pic (face façade)
        (0.88, -22.0 + facade_vs_south_offset, 0.20),  # milieu après-midi
        (0.70, -45.0 + facade_vs_south_offset, 0.15),  # après-midi
    ]

    def _weighted_shading(noon_altitude: float) -> float:
        """Calcule l'ombrage moyen pondéré sur la journée."""
        total = 0.0
        for alt_frac, az_offset, weight in hour_configs:
            alt = noon_altitude * alt_frac
            az = facade_azimuth_deg + az_offset
            fraction = compute_casquette_shadow_fraction(
                depth_m, alt, az, facade_azimuth_deg, window_height_m,
            )
            total += fraction * weight
        return total

    # Été : pondération 60% solstice + 40% mi-saison
    summer_solstice = _weighted_shading(summer_noon_alt)
    summer_equinox = _weighted_shading(equinox_noon_alt)
    summer_shading = 0.60 * summer_solstice + 0.40 * summer_equinox

    # Hiver : pondération 60% solstice + 40% mi-saison
    winter_solstice = _weighted_shading(winter_noon_alt)
    winter_equinox = _weighted_shading(equinox_noon_alt)
    winter_blocking = 0.60 * winter_solstice + 0.40 * winter_equinox

    return CasquetteSeasonalFactors(
        summer_shading_factor=round(summer_shading, 3),
        winter_blocking_factor=round(winter_blocking, 3),
        summer_avg_altitude_deg=round(summer_noon_alt, 1),
        winter_avg_altitude_deg=round(winter_noon_alt, 1),
    )




# ============================================================================
# EXPORTS
# ============================================================================

__all__ = [
    "compute_casquette_shadow_fraction",
    "compute_casquette_seasonal_factors",
    "CasquetteSeasonalFactors",
]
