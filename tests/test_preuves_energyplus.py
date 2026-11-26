"""Les preuves longues : ventilation de nuit, serre accolée, dalle sur terre-plein. À jouer par `pytest -m lent`.

Chaque cas est comparé à une référence extérieure à ce dépôt : EnergyPlus sur les modèles du laboratoire NREL
pour les cas de la norme, des solutions numériques vérifiées pour la dalle.
"""

import sys
from pathlib import Path

import pytest

pytest.importorskip("honeybee_energy")
from honeybee_energy.config import folders  # noqa: E402

if not folders.energyplus_exe:
    pytest.skip("EnergyPlus n'est pas installé", allow_module_level=True)

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "verification"))
import bestest_nuit  # noqa: E402
import bestest_serre  # noqa: E402
import dalle  # noqa: E402
import ouvrants  # noqa: E402
import reponse_thermique as banc_des_sondes  # noqa: E402

from rayflect import moteur  # noqa: E402

pytestmark = pytest.mark.lent

ECART_NREL_MAX = 0.005          # 0,5 % : même moteur, autre description du même local
ECART_NREL_MAX_C = 0.1          # sur une température, en °C
# Le sol calculé face aux solutions vérifiées : écart mesuré de -2,3 % à +3,5 % (énergie), de -3,0 % à +3,3 % (pointe).
ECART_DALLE_MAX = 0.04
DERIVE_DALLE_MAX = 0.005        # d'une année sur la suivante : le sol a trouvé son régime


def _proche(valeur: float, attendue: float, cle: str) -> bool:
    if cle.startswith("t_"):
        return abs(valeur - attendue) <= ECART_NREL_MAX_C
    return valeur == pytest.approx(attendue, rel=ECART_NREL_MAX)


@pytest.fixture(scope="module")
def nuit(tmp_path_factory):
    sortie = tmp_path_factory.mktemp("nuit")
    cas = list(bestest_nuit.BASES)
    return dict(zip(cas, moteur.ensemble(lambda c: bestest_nuit.calculer(c, sortie), cas,
                                         moteur.calculs_en_meme_temps())))


@pytest.mark.parametrize("cas", list(bestest_nuit.BASES))
def test_la_ventilation_de_nuit_est_proche_d_energyplus_au_laboratoire(nuit, cas):
    for cle, (_mini, _maxi, attendue) in bestest_nuit.REFERENCES[cas].items():
        assert _proche(nuit[cas][cle], attendue, cle), (cas, cle, nuit[cas][cle], attendue)


@pytest.mark.parametrize("cas", list(bestest_nuit.BASES))
def test_la_ventilation_de_nuit_est_dans_la_plage_de_la_norme(nuit, cas):
    for cle, (mini, maxi, _attendue) in bestest_nuit.REFERENCES[cas].items():
        assert mini <= nuit[cas][cle] <= maxi, (cas, cle, nuit[cas][cle])


def test_le_chauffage_est_coupe_et_l_inertie_garde_la_fraicheur_de_la_nuit(nuit):
    assert nuit["650"]["chauffage_mwh"] == 0.0 and nuit["950"]["chauffage_mwh"] == 0.0
    # Le local lourd garde le frais de la nuit : il lui faut bien moins de froid le jour, et il monte moins haut.
    assert nuit["950"]["froid_mwh"] < 0.25 * nuit["650"]["froid_mwh"]
    assert nuit["950FF"]["t_max_c"] < nuit["650FF"]["t_max_c"] - 20.0


@pytest.fixture(scope="module")
def serre(tmp_path_factory):
    sortie = tmp_path_factory.mktemp("serre")
    repartitions = ["FullInteriorAndExterior", "FullExterior"]
    return dict(zip(repartitions, moteur.ensemble(lambda r: bestest_serre.calculer(sortie, r), repartitions, 2)))


def test_la_serre_est_proche_d_energyplus_au_laboratoire(serre):
    for cle, (_mini, _maxi, attendue) in bestest_serre.REFERENCES.items():
        valeur = serre["FullInteriorAndExterior"][cle]
        assert _proche(valeur, attendue, cle), (cle, valeur, attendue)


def test_la_serre_est_dans_la_plage_de_la_norme(serre):
    for cle, (mini, maxi, attendue) in bestest_serre.REFERENCES.items():
        # La plage est une statistique de 5 programmes : l'EnergyPlus de référence en sort lui-même d'un cheveu
        # sur la pointe de froid (1,48004 kW pour un maximum de 1,4799).
        assert mini <= serre["FullInteriorAndExterior"][cle] <= max(maxi, attendue * 1.001), cle


def test_le_soleil_mis_au_sol_fausse_la_serre(serre):
    # Avec tout le soleil au sol, le mur commun en reçoit moins : la pièce arrière demande plus de chauffage.
    juste, au_sol = serre["FullInteriorAndExterior"], serre["FullExterior"]
    assert au_sol["chauffage_mwh"] > 1.02 * juste["chauffage_mwh"]
    assert au_sol["t_serre_moyenne_c"] > juste["t_serre_moyenne_c"]


