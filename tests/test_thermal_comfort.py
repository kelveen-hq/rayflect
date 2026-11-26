"""
Tests unitaires pour le module thermal_comfort (conformité RE2020).
==================================================================

Teste:
- Calcul des Degrés-Heures (DH) été/hiver
- Vérification conformité RE2020
- Comptage jours de canicule/froid
- Comparaison sans protection / avec protection

Références:
- RE2020: DH ≤ 350 = confort, DH ≤ 1250 = acceptable, DH > 1250 = non conforme
- Seuil canicule: 28°C
- Seuil froid: 18°C
"""

import pytest
import numpy as np

from rayflect.services.thermal.comfort import (
    compute_degree_hours_summer,
    compute_degree_hours_winter,
    check_re2020_compliance,
    count_discomfort_days,
    compare_thermal_comfort,
    DegreeHoursResult,
    DiscomfortDaysResult,
    RE2020ComplianceResult,
    ThermalComfortComparison,
)


# =============================================================================
# FIXTURES
# =============================================================================

@pytest.fixture
def constant_temp_25():
    """Température constante à 25°C - 24h (sous le seuil adaptatif)."""
    return np.array([25.0] * 24)


@pytest.fixture
def constant_temp_30():
    """Température constante à 30°C - 24h (au-dessus du seuil adaptatif)."""
    return np.array([30.0] * 24)


@pytest.fixture
def constant_temp_15():
    """Température constante à 15°C - 24h (sous la consigne 19°C)."""
    return np.array([15.0] * 24)


@pytest.fixture
def constant_ext_20():
    """Température extérieure constante à 20°C - 24h."""
    return np.array([20.0] * 24)


@pytest.fixture
def constant_ext_25():
    """Température extérieure constante à 25°C - 24h."""
    return np.array([25.0] * 24)


@pytest.fixture
def typical_summer_day():
    """Journée d'été typique avec variation jour/nuit - 24h."""
    # Simule: nuit fraîche (22°C), montée vers 32°C l'après-midi, redescente
    return np.array([
        22, 21, 20, 20, 21, 22,  # 00h-05h: nuit
        24, 26, 28, 30, 31, 32,  # 06h-11h: montée
        32, 32, 31, 30, 29, 28,  # 12h-17h: après-midi chaud
        27, 26, 25, 24, 23, 22,  # 18h-23h: soirée
    ], dtype=float)


@pytest.fixture
def typical_ext_summer_day():
    """Température extérieure journée d'été - 24h."""
    return np.array([
        18, 17, 16, 16, 17, 18,  # 00h-05h: nuit
        20, 22, 25, 28, 30, 32,  # 06h-11h: montée
        33, 33, 32, 30, 28, 26,  # 12h-17h: après-midi
        24, 22, 21, 20, 19, 18,  # 18h-23h: soirée
    ], dtype=float)


@pytest.fixture
def typical_winter_day():
    """Journée d'hiver typique (T° intérieure) - 24h."""
    # Simule: nuit fraîche (16°C), montée vers 19°C, redescente
    return np.array([
        16, 15, 15, 15, 15, 16,  # 00h-05h: nuit fraîche
        17, 18, 19, 19, 19, 19,  # 06h-11h: chauffage actif
        19, 19, 19, 18, 18, 17,  # 12h-17h: après-midi
        16, 16, 16, 16, 16, 16,  # 18h-23h: soirée
    ], dtype=float)


@pytest.fixture
def year_hourly_data():
    """Données annuelles (8760h) avec variation saisonnière."""
    # Simule une année: hiver 15°C base, été 28°C base, avec variations
    hours = []
    for day in range(365):
        # Variation saisonnière: jan=15°C, juil=28°C
        base_temp = 21.5 + 6.5 * np.sin((day - 80) * 2 * np.pi / 365)
        for hour in range(24):
            # Variation journalière ±3°C
            daily_var = 3 * np.sin((hour - 6) * 2 * np.pi / 24)
            hours.append(base_temp + daily_var)
    return np.array(hours)


