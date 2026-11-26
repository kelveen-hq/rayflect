"""Les degrés-heures d'inconfort de la RE2020, sans calcul : la moyenne glissante, la période, le seuil, la somme."""

import pytest

from rayflect import confort

JOURS = 365


def _annee(par_jour) -> list:
    """Une année horaire dont chaque jour vaut `par_jour(j)` à toute heure."""
    return [par_jour(h // 24) for h in range(JOURS * 24)]


def test_la_moyenne_glissante_suit_la_formule():
    rm = confort.moyennes_glissantes(_annee(lambda j: 20.0))
    assert rm[0] == 0.0                                     # la méthode part de 0
    assert rm[1] == pytest.approx(4.0)                      # 0,8 × 0 + 0,2 × 20
    assert rm[2] == pytest.approx(7.2)                      # 0,8 × 4 + 0,2 × 20
    assert rm[60] == pytest.approx(20.0, abs=1e-4)


def test_la_periode_va_du_premier_au_dernier_jour_a_16_degres():
    # 10 °C l'hiver, 25 °C du jour 150 au jour 249 : la moyenne glissante passe 16 °C quelques jours après.
    rm = confort.moyennes_glissantes(_annee(lambda j: 25.0 if 150 <= j < 250 else 10.0))
    premier, dernier = confort.periode(rm)
    assert 150 < premier < 156 and 250 < dernier < 256
    assert confort.periode(confort.moyennes_glissantes(_annee(lambda j: 12.0))) is None


@pytest.mark.parametrize("dehors_c, attendu", [(10.0, None), (17.0, 26.41), (20.0, 27.4), (30.0, 28.0)])
def test_le_seuil_va_de_la_consigne_a_2_degres_au_dessus(dehors_c, attendu):
    # Au jour 200, la moyenne glissante a rejoint la température constante du dehors.
    seuil = confort.seuils(_annee(lambda j: dehors_c), 26.0, habitation=False)[200 * 24 + 12]
    if attendu is None:
        assert seuil is None                                # 10 °C : jamais en période de confort adaptatif
    else:
        assert seuil == pytest.approx(attendu, abs=0.01)    # 0,33 × 17 + 20,8 ; 0,33 × 20 + 20,8 ; plafond à 28


def test_la_nuit_en_logement_le_seuil_est_la_consigne():
    seuils = confort.seuils(_annee(lambda j: 25.0), 26.0, habitation=True)
    jour = 200 * 24
    assert seuils[jour + 3] == 26.0 and seuils[jour + 23] == 26.0      # 3 h et 23 h : la nuit
    assert seuils[jour + 5] == 26.0                                     # de 5 h à 6 h, la nuit encore
    assert seuils[jour + 6] == pytest.approx(28.0)                      # de 6 h à 7 h, le jour
    assert seuils[jour + 21] == pytest.approx(28.0)                     # de 21 h à 22 h, le jour
    bureau = confort.seuils(_annee(lambda j: 25.0), 26.0, habitation=False)
    assert bureau[jour + 3] == pytest.approx(28.0)


def test_le_dh_somme_ce_qui_depasse_en_occupation_et_en_periode():
    seuils = [None, 26.0, 26.0, 27.0, 27.0, 28.0]
    ressentie = [35.0, 29.0, 26.0, 28.0, 30.0, 31.0]
    occupe = [True, True, True, True, False, True]
    rendu = confort.indicateurs(ressentie, seuils, occupe, habitation=False)
    # Hors période (heure 0) et inoccupée (heure 4) : rien. Sinon 3 + 0 + 1 + 3 ; le seuil atteint compte une heure.
    assert rendu == {"dh": 7, "heures": 4, "heures_plus_1": 3, "heures_plus_2": 2, "dh_nuit": None}


def test_le_dh_de_nuit_en_logement():
    seuils = confort.seuils(_annee(lambda j: 25.0), 26.0, habitation=True)
    ressentie = [27.0] * (JOURS * 24)
    rendu = confort.indicateurs(ressentie, seuils, [True] * (JOURS * 24), habitation=True)
    premier, dernier = confort.periode(confort.moyennes_glissantes(_annee(lambda j: 25.0)))
    nuits = dernier - premier + 1
    assert rendu["dh_nuit"] == 8 * nuits                    # 27 °C passe le seuil de la nuit (26), de 1 °C
    # Le jour, le seuil est de 28 °C, sauf les premiers jours : la moyenne glissante vient de passer 16 °C et le seuil
    # n'est encore que de 26,1 à 27 °C.
    assert 0 < rendu["dh"] - rendu["dh_nuit"] < 0.01 * rendu["dh"]


def test_une_etude_climatisee_le_dit():
    lignes = confort.expliquer((150, 250), 26.0, False, climatisation=True)
    assert any("étude climatisée : pas de DH" in ligne for ligne in lignes)
    assert confort.expliquer(None, 26.0, False, False)[0].startswith("période de confort adaptatif : aucune")