@pytest.fixture(scope="module")
def dalles(tmp_path_factory):
    sortie = tmp_path_factory.mktemp("dalle")
    cas = list(dalle.CAS)
    return dict(zip(cas, moteur.ensemble(lambda c: dalle.calculer(c, sortie), cas, moteur.calculs_en_meme_temps())))


@pytest.mark.parametrize("cas", list(dalle.CAS))
def test_la_dalle_est_proche_des_solutions_verifiees(dalles, cas):
    rendu = dalles[cas]
    assert abs(rendu["ecart"]) <= ECART_DALLE_MAX, rendu
    assert abs(rendu.get("ecart_de_pointe", 0.0)) <= ECART_DALLE_MAX, rendu
    assert abs(rendu["derive_sur_1_an"]) <= DERIVE_DALLE_MAX, rendu
    assert rendu["air_c"] == pytest.approx(dalle.T_INTERIEURE_C, abs=0.01)
    # Seule la dalle échange : ce que fournit le chauffage est ce qui part par le plancher.
    assert rendu["plancher_w"] == pytest.approx(rendu["flux_w"], rel=0.005)


def test_les_sens_que_la_physique_impose_a_la_dalle(dalles):
    # Un sol moins conducteur laisse partir moins de chaleur.
    assert dalles["GC80b"]["energie_kwh"] < 0.35 * dalles["GC40b"]["energie_kwh"]
    # Une nappe à 2 m, tenue à 10 °C, tire plus de chaleur qu'un sol profond de 15 m.
    assert dalles["GC55b"]["energie_kwh"] > 1.4 * dalles["GC40b"]["energie_kwh"]
    # À aire égale, une dalle étroite a plus de rive : elle perd plus.
    assert dalles["GC45b"]["energie_kwh"] > 1.3 * dalles["GC40b"]["energie_kwh"]
    # Un échange plus faible à la surface freine le flux.
    assert dalles["GC70b"]["energie_kwh"] < dalles["GC40b"]["energie_kwh"]


@pytest.mark.parametrize("cas", list(ouvrants.CAS))
def test_energyplus_applique_les_formules_de_debit_des_ouvrants(tmp_path, cas):
    rendu = ouvrants.calculer(cas, tmp_path)
    # Sur l'année, le débit d'EnergyPlus est celui des formules ; pas à pas, l'écart vient de la température de
    # la pièce, qu'EnergyPlus prend au sous-pas précédent.
    assert rendu["energyplus_sur_formule"] == pytest.approx(1.0, abs=0.005), rendu
    assert rendu["ecart_median"] < 0.001 and rendu["ecart_a_95_pour_cent"] < 0.05, rendu
    assert rendu["debit_moyen_m3_s"] > 0.3


ECART_DE_CONDUCTIVITE_MAX = 0.05    # mesuré : +2,6 % à +3,9 %, les bouts de la sonde aplatissant un peu la pente


@pytest.fixture(scope="module")
def reponses_thermiques(tmp_path_factory):
    sortie = tmp_path_factory.mktemp("sondes")
    sols = list(banc_des_sondes.CONDUCTIVITES)
    return dict(zip(sols, moteur.ensemble(lambda k: banc_des_sondes.calculer(k, sortie), sols, len(sols))))


@pytest.mark.parametrize("sol", list(banc_des_sondes.CONDUCTIVITES))
def test_l_essai_de_reponse_thermique_retrouve_la_conductivite_du_sol(reponses_thermiques, sol):
    rendu = reponses_thermiques[sol]
    assert abs(rendu["ecart"]) <= ECART_DE_CONDUCTIVITE_MAX, rendu
    # Toute la puissance injectée passe au sol, et l'eau s'échauffe.
    assert rendu["puissance_moyenne_w"] == pytest.approx(-banc_des_sondes.PUISSANCE_W, rel=0.005)
    assert rendu["eau_au_bout_d_un_an_c"] > banc_des_sondes.SOL_C + 10.0


def test_la_resistance_du_forage_ne_depend_pas_du_sol(reponses_thermiques):
    resistances = [r["resistance_du_forage_m_k_w"] for r in reponses_thermiques.values()]
    assert max(resistances) - min(resistances) < 0.005 and 0.05 < min(resistances) < 0.25
    # Un sol plus conducteur évacue mieux : l'eau monte moins haut.
    assert reponses_thermiques[3.0]["eau_au_bout_d_un_an_c"] < reponses_thermiques[1.5]["eau_au_bout_d_un_an_c"] - 5.0


def test_le_mur_trombe_suit_les_mesures_de_los_alamos(tmp_path):
    import trombe_los_alamos

    try:
        trombe_los_alamos.texte_de_la_these()
    except FileNotFoundError as absent:
        pytest.skip(str(absent))
    rendu = trombe_los_alamos.calculer(tmp_path)
    # Mesuré le 19/11/2026 : biais de +0,9, -1,0 et -1,0 °C ; flux à travers le mur +14,1 % (la thèse : +12,8 %).
    for cle in ("face_dans_la_lame_c", "face_dans_la_piece_c", "globe_c"):
        assert abs(rendu[cle]["biais"]) <= 1.5 and rendu[cle]["ecart_quadratique"] <= 3.5, (cle, rendu[cle])
    assert abs(rendu["flux_moyen_a_travers_le_mur_w_m2"]["ecart_pourcent"]) <= 20.0
