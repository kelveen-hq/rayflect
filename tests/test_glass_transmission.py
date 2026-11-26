"""Tests pour le module glass_transmission.py.

Vérifie les calculs de transmission du vitrage :
- Modèle ASHRAE
- Modèle Fresnel
- Modèle simple
- Propriétés standards des vitrages
"""

import pytest

from src.rayflect.services.optics.glass import (
    GlassProperties,
    TransmissionModel,
    TransmissionResult,
    compute_glass_transmission,
    compute_transmission_ashrae,
    compute_transmission_fresnel,
    compute_transmission_simple,
    compute_transmitted_flux,
    get_standard_glass_properties,
)


class TestASHRAEModel:
    """Tests pour le modèle ASHRAE."""

    def test_normal_incidence(self):
        """À incidence normale, τ = τ₀."""
        # Utiliser GlassProperties explicite
        glass = GlassProperties(tau_normal=0.78)  # Double vitrage standard
        result = compute_transmission_ashrae(0.0, glass)

        assert abs(result.tau - 0.78) < 0.01
        assert abs(result.angular_factor - 1.0) < 0.01

    def test_grazing_incidence(self):
        """À incidence rasante (90°), τ ≈ 0."""
        result = compute_transmission_ashrae(90.0)

        assert result.tau == 0.0
        assert result.angular_factor == 0.0

    def test_60_degrees(self):
        """À 60°, le facteur angulaire est significativement réduit."""
        result = compute_transmission_ashrae(60.0)

        # LBNL Low-E référence : IAM(60°) ≈ 0.686
        # Polynôme ajusté : IAM(60°) ≈ 0.675
        assert 0.60 < result.angular_factor < 0.75
        assert result.tau > 0
        assert result.tau < 0.85

    def test_45_degrees(self):
        """À 45°, la transmission est modérément réduite."""
        result = compute_transmission_ashrae(45.0)

        # LBNL Low-E référence : IAM(45°) ≈ 0.873
        # Polynôme ajusté : IAM(45°) ≈ 0.87
        assert 0.82 < result.angular_factor < 0.92
        assert result.tau > 0.5

    def test_negative_angle_treated_as_positive(self):
        """Les angles négatifs sont traités comme positifs."""
        result_pos = compute_transmission_ashrae(45.0)
        result_neg = compute_transmission_ashrae(-45.0)

        assert abs(result_pos.tau - result_neg.tau) < 0.001

    def test_conservation_of_energy(self):
        """τ + ρ + α ≤ 1 (conservation de l'énergie)."""
        for angle in [0, 30, 45, 60, 75]:
            result = compute_transmission_ashrae(float(angle))
            total = result.tau + result.reflectance + result.absorptance
            assert total <= 1.0 + 0.01  # Petite marge numérique


class TestFresnelModel:
    """Tests pour le modèle Fresnel."""

    def test_normal_incidence(self):
        """À incidence normale, transmission proche de τ₀."""
        glass = GlassProperties(tau_normal=0.85)
        result = compute_transmission_fresnel(0.0, glass)

        # À incidence normale, le modèle Fresnel doit être proche de τ₀
        assert abs(result.tau - 0.85) < 0.15

    def test_grazing_incidence(self):
        """À incidence rasante, la transmission diminue fortement."""
        result = compute_transmission_fresnel(85.0)

        assert result.tau < 0.3  # Très réduite à 85°
        assert result.reflectance > 0.5  # Réflexion dominante

    def test_brewster_angle_region(self):
        """Autour de l'angle de Brewster (~56° pour verre), comportement particulier."""
        # L'angle de Brewster pour n=1.52 est arctan(1.52) ≈ 56.7°
        result = compute_transmission_fresnel(57.0)

        # La transmission doit encore être significative
        assert result.tau > 0.2

    def test_total_internal_reflection_impossible(self):
        """Pas de réflexion totale interne (lumière vient de l'air)."""
        # La réflexion totale interne ne peut pas se produire
        # quand la lumière vient de l'air (n=1) vers le verre (n>1)
        result = compute_transmission_fresnel(89.0)

        # Même à 89°, il y a toujours une petite transmission
        # (mais très faible car réflexion très élevée)
        assert result.reflectance < 1.0


class TestSimpleModel:
    """Tests pour le modèle simple (cosinus)."""

    def test_normal_incidence(self):
        """À incidence normale, τ = τ₀."""
        # Utiliser un vitrage avec tau_normal explicite pour le test
        glass = GlassProperties(tau_normal=0.78)  # Double vitrage standard
        result = compute_transmission_simple(0.0, glass)

        assert abs(result.tau - 0.78) < 0.01
        assert abs(result.angular_factor - 1.0) < 0.01

    def test_60_degrees(self):
        """À 60°, f = cos(60°) = 0.5."""
        glass = GlassProperties(tau_normal=0.78)
        result = compute_transmission_simple(60.0, glass)

        assert abs(result.angular_factor - 0.5) < 0.01
        assert abs(result.tau - 0.78 * 0.5) < 0.01

    def test_grazing_incidence(self):
        """À 90°, τ = 0."""
        result = compute_transmission_simple(90.0)

        assert result.tau == 0.0
        assert result.angular_factor == 0.0


