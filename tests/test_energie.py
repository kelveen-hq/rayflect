"""Des besoins à l'énergie achetée, au CO2 et aux euros. Aucun essai ne sort sur le réseau : la réponse
d'Eurostat est rejouée."""

import json
import time

import pytest

from rayflect import energie

REPONSE = {"value": {"0": 0.10, "1": 0.12, "2": None},
           "dimension": {"time": {"category": {"index": {"2025-S1": 0, "2025-S2": 1, "2026-S1": 2}}}}}


@pytest.fixture()
def eurostat(monkeypatch):
    appels = []

    def rejouer(adresse, delai_s):
        appels.append(adresse)
        return REPONSE

    monkeypatch.setattr(energie, "_demander", rejouer)
    return appels


def test_le_gaz_se_compte_au_rendement_et_se_facture_au_pcs():
    config = energie.Energie("gaz")
    compte = energie.bilan(9000.0, 0.0, config, {"gaz": energie.Prix(0.10, "donné")})
    assert compte["chauffage_kwh"] == 10000                 # 9 000 kWh de chaleur à 0,9 de rendement
    assert compte["kgco2"] == 2270                          # 10 000 kWh à 0,227 kgCO2 par kWh
    assert compte["euros"] == 1110                          # 11 100 kWh facturés au PCS, à 0,10 €


def test_une_pompe_a_chaleur_et_une_climatisation_sur_la_meme_electricite():
    config = energie.Energie("pac")
    compte = energie.bilan(9000.0, 6000.0, config, {"electricite": energie.Prix(0.20, "donné")})
    assert (compte["chauffage_kwh"], compte["climatisation_kwh"]) == (3000, 2000)
    assert compte["kgco2"] == round(3000 * 0.079 + 2000 * 0.064)
    assert compte["euros"] == 1000


def test_les_rendements_donnes_passent_avant_ceux_du_code():
    config = energie.Energie("gaz", rendement_chauffage=0.6, rendement_climatisation=2.0)
    compte = energie.bilan(6000.0, 4000.0, config, {})
    assert (compte["chauffage_kwh"], compte["climatisation_kwh"]) == (10000, 2000)


def test_sans_prix_les_euros_manquent_et_c_est_dit():
    config = energie.Energie("fioul")
    prix = {"fioul": None}
    compte = energie.bilan(8000.0, 0.0, config, prix)
    assert compte["euros"] is None and compte["kgco2"] == round(10000 * 0.324)
    assert any("À DEMANDER : le prix du kWh de fioul" in ligne for ligne in energie.justification(config, prix, False))


def test_un_reseau_de_chaleur_demande_son_facteur():
    config = energie.Energie("reseau_de_chaleur")
    assert energie.bilan(9500.0, 0.0, config, {})["kgco2"] is None
    assert any("propre à chaque réseau" in ligne for ligne in energie.justification(config, {}, False))
    donne = energie.Energie("reseau_de_chaleur", facteur_chauffage_kgco2_kwh=0.1)
    assert energie.bilan(9500.0, 0.0, donne, {})["kgco2"] == 1000


def test_hors_de_france_les_facteurs_se_demandent():
    config = energie.Energie("gaz", pays="DE")
    assert energie.bilan(9000.0, 0.0, config, {})["kgco2"] is None
    assert any("ne valent que pour la France" in ligne for ligne in energie.justification(config, {}, False))
    assert energie.bilan(9000.0, 0.0, energie.Energie("gaz", pays="DE", facteur_chauffage_kgco2_kwh=0.2), {})[
        "kgco2"] == 2000


def test_le_prix_d_eurostat_est_le_dernier_semestre_connu_dans_la_bonne_tranche(eurostat, tmp_path):
    prix = energie.prix_eurostat("electricite", "FR", 600e3, menage=False, dossier=tmp_path)
    assert prix.eur_kwh == 0.12 and "2025-S2" in prix.origine and "MWH500-1999" in prix.origine
    assert "nrg_pc_205" in eurostat[0] and "tax=X_VAT" in eurostat[0] and "geo=FR" in eurostat[0]
    menage = energie.prix_eurostat("gaz", "FR", 15000.0, menage=True, dossier=tmp_path)
    assert "nrg_pc_202" in eurostat[1] and "tax=I_TAX" in eurostat[1] and "GJ20-199" in menage.origine


def test_le_prix_est_garde_puis_redemande_au_bout_d_un_mois(eurostat, tmp_path):
    energie.prix_eurostat("gaz", "FR", 50000.0, False, dossier=tmp_path)
    energie.prix_eurostat("gaz", "FR", 50000.0, False, dossier=tmp_path)
    assert len(eurostat) == 1
    fichier = next(tmp_path.glob("*.json"))
    garde = json.loads(fichier.read_text(encoding="utf-8"))
    garde["lu_le"] = time.time() - 40 * 24 * 3600
    fichier.write_text(json.dumps(garde), encoding="utf-8")
    energie.prix_eurostat("gaz", "FR", 50000.0, False, dossier=tmp_path)
    assert len(eurostat) == 2


def test_eurostat_muet_rend_l_ancienne_valeur_ou_rien(monkeypatch, tmp_path):
    def panne(adresse, delai_s):
        raise OSError("hors ligne")

    monkeypatch.setattr(energie, "_demander", panne)
    assert energie.prix_eurostat("gaz", "FR", 50000.0, False, dossier=tmp_path) is None
    (tmp_path / "nrg_pc_203_FR_X_VAT_GJ_LT1000.json").write_text(
        json.dumps({"eur_kwh": 0.09, "semestre": "2024-S2", "lu_le": 0.0}), encoding="utf-8")
    ancien = energie.prix_eurostat("gaz", "FR", 50000.0, False, dossier=tmp_path)
    assert ancien.eur_kwh == 0.09 and "ne répond pas" in ancien.origine


def test_le_prix_donne_passe_avant_eurostat_et_aucun_prix_n_est_invente(eurostat, tmp_path):
    config = energie.Energie("gaz", prix_chauffage_eur_kwh=0.15)
    prix = energie.prix_de_l_etude(config, {"gaz": 50000.0, "electricite": 3000.0}, False, dossier=tmp_path)
    assert prix["gaz"] == energie.Prix(0.15, "donné") and "Eurostat" in prix["electricite"].origine
    bois = energie.prix_de_l_etude(energie.Energie("bois"), {"bois": 50000.0}, False, dossier=tmp_path)
    assert bois["bois"] is None


@pytest.mark.parametrize("arguments, attendu", [
    ({"chauffage": "charbon"}, "chauffage inconnu"),
    ({"rendement_chauffage": 0}, "rendement_chauffage"),
    ({"prix_electricite_eur_kwh": -0.1}, "prix_electricite_eur_kwh"),
])
def test_une_description_impossible_est_refusee(arguments, attendu):
    with pytest.raises(energie.EnergieInvalide, match=attendu):
        energie.Energie(**arguments)
