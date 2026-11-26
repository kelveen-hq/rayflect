"""L'ombre d'une casquette grandit avec le soleil : c'est sa raison d'être.

Un débord horizontal projette sous lui une ombre de

    profondeur × tan(altitude) / cos(écart d'azimut)

Un soleil haut y fait une ombre longue, un soleil bas une ombre courte : la
casquette protège l'été et laisse passer l'hiver. Ces essais tiennent ce
sens, la géométrie, et la règle saisonnière qui en découle.
"""
from __future__ import annotations

import math

import pytest

from rayflect.services.analysis.casquette import (
    compute_casquette_seasonal_factors,
    compute_casquette_shadow_fraction,
)

SUD = 180.0
BAIE_H = 1.80
BORDEAUX_LAT = 44.8


def test_l_ombre_suit_la_hauteur_du_soleil():
    """LE SENS, et rien d'autre : plus le soleil monte, plus l'ombre descend."""
    precedent = -1.0
    for altitude in (10.0, 20.0, 30.0, 45.0, 60.0, 70.0):
        f = compute_casquette_shadow_fraction(0.40, altitude, SUD, SUD, BAIE_H)
        assert f > precedent, (altitude, f, precedent)
        precedent = f


def test_la_geometrie_tombe_sur_le_calcul_a_la_main():
    """L'ombre d'un débord tombe SOUS lui de `profondeur × tan(altitude)`.

    On refait le calcul à la main plutôt que d'épingler une valeur : un essai
    qui ne fait que recopier le code ne garde rien.
    """
    for profondeur in (0.20, 0.40, 0.80):
        for altitude in (25.0, 45.0, 65.0):
            attendu = min(1.0, profondeur * math.tan(math.radians(altitude)) / BAIE_H)
            assert compute_casquette_shadow_fraction(
                profondeur, altitude, SUD, SUD, BAIE_H) == pytest.approx(
                    attendu, abs=1e-6), (profondeur, altitude)


def test_les_deux_exemples_de_la_docstring_etaient_echanges():
    """Les 2 exemples de la docstring du modèle : 48 % l'été, 10 % l'hiver.

    0,40 m de débord sur une baie de 1,80 m, plein sud :
      · soleil d'été à 65°   -> 0,40 × tan 65° = 0,86 m -> 48 %
      · soleil d'hiver à 25° -> 0,40 × tan 25° = 0,19 m -> 10 %
    """
    ete = compute_casquette_shadow_fraction(0.40, 65.0, SUD, SUD, BAIE_H)
    hiver = compute_casquette_shadow_fraction(0.40, 25.0, SUD, SUD, BAIE_H)
    assert ete == pytest.approx(0.48, abs=0.01)
    assert hiver == pytest.approx(0.10, abs=0.01)
    assert ete > 4 * hiver


def test_l_ete_est_toujours_plus_protege_que_l_hiver():
    """La règle bioclimatique, tenue à toutes les profondeurs utiles.

    Si cette relation s'inversait, une casquette n'aurait plus aucun sens.
    """
    for profondeur in (0.20, 0.40, 0.60, 0.80, 1.20):
        f = compute_casquette_seasonal_factors(
            profondeur, BORDEAUX_LAT, window_height_m=BAIE_H)
        assert f.summer_shading_factor > f.winter_blocking_factor, profondeur
        assert f.summer_avg_altitude_deg > f.winter_avg_altitude_deg


def test_un_soleil_derriere_la_facade_n_ombre_rien():
    assert compute_casquette_shadow_fraction(0.40, 40.0, 0.0, SUD, BAIE_H) == 0.0
    assert compute_casquette_shadow_fraction(0.40, -5.0, SUD, SUD, BAIE_H) == 0.0
    assert compute_casquette_shadow_fraction(0.0, 40.0, SUD, SUD, BAIE_H) == 0.0
