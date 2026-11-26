"""Un bâtiment commun joué par EnergyPlus : le niveau non chauffé et le mur mitoyen changent bien le calcul.

La météo est celle de Denver : rien n'est demandé au réseau.
"""

import json
import sys
from pathlib import Path

import pytest

pytest.importorskip("honeybee_energy")
from honeybee_energy.config import folders  # noqa: E402

if not folders.energyplus_exe:
    pytest.skip("EnergyPlus n'est pas installé", allow_module_level=True)

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "verification"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import reference  # noqa: E402
from test_lecture_batiment_commun import atelier_et_bureaux  # noqa: E402

try:
    DENVER = reference.meteo_de_denver()
except reference.ReferenceIndisponible as erreur:
    pytest.skip(f"météo de référence indisponible : {erreur}", allow_module_level=True)

from rayflect import etude, moteur  # noqa: E402

ETUDE = '''maquette = "batiment.json"
usage = "bureau"
ombres_tous_les_n_jours = 30
[lieu]
meteo = '{meteo}'
[[scenario]]
nom = "tel quel"
'''


def _variantes():
    tel_quel = atelier_et_bureaux()
    tout_chauffe = atelier_et_bureaux()
    del tout_chauffe["niveaux"][0]["chauffage"]
    sans_voisin = atelier_et_bureaux()
    sans_voisin["facades"][2]["mitoyenne"] = {"valeur": False, "provenance": "saisie"}
    return {"atelier non chauffé": tel_quel, "tout chauffé": tout_chauffe, "sans mitoyen": sans_voisin}


@pytest.fixture(scope="module")
def bilans(tmp_path_factory):
    # Les dossiers se créent avant de lancer les calculs ensemble : pytest ne sait pas les créer depuis 3 fils.
    dossiers = {nom: tmp_path_factory.mktemp("commun") for nom in _variantes()}

    def jouer(paire):
        nom, batiment = paire
        dossier = dossiers[nom]
        (dossier / "batiment.json").write_text(json.dumps(batiment), encoding="utf-8")
        (dossier / "etude.toml").write_text(ETUDE.format(meteo=DENVER), encoding="utf-8")
        return nom, etude.calculer(etude.lire(dossier / "etude.toml"), dossier / "sortie", dire=lambda _texte: None)

    return dict(moteur.ensemble(jouer, list(_variantes().items()), 3))


def _chauffage(bilan):
    return bilan["chauffage_kwh"]["tel quel"]


def test_un_atelier_non_chauffe_baisse_le_chauffage_sans_l_annuler(bilans):
    non_chauffe, chauffe = _chauffage(bilans["atelier non chauffé"]), _chauffage(bilans["tout chauffé"])
    # Mesuré : -8 %. Peu, parce que le sol sous le plancher est pris à 18 °C par défaut : l'atelier reste tiède
    # (12 à 28 °C), et les bureaux perdent par leur plancher une part de ce que l'atelier ne demande plus.
    assert 0.5 * chauffe < non_chauffe < 0.97 * chauffe


def test_un_mur_mitoyen_baisse_le_chauffage(bilans):
    assert _chauffage(bilans["atelier non chauffé"]) < _chauffage(bilans["sans mitoyen"])
    assert bilans["sans mitoyen"]["repris"]["murs_mitoyens"] == 0


def test_le_compte_rendu_dit_ce_qui_est_non_chauffe_mitoyen_et_non_repris(bilans):
    bilan = bilans["atelier non chauffé"]
    assert bilan["repris"]["niveaux_non_chauffes"] == ["Atelier"] and bilan["repris"]["murs_mitoyens"] == 2
    # L'atelier non chauffé ne compte pas dans les heures chaudes : personne n'y travaille.
    assert [cle.split(" | ")[1] for cle in bilan["heures_au_dessus_de_26"]] == ["Bureaux"]
    assert [cle.split(" | ")[1] for cle in bilans["tout chauffé"]["heures_au_dessus_de_26"]] == ["Atelier", "Bureaux"]
    assert any(m.startswith("non repris du bâtiment : niveau 0 : usage « stockage »") for m in bilan["a_demander"])
    assert any(h.startswith("d'où vient le bâtiment :") and "dessinee" in h for h in bilan["hypotheses"])
    texte = etude.presenter(bilan)
    assert "non chauffé : Atelier" in texte and "mitoyen : 2 murs, 72.0 m²" in texte
