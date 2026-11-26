"""
Modèle de COP variable de pompe à chaleur air-air selon la température extérieure.

Le COP nominal d'une PAC est mesuré à +7°C extérieur / +20°C intérieur
(EN 14825). En conditions réelles, la performance se dégrade quand la
température extérieure baisse (givre sur échangeur, Carnot défavorable).

Ce module fournit la courbe COP = f(T_ext) basée sur les données
constructeurs et les normes EN 14825 / EHPA.

Usage:
    from rayflect.services.analysis.pac_model import (
        pac_cop_at_temperature,
        pac_seasonal_cop,
    )
"""

from __future__ import annotations

from typing import List, Tuple

from ...config.system_constants import SYSTEM_DEFAULTS


# ============================================================================
# CONSTANTES (aliasées depuis SYSTEM_DEFAULTS)
# ============================================================================

_COP_NOMINAL = SYSTEM_DEFAULTS.hvac_cop_heating
_RATED_TEMP = SYSTEM_DEFAULTS.pac_cop_rated_temp_c
_MIN_TEMP = SYSTEM_DEFAULTS.pac_cop_min_temp_c
_FACTOR_MINUS7 = SYSTEM_DEFAULTS.pac_cop_at_minus7_factor
_FACTOR_MINUS15 = SYSTEM_DEFAULTS.pac_cop_at_minus15_factor


# ============================================================================
# FONCTIONS
# ============================================================================

def pac_cop_at_temperature(
    t_ext_c: float,
    cop_nominal: float = _COP_NOMINAL,
) -> float:
    """Calcule le COP d'une PAC air-air à une température extérieure donnée.

    Modèle par interpolation linéaire entre 3 points de référence EN 14825 :
    - +7°C : COP = COP_nominal (100%)
    - -7°C : COP = COP_nominal × 0.57 (condition D, givrage)
    - -15°C : COP = COP_nominal × 0.37 (limite basse)
    - Au-dessus de +7°C : COP stable (rendement nominal ou légèrement meilleur)
    - En dessous de -15°C : backup électrique, COP = 1.0

    Args:
        t_ext_c: Température extérieure (°C).
        cop_nominal: COP nominal à +7°C (défaut: SYSTEM_DEFAULTS.hvac_cop_heating).

    Returns:
        COP effectif de la PAC (≥ 1.0).

    Example:
        >>> pac_cop_at_temperature(7.0)    # COP nominal
        3.5
        >>> pac_cop_at_temperature(-7.0)   # Condition D
        2.0
        >>> pac_cop_at_temperature(-20.0)  # Backup
        1.0
    """
    if t_ext_c >= _RATED_TEMP:
        # Au-dessus de la température nominale : COP stable
        return cop_nominal

    if t_ext_c >= -7.0:
        # Interpolation linéaire +7°C → -7°C
        # COP va de cop_nominal à cop_nominal × factor_minus7
        cop_at_minus7 = cop_nominal * _FACTOR_MINUS7
        frac = (_RATED_TEMP - t_ext_c) / (_RATED_TEMP + 7.0)
        cop = cop_nominal - frac * (cop_nominal - cop_at_minus7)
        return max(1.0, cop)

    if t_ext_c >= _MIN_TEMP:
        # Interpolation linéaire -7°C → -15°C
        cop_at_minus7 = cop_nominal * _FACTOR_MINUS7
        cop_at_min = cop_nominal * _FACTOR_MINUS15
        frac = (-7.0 - t_ext_c) / (-7.0 - _MIN_TEMP)
        cop = cop_at_minus7 - frac * (cop_at_minus7 - cop_at_min)
        return max(1.0, cop)

    # En dessous de la température minimale : backup électrique
    return 1.0


def pac_seasonal_cop(
    monthly_temps_c: List[float],
    cop_nominal: float = _COP_NOMINAL,
    heating_season_months: Tuple[int, ...] = (1, 2, 3, 4, 10, 11, 12),
) -> float:
    """Calcule le SCOP (COP saisonnier) à partir des températures mensuelles.

    Moyenne pondérée du COP sur les mois de chauffage, en tenant compte de la
    dégradation à basse température.

    Args:
        monthly_temps_c: Liste de 12 températures moyennes mensuelles (°C).
        cop_nominal: COP nominal à +7°C.
        heating_season_months: Mois de la saison de chauffage (1=jan, 12=déc).

    Returns:
        SCOP moyen sur la saison de chauffage.

    Raises:
        ValueError: Si monthly_temps_c ne contient pas 12 valeurs.
    """
    if len(monthly_temps_c) != 12:
        raise ValueError("monthly_temps_c must contain exactly 12 values")

    heating_cops = []
    for month_1based in heating_season_months:
        idx = month_1based - 1
        t = monthly_temps_c[idx]
        cop = pac_cop_at_temperature(t, cop_nominal)
        heating_cops.append(cop)

    if not heating_cops:
        return cop_nominal

    return sum(heating_cops) / len(heating_cops)


def pac_hourly_cop_series(
    hourly_temps_c: List[float],
    cop_nominal: float = _COP_NOMINAL,
) -> List[float]:
    """Calcule le COP horaire de la PAC pour chaque heure de l'année.

    Args:
        hourly_temps_c: Liste de 8760 températures horaires (°C).
        cop_nominal: COP nominal à +7°C.

    Returns:
        Liste de 8760 COP horaires.
    """
    return [pac_cop_at_temperature(t, cop_nominal) for t in hourly_temps_c]


# ============================================================================
# EXPORTS
# ============================================================================

__all__ = [
    "pac_cop_at_temperature",
    "pac_seasonal_cop",
    "pac_hourly_cop_series",
]
