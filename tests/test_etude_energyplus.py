"""Une étude jouée de bout en bout : construire, écrire, lancer, lire. Avec EnergyPlus.

Le bâtiment est décrit par ses chiffres, la météo est celle de Denver (les cas de la norme ANSI/ASHRAE 140) :
rien n'est demandé au réseau.
"""

import sys
from dataclasses import dataclass
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

from rayflect import etude, extensions, lieu as lieux  # noqa: E402

DEHORS = "Site Outdoor Air Drybulb Temperature"
MARQUE = "! retouché par la sonde"

ETUDE = '''usage = "bureau"
climatisation = true
ombres_tous_les_n_jours = 30
calculs_en_meme_temps = {ensemble}
[lieu]
meteo = '{meteo}'
[batiment]
longueur_m = 20.0
largeur_m = 10.0
niveaux = 1
hauteur_d_etage_m = 3.0
vitrage_m2 = {{ S = 24.0, N = 8.0 }}
[[scenario]]
nom = "sans"
[[scenario]]
nom = "casquettes"
[[scenario.element]]
type = "casquette"
profondeur_m = 1.0
orientations = ["S"]
[[scenario]]
nom = "sondé"
[[scenario.element]]
type = "sonde_du_dehors"
'''


@dataclass(frozen=True)
class _Sonde:
    """Un élément d'essai, comme en déclarerait un autre paquet : il ne change rien au bâtiment."""
    nom: str = "dehors"


def _poser(modele, sonde, contexte):
    contexte["reglages"].output.add_output(DEHORS)          # une sortie de plus, demandée par les réglages
    return None


def _retoucher(texte, sonde, contexte):
    assert "Building," in texte or "Building\n" in texte    # le fichier entier, pas un morceau
    contexte.setdefault("a_dire", []).append("sonde posée dehors")
    return texte + f"\n{MARQUE} du scénario {contexte['scenario']}\n"


def _lire(annee, sonde, contexte):
    series = annee.data_collections_by_output_name(DEHORS)
    return {"heures": len(series[0].values), "moyenne_c": round(sum(series[0].values) / len(series[0].values), 2)}


@pytest.fixture(scope="module")
def bilans(tmp_path_factory):
    extensions.enregistrer("sonde_du_dehors", _Sonde, _poser, _retoucher, _lire)
    completer, lieux.completer = lieux.completer, lambda lieu, *a, **k: lieu      # rien n'est demandé au réseau
    try:
        rendus = {}
        for ensemble in (1, 2):
            dossier = tmp_path_factory.mktemp(f"etude_{ensemble}")
            fichier = dossier / "etude.toml"
            fichier.write_text(ETUDE.format(ensemble=ensemble, meteo=DENVER), encoding="utf-8")
            suivis = []
            rendus[ensemble] = (etude.calculer(etude.lire(fichier), dossier, lambda _texte: None, suivis.append),
                                dossier, suivis)
        yield rendus
    finally:
        lieux.completer = completer
        extensions.retirer("sonde_du_dehors")


def test_une_casquette_au_sud_baisse_le_besoin_de_froid(bilans):
    bilan, _, _ = bilans[2]
    assert bilan["scenarios"] == ["sans", "casquettes", "sondé"]
    assert bilan["froid_kwh"]["casquettes"] < 0.97 * bilan["froid_kwh"]["sans"]
    # L'ombre de l'été est aussi une ombre d'hiver : le chauffage ne baisse pas.
    assert bilan["chauffage_kwh"]["casquettes"] >= bilan["chauffage_kwh"]["sans"]


def test_lancer_les_scenarios_ensemble_ne_change_aucun_chiffre(bilans):
    seul, ensemble = bilans[1][0], bilans[2][0]
    assert (seul["moteur"]["calculs_en_meme_temps"], ensemble["moteur"]["calculs_en_meme_temps"]) == (1, 2)
    for cle in ("chauffage_kwh", "froid_kwh", "froid_avec_vapeur_kwh", "heures_au_dessus_de_26", "autonomie_300_lux",
                "puissance", "changements"):
        assert seul[cle] == ensemble[cle], cle


def test_un_element_qui_ne_change_rien_rend_le_batiment_tel_qu_il_est(bilans):
    bilan, _, _ = bilans[2]
    assert bilan["chauffage_kwh"]["sondé"] == bilan["chauffage_kwh"]["sans"]
    assert bilan["froid_kwh"]["sondé"] == bilan["froid_kwh"]["sans"]


def test_un_element_etendu_retouche_le_fichier_et_lit_l_annee_seule(bilans):
    bilan, dossier, _ = bilans[2]
    assert MARQUE + " du scénario sondé" in (dossier / "sondé" / "in.idf").read_text(encoding="utf-8")
    assert MARQUE not in (dossier / "sans" / "in.idf").read_text(encoding="utf-8")
    assert bilan["changements"]["sondé"] == ["sonde posée dehors"]
    # Le calcul joue aussi un jour de base : la sonde ne voit que les 8 760 heures de l'année.
    lue = bilan["extensions"]["sondé"]["sonde_du_dehors"][0]
    assert lue["heures"] == 8760
    assert 5.0 < lue["moyenne_c"] < 15.0            # Denver : autour de 10 °C sur l'année
    assert set(bilan["extensions"]) == {"sondé"}


@pytest.mark.parametrize("ensemble", [1, 2])
def test_le_calcul_dit_ou_il_en_est_du_debut_a_la_fin(bilans, ensemble):
    suivis = bilans[ensemble][2]
    assert suivis[0].etapes == (
        "lire le bâtiment", "trouver le lieu et la météo", "calculer « sans », le bâtiment tel qu'il est",
        f"calculer les 2 autres scénarios, {ensemble} à la fois", "écrire le bilan")
    assert [s.rang for s in suivis] == sorted(s.rang for s in suivis)       # les étapes ne reculent pas
    assert {s.rang for s in suivis} == {1, 2, 3, 4, 5}
    parts = [s.part for s in suivis]
    assert parts == sorted(parts) and parts[0] == 0.0 and parts[-1] == 1.0   # le pourcentage non plus
    # EnergyPlus dit où il en est de l'année : l'avancement ne saute pas de 0 à 100 %.
    assert len({round(s.part, 2) for s in suivis if s.rang in (3, 4)}) > 10
    # Le temps restant s'annonce en cours de route, et ne dépasse jamais l'ordre de grandeur du calcul entier.
    restes = [s.reste_s for s in suivis if s.rang == 4 and s.reste_s is not None]
    assert restes and max(restes) < 600 and suivis[-1].reste_s == 0.0
    assert set(suivis[-2].en_cours) <= {"casquettes", "sondé"}
