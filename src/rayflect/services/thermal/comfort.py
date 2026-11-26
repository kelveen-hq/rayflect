"""
Calculs de confort thermique et conformité RE2020.

Ce module implémente les indicateurs de confort thermique réglementaires :
- Calcul des Degrés-Heures (DH) d'inconfort selon RE2020
- Température de confort adaptatif selon EN 15251
- Vérification de la conformité RE2020
- Comptage des jours de canicule et de fraîcheur excessive

L'indicateur DH (Degrés-Heures) est le critère principal de confort d'été
de la RE2020. Il cumule les écarts entre température intérieure et
température de confort adaptatif pendant les heures d'occupation.

Seuils RE2020:
    - DH ≤ 350 : Bâtiment confortable, pas de climatisation nécessaire
    - 350 < DH ≤ 1250 : Inconfort modéré, climatisation optionnelle
    - DH > 1250 : NON CONFORME - Bâtiment non constructible

Usage:
    from rayflect.services.thermal.comfort import (
        compute_degree_hours_summer,
        compute_degree_hours_winter,
        check_re2020_compliance,
        count_discomfort_days,
        compute_adaptive_comfort_bounds,
    )

    # Calculer les DH d'été
    dh_result = compute_degree_hours_summer(t_interior, t_exterior)
    print(f"DH surchauffe: {dh_result.dh_total:.0f} °C·h")

    # Vérifier conformité RE2020
    compliance = check_re2020_compliance(dh_result.dh_total)
    if compliance["compliant"]:
        print("✓ Conforme RE2020")
    else:
        print(f"✗ Non conforme: {compliance['message']}")
"""

from __future__ import annotations

import numpy as np
from dataclasses import dataclass
from typing import Optional

from ...config.system_constants import SYSTEM_DEFAULTS


# =============================================================================
# CONSTANTES RE2020
# =============================================================================

# Seuils de Degrés-Heures RE2020
RE2020_DH_COMFORT: float = 350.0
"""Seuil DH pour confort sans climatisation [°C·h]."""

RE2020_DH_MAX: float = 1250.0
"""Seuil DH maximal réglementaire RE2020 [°C·h]."""

# Seuils de température pour comptage jours d'inconfort
HEATWAVE_THRESHOLD_C: float = 28.0
"""Seuil température intérieure pour canicule [°C]."""

COLD_THRESHOLD_C: float = 18.0
"""Seuil température intérieure pour froid [°C]."""

# Seuils additionnels pour statistiques détaillées
COMFORT_UPPER_THRESHOLD_C: float = 26.0
"""Seuil supérieur de confort (avant inconfort) [°C]."""

COMFORT_LOWER_THRESHOLD_C: float = 19.0
"""Seuil inférieur de confort (avant froid) [°C]."""


# =============================================================================
# STRUCTURES DE DONNÉES
# =============================================================================

@dataclass
class DegreeHoursResult:
    """Résultat du calcul des degrés-heures.

    Attributes:
        dh_total: Total des degrés-heures cumulés [°C·h]
        hours_discomfort: Nombre d'heures d'inconfort
        max_deviation: Écart maximal à la température de confort [°C]
        avg_deviation: Écart moyen pendant les heures d'inconfort [°C]
        hours_analyzed: Nombre total d'heures analysées
    """
    dh_total: float
    hours_discomfort: int
    max_deviation: float
    avg_deviation: float
    hours_analyzed: int = 0


@dataclass
class DiscomfortDaysResult:
    """Résultat du comptage des jours d'inconfort.

    Attributes:
        days_heatwave: Jours avec au moins 1h > seuil canicule
        days_cold: Jours avec au moins 1h < seuil froid
        total_days: Nombre total de jours analysés
        pct_heatwave: Pourcentage de jours de canicule
        pct_cold: Pourcentage de jours trop froids
        hours_above_26: Heures au-dessus de 26°C
        hours_above_28: Heures au-dessus de 28°C
        hours_below_19: Heures en-dessous de 19°C
    """
    days_heatwave: int
    days_cold: int
    total_days: int
    pct_heatwave: float
    pct_cold: float
    hours_above_26: int
    hours_above_28: int
    hours_below_19: int