class TestGlassProperties:
    """Tests pour les propriétés du vitrage."""

    def test_default_properties(self):
        """Les propriétés par défaut sont cohérentes (double vitrage)."""
        glass = GlassProperties()

        # Double vitrage standard : tau_normal = 0.78
        assert 0.7 <= glass.tau_normal <= 0.85
        assert 1.4 <= glass.n_glass <= 1.6
        assert glass.n_layers == 2
        assert 0.0 < glass.absorptivity < 0.2
        assert 0.3 < glass.g_factor < 0.8
        # Vérifier conservation de l'énergie
        assert abs(glass.tau_normal + glass.reflectance_normal + glass.absorptivity - 1.0) < 0.01

    def test_custom_properties(self):
        """Les propriétés personnalisées sont respectées."""
        glass = GlassProperties(
            tau_normal=0.70,
            n_glass=1.55,
            n_layers=3,
            absorptivity=0.10,
            g_factor=0.45,
        )

        result = compute_glass_transmission(0.0, glass)

        assert abs(result.tau - 0.70) < 0.01

    def test_standard_glass_types(self):
        """Les types de vitrage standards sont définis."""
        types = ["single", "double", "double_low_e", "triple", "triple_low_e"]

        for glass_type in types:
            glass = get_standard_glass_properties(glass_type)
            assert isinstance(glass, GlassProperties)
            assert 0 < glass.tau_normal <= 1

    def test_unknown_glass_type_raises(self):
        """Un type de vitrage inconnu lève une erreur."""
        with pytest.raises(ValueError, match="Unknown glass type"):
            get_standard_glass_properties("quadruple_mega_low_e")

    def test_single_vs_double_glazing(self):
        """Le simple vitrage transmet plus que le double."""
        single = get_standard_glass_properties("single")
        double = get_standard_glass_properties("double")

        assert single.tau_normal > double.tau_normal


class TestMainInterface:
    """Tests pour l'interface principale."""

    def test_model_selection(self):
        """Tous les modèles sont sélectionnables."""
        for model in TransmissionModel:
            result = compute_glass_transmission(30.0, model=model)
            assert isinstance(result, TransmissionResult)
            assert 0 <= result.tau <= 1

    def test_constant_model(self):
        """Le modèle constant ignore l'angle."""
        result_0 = compute_glass_transmission(0.0, model=TransmissionModel.CONSTANT)
        result_60 = compute_glass_transmission(60.0, model=TransmissionModel.CONSTANT)

        assert abs(result_0.tau - result_60.tau) < 0.001

    def test_models_agree_at_normal(self):
        """Tous les modèles donnent τ₀ à incidence normale."""
        glass = GlassProperties(tau_normal=0.85)

        for model in [TransmissionModel.ASHRAE, TransmissionModel.SIMPLE]:
            result = compute_glass_transmission(0.0, glass, model)
            assert abs(result.tau - 0.85) < 0.02


class TestTransmittedFlux:
    """Tests pour le calcul du flux transmis."""

    def test_basic_transmission(self):
        """Flux transmis = flux incident × τ."""
        flux_in = 1000.0  # W
        # Avec double vitrage par défaut (tau_normal=0.78)
        flux_out = compute_transmitted_flux(flux_in, 0.0)

        assert abs(flux_out - 780.0) < 50  # ~780 W attendu pour τ=0.78

    def test_zero_flux(self):
        """Flux incident nul donne flux transmis nul."""
        flux_out = compute_transmitted_flux(0.0, 45.0)

        assert flux_out == 0.0

    def test_flux_decreases_with_angle(self):
        """Le flux transmis diminue avec l'angle."""
        flux_in = 1000.0

        flux_0 = compute_transmitted_flux(flux_in, 0.0)
        flux_30 = compute_transmitted_flux(flux_in, 30.0)
        flux_60 = compute_transmitted_flux(flux_in, 60.0)

        assert flux_0 > flux_30 > flux_60


class TestPhysicalConsistency:
    """Tests de cohérence physique."""

    def test_transmission_bounded(self):
        """0 ≤ τ ≤ τ₀ pour tous les angles."""
        glass = GlassProperties(tau_normal=0.85)

        for angle in range(0, 91, 5):
            result = compute_glass_transmission(float(angle), glass)
            assert 0 <= result.tau <= glass.tau_normal + 0.01

    def test_angular_factor_bounded(self):
        """0 ≤ f(θ) ≤ 1 pour tous les angles."""
        for angle in range(0, 91, 5):
            result = compute_glass_transmission(float(angle))
            assert 0 <= result.angular_factor <= 1.0 + 0.01

    def test_monotonic_decrease(self):
        """La transmission diminue de façon monotone avec l'angle."""
        prev_tau = 1.0

        for angle in range(0, 91, 5):
            result = compute_glass_transmission(float(angle))
            assert result.tau <= prev_tau + 0.001  # Petite marge numérique
            prev_tau = result.tau

    def test_ashrae_vs_fresnel_similar_trend(self):
        """ASHRAE et Fresnel ont des tendances similaires."""
        angles = [0, 30, 45, 60, 75]

        ashrae_taus = [compute_glass_transmission(a, model=TransmissionModel.ASHRAE).tau for a in angles]
        fresnel_taus = [compute_glass_transmission(a, model=TransmissionModel.FRESNEL).tau for a in angles]

        # Les deux doivent diminuer
        assert all(ashrae_taus[i] >= ashrae_taus[i+1] for i in range(len(ashrae_taus)-1))
        assert all(fresnel_taus[i] >= fresnel_taus[i+1] for i in range(len(fresnel_taus)-1))
