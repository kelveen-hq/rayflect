"""Tests unitaires pour le module irradiance.

Vérifie les estimations DNI, direction diffuse et projection de surface.
"""

import math
import numpy as np
import pytest
from dataclasses import dataclass

from rayflect.services.solar.irradiance import (
    estimate_direct_normal_irradiance,
    diffuse_source_direction,
    project_surface,
    DIFFUSE_PLANE_OFFSET_DEG,
)


@dataclass
class MockWeatherSample:
    """Sample météo simulé pour les tests."""
    global_horizontal_irradiance: float = 0.0
    diffuse_horizontal_irradiance: float = 0.0
    direct_normal_irradiance: float | None = None


class TestEstimateDirectNormalIrradiance:
    """Tests d'estimation du DNI."""

    def test_uses_provided_dni_if_available(self):
        """Si DNI est fourni directement, on l'utilise."""
        sample = MockWeatherSample(
            global_horizontal_irradiance=500.0,
            diffuse_horizontal_irradiance=100.0,
            direct_normal_irradiance=700.0,
        )
        dni = estimate_direct_normal_irradiance(sample, 45.0)
        assert dni == pytest.approx(700.0, abs=1e-6)

    def test_computes_dni_from_ghi_dhi(self):
        """DNI estimé à partir de GHI - DHI / cos(zenith)."""
        ghi = 600.0
        dhi = 100.0
        elevation = 45.0  # zenith = 45°
        sample = MockWeatherSample(
            global_horizontal_irradiance=ghi,
            diffuse_horizontal_irradiance=dhi,
        )
        dni = estimate_direct_normal_irradiance(sample, elevation)
        # beam = ghi - dhi = 500
        # cos(zenith) = cos(45°) ≈ 0.707
        expected = 500.0 / math.cos(math.radians(45.0))
        assert dni == pytest.approx(expected, rel=1e-3)

    def test_returns_zero_for_negative_beam(self):
        """Si GHI < DHI, beam est négatif → retourne 0."""
        sample = MockWeatherSample(
            global_horizontal_irradiance=50.0,
            diffuse_horizontal_irradiance=100.0,
        )
        dni = estimate_direct_normal_irradiance(sample, 45.0)
        assert dni == 0.0

    def test_handles_low_elevation(self):
        """Soleil très bas → cos(zenith) petit mais > 1e-3."""
        sample = MockWeatherSample(
            global_horizontal_irradiance=100.0,
            diffuse_horizontal_irradiance=80.0,
        )
        dni = estimate_direct_normal_irradiance(sample, 5.0)  # zenith = 85°
        # Ne doit pas planter, doit retourner une valeur
        assert dni >= 0.0

    def test_handles_zenith_sun(self):
        """Soleil au zénith → cos = 1."""
        sample = MockWeatherSample(
            global_horizontal_irradiance=1000.0,
            diffuse_horizontal_irradiance=200.0,
        )
        dni = estimate_direct_normal_irradiance(sample, 90.0)
        # beam = 800, cos(0°) = 1
        assert dni == pytest.approx(800.0, rel=1e-3)


class TestDiffuseSourceDirection:
    """Tests de direction diffuse moyenne."""

    def test_south_facade_direction_has_positive_z(self):
        """Façade Sud → direction diffuse a une composante Z positive."""
        facade_normal = np.array([0.0, -1.0, 0.0])  # Sud
        direction = diffuse_source_direction(facade_normal)
        assert direction[2] > 0  # Composante vers le haut

    def test_direction_is_unit_vector(self):
        """La direction retournée est unitaire."""
        facade_normal = np.array([0.0, -1.0, 0.0])
        direction = diffuse_source_direction(facade_normal)
        assert np.linalg.norm(direction) == pytest.approx(1.0, abs=1e-9)

    def test_east_facade_direction(self):
        """Façade Est → direction a une composante X positive."""
        facade_normal = np.array([1.0, 0.0, 0.0])  # Est
        direction = diffuse_source_direction(facade_normal)
        assert direction[0] > 0
        assert direction[2] > 0

    def test_zero_facade_raises(self):
        """Une normale nulle lève une erreur."""
        with pytest.raises(ValueError, match="zero length"):
            diffuse_source_direction(np.array([0.0, 0.0, 0.0]))

    def test_angle_matches_offset(self):
        """L'angle avec la verticale correspond à DIFFUSE_PLANE_OFFSET_DEG."""
        facade_normal = np.array([0.0, -1.0, 0.0])
        direction = diffuse_source_direction(facade_normal)
        # Angle avec la verticale
        vertical = np.array([0.0, 0.0, 1.0])
        cos_angle = np.dot(direction, vertical)
        angle_deg = math.degrees(math.acos(cos_angle))
        # L'angle depuis la verticale est DIFFUSE_PLANE_OFFSET_DEG (30°)
        assert angle_deg == pytest.approx(DIFFUSE_PLANE_OFFSET_DEG, abs=1.0)


class TestProjectSurface:
    """Tests de projection de surface."""

    def test_perpendicular_full_projection(self):
        """Surface perpendiculaire → projection complète."""
        normal = np.array([0.0, 1.0, 0.0])
        direction = np.array([0.0, 1.0, 0.0])
        projected = project_surface(2.0, normal, direction)
        assert projected == pytest.approx(2.0, abs=1e-9)

    def test_parallel_zero_projection(self):
        """Surface parallèle → projection nulle."""
        normal = np.array([0.0, 1.0, 0.0])
        direction = np.array([1.0, 0.0, 0.0])
        projected = project_surface(2.0, normal, direction)
        assert projected == pytest.approx(0.0, abs=1e-9)

    def test_45deg_projection(self):
        """45° → projection = area × cos(45°)."""
        normal = np.array([0.0, 1.0, 0.0])
        direction = np.array([0.0, 1.0, 1.0]) / math.sqrt(2)
        projected = project_surface(2.0, normal, direction)
        expected = 2.0 * math.cos(math.radians(45))
        assert projected == pytest.approx(expected, abs=1e-6)

    def test_negative_cos_returns_zero(self):
        """Direction opposée à la normale → projection nulle."""
        normal = np.array([0.0, 1.0, 0.0])
        direction = np.array([0.0, -1.0, 0.0])
        projected = project_surface(2.0, normal, direction)
        assert projected == 0.0

    def test_zero_area_returns_zero(self):
        """Surface nulle → projection nulle."""
        normal = np.array([0.0, 1.0, 0.0])
        direction = np.array([0.0, 1.0, 0.0])
        projected = project_surface(0.0, normal, direction)
        assert projected == 0.0


class TestConstants:
    """Tests des constantes du module."""

    def test_diffuse_plane_offset_is_reasonable(self):
        """L'offset de plan diffus est un angle raisonnable."""
        assert 0.0 < DIFFUSE_PLANE_OFFSET_DEG < 90.0
