"""Un mur Trombe dans une étude, joué par EnergyPlus : les sens que la physique impose.

Le bâtiment est décrit par ses chiffres, la météo est celle de Denver (hiver froid et ensoleillé) : rien n'est
demandé au réseau.
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

from rayflect import etude, trombe  # noqa: E402

ETUDE = '''usage = "logement"
ombres_tous_les_n_jours = 30
[lieu]
meteo = '{meteo}'
[batiment]
longueur_m = 20.0
largeur_m = 10.0
niveaux = 1
hauteur_d_etage_m = 3.0
vitrage_m2 = {{ S = 16.0, N = 10.0 }}
[[scenario]]
nom = "sans"
[[scenario]]
nom = "trombe"
[[scenario.element]]
type = "mur_trombe"
[[scenario]]
nom = "tablette"
[[scenario.element]]
type = "mur_trombe"
tablette_m = 0.5
[[scenario]]
nom = "au nord"
[[scenario.element]]
type = "mur_trombe"
orientations = ["N"]
'''


@pytest.fixture(scope="module")
def bilan(tmp_path_factory):
    dossier = tmp_path_factory.mktemp("trombe")
    fichier = dossier / "etude.toml"
    fichier.write_text(ETUDE.format(meteo=DENVER), encoding="utf-8")
    return etude.calculer(etude.lire(fichier), dossier / "sortie", dire=lambda _texte: None)


def _heures_chaudes(bilan, nom):
    return sum(ligne[nom] for ligne in bilan["heures_au_dessus_de_26"].values())


def test_au_sud_le_mur_baisse_le_chauffage_et_rechauffe_l_ete(bilan):
    chauffage = bilan["chauffage_kwh"]
    assert chauffage["trombe"] < 0.95 * chauffage["sans"]
    assert _heures_chaudes(bilan, "trombe") > _heures_chaudes(bilan, "sans")
    mur = bilan["extensions"]["trombe"]["mur_trombe"][0]
    assert mur["aire_m2"] == 17.0 and mur["donne_a_la_piece_en_saison_de_chauffe_kwh"] > 0
    assert mur["lame_au_plus_chaud_c"] > 40.0


def test_la_tablette_coupe_le_soleil_d_ete_et_un_peu_de_celui_d_hiver(bilan):
    assert _heures_chaudes(bilan, "tablette") < _heures_chaudes(bilan, "trombe")
    assert bilan["chauffage_kwh"]["trombe"] < bilan["chauffage_kwh"]["tablette"] < bilan["chauffage_kwh"]["sans"]


def test_au_nord_sans_soleil_direct_le_mur_ne_rapporte_presque_rien(bilan):
    chauffage = bilan["chauffage_kwh"]
    gagne_au_sud, gagne_au_nord = chauffage["sans"] - chauffage["trombe"], chauffage["sans"] - chauffage["au nord"]
    assert gagne_au_nord < 0.25 * gagne_au_sud
    donne = {nom: bilan["extensions"][nom]["mur_trombe"][0]["donne_a_la_piece_en_saison_de_chauffe_kwh"]
             for nom in ("trombe", "au nord")}
    assert donne["au nord"] < 0.25 * donne["trombe"]


def test_tous_les_scenarios_suivent_le_soleil_dedans_et_la_lame_n_est_pas_une_piece(bilan):
    assert bilan["moteur"]["reglages"]["repartition_du_soleil"] == trombe.SOLEIL_SUIVI_DEDANS
    assert not any("TROMBE" in cle.upper() for cle in bilan["heures_au_dessus_de_26"])
    assert "sans" not in bilan["extensions"]
    assert "Mur Trombe, « tablette »" in etude.presenter(bilan)