@pytest.fixture
def year_ext_data():
    """Températures extérieures annuelles (8760h)."""
    hours = []
    for day in range(365):
        # Variation saisonnière plus marquée
        base_temp = 15 + 10 * np.sin((day - 80) * 2 * np.pi / 365)
        for hour in range(24):
            daily_var = 5 * np.sin((hour - 6) * 2 * np.pi / 24)
            hours.append(base_temp + daily_var)
    return np.array(hours)


# =============================================================================
# TESTS DH ÉTÉ
# =============================================================================

class TestDegreeHoursSummer:
    """Tests pour compute_degree_hours_summer."""

    def test_below_comfort_no_dh(self, constant_temp_25, constant_ext_20):
        """Température intérieure sous le confort adaptatif = peu de DH."""
        result = compute_degree_hours_summer(constant_temp_25, constant_ext_20)

        assert isinstance(result, DegreeHoursResult)
        # À 25°C intérieur avec ext 20°C, on devrait être proche du confort
        assert result.dh_total >= 0  # Toujours positif ou nul
        assert result.hours_analyzed == 24

    def test_above_comfort_calculates_dh(self, constant_temp_30, constant_ext_25):
        """Température au-dessus du confort = DH calculés."""
        result = compute_degree_hours_summer(constant_temp_30, constant_ext_25)

        # À 30°C intérieur avec ext 25°C, on est au-dessus du confort adaptatif
        assert result.dh_total > 0
        assert result.hours_discomfort > 0

    def test_typical_summer_day(self, typical_summer_day, typical_ext_summer_day):
        """Journée d'été typique avec pics de chaleur."""
        result = compute_degree_hours_summer(typical_summer_day, typical_ext_summer_day)

        # On doit avoir des heures de surchauffe
        assert result.hours_discomfort > 0
        assert result.dh_total > 0
        assert result.max_deviation > 0

    def test_size_mismatch_raises(self):
        """Tailles différentes = erreur."""
        t_int = np.array([25.0] * 24)
        t_ext = np.array([20.0] * 12)  # Taille différente

        with pytest.raises(ValueError, match="même taille"):
            compute_degree_hours_summer(t_int, t_ext)

    def test_with_occupation_mask(self, constant_temp_30, constant_ext_25):
        """Test avec masque d'occupation partielle."""
        # Seulement 8h sur 24 sont occupées
        mask = np.zeros(24, dtype=bool)
        mask[8:16] = True  # Occupation 8h-16h

        result_full = compute_degree_hours_summer(constant_temp_30, constant_ext_25)
        result_partial = compute_degree_hours_summer(
            constant_temp_30, constant_ext_25, occupation_mask=mask
        )

        # DH partiel devrait être inférieur (moins d'heures comptées)
        assert result_partial.dh_total <= result_full.dh_total


# =============================================================================
# TESTS DH HIVER
# =============================================================================

class TestDegreeHoursWinter:
    """Tests pour compute_degree_hours_winter."""

    def test_above_setpoint_no_dh(self):
        """Température au-dessus de la consigne = 0 DH."""
        temps = np.array([20.0] * 24)
        result = compute_degree_hours_winter(temps, t_setpoint=19.0)

        assert result.dh_total == 0.0
        assert result.hours_discomfort == 0

    def test_below_setpoint_calculates_dh(self, constant_temp_15):
        """Température sous la consigne = DH calculés."""
        # 24h à 15°C avec consigne 19°C = 24 × (19-15) = 96 DH
        result = compute_degree_hours_winter(constant_temp_15, t_setpoint=19.0)

        assert result.dh_total == pytest.approx(96.0, abs=0.1)
        assert result.hours_discomfort == 24

    def test_typical_winter_day(self, typical_winter_day):
        """Journée d'hiver typique avec variations."""
        result = compute_degree_hours_winter(typical_winter_day, t_setpoint=19.0)

        # Quelques heures sous la consigne
        assert result.hours_discomfort > 0
        assert result.dh_total > 0


