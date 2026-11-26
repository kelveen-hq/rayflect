"""Structures météo immuables utilisées des services."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Iterable, Optional, Tuple


def _validate_monotonic(samples: Tuple["WeatherSample", ...]) -> None:
    timestamps = [sample.timestamp for sample in samples]
    if any(earlier >= later for earlier, later in zip(timestamps, timestamps[1:])):
        raise ValueError("weather samples must be strictly increasing in time")


@dataclass(frozen=True)
class WeatherSample:
    """Point météo horaire utilisé par les services physiques.

    Toutes les intensités sont exprimées en W/m² et les températures en °C.
    """

    timestamp: datetime
    global_horizontal_irradiance: float
    diffuse_horizontal_irradiance: float
    ambient_temperature_c: float
    direct_normal_irradiance: float | None = None
    wind_speed_m_s: float = 0.0


@dataclass(frozen=True)
class WeatherSeries:
    """Séquence ordonnée de mesures météo à pas de temps fixe."""

    samples: Tuple[WeatherSample, ...]
    sampling_minutes: int

    def __post_init__(self) -> None:
        if not self.samples:
            raise ValueError("weather series cannot be empty")
        if self.sampling_minutes <= 0:
            raise ValueError("sampling_minutes must be > 0")
        _validate_monotonic(self.samples)

    @classmethod
    def from_iterable(
        cls,
        records: Iterable[WeatherSample],
        sampling_minutes: int,
    ) -> "WeatherSeries":
        """Crée une série en gelant les échantillons fournis."""

        return cls(tuple(records), sampling_minutes)

    def total_incident_energy_wh(
        self,
        surface_area_m2: float,
        *,
        scaling_factors: Optional[Iterable[float]] = None,
    ) -> float:
        """Énergie incidente totale sur la surface considérée (Wh).

        Le calcul suppose que `global_horizontal_irradiance` est constant sur
        l'intervalle de `sampling_minutes`.
        """

        if surface_area_m2 <= 0:
            raise ValueError("surface_area_m2 must be > 0")
        time_factor = self.sampling_minutes / 60.0
        if scaling_factors is not None:
            factors = tuple(scaling_factors)
            if len(factors) != len(self.samples):
                raise ValueError("scaling_factors must match sample count")
        else:
            factors = tuple(1.0 for _ in self.samples)
        return sum(
            sample.global_horizontal_irradiance
            * max(0.0, factor)
            * surface_area_m2
            * time_factor
            for sample, factor in zip(self.samples, factors)
        )

    @property
    def sample_count(self) -> int:
        """Nombre d'échantillons contenus dans la série."""

        return len(self.samples)
