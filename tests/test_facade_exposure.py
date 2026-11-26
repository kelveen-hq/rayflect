"""
Tests pour les fonctions d'exposition façade.

Teste :
- compute_facade_sun_hours() : heures de lever/coucher spécifiques à une façade
- project_sun_to_facade_plane() : projection du soleil dans le repère façade
- compute_facade_exposure_profile() : profil d'exposition journalier
"""

import math
import pytest
from datetime import datetime

from rayflect.services.solar.position import (
    SolarPosition,
    compute_facade_sun_hours,
    project_sun_to_facade_plane,
    compute_facade_exposure_profile,
    compute_facade_incidence,
)


class TestFacadeSunHours:
    """Tests pour compute_facade_sun_hours()."""

    @pytest.fixture
    def paris_coords(self):
        """Coordonnées de Paris."""
        return {"latitude_deg": 48.85, "longitude_deg": 2.35}

    @pytest.fixture
    def summer_solstice(self):
        """Solstice d'été."""
        return datetime(2024, 6, 21)

    @pytest.fixture
    def winter_solstice(self):
        """Solstice d'hiver."""
        return datetime(2024, 12, 21)

    def test_south_facade_longest_exposure(self, paris_coords, summer_solstice):
        """Une façade Sud est exposée la majeure partie de la journée."""
        result = compute_facade_sun_hours(
            date=summer_solstice,
            facade_azimuth_deg=180.0,  # Sud
            **paris_coords,
        )

        assert result.is_ever_exposed is True
        # Façade Sud exposée de ~6h à ~18h (grosso modo)
        assert result.facade_sunrise is not None
        assert result.facade_sunset is not None
        # Note: À Paris (longitude 2.35°E), le midi solaire est décalé
        # Donc ~8-9h d'exposition directe est réaliste
        assert result.total_sun_hours > 8  # Plus de 8h d'exposition

    def test_east_facade_morning_only(self, paris_coords, summer_solstice):
        """Une façade Est n'est exposée que le matin."""
        result = compute_facade_sun_hours(
            date=summer_solstice,
            facade_azimuth_deg=90.0,  # Est
            **paris_coords,
        )

        assert result.is_ever_exposed is True
        assert result.facade_sunrise is not None
        assert result.facade_sunset is not None

        # Façade Est : coucher avant midi solaire (~12h-13h)
        assert result.facade_sunset < 14.0
        # Et lever tôt le matin
        assert result.facade_sunrise < 8.0

    def test_west_facade_afternoon_only(self, paris_coords, summer_solstice):
        """Une façade Ouest n'est exposée que l'après-midi."""
        result = compute_facade_sun_hours(
            date=summer_solstice,
            facade_azimuth_deg=270.0,  # Ouest
            **paris_coords,
        )

        assert result.is_ever_exposed is True
        assert result.facade_sunrise is not None
        assert result.facade_sunset is not None

        # Façade Ouest : lever après midi solaire
        assert result.facade_sunrise > 11.0
        # Et coucher tard
        assert result.facade_sunset > 18.0

    def test_north_facade_summer(self, paris_coords, summer_solstice):
        """Une façade Nord peut être exposée en été (lever/coucher)."""
        result = compute_facade_sun_hours(
            date=summer_solstice,
            facade_azimuth_deg=0.0,  # Nord
            **paris_coords,
        )

        # À Paris en été, le soleil passe brièvement au Nord
        # La façade Nord peut être exposée très tôt le matin et très tard le soir
        if result.is_ever_exposed:
            # Si exposée, c'est aux extrémités de la journée
            assert result.total_sun_hours < 5  # Moins longtemps qu'une façade Sud

    def test_north_facade_winter(self, paris_coords, winter_solstice):
        """Une façade Nord n'est jamais exposée en hiver."""
        result = compute_facade_sun_hours(
            date=winter_solstice,
            facade_azimuth_deg=0.0,  # Nord
            **paris_coords,
        )

        # En hiver, le soleil ne passe jamais au Nord
        assert result.is_ever_exposed is False
        assert result.total_sun_hours == 0.0

    def test_is_facade_exposed_at_hour(self, paris_coords, summer_solstice):
        """Test de la méthode is_facade_exposed_at()."""
        result = compute_facade_sun_hours(
            date=summer_solstice,
            facade_azimuth_deg=90.0,  # Est
            **paris_coords,
        )

        # Façade Est : exposée le matin, pas l'après-midi
        assert result.is_facade_exposed_at(7.0) is True   # 7h du matin
        assert result.is_facade_exposed_at(16.0) is False  # 16h

    def test_dataclass_properties(self, paris_coords, summer_solstice):
        """Vérifie les propriétés de FacadeSunHours."""
        result = compute_facade_sun_hours(
            date=summer_solstice,
            facade_azimuth_deg=180.0,
            **paris_coords,
        )

        assert result.facade_sun_duration_hours >= 0
        if result.is_ever_exposed:
            expected_duration = result.facade_sunset - result.facade_sunrise
            assert abs(result.facade_sun_duration_hours - expected_duration) < 0.01