@dataclass
class RE2020ComplianceResult:
    """Résultat de la vérification conformité RE2020.

    Attributes:
        dh_summer: Degrés-heures de surchauffe calculés
        category: Catégorie ("confortable", "inconfort_modere", "non_conforme")
        compliant: True si DH ≤ 1250
        needs_cooling: True si climatisation probablement nécessaire
        message: Message descriptif
        margin_to_threshold: Marge par rapport au seuil 1250 [°C·h]
    """
    dh_summer: float
    category: str
    compliant: bool
    needs_cooling: bool
    message: str
    margin_to_threshold: float


# =============================================================================
# TEMPÉRATURE DE CONFORT ADAPTATIF
# =============================================================================

def compute_adaptive_comfort_bounds(
    t_ext_running_mean: float,
    category: str = "II"
) -> tuple[float, float]:
    """
    Calcule les bornes de confort adaptatif selon EN 15251.

    La température de confort dépend de la température extérieure
    moyenne glissante sur les 7 derniers jours. C'est le modèle
    utilisé par la RE2020 pour définir le confort d'été.

    Formule de base (température neutre):
        T_neutral = 0.33 × T_ext_running_mean + 18.8

    Les catégories EN 15251 définissent les plages acceptables:
        - Catégorie I : ±2°C (haut standing, personnes fragiles)
        - Catégorie II : ±3°C (normal, bâtiments neufs)
        - Catégorie III : ±4°C (acceptable, rénovation)

    Args:
        t_ext_running_mean: Moyenne glissante température extérieure
                           sur 7 jours [°C]
        category: Catégorie de confort EN 15251 ("I", "II", "III")

    Returns:
        (t_min, t_max): Bornes de confort en °C, bornées à [19, 28]

    Example:
        >>> t_min, t_max = compute_adaptive_comfort_bounds(25.0, "II")
        >>> print(f"Confort: {t_min:.1f}°C - {t_max:.1f}°C")
        Confort: 24.1°C - 28.0°C
    """
    # Température neutre de confort (formule EN 15251)
    t_neutral = 0.33 * t_ext_running_mean + 18.8

    # Plages acceptables par catégorie
    offsets = {
        "I": 2.0,   # Personnes fragiles, haut standing
        "II": 3.0,  # Normal, bâtiments neufs (défaut RE2020)
        "III": 4.0, # Acceptable, rénovation
    }
    offset = offsets.get(category, 3.0)

    # Calculer les bornes avec limites absolues
    t_min = max(19.0, t_neutral - offset)
    t_max = min(28.0, t_neutral + offset)

    return t_min, t_max


