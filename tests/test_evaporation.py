"""L'évaporation d'un mur végétalisé, sans calcul d'EnergyPlus : la formule, le soleil du mur, le bilan des modules."""

import math

import pytest

from rayflect import evaporation


def test_l_exemple_horaire_de_la_fao():
    # FAO 56, exemple 19 : N'Diaye (Sénégal), 1er octobre, 14 h à 15 h, 38 °C, 52 % d'humidité (ea = 6,625 × 0,52),
    # u2 = 3,3 m/s, Rn = 1,749 et G = 0,175 MJ/m², 8 m d'altitude (101,2 kPa). La FAO trouve 0,63 mm/h, Cd = 0,34.
    ea = 0.6108 * math.exp(17.27 * 38.0 / (38.0 + 237.3)) * 0.52
    rosee = 237.3 * math.log(ea / 0.6108) / (17.27 - math.log(ea / 0.6108))
    et0 = evaporation.et0_horaire(38.0, rosee, 101.2, 3.3, 1.749 - 0.175, True, cd=0.34)
    assert et0 == pytest.approx(0.63, abs=0.01)


def test_rien_ne_s_evapore_sans_energie_ni_air_sec():
    assert evaporation.et0_horaire(20.0, 20.0, 101.3, 2.0, 0.0, False) == 0.0     # air saturé, nuit
    assert evaporation.et0_horaire(20.0, 10.0, 101.3, 2.0, -0.5, False) > 0.0      # Rn négatif ramené à 0, l'air sec seul


def test_le_vent_a_2_m():
    assert evaporation.vent_a_2_m(1.0) == pytest.approx(0.748, abs=0.001)          # FAO 56, équation 47


class _Serie:
    def __init__(self, valeurs):
        self.values = valeurs


class _Epw:
    """Une année de 8 760 heures, toutes pareilles : un ciel clair à midi solaire est inutile ici, le soleil est donné."""
    def __init__(self, soleil_direct: float):
        from ladybug.location import Location
        self.location = Location(latitude=44.8, longitude=-0.6, time_zone=1)
        n = 8760
        self.dry_bulb_temperature = _Serie([25.0] * n)
        self.dew_point_temperature = _Serie([12.0] * n)
        self.atmospheric_station_pressure = _Serie([101300.0] * n)
        self.wind_speed = _Serie([2.0] * n)
        self.direct_normal_radiation = _Serie([soleil_direct] * n)
        self.diffuse_horizontal_radiation = _Serie([100.0] * n)
        self.global_horizontal_radiation = _Serie([300.0] * n)


def test_les_modules_arroses_sont_plus_frais_que_les_modules_secs():
    epw = _Epw(600.0)
    secs, eau_secs = evaporation.modules(epw, 180.0, 0.76, arrose=False)
    arroses, eau = evaporation.modules(epw, 180.0, 0.76, arrose=True)
    juillet_midi = 181 * 24 + 12
    assert sum(eau_secs) == 0.0 and eau[juillet_midi] > 0.0
    assert arroses[juillet_midi] < secs[juillet_midi]                              # l'eau refroidit
    assert secs[juillet_midi] > 25.0                                               # le soleil chauffe
    assert eau[15 * 24 + 12] == 0.0                                                # janvier : hors saison d'arrosage
    nuit = 181 * 24 + 2                                                            # 2 h du matin : pas de soleil
    assert secs[nuit] == pytest.approx(25.0 + (0.77 * (100.0 * 0.5 + 300.0 * 0.1))
                                       / (5.0 + 2 * (4 + 4 * evaporation.vent_a_2_m(2.0))), abs=1e-6)


def test_l_eau_est_confrontee_aux_mesures():
    ligne = evaporation.dire_l_eau([0.12] * 8760)                                  # 2,9 L/m² par jour
    assert "2.9 L par m² et par jour l'été, dans la fourchette mesurée de 2.5 à 5 L" in ligne
    assert "sous la fourchette" in evaporation.dire_l_eau([0.01] * 8760)
