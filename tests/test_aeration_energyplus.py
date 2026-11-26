"""Les fenêtres et la ventilation d'un scénario, jouées par EnergyPlus : les sens que la physique impose.

Le bâtiment est décrit par ses chiffres, la météo est celle de Denver (jours chauds, nuits fraîches) : rien
n'est demandé au réseau.
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
fenetres = "fermees"
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
nom = "fermées"
[[scenario]]
nom = "le jour"
[[scenario.element]]
type = "ouvrants"
[[scenario]]
nom = "jour et nuit"
[[scenario.element]]
type = "ouvrants"
heures = [0, 24]
[[scenario]]
nom = "traversant"
[[scenario.element]]
type = "ouvrants"
heures = [0, 24]
traversant = true
[[scenario]]
nom = "sud seul"
[[scenario.element]]
type = "ouvrants"
heures = [0, 24]
traversant = true
orientations = ["S"]
[[scenario]]
nom = "surventilé"
[[scenario.element]]
type = "ventilation"
surventilation_vol_h = 4.0
[[scenario]]
nom = "double flux"
[[scenario.element]]
type = "ventilation"
double_flux = true
'''


@pytest.fixture(scope="module")
def bilan(tmp_path_factory):
    dossier = tmp_path_factory.mktemp("aeration")
    fichier = dossier / "etude.toml"
    fichier.write_text(ETUDE.format(meteo=DENVER), encoding="utf-8")
    return etude.calculer(etude.lire(fichier), dossier / "sortie", dire=lambda _texte: None)


def _heures_chaudes(bilan, nom):
    return sum(ligne[nom] for ligne in bilan["heures_au_dessus_de_26"].values())


def test_plus_on_ouvre_moins_il_fait_chaud(bilan):
    chaud = {nom: _heures_chaudes(bilan, nom) for nom in bilan["scenarios"]}
    assert chaud["le jour"] < chaud["fermées"]
    assert chaud["jour et nuit"] < chaud["le jour"]             # la nuit décharge les murs
    assert chaud["traversant"] < chaud["jour et nuit"]          # le vent ajoute son débit
    assert chaud["jour et nuit"] < chaud["sud seul"] < chaud["fermées"]     # moins d'ouvrants, moins d'air


def test_ouvrir_au_dessus_de_24_degres_ne_coute_presque_pas_de_chauffage(bilan):
    chauffage = bilan["chauffage_kwh"]
    assert chauffage["traversant"] == pytest.approx(chauffage["fermées"], rel=0.02)


def test_la_ventilation_d_un_scenario_remplace_celle_de_l_etude(bilan):
    assert _heures_chaudes(bilan, "surventilé") < _heures_chaudes(bilan, "fermées")
    assert bilan["chauffage_kwh"]["double flux"] < 0.9 * bilan["chauffage_kwh"]["fermées"]


def test_le_compte_rendu_dit_ce_que_chaque_scenario_ouvre(bilan):
    dits = bilan["changements"]
    assert "fermées" not in dits
    assert any("en occupation" in d for d in dits["le jour"])
    assert any("traversante" in d for d in dits["traversant"])
    assert any("ouvrants d'un seul côté" in d for d in dits["sud seul"])
    assert any("surventilation de 4 vol/h" in d for d in dits["surventilé"])
    assert any("échangeur à 73 %" in d for d in dits["double flux"])
