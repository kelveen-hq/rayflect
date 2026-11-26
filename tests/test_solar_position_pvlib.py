"""Tests pour les fonctions pvlib dans solar_position.py."""

import pytest
from datetime import datetime
from zoneinfo import ZoneInfo

from rayflect.services.solar.position import (
    SolarPosition,
    is_pvlib_available,
    compute_sun_position_pvlib,
    compute_sun_positions_batch,
    compute_sun_position_auto,
    estimate_sun_position_simple,
)


class TestPvlibAvailability:
    """Tests pour la detection de pvlib."""

    def test_is_pvlib_available_returns_bool(self):
        """La fonction retourne un booleen."""
        result = is_pvlib_available()
        assert isinstance(result, bool)


class TestEstimateSunPositionSimple:
    """Tests pour la methode simplifiee (fallback)."""

    def test_midday_summer_high_elevation(self):
        """A midi en ete, elevation elevee."""
        # 21 juin, midi solaire, latitude 45N
        pos = estimate_sun_position_simple(
            hour=12.0,
            day_of_year=172,  # 21 juin
            latitude_deg=45.0,
        )

        assert pos.elevation_deg > 60  # Soleil haut
        assert 160 < pos.azimuth_deg < 200  # Proche du Sud

    def test_midday_winter_lower_elevation(self):
        """A midi en hiver, elevation plus basse."""
        summer = estimate_sun_position_simple(12.0, 172, 45.0)
        winter = estimate_sun_position_simple(12.0, 355, 45.0)  # 21 dec

        assert winter.elevation_deg < summer.elevation_deg

    def test_morning_east_azimuth(self):
        """Le matin, azimut vers l'Est."""
        pos = estimate_sun_position_simple(
            hour=8.0,
            day_of_year=172,
            latitude_deg=45.0,
        )

        assert 60 < pos.azimuth_deg < 120  # Est-ish

    def test_evening_west_azimuth(self):
        """Le soir, azimut vers l'Ouest."""
        pos = estimate_sun_position_simple(
            hour=18.0,
            day_of_year=172,
            latitude_deg=45.0,
        )

        assert 240 < pos.azimuth_deg < 300  # Ouest-ish

    def test_night_negative_elevation(self):
        """La nuit, elevation nulle ou negative."""
        pos = estimate_sun_position_simple(
            hour=2.0,
            day_of_year=172,
            latitude_deg=45.0,
        )

        assert pos.elevation_deg <= 0


@pytest.mark.skipif(not is_pvlib_available(), reason="pvlib not installed")
class TestComputeSunPositionPvlib:
    """Tests pour la fonction pvlib (si disponible)."""

    def test_basic_calculation(self):
        """Test de base du calcul pvlib."""
        ts = datetime(2024, 6, 21, 12, 0, 0, tzinfo=ZoneInfo("UTC"))
        pos = compute_sun_position_pvlib(
            timestamp=ts,
            latitude_deg=45.0,
            longitude_deg=0.0,
        )

        assert isinstance(pos, SolarPosition)
        assert 0 <= pos.elevation_deg <= 90
        assert 0 <= pos.azimuth_deg < 360

    def test_summer_high_elevation(self):
        """En ete, elevation elevee a midi."""
        ts = datetime(2024, 6, 21, 12, 0, 0, tzinfo=ZoneInfo("UTC"))
        pos = compute_sun_position_pvlib(ts, 45.0, 0.0)

        assert pos.elevation_deg > 50

    def test_winter_lower_elevation(self):
        """En hiver, elevation plus basse."""
        summer = compute_sun_position_pvlib(
            datetime(2024, 6, 21, 12, 0, tzinfo=ZoneInfo("UTC")), 45.0, 0.0
        )
        winter = compute_sun_position_pvlib(
            datetime(2024, 12, 21, 12, 0, tzinfo=ZoneInfo("UTC")), 45.0, 0.0
        )

        assert winter.elevation_deg < summer.elevation_deg


@pytest.mark.skipif(not is_pvlib_available(), reason="pvlib not installed")
class TestComputeSunPositionsBatch:
    """Tests pour le calcul batch (vectorise)."""

    def test_batch_returns_dict(self):
        """Le batch retourne un dictionnaire."""
        timestamps = [
            datetime(2024, 6, 21, h, 0, tzinfo=ZoneInfo("UTC"))
            for h in range(6, 20)
        ]

        result = compute_sun_positions_batch(
            timestamps=timestamps,
            latitude_deg=45.0,
            longitude_deg=0.0,
        )

        assert isinstance(result, dict)
        assert len(result) == len(timestamps)

    def test_batch_contains_solar_positions(self):
        """Chaque element est une SolarPosition."""
        timestamps = [
            datetime(2024, 6, 21, 12, 0, tzinfo=ZoneInfo("UTC")),
            datetime(2024, 6, 21, 15, 0, tzinfo=ZoneInfo("UTC")),
        ]

        result = compute_sun_positions_batch(timestamps, 45.0, 0.0)

        for ts, pos in result.items():
            assert isinstance(pos, SolarPosition)

    def test_batch_empty_list(self):
        """Liste vide retourne dict vide."""
        result = compute_sun_positions_batch([], 45.0, 0.0)
        assert result == {}

    def test_batch_consistent_with_single(self):
        """Le batch donne les memes resultats que les appels individuels."""
        ts = datetime(2024, 6, 21, 12, 0, tzinfo=ZoneInfo("UTC"))

        single = compute_sun_position_pvlib(ts, 45.0, 0.0)
        batch = compute_sun_positions_batch([ts], 45.0, 0.0)

        assert abs(single.elevation_deg - batch[ts].elevation_deg) < 0.1
        assert abs(single.azimuth_deg - batch[ts].azimuth_deg) < 0.1


class TestComputeSunPositionAuto:
    """Tests pour la selection automatique de methode."""

    def test_returns_solar_position(self):
        """Retourne toujours une SolarPosition."""
        ts = datetime(2024, 6, 21, 12, 0, tzinfo=ZoneInfo("UTC"))
        pos = compute_sun_position_auto(ts, 45.0, 0.0)

        assert isinstance(pos, SolarPosition)

    def test_prefer_pvlib_false_uses_simple(self):
        """Avec prefer_pvlib=False, utilise la methode simple."""
        ts = datetime(2024, 6, 21, 12, 0, tzinfo=ZoneInfo("UTC"))

        simple = estimate_sun_position_simple(12.0, 172, 45.0)
        auto = compute_sun_position_auto(ts, 45.0, 0.0, prefer_pvlib=False)

        # Devrait etre proche (pas exactement egal car la methode simple
        # est simplifiee)
        assert abs(simple.elevation_deg - auto.elevation_deg) < 5

    @pytest.mark.skipif(not is_pvlib_available(), reason="pvlib not installed")
    def test_prefer_pvlib_true_uses_pvlib(self):
        """Avec prefer_pvlib=True et pvlib dispo, utilise pvlib."""
        ts = datetime(2024, 6, 21, 12, 0, tzinfo=ZoneInfo("UTC"))

        pvlib_result = compute_sun_position_pvlib(ts, 45.0, 0.0)
        auto = compute_sun_position_auto(ts, 45.0, 0.0, prefer_pvlib=True)

        assert abs(pvlib_result.elevation_deg - auto.elevation_deg) < 0.01
