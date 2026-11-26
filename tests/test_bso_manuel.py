"""Le BSO manœuvré à la main.

Le pilote est pur : on le nourrit heure par heure et on lit la part des baies
baissée. Ces essais tiennent ce que dit la littérature, et rien de plus :
personne ne baisse un local vide, l'état persiste, on baisse au soleil direct,
on relève rarement, la population de la façade compte.
"""
from __future__ import annotations

import pytest

from rayflect.config.system_constants import SYSTEM_DEFAULTS
from rayflect.services.analysis.bso_model import (
    BSO_PILOTAGES, PiloteBSOManuel, facteur_ombrage_bso_baisse, irradiance_directe_facade,
    population_bso_manuel, verifier_population)

BUREAU = set(range(8, 18))
SOLEIL, OMBRE = 400.0, 0.0


def _journee(p, jour_ouvre=True, soleil=lambda h: SOLEIL if 9 <= h <= 15 else OMBRE, chaud=False):
    return [p.pas(h, jour_ouvre, soleil(h), chaud) for h in range(24)]


def test_les_populations_par_defaut_somment_a_un():
    assert sum(w for _, w in population_bso_manuel(False)) == pytest.approx(1.0)
    assert sum(w for _, w in population_bso_manuel(True)) == pytest.approx(1.0)
    assert "manuel" in BSO_PILOTAGES


def test_une_population_qui_ne_somme_pas_a_un_est_refusee():
    with pytest.raises(ValueError):
        verifier_population((("dynamique", 0.5),))
    with pytest.raises(ValueError):
        verifier_population((("inconnu", 1.0),))


def test_personne_ne_baisse_un_bureau_vide_le_week_end():
    p = PiloteBSOManuel(False, BUREAU, population=(("dynamique", 1.0),))
    for f, _ in _journee(p, jour_ouvre=False):
        assert f == 0.0


def test_l_etat_persiste_quand_le_bureau_se_vide():
    p = PiloteBSOManuel(False, BUREAU, population=(("dynamique", 1.0),))
    jour = _journee(p)
    assert jour[15][0] == 1.0          # baissé au soleil
    assert jour[23][0] == 1.0          # personne pour relever : il reste baissé la nuit
    _journee(p, jour_ouvre=False)      # le week-end : toujours baissé
    assert p.part_baissee() == 1.0
    lundi = _journee(p, soleil=lambda h: OMBRE)
    assert lundi[8][0] == 0.0          # relevé en arrivant, à l'ombre


def test_le_dynamique_ne_releve_pas_en_journee():
    """Lightswitch-2002 : on relève en arrivant, pas pendant la journée."""
    p = PiloteBSOManuel(False, BUREAU, population=(("dynamique", 1.0),))
    jour = _journee(p, soleil=lambda h: SOLEIL if h == 9 else OMBRE)
    assert jour[9][0] == 1.0 and jour[17][0] == 1.0


def test_les_fixes_ne_bougent_jamais():
    p = PiloteBSOManuel(False, BUREAU, population=(("toujours_baisse", 0.4), ("jamais_baisse", 0.6)))
    for f, _ in _journee(p) + _journee(p, soleil=lambda h: OMBRE):
        assert f == pytest.approx(0.4)


def test_en_logement_le_soleil_seul_ne_fait_pas_baisser():
    """Le logement baisse contre la chaleur, pas contre l'éblouissement."""
    p = PiloteBSOManuel(True, set(range(6, 22)), population=(("chaleur", 1.0),))
    assert max(f for f, _ in _journee(p, chaud=False)) == 0.0
    assert max(f for f, _ in _journee(p, chaud=True)) > 0.3     # 50 % des logements sont vides en journée


def test_le_logement_vide_en_journee_ne_baisse_qu_au_retour():
    initial = SYSTEM_DEFAULTS.bso_manuel_logement_part_vide_journee
    object.__setattr__(SYSTEM_DEFAULTS, "bso_manuel_logement_part_vide_journee", 1.0)
    try:
        p = PiloteBSOManuel(True, set(range(6, 22)), population=(("chaleur", 1.0),))
        jour = _journee(p, soleil=lambda h: SOLEIL if 6 <= h <= 20 else OMBRE, chaud=True)
    finally:
        object.__setattr__(SYSTEM_DEFAULTS, "bso_manuel_logement_part_vide_journee", initial)
    assert jour[9][0] == jour[17][0]           # personne entre 8 h et 18 h
    assert jour[18][0] > jour[17][0]           # on baisse en rentrant
    assert jour[12][1] == 0.0                  # aucun éclairage rallumé dans un logement vide


def test_la_population_est_la_moyenne_ponderee_de_ses_comportements():
    a = PiloteBSOManuel(False, BUREAU, population=(("dynamique", 1.0),))
    b = PiloteBSOManuel(False, BUREAU, population=(("probabiliste", 1.0),))
    m = PiloteBSOManuel(False, BUREAU, population=(("dynamique", 0.3), ("probabiliste", 0.7)))
    for h in range(24):
        s = SOLEIL if 9 <= h <= 15 else OMBRE
        fa, fb, fm = a.pas(h, True, s, False)[0], b.pas(h, True, s, False)[0], m.pas(h, True, s, False)[0]
        assert fm == pytest.approx(0.3 * fa + 0.7 * fb)


def test_un_bso_baisse_garde_ses_lames_et_n_isole_pas_la_nuit():
    assert facteur_ombrage_bso_baisse(-5.0, 0.76) == 0.0
    sf = facteur_ombrage_bso_baisse(30.0, 0.76)
    assert sf == pytest.approx(1.0 - SYSTEM_DEFAULTS.bso_manuel_g_tot_baisse / 0.76)
    assert facteur_ombrage_bso_baisse(60.0, 0.76) == sf      # l'occupant ne suit pas le soleil


def test_le_soleil_direct_sur_la_facade():
    assert irradiance_directe_facade(800.0, 30.0, 180.0, 0.0) == 0.0      # façade nord, soleil au sud
    assert irradiance_directe_facade(800.0, 30.0, 180.0, 180.0) == pytest.approx(800.0 * 0.8660254, rel=1e-6)
