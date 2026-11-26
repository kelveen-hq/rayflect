"""Le bilan de chaleur poste par poste, sur une étude jouée avec EnergyPlus.

Le bâtiment est décrit par ses chiffres, la météo est celle de Denver : rien n'est demandé au réseau. Le bilan doit
se refermer, rendre le besoin de chauffage tel qu'il est compté, et dire ce qu'un scénario change là où il le change.
Les mêmes calculs servent aux degrés-heures d'inconfort (rayflect.confort).
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

from rayflect import bilan, etude, lieu as lieux  # noqa: E402

ETUDE = '''usage = "bureau"
climatisation = {clim}
ombres_tous_les_n_jours = 30
calculs_en_meme_temps = 3
[lieu]
meteo = '{meteo}'
[batiment]
longueur_m = 20.0
largeur_m = 10.0
niveaux = 2
hauteur_d_etage_m = 3.0
vitrage_m2 = {{ S = 24.0, N = 8.0, O = 10.0 }}
[[scenario]]
nom = "sans"
[[scenario]]
nom = "casquettes"
[[scenario.element]]
type = "casquette"
profondeur_m = 1.0
orientations = ["S", "O"]
[[scenario]]
nom = "double flux"
[[scenario.element]]
type = "ventilation"
double_flux = true
'''


def _jouer(dossier: Path, clim: bool) -> dict:
    fichier = dossier / "etude.toml"
    fichier.write_text(ETUDE.format(clim="true" if clim else "false", meteo=DENVER), encoding="utf-8")
    completer, lieux.completer = lieux.completer, lambda lieu, *a, **k: lieu      # rien n'est demandé au réseau
    try:
        return etude.calculer(etude.lire(fichier), dossier / "sortie", dire=lambda _texte: None)
    finally:
        lieux.completer = completer


@pytest.fixture(scope="module")
def bilans(tmp_path_factory):
    # Les dossiers sont créés avant les calculs : mktemp n'est pas sûr depuis plusieurs fils.
    dossiers = {clim: tmp_path_factory.mktemp(f"bilan_{'clim' if clim else 'libre'}") for clim in (False, True)}
    return {clim: _jouer(dossier, clim) for clim, dossier in dossiers.items()}


def _poste(chaleur: dict, poste: str, cote=None) -> int:
    return sum(ligne["kwh"] for ligne in chaleur["postes"] if ligne["poste"] == poste and ligne["cote"] == cote)


@pytest.mark.parametrize("clim", [False, True])
def test_le_bilan_se_referme(bilans, clim):
    for nom, chaleur in bilans[clim]["bilan_de_chaleur"].items():
        assert chaleur["ecart_part"] < bilan.ECART_SUPPORTE, (nom, chaleur["ecart_kwh"], chaleur["ecart_part"])
        for ligne in chaleur["postes"]:
            assert sum(ligne["par_mois"]) == pytest.approx(ligne["kwh"], abs=12), ligne


@pytest.mark.parametrize("clim", [False, True])
def test_le_chauffage_et_le_froid_sont_les_besoins_comptes(bilans, clim):
    rendu = bilans[clim]
    for nom, chaleur in rendu["bilan_de_chaleur"].items():
        assert _poste(chaleur, bilan.CHAUFFAGE) == pytest.approx(rendu["chauffage_kwh"][nom], rel=0.005, abs=2), nom
        if clim:
            assert -_poste(chaleur, bilan.FROID) == pytest.approx(rendu["froid_kwh"][nom], rel=0.005, abs=2), nom
        else:
            assert _poste(chaleur, bilan.FROID) == 0


def test_les_signes_suivent_la_physique(bilans):
    sans = bilans[False]["bilan_de_chaleur"]["sans"]
    for cote in ("N", "E", "S", "O"):
        assert _poste(sans, bilan.MURS, cote) < 0, cote         # un mur perd l'hiver plus qu'il ne gagne l'été
    assert _poste(sans, bilan.BAIES_SOLEIL, "S") > _poste(sans, bilan.BAIES_SOLEIL, "O") > \
        _poste(sans, bilan.BAIES_SOLEIL, "N") > 0               # 24, 10 et 8 m² de vitrage
    assert _poste(sans, bilan.TOITURE) < 0 and _poste(sans, bilan.INFILTRATIONS) < 0
    assert _poste(sans, bilan.APPORTS) > 0
    hiver = {bilan._nom(ligne): bilan._somme(ligne, bilan.HIVER) for ligne in sans["postes"]}
    assert hiver[bilan.CHAUFFAGE] > 0.5 * sum(-v for v in hiver.values() if v < 0)


def test_une_casquette_retire_du_soleil_la_ou_elle_est(bilans):
    rendu = bilans[False]["bilan_de_chaleur"]
    sans, casquettes = rendu["sans"], rendu["casquettes"]
    assert _poste(casquettes, bilan.BAIES_SOLEIL, "S") < 0.8 * _poste(sans, bilan.BAIES_SOLEIL, "S")
    assert _poste(casquettes, bilan.BAIES_SOLEIL, "N") == pytest.approx(_poste(sans, bilan.BAIES_SOLEIL, "N"), rel=0.02)
    assert bilan.ecarts(casquettes, sans)[0][0] == "baies, soleil S"


def test_la_double_flux_se_lit_dans_l_air(bilans):
    rendu = bilans[False]["bilan_de_chaleur"]
    sans, double = rendu["sans"], rendu["double flux"]
    assert _poste(sans, bilan.DOUBLE_FLUX) == 0
    assert _poste(double, bilan.DOUBLE_FLUX) < 0                # l'air neuf, réchauffé par la machine
    # Sans le ventilateur simple flux, l'air neuf ne passe plus par la ventilation : elle ne perd plus que par les
    # fenêtres ouvertes.
    assert _poste(double, bilan.VENTILATION_ET_FENETRES) > _poste(sans, bilan.VENTILATION_ET_FENETRES)
    assert _poste(double, bilan.CHAUFFAGE) < _poste(sans, bilan.CHAUFFAGE)


def test_les_degres_heures_sont_rendus_sans_climatisation_seulement(bilans):
    libre, clim = bilans[False]["confort_d_ete"], bilans[True]["confort_d_ete"]
    assert libre["periode"] is not None and libre["pieces"]
    for par_scenario in libre["pieces"].values():
        assert par_scenario["casquettes"]["dh"] < par_scenario["sans"]["dh"]    # moins de soleil, moins d'inconfort
        for v in par_scenario.values():
            assert v["heures"] >= v["heures_plus_1"] >= v["heures_plus_2"] and v["dh_nuit"] is None
    assert clim["pieces"] == {} and any("étude climatisée" in c for c in clim["comment"])
    # Le DH ne compte que ce qui passe le seuil adaptatif, de 26 à 28 °C : moins d'heures qu'au-dessus de 26 °C.
    for cle, par_scenario in libre["pieces"].items():
        assert par_scenario["sans"]["heures"] <= bilans[False]["heures_au_dessus_de_26"][cle]["sans"]


def test_le_carbone_se_mesure_sur_ce_qui_est_pose(bilans):
    carbones = bilans[False]["carbone"]
    assert carbones["sans"]["lignes"] == [] and carbones["sans"]["kgco2e"] == 0
    casquettes = carbones["casquettes"]["lignes"]
    assert [ligne["element"] for ligne in casquettes] == ["casquette"]
    # 1 m de profondeur au-dessus des baies sud et ouest : la surface mesurée est celle des baies de ces façades, en
    # largeur. Elle se retrouve dans la masse, à 8,1 kg/m² d'aluminium.
    aire = float(casquettes[0]["quantite"].split()[0])
    assert 5.0 < aire < 60.0 and casquettes[0]["masse_kg"] == round(aire * 8.1)
    assert carbones["double flux"]["non_chiffres"] == ["ventilation : une machine"]


def test_la_lumiere_du_bord_de_baie(bilans):
    lumiere_ = bilans[False]["lumiere"]
    assert lumiere_
    for par_scenario in lumiere_.values():
        sans, casquettes = par_scenario["sans"], par_scenario["casquettes"]
        assert sans["bord_plus_de_3000_lux"] is not None and sans["eblouissement_bord"] is not None
        assert sans["bord_plus_de_2000_lux"] >= sans["bord_plus_de_3000_lux"]
        assert sans["bord_plus_de_3000_lux"] >= sans["centre_plus_de_3000_lux"]     # plus de lumière près de la vitre
        assert casquettes["bord_plus_de_3000_lux"] <= sans["bord_plus_de_3000_lux"]
    assert "à 1 m de la baie (trop de lumière)" in etude.presenter(bilans[False])


def test_le_compte_rendu_dit_d_ou_vient_la_chaleur(bilans):
    texte = etude.presenter(bilans[False])
    assert "D'où vient la chaleur des pièces chauffées" in texte
    assert "en hiver, la chaleur part surtout par :" in texte
    assert "« casquettes » change surtout : baies, soleil S" in texte
    assert "À VÉRIFIER" not in texte
