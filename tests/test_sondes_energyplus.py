"""Des sondes dans une étude, jouées par EnergyPlus : le bâtiment, puis la boucle de sol sur ses besoins.

Le bâtiment est décrit par ses chiffres, la météo est celle de Denver : rien n'est demandé au réseau.
"""

import sys
from pathlib import Path

import pytest

pytest.importorskip("honeybee_energy")
from honeybee_energy.config import folders  # noqa: E402

if not folders.energyplus_exe:
    pytest.skip("EnergyPlus n'est pas installé", allow_module_level=True)

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "verification"))
import reference  # noqa: E402

try:
    DENVER = reference.meteo_de_denver()
except reference.ReferenceIndisponible as erreur:
    pytest.skip(f"météo de référence indisponible : {erreur}", allow_module_level=True)

from rayflect import etude  # noqa: E402

ETUDE = '''usage = "bureau"
climatisation = true
ombres_tous_les_n_jours = 30
[lieu]
meteo = '{meteo}'
[batiment]
longueur_m = 20.0
largeur_m = 10.0
niveaux = 1
hauteur_d_etage_m = 3.0
vitrage_m2 = {{ S = 20.0, N = 12.0 }}
[[scenario]]
nom = "sans"
[[scenario]]
nom = "champ court"
[[scenario.element]]
type = "sondes"
rangees = [1, 1]
profondeur_m = 60
annees = 2
[[scenario]]
nom = "champ long"
[[scenario.element]]
type = "sondes"
rangees = [2, 2]
profondeur_m = 100
annees = 2
'''


@pytest.fixture(scope="module")
def joue(tmp_path_factory):
    dossier = tmp_path_factory.mktemp("sondes")
    fichier = dossier / "etude.toml"
    fichier.write_text(ETUDE.format(meteo=DENVER), encoding="utf-8")
    dits = []
    return etude.calculer(etude.lire(fichier), dossier / "sortie", dire=dits.append), dits, dossier / "sortie"


def test_les_sondes_ne_changent_pas_le_batiment(joue):
    bilan, _dits, _sortie = joue
    for cle in ("chauffage_kwh", "froid_kwh"):
        assert bilan[cle]["champ court"] == bilan[cle]["sans"] == bilan[cle]["champ long"]


def test_chaque_scenario_recoit_le_bilan_de_son_propre_champ(joue):
    bilan, dits, sortie = joue
    court = bilan["extensions"]["champ court"]["sondes"][0]
    long = bilan["extensions"]["champ long"]["sondes"][0]
    assert "sans" not in bilan["extensions"]
    assert (court["sondes"], court["longueur_m"]) == (1, 60.0) and (long["sondes"], long["longueur_m"]) == (4, 400.0)
    # Chacun a sa boucle, dans son dossier, et le calcul l'a annoncée.
    assert (sortie / "champ_court" / "sondes" / "eplusout.sql").exists()
    assert (sortie / "champ_long" / "sondes" / "eplusout.sql").exists()
    assert sum("la boucle de sol se calcule sur 2 ans" in d for d in dits) == 2


def test_la_charge_sur_le_sol_est_celle_des_besoins(joue):
    bilan, _dits, _sortie = joue
    champ = bilan["extensions"]["champ long"]["sondes"][0]
    # COP de 4 : les 3 quarts du chauffage viennent du sol. Géocooling : tout le froid, vapeur comprise, y va.
    assert champ["pris_au_sol_kwh_an"] == pytest.approx(0.75 * bilan["chauffage_kwh"]["sans"], rel=0.002)
    assert champ["rendu_au_sol_kwh_an"] == pytest.approx(bilan["froid_avec_vapeur_kwh"]["sans"], rel=0.002)


def test_un_champ_plus_long_tient_l_eau_plus_pres_du_sol(joue):
    bilan, _dits, _sortie = joue
    court = bilan["extensions"]["champ court"]["sondes"][0]
    long = bilan["extensions"]["champ long"]["sondes"][0]
    for annee in ("premiere_annee", "derniere_annee"):
        assert long[annee]["retour_du_sol_min_c"] > court[annee]["retour_du_sol_min_c"]
        assert long[annee]["retour_du_sol_max_c"] < court[annee]["retour_du_sol_max_c"]
    assert court["pointe_prise_w_m"] > 6 * long["pointe_prise_w_m"]
    assert long["premiere_annee"]["retour_du_sol_min_c"] < long["sol_c"] < long["premiere_annee"]["retour_du_sol_max_c"]


def test_le_compte_rendu_montre_les_sondes(joue):
    bilan, _dits, _sortie = joue
    texte = etude.presenter(bilan)
    assert "Sondes géothermiques, « champ long »" in texte and "4 sondes, 400 m en tout" in texte
    assert any("sondes géothermiques : 1 sonde de 60 m" in d for d in bilan["changements"]["champ court"])
