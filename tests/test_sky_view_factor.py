"""Tests unitaires pour les modules de Sky View Factor.

Tests des modèles de calcul du Sky View Factor :
- Modèle simple (surface inclinée isolée)
- Modèle avec obstacle horizontal
- DHI effectif (ciel et réflexion du sol)
"""

import math
import pytest
from rayflect.services.solar.sky_view import (
    compute_simple_svf,
    compute_ground_view_factor,
    compute_svf_with_obstacle,
    compute_effective_dhi,
    ObstacleConfig,
    SkyViewResult,
)


# =============================================================================
# TESTS DU MODÈLE SIMPLE (surface inclinée)
# =============================================================================

class TestSimpleSVF:
    """Tests du modèle simple F_sky = (1 + cos(β)) / 2."""

    def test_horizontal_surface(self):
        """Surface horizontale (β=0°) → F_sky = 1 (voit tout le ciel)."""
        f_sky = compute_simple_svf(0.0)
        assert f_sky == pytest.approx(1.0, abs=0.001)

    def test_vertical_surface(self):
        """Surface verticale (β=90°) → F_sky = 0.5 (voit moitié du ciel)."""
        f_sky = compute_simple_svf(90.0)
        assert f_sky == pytest.approx(0.5, abs=0.001)

    def test_45_degree_surface(self):
        """Surface à 45° → F_sky ≈ 0.854."""
        f_sky = compute_simple_svf(45.0)
        expected = 0.5 * (1 + math.cos(math.radians(45)))
        assert f_sky == pytest.approx(expected, abs=0.001)
        assert 0.85 < f_sky < 0.86

    def test_inverted_surface(self):
        """Surface inversée (β=180°) → F_sky = 0 (face au sol)."""
        f_sky = compute_simple_svf(180.0)
        assert f_sky == pytest.approx(0.0, abs=0.001)

    def test_monotonic_decrease(self):
        """F_sky décroît de 0° à 180°."""
        previous = 1.1
        for angle in range(0, 181, 10):
            f_sky = compute_simple_svf(float(angle))
            assert f_sky < previous, f"F_sky should decrease at {angle}°"
            previous = f_sky


class TestGroundViewFactor:
    """Tests du facteur de vue du sol."""

    def test_horizontal_no_ground(self):
        """Surface horizontale (β=0°) → F_ground = 0."""
        f_ground = compute_ground_view_factor(0.0)
        assert f_ground == pytest.approx(0.0, abs=0.001)

    def test_vertical_half_ground(self):
        """Surface verticale (β=90°) → F_ground = 0.5."""
        f_ground = compute_ground_view_factor(90.0)
        assert f_ground == pytest.approx(0.5, abs=0.001)

    def test_complementary_to_sky(self):
        """F_sky + F_ground = 1 pour toute inclinaison."""
        for angle in range(0, 181, 15):
            f_sky = compute_simple_svf(float(angle))
            f_ground = compute_ground_view_factor(float(angle))
            assert f_sky + f_ground == pytest.approx(1.0, abs=0.001)


# =============================================================================
# TESTS DU MODÈLE AVEC OBSTACLE
# =============================================================================

class TestObstacleSVF:
    """Tests du modèle avec obstacle horizontal."""

    def test_no_obstacle(self):
        """Sans obstacle → même que simple SVF."""
        no_obstacle = ObstacleConfig(depth_m=0, height_above_m=1.0)
        result = compute_svf_with_obstacle(45.0, no_obstacle)
        simple = compute_simple_svf(45.0)
        assert result.f_sky == pytest.approx(simple, abs=0.001)
        assert result.f_obstacle == pytest.approx(0.0, abs=0.001)

    def test_small_obstacle_reduces_svf(self):
        """Un petit obstacle réduit le SVF."""
        obstacle = ObstacleConfig(depth_m=0.5, height_above_m=2.0)
        result = compute_svf_with_obstacle(30.0, obstacle)
        simple = compute_simple_svf(30.0)
        assert result.f_sky < simple
        assert result.f_obstacle > 0

    def test_larger_obstacle_more_reduction(self):
        """Un obstacle plus profond réduit davantage."""
        small = ObstacleConfig(depth_m=0.5, height_above_m=2.0)
        large = ObstacleConfig(depth_m=1.5, height_above_m=2.0)

        result_small = compute_svf_with_obstacle(30.0, small)
        result_large = compute_svf_with_obstacle(30.0, large)

        assert result_large.f_sky < result_small.f_sky
        assert result_large.f_obstacle > result_small.f_obstacle


# =============================================================================
# TESTS CALCUL DHI EFFECTIF
# =============================================================================

class TestEffectiveDHI:
    """Tests du calcul du DHI effectif."""

    def test_sky_contribution(self):
        """Le DHI ciel est pondéré par F_sky."""
        svf = SkyViewResult(
            f_sky=0.8, f_ground=0.2, f_obstacle=0.0,
            effective_tilt_deg=30.0, details={}
        )

        dhi_sky, dhi_ground, dhi_total = compute_effective_dhi(
            dhi_w_m2=100, ghi_w_m2=500, svf_result=svf
        )

        assert dhi_sky == pytest.approx(80.0)  # 100 × 0.8

    def test_ground_reflection(self):
        """La réflexion du sol dépend de GHI et albédo."""
        svf = SkyViewResult(
            f_sky=0.5, f_ground=0.5, f_obstacle=0.0,
            effective_tilt_deg=90.0, details={}
        )

        dhi_sky, dhi_ground, dhi_total = compute_effective_dhi(
            dhi_w_m2=100, ghi_w_m2=800, svf_result=svf, ground_albedo=0.2
        )

        # Ground = GHI × albedo × F_ground = 800 × 0.2 × 0.5 = 80
        assert dhi_ground == pytest.approx(80.0)