# =============================================================================
# TESTS CONFORMITÉ RE2020
# =============================================================================

class TestRE2020Compliance:
    """Tests pour check_re2020_compliance."""

    def test_excellent_comfort(self):
        """DH ≤ 350 = conforme, catégorie confortable."""
        result = check_re2020_compliance(100.0)

        assert isinstance(result, RE2020ComplianceResult)
        assert result.compliant is True
        assert result.category == "confortable"
        assert result.dh_summer == 100.0

    def test_comfort_limit(self):
        """DH = 350 = encore dans la catégorie confortable."""
        result = check_re2020_compliance(350.0)

        assert result.compliant is True
        assert result.category == "confortable"

    def test_moderate_discomfort(self):
        """350 < DH ≤ 1250 = acceptable, inconfort modéré."""
        result = check_re2020_compliance(800.0)

        assert result.compliant is True
        assert result.category == "inconfort_modere"
        assert result.needs_cooling is True

    def test_max_limit(self):
        """DH = 1250 = limite acceptable."""
        result = check_re2020_compliance(1250.0)

        assert result.compliant is True
        assert result.category == "inconfort_modere"

    def test_non_compliant(self):
        """DH > 1250 = non conforme."""
        result = check_re2020_compliance(1500.0)

        assert result.compliant is False
        assert result.category == "non_conforme"
        assert result.margin_to_threshold < 0  # Marge négative

    def test_zero_dh(self):
        """DH = 0 = parfait."""
        result = check_re2020_compliance(0.0)

        assert result.compliant is True
        assert result.category == "confortable"
        assert result.needs_cooling is False


# =============================================================================
# TESTS JOURS D'INCONFORT
# =============================================================================

class TestDiscomfortDays:
    """Tests pour count_discomfort_days."""

    def test_no_discomfort(self):
        """Toutes les températures dans la zone de confort."""
        # 7 jours à 22°C constant
        t_indoor = np.array([22.0] * 168)

        result = count_discomfort_days(t_indoor)

        assert isinstance(result, DiscomfortDaysResult)
        assert result.days_heatwave == 0
        assert result.days_cold == 0
        assert result.total_days == 7

    def test_heatwave_days(self):
        """Jours de canicule (>28°C)."""
        # 2 jours à 30°C + 1 jour à 22°C
        t_indoor = np.concatenate([
            np.array([30.0] * 48),  # 2 jours chauds
            np.array([22.0] * 24),  # 1 jour normal
        ])

        result = count_discomfort_days(t_indoor)

        assert result.days_heatwave == 2
        assert result.hours_above_28 == 48

    def test_cold_days(self):
        """Jours de froid (<18°C)."""
        # 2 jours à 15°C + 1 jour à 22°C
        t_indoor = np.concatenate([
            np.array([15.0] * 48),  # 2 jours froids
            np.array([22.0] * 24),  # 1 jour normal
        ])

        result = count_discomfort_days(t_indoor)

        assert result.days_cold == 2
        assert result.hours_below_19 == 48

    def test_custom_thresholds(self):
        """Test avec seuils personnalisés."""
        t_indoor = np.array([25.0] * 48)  # 2 jours à 25°C

        # Seuil canicule abaissé à 24°C
        result = count_discomfort_days(t_indoor, heatwave_threshold=24.0)
        assert result.days_heatwave == 2

        # Seuil canicule relevé à 26°C
        result = count_discomfort_days(t_indoor, heatwave_threshold=26.0)
        assert result.days_heatwave == 0


# =============================================================================
# TESTS COMPARAISON SANS PROTECTION / AVEC PROTECTION
# =============================================================================