class TestProjectSunToFacadePlane:
    """Tests pour project_sun_to_facade_plane()."""

    def test_sun_directly_in_front_south_facade(self):
        """Soleil pile en face d'une façade Sud à midi."""
        sun = SolarPosition(elevation_deg=45.0, azimuth_deg=180.0)  # Plein Sud
        proj = project_sun_to_facade_plane(sun, facade_azimuth_deg=180.0)

        assert proj.is_in_front is True
        # Soleil pile en face → pas de décalage horizontal
        assert abs(proj.horizontal_offset_deg) < 1.0
        # Élévation projetée = élévation réelle
        assert abs(proj.projected_elevation_deg - 45.0) < 2.0

    def test_sun_from_left_southeast(self):
        """Soleil Sud-Est vient de la gauche pour une façade Sud."""
        sun = SolarPosition(elevation_deg=45.0, azimuth_deg=135.0)  # Sud-Est
        proj = project_sun_to_facade_plane(sun, facade_azimuth_deg=180.0)

        assert proj.is_in_front is True
        # Soleil vient de la gauche (vu de l'intérieur) → offset négatif
        assert proj.horizontal_offset_deg < 0
        assert proj.x_component < 0  # Composante vers la gauche

    def test_sun_from_right_southwest(self):
        """Soleil Sud-Ouest vient de la droite pour une façade Sud."""
        sun = SolarPosition(elevation_deg=45.0, azimuth_deg=225.0)  # Sud-Ouest
        proj = project_sun_to_facade_plane(sun, facade_azimuth_deg=180.0)

        assert proj.is_in_front is True
        # Soleil vient de la droite → offset positif
        assert proj.horizontal_offset_deg > 0
        assert proj.x_component > 0

    def test_sun_behind_facade(self):
        """Soleil derrière la façade → pas d'exposition."""
        sun = SolarPosition(elevation_deg=45.0, azimuth_deg=0.0)  # Nord
        proj = project_sun_to_facade_plane(sun, facade_azimuth_deg=180.0)  # Façade Sud

        assert proj.is_in_front is False
        assert proj.depth_component < 0

    def test_night_returns_zeros(self):
        """Soleil sous l'horizon → tout à zéro."""
        sun = SolarPosition(elevation_deg=-5.0, azimuth_deg=180.0)
        proj = project_sun_to_facade_plane(sun, facade_azimuth_deg=180.0)

        assert proj.is_in_front is False
        assert proj.x_component == 0.0
        assert proj.z_component == 0.0

    def test_east_facade_morning(self):
        """Façade Est le matin → soleil devant."""
        sun = SolarPosition(elevation_deg=30.0, azimuth_deg=90.0)  # Plein Est
        proj = project_sun_to_facade_plane(sun, facade_azimuth_deg=90.0)

        assert proj.is_in_front is True
        assert abs(proj.horizontal_offset_deg) < 5.0  # Quasi en face

    def test_east_facade_afternoon(self):
        """Façade Est l'après-midi → soleil derrière."""
        sun = SolarPosition(elevation_deg=45.0, azimuth_deg=270.0)  # Plein Ouest
        proj = project_sun_to_facade_plane(sun, facade_azimuth_deg=90.0)  # Façade Est

        assert proj.is_in_front is False

    def test_to_2d_incidence_compatibility(self):
        """Vérifie la compatibilité avec les calculs 2D existants."""
        sun = SolarPosition(elevation_deg=45.0, azimuth_deg=180.0)
        proj = project_sun_to_facade_plane(sun, facade_azimuth_deg=180.0)

        # Méthode existante
        incidence = compute_facade_incidence(sun, facade_azimuth_deg=180.0)

        # Les deux doivent être cohérentes
        x_2d, z_2d = proj.to_2d_incidence()

        # Le vecteur doit être normalisé
        norm = math.sqrt(x_2d**2 + z_2d**2)
        assert abs(norm - 1.0) < 0.01 or norm == 0.0

        # L'élévation effective doit correspondre
        if x_2d > 0:
            elev_from_proj = math.degrees(math.atan2(z_2d, x_2d))
            assert abs(elev_from_proj - incidence.effective_elevation_deg) < 5.0