def compute_running_mean_temperature(
    t_exterior_hourly: np.ndarray,
    window_hours: int = 168
) -> np.ndarray:
    """
    Calcule la moyenne glissante de la température extérieure.

    Pour le calcul RE2020, on utilise une fenêtre de 7 jours (168h)
    pour lisser les variations quotidiennes et obtenir la tendance.

    Args:
        t_exterior_hourly: Températures extérieures horaires [°C]
        window_hours: Taille de la fenêtre glissante en heures (défaut: 168 = 7 jours)

    Returns:
        Moyenne glissante, même taille que l'entrée
    """
    n = len(t_exterior_hourly)
    window = min(window_hours, n)

    # Convolution pour moyenne glissante
    kernel = np.ones(window) / window
    t_running = np.convolve(t_exterior_hourly, kernel, mode='same')

    # Corriger les bords (où la fenêtre n'est pas complète)
    for i in range(window // 2):
        t_running[i] = np.mean(t_exterior_hourly[:i + window // 2 + 1])
        t_running[-(i + 1)] = np.mean(t_exterior_hourly[-(i + window // 2 + 1):])

    return t_running


# =============================================================================
# CALCUL DES DEGRÉS-HEURES
# =============================================================================

def compute_degree_hours_summer(
    t_interior: np.ndarray,
    t_exterior: np.ndarray,
    occupation_mask: Optional[np.ndarray] = None,
    comfort_category: str = "II"
) -> DegreeHoursResult:
    """
    Calcule les Degrés-Heures de surchauffe (indicateur RE2020 été).

    Le DH cumule les écarts positifs entre température intérieure
    et température de confort adaptatif, pendant les heures d'occupation.

    Formule:
        DH = Σ max(0, T_int - T_confort_max) pour chaque heure occupée

    Args:
        t_interior: Températures intérieures horaires [°C], array 1D
        t_exterior: Températures extérieures horaires [°C], même taille
        occupation_mask: Masque d'occupation (True = occupé).
                        Si None, toutes les heures sont considérées occupées.
        comfort_category: Catégorie EN 15251 ("I", "II", "III")

    Returns:
        DegreeHoursResult avec DH cumulés et statistiques

    Example:
        >>> t_int = np.array([22, 24, 26, 28, 30, 29, 27, 25])  # 8h de données
        >>> t_ext = np.array([20, 22, 25, 28, 30, 28, 25, 22])
        >>> result = compute_degree_hours_summer(t_int, t_ext)
        >>> print(f"DH: {result.dh_total:.1f} °C·h")
    """
    # Validation des entrées
    t_interior = np.asarray(t_interior, dtype=float)
    t_exterior = np.asarray(t_exterior, dtype=float)
    n_hours = len(t_interior)

    if len(t_exterior) != n_hours:
        raise ValueError(
            f"t_interior ({n_hours}) et t_exterior ({len(t_exterior)}) "
            "doivent avoir la même taille"
        )

    # Masque d'occupation (défaut: tout occupé)
    if occupation_mask is None:
        occupation_mask = np.ones(n_hours, dtype=bool)
    else:
        occupation_mask = np.asarray(occupation_mask, dtype=bool)

    # Calculer la moyenne glissante de T_ext (7 jours)
    t_ext_running = compute_running_mean_temperature(t_exterior)

    # Calculer T_confort_max pour chaque heure
    t_comfort_max = np.array([
        compute_adaptive_comfort_bounds(t_rm, comfort_category)[1]
        for t_rm in t_ext_running
    ])

    # Écarts positifs = surchauffe
    deviations = np.maximum(0, t_interior - t_comfort_max)
    deviations_occupied = deviations * occupation_mask

    # Statistiques
    dh_total = float(np.sum(deviations_occupied))
    hours_discomfort = int(np.sum(deviations_occupied > 0))

    if hours_discomfort > 0:
        max_deviation = float(np.max(deviations_occupied))
        avg_deviation = float(np.mean(deviations_occupied[deviations_occupied > 0]))
    else:
        max_deviation = 0.0
        avg_deviation = 0.0

    return DegreeHoursResult(
        dh_total=dh_total,
        hours_discomfort=hours_discomfort,
        max_deviation=max_deviation,
        avg_deviation=avg_deviation,
        hours_analyzed=n_hours,
    )


def compute_degree_hours_winter(
    t_interior: np.ndarray,
    t_setpoint: float = SYSTEM_DEFAULTS.setpoint_heating_default_c,
    occupation_mask: Optional[np.ndarray] = None
) -> DegreeHoursResult:
    """
    Calcule les Degrés-Heures de sous-température (inconfort hiver).

    Contrairement à l'été, l'hiver utilise une température de consigne
    fixe plutôt qu'un confort adaptatif.

    Formule:
        DH_winter = Σ max(0, T_consigne - T_int) pour chaque heure occupée

    Args:
        t_interior: Températures intérieures horaires [°C]
        t_setpoint: Température de consigne chauffage [°C]
        occupation_mask: Masque d'occupation (True = occupé)

    Returns:
        DegreeHoursResult avec DH de sous-chauffe

    Example:
        >>> t_int = np.array([18, 17, 16, 18, 19, 20, 19, 18])
        >>> result = compute_degree_hours_winter(t_int, t_setpoint=19.0)
        >>> print(f"DH sous-chauffe: {result.dh_total:.1f} °C·h")
    """
    t_interior = np.asarray(t_interior, dtype=float)
    n_hours = len(t_interior)

    if occupation_mask is None:
        occupation_mask = np.ones(n_hours, dtype=bool)
    else:
        occupation_mask = np.asarray(occupation_mask, dtype=bool)

    # Écarts négatifs = sous-température
    deviations = np.maximum(0, t_setpoint - t_interior)
    deviations_occupied = deviations * occupation_mask

    dh_total = float(np.sum(deviations_occupied))
    hours_discomfort = int(np.sum(deviations_occupied > 0))

    if hours_discomfort > 0:
        max_deviation = float(np.max(deviations_occupied))
        avg_deviation = float(np.mean(deviations_occupied[deviations_occupied > 0]))
    else:
        max_deviation = 0.0
        avg_deviation = 0.0

    return DegreeHoursResult(
        dh_total=dh_total,
        hours_discomfort=hours_discomfort,
        max_deviation=max_deviation,
        avg_deviation=avg_deviation,
        hours_analyzed=n_hours,
    )


# =============================================================================
# CONFORMITÉ RE2020
# =============================================================================

def check_re2020_compliance(dh_summer: float) -> RE2020ComplianceResult:
    """
    Vérifie la conformité RE2020 basée sur les DH d'été.

    Catégories RE2020:
        - DH ≤ 350 : "confortable" - Pas besoin de climatisation
        - 350 < DH ≤ 1250 : "inconfort_modere" - Clim optionnelle (pénalité Cep)
        - DH > 1250 : "non_conforme" - Bâtiment non constructible

    Args:
        dh_summer: Degrés-Heures de surchauffe annuels [°C·h]

    Returns:
        RE2020ComplianceResult avec statut de conformité

    Example:
        >>> result = check_re2020_compliance(800)
        >>> print(f"Catégorie: {result.category}")
        >>> print(f"Conforme: {result.compliant}")
        Catégorie: inconfort_modere
        Conforme: True
    """
    margin = RE2020_DH_MAX - dh_summer

    if dh_summer <= RE2020_DH_COMFORT:
        return RE2020ComplianceResult(
            dh_summer=dh_summer,
            category="confortable",
            compliant=True,
            needs_cooling=False,
            message="Bâtiment confortable sans climatisation",
            margin_to_threshold=margin,
        )
    elif dh_summer <= RE2020_DH_MAX:
        return RE2020ComplianceResult(
            dh_summer=dh_summer,
            category="inconfort_modere",
            compliant=True,
            needs_cooling=True,
            message="Climatisation optionnelle (pénalité Cep si installée)",
            margin_to_threshold=margin,
        )
    else:
        return RE2020ComplianceResult(
            dh_summer=dh_summer,
            category="non_conforme",
            compliant=False,
            needs_cooling=True,
            message=f"NON CONFORME RE2020 - DH = {dh_summer:.0f} > 1250",
            margin_to_threshold=margin,
        )


# =============================================================================
# COMPTAGE DES JOURS D'INCONFORT
# =============================================================================

def count_discomfort_days(
    t_interior_hourly: np.ndarray,
    heatwave_threshold: float = HEATWAVE_THRESHOLD_C,
    cold_threshold: float = COLD_THRESHOLD_C
) -> DiscomfortDaysResult:
    """
    Compte les jours d'inconfort (canicule et froid).

    Un jour est compté comme "canicule" si la température intérieure
    dépasse le seuil pendant au moins 1 heure.

    Un jour est compté comme "froid" si la température intérieure
    descend sous le seuil pendant au moins 1 heure.

    Args:
        t_interior_hourly: Températures intérieures horaires [°C]
        heatwave_threshold: Seuil canicule [°C] (défaut: 28°C)
        cold_threshold: Seuil froid [°C] (défaut: 18°C)

    Returns:
        DiscomfortDaysResult avec comptage détaillé

    Example:
        >>> t_year = np.random.normal(22, 5, 8760)  # 1 an de données
        >>> result = count_discomfort_days(t_year)
        >>> print(f"Jours canicule: {result.days_heatwave}")
        >>> print(f"Jours froids: {result.days_cold}")
    """
    t_interior = np.asarray(t_interior_hourly, dtype=float)
    n_hours = len(t_interior)
    n_days = n_hours // 24

    days_heatwave = 0
    days_cold = 0

    # Comptage par jour
    for day in range(n_days):
        start = day * 24
        end = start + 24
        t_day = t_interior[start:end]

        # Canicule : au moins 1h > seuil
        if np.any(t_day > heatwave_threshold):
            days_heatwave += 1

        # Froid : au moins 1h < seuil
        if np.any(t_day < cold_threshold):
            days_cold += 1

    # Comptage heures détaillées
    hours_above_26 = int(np.sum(t_interior > COMFORT_UPPER_THRESHOLD_C))
    hours_above_28 = int(np.sum(t_interior > HEATWAVE_THRESHOLD_C))
    hours_below_19 = int(np.sum(t_interior < COMFORT_LOWER_THRESHOLD_C))

    # Pourcentages
    pct_heatwave = 100 * days_heatwave / n_days if n_days > 0 else 0.0
    pct_cold = 100 * days_cold / n_days if n_days > 0 else 0.0

    return DiscomfortDaysResult(
        days_heatwave=days_heatwave,
        days_cold=days_cold,
        total_days=n_days,
        pct_heatwave=pct_heatwave,
        pct_cold=pct_cold,
        hours_above_26=hours_above_26,
        hours_above_28=hours_above_28,
        hours_below_19=hours_below_19,
    )


# =============================================================================
# COMPARAISON SANS PROTECTION / AVEC PROTECTION
# =============================================================================

@dataclass
class ThermalComfortComparison:
    """Comparaison du confort thermique sans protection et avec protection.

    Attributes:
        dh_summer_without: DH surchauffe sans protection
        dh_summer_with: DH surchauffe avec protection
        dh_winter_without: DH sous-température sans protection
        dh_winter_with: DH sous-température avec protection
        reduction_summer_pct: Réduction DH été en %
        reduction_winter_pct: Réduction DH hiver en %
        days_heatwave_without: Jours canicule sans protection
        days_heatwave_with: Jours canicule avec protection
        days_cold_without: Jours froids sans protection
        days_cold_with: Jours froids avec protection
        compliance_without: Conformité RE2020 sans protection
        compliance_with: Conformité RE2020 avec protection
    """
    dh_summer_without: float
    dh_summer_with: float
    dh_winter_without: float
    dh_winter_with: float
    reduction_summer_pct: float
    reduction_winter_pct: float
    days_heatwave_without: int
    days_heatwave_with: int
    days_cold_without: int
    days_cold_with: int
    compliance_without: RE2020ComplianceResult
    compliance_with: RE2020ComplianceResult


def compare_thermal_comfort(
    t_interior_without: np.ndarray,
    t_interior_with: np.ndarray,
    t_exterior: np.ndarray,
    t_setpoint_heating: float = SYSTEM_DEFAULTS.setpoint_heating_default_c,
    comfort_category: str = "II"
) -> ThermalComfortComparison:
    """
    Compare le confort thermique sans protection et avec protection.

    Args:
        t_interior_without: T° intérieure horaire SANS protection [°C]
        t_interior_with: T° intérieure horaire AVEC protection [°C]
        t_exterior: T° extérieure horaire [°C]
        t_setpoint_heating: Consigne chauffage [°C]
        comfort_category: Catégorie EN 15251

    Returns:
        ThermalComfortComparison avec tous les indicateurs

    Example:
        >>> # Simulation sur 1 semaine (168h)
        >>> t_ext = np.random.normal(25, 5, 168)
        >>> t_without = t_ext + 5  # Bâtiment suit l'extérieur + 5°C
        >>> t_with = np.clip(t_without - 2, 20, 26)  # La protection réduit de 2°C
        >>> comparison = compare_thermal_comfort(t_without, t_with, t_ext)
        >>> print(f"Réduction DH été: {comparison.reduction_summer_pct:.1f}%")
    """
    # Calcul DH été
    dh_summer_without = compute_degree_hours_summer(
        t_interior_without, t_exterior, comfort_category=comfort_category
    )
    dh_summer_with = compute_degree_hours_summer(
        t_interior_with, t_exterior, comfort_category=comfort_category
    )

    # Calcul DH hiver
    dh_winter_without = compute_degree_hours_winter(
        t_interior_without, t_setpoint=t_setpoint_heating
    )
    dh_winter_with = compute_degree_hours_winter(
        t_interior_with, t_setpoint=t_setpoint_heating
    )

    # Réductions en %
    if dh_summer_without.dh_total > 0:
        reduction_summer = 100 * (1 - dh_summer_with.dh_total / dh_summer_without.dh_total)
    else:
        reduction_summer = 0.0

    if dh_winter_without.dh_total > 0:
        reduction_winter = 100 * (1 - dh_winter_with.dh_total / dh_winter_without.dh_total)
    else:
        reduction_winter = 0.0

    # Jours d'inconfort
    days_without = count_discomfort_days(t_interior_without)
    days_with = count_discomfort_days(t_interior_with)

    # Conformité RE2020
    compliance_without = check_re2020_compliance(dh_summer_without.dh_total)
    compliance_with = check_re2020_compliance(dh_summer_with.dh_total)

    return ThermalComfortComparison(
        dh_summer_without=dh_summer_without.dh_total,
        dh_summer_with=dh_summer_with.dh_total,
        dh_winter_without=dh_winter_without.dh_total,
        dh_winter_with=dh_winter_with.dh_total,
        reduction_summer_pct=reduction_summer,
        reduction_winter_pct=reduction_winter,
        days_heatwave_without=days_without.days_heatwave,
        days_heatwave_with=days_with.days_heatwave,
        days_cold_without=days_without.days_cold,
        days_cold_with=days_with.days_cold,
        compliance_without=compliance_without,
        compliance_with=compliance_with,
    )