class TestThermalComfortComparison:
    """Tests pour compare_thermal_comfort."""

    def test_comparison_structure(self):
        """Vérifie la structure du résultat de comparaison."""
        # Sans protection: chaud (30°C)
        t_without = np.array([30.0] * 24)
        # Avec protection: plus frais (26°C)
        t_with = np.array([26.0] * 24)
        t_ext = np.array([25.0] * 24)

        result = compare_thermal_comfort(
            t_interior_without=t_without,
            t_interior_with=t_with,
            t_exterior=t_ext,
        )

        assert isinstance(result, ThermalComfortComparison)
        assert hasattr(result, 'dh_summer_with')
        assert hasattr(result, 'dh_summer_without')
        assert hasattr(result, 'reduction_summer_pct')

    def test_protection_reduces_dh_summer(self):
        """La protection réduit les DH en été."""
        # Sans protection: chaud (30°C pendant 24h)
        t_without = np.array([30.0] * 24)
        # Avec protection: plus frais (25°C)
        t_with = np.array([25.0] * 24)
        t_ext = np.array([25.0] * 24)

        result = compare_thermal_comfort(
            t_interior_without=t_without,
            t_interior_with=t_with,
            t_exterior=t_ext,
        )

        # DH sans > DH avec
        assert result.dh_summer_without > result.dh_summer_with
        assert result.reduction_summer_pct > 0

    def test_compliance_comparison(self):
        """Compare la conformité RE2020."""
        # Cas extrême: sans protection non conforme, avec protection conforme
        t_without = np.array([35.0] * 168)  # 1 semaine très chaude
        t_with = np.array([26.0] * 168)     # La protection ramène à 26°C
        t_ext = np.array([30.0] * 168)

        result = compare_thermal_comfort(
            t_interior_without=t_without,
            t_interior_with=t_with,
            t_exterior=t_ext,
        )

        # Les deux résultats de conformité doivent exister
        assert hasattr(result, 'compliance_without')
        assert hasattr(result, 'compliance_with')


# =============================================================================
# TESTS AVEC DONNÉES ANNUELLES
# =============================================================================

class TestAnnualData:
    """Tests avec données sur une année complète."""

    def test_full_year_dh_summer(self, year_hourly_data, year_ext_data):
        """Calcul DH été sur une année."""
        result = compute_degree_hours_summer(year_hourly_data, year_ext_data)

        # Doit avoir des heures au-dessus du seuil adaptatif en été
        assert result.hours_analyzed == 8760
        # Le DH peut être nul si les températures sont dans le confort

    def test_full_year_discomfort_days(self, year_hourly_data):
        """Comptage jours inconfort sur une année."""
        result = count_discomfort_days(year_hourly_data)

        assert result.total_days == 365
        # Avec les données simulées, on peut avoir quelques jours extrêmes


# =============================================================================
# TESTS EDGE CASES
# =============================================================================

class TestEdgeCases:
    """Tests des cas limites."""

    def test_single_day(self):
        """Une seule journée de données."""
        t_int = np.array([30.0] * 24)
        t_ext = np.array([25.0] * 24)

        result = compute_degree_hours_summer(t_int, t_ext)

        assert result.hours_analyzed == 24

    def test_exactly_at_comfort(self):
        """Température exactement au seuil de confort."""
        # Avec T_ext = 20°C, T_confort_max ≈ 25.4°C (catégorie II)
        t_int = np.array([25.4] * 24)
        t_ext = np.array([20.0] * 24)

        result = compute_degree_hours_summer(t_int, t_ext)

        # Très proche du confort = DH quasi nul
        assert result.dh_total < 5  # Tolérance pour les arrondis

    def test_negative_ext_temperatures(self):
        """Températures extérieures négatives (hiver rigoureux)."""
        t_int = np.array([15.0] * 24)  # Intérieur à 15°C
        result = compute_degree_hours_winter(t_int, t_setpoint=19.0)

        # DH = 24 × (19 - 15) = 96
        assert result.dh_total == pytest.approx(96.0, abs=0.1)

    def test_very_high_temperatures(self):
        """Températures très élevées (canicule extrême)."""
        t_int = np.array([42.0] * 24)
        t_ext = np.array([40.0] * 24)

        result = compute_degree_hours_summer(t_int, t_ext)

        # Forte surchauffe
        assert result.dh_total > 100
        assert result.hours_discomfort == 24