class TestFacadeExposureProfile:
    """Tests pour compute_facade_exposure_profile()."""

    def test_profile_structure(self):
        """Vérifie la structure du profil retourné."""
        profile = compute_facade_exposure_profile(
            date=datetime(2024, 6, 21),
            latitude_deg=45.0,
            longitude_deg=0.0,
            facade_azimuth_deg=180.0,
            time_step_minutes=60,
        )

        assert len(profile) > 0

        # Vérifier les clés présentes
        first = profile[0]
        expected_keys = [
            'timestamp', 'hour', 'elevation_deg', 'azimuth_deg',
            'is_daylight', 'is_exposed', 'exposure_type',
            'incidence_angle_deg', 'cosine_factor',
            'projected_elevation_deg', 'horizontal_offset_deg',
            'sun_2d_x', 'sun_2d_z',
        ]
        for key in expected_keys:
            assert key in first, f"Clé manquante: {key}"

    def test_profile_south_facade_midday_best(self):
        """Le meilleur moment pour une façade Sud est autour de midi."""
        profile = compute_facade_exposure_profile(
            date=datetime(2024, 6, 21),
            latitude_deg=45.0,
            longitude_deg=0.0,
            facade_azimuth_deg=180.0,
            time_step_minutes=30,
        )

        # Trouver le moment avec le meilleur cosine_factor
        exposed = [p for p in profile if p['is_exposed']]
        if exposed:
            best = max(exposed, key=lambda p: p['cosine_factor'])
            # Le meilleur moment devrait être autour de midi solaire
            assert 10 <= best['hour'] <= 14

    def test_profile_east_facade_morning_best(self):
        """Le meilleur moment pour une façade Est est le matin."""
        profile = compute_facade_exposure_profile(
            date=datetime(2024, 6, 21),
            latitude_deg=45.0,
            longitude_deg=0.0,
            facade_azimuth_deg=90.0,  # Est
            time_step_minutes=30,
        )

        exposed = [p for p in profile if p['is_exposed']]
        if exposed:
            best = max(exposed, key=lambda p: p['cosine_factor'])
            # Le meilleur moment devrait être le matin
            assert best['hour'] < 12


class TestFacadeProjectionProperties:
    """Tests pour les propriétés de FacadeProjection."""

    def test_horizontal_offset_deg_property(self):
        """Vérifie que horizontal_offset_deg == projected_azimuth_deg."""
        sun = SolarPosition(elevation_deg=45.0, azimuth_deg=160.0)
        proj = project_sun_to_facade_plane(sun, facade_azimuth_deg=180.0)

        assert proj.horizontal_offset_deg == proj.projected_azimuth_deg


class TestIntegrationWithExistingCode:
    """Tests d'intégration avec le code existant."""

    def test_facade_incidence_consistency(self):
        """Les nouvelles fonctions sont cohérentes avec compute_facade_incidence()."""
        sun = SolarPosition(elevation_deg=50.0, azimuth_deg=150.0)
        facade_azimuth = 180.0

        # Ancienne méthode
        incidence = compute_facade_incidence(sun, facade_azimuth)

        # Nouvelle méthode
        projection = project_sun_to_facade_plane(sun, facade_azimuth)

        # Les deux doivent s'accorder sur l'exposition
        assert incidence.is_exposed == projection.is_in_front

    def test_sun_hours_vs_profile(self):
        """Les heures calculées correspondent au profil."""
        date = datetime(2024, 6, 21)
        lat, lon = 45.0, 0.0
        facade = 180.0

        sun_hours = compute_facade_sun_hours(
            date, lat, lon, facade, time_step_minutes=30
        )

        profile = compute_facade_exposure_profile(
            date, lat, lon, facade, time_step_minutes=30
        )

        # Compter les heures exposées dans le profil
        exposed_count = sum(1 for p in profile if p['is_exposed'])

        # Devrait être cohérent avec total_sun_hours (à la résolution près)
        if sun_hours.is_ever_exposed:
            assert exposed_count > 0
            # Approximativement le même nombre d'heures (30min pas = 2 par heure)
            profile_hours = exposed_count * 0.5
            assert abs(profile_hours - sun_hours.total_sun_hours) < 2.0  # Tolérance 2h
