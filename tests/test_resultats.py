"""Le format des résultats : le schéma, son empreinte, et le contrôle d'un bilan. Sans calcul.

Les bilans réels sont contrôlés à chaque étude jouée par les essais avec EnergyPlus : `etude.calculer` refuse
d'écrire un bilan qui ne suit pas son format.
"""

import copy

import pytest

from rayflect import etude, resultats


def bilan_minimal() -> dict:
    """Un bilan de 2 scénarios et 1 pièce, aux clés que l'étude écrit."""
    deux = {"sans": 1.0, "avec": 2.0}
    return {
        "format": resultats.entete(), "maquette": "b.ifc", "lieu": "Bordeaux", "lieu_fiche": [], "meteo": "m.epw",
        "meteo_a_savoir": [], "hypotheses": ["usage bureau [S]"], "heures_d_occupation": 2600,
        "scenarios": ["sans", "avec"], "pieces": [{"cle": "0 | rdc | entier", "rang": 0, "niveau": "rdc", "cote": "entier"}],
        "repris": {"zones": 1, "baies": 4, "aire_reposee_m2": 9.5, "aire_relevee_m2": 10.0, "baies_ecartees": 0,
                   "niveaux_ecartes": [], "niveaux_non_chauffes": [], "murs_mitoyens": 0, "aire_mitoyenne_m2": 0.0},
        "voisins": None, "bso_manuels": None, "a_demander": [],
        "heures_au_dessus_de_26": {"0 | rdc | entier": {"sans": 300, "avec": 200}},
        "autonomie_300_lux": {"0 | rdc | entier": {"sans": 0.7, "avec": None}},
        "chauffage_kwh": deux, "froid_kwh": {}, "froid_avec_vapeur_kwh": {}, "energie": {}, "energie_comment": [],
        "production_pv_kwh": {}, "duree_s": deux, "changements": {"avec": ["une casquette"]},
        "puissance": {nom: {"chauffage_au_jour_de_base_kw": 10.0, "chauffage_au_jour_de_base_w_m2": 50,
                            "temperature_de_base_c": -5.0, "pointe_de_froid": None,
                            "pointe_de_chauffage": {"kw": 8.0, "quand": "28/12 à 8 h", "dehors_c": -2.0}}
                      for nom in deux},
        "puissance_comment": [],
        "moteur": {"versions": {"energyplus": "25.2.0"}, "reglages": {"pas_de_temps_par_heure": 4},
                   "avertissements": {"sans": 0, "avec": 1}, "calculs_en_meme_temps": 2},
    }


def test_l_empreinte_ecrite_est_celle_du_schema():
    schema = resultats.lire_le_schema()
    assert schema["x-empreinte"] == resultats.empreinte(schema), "réécrire par python -m rayflect.resultats --ecrire-empreinte"
    assert schema["x-version"] == resultats.VERSION == 1
    assert resultats.entete() == {"nom": "rayflect-resultats", "version": 1, "empreinte": schema["x-empreinte"]}


def test_un_bilan_bien_forme_suit_le_format():
    assert resultats.erreurs(bilan_minimal()) == []
    avec_extensions = bilan_minimal()
    avec_extensions["extensions"] = {"avec": {"sondes": [{"sondes": 4}]}}
    assert resultats.erreurs(avec_extensions) == []
    avec_le_bilan = bilan_minimal()
    avec_le_bilan["bilan_de_chaleur"] = {"sans": BILAN_DE_CHALEUR}
    assert resultats.erreurs(avec_le_bilan) == []
    avec_le_confort = bilan_minimal()
    avec_le_confort["confort_d_ete"] = {
        "pieces": {"0 | rdc | entier": {"sans": {"dh": 420, "heures": 210, "heures_plus_1": 90, "heures_plus_2": 30,
                                                 "dh_nuit": None}}},
        "periode": {"premier_jour": 132, "dernier_jour": 277}, "comment": ["seuil bas : 350 °C.h"]}
    assert resultats.erreurs(avec_le_confort) == []
    avec_le_confort["confort_d_ete"]["pieces"]["0 | rdc | entier"]["sans"]["dh"] = -1
    assert any("sous le minimum" in e for e in resultats.erreurs(avec_le_confort))


BILAN_DE_CHALEUR = {"postes": [{"poste": "murs", "cote": "S", "kwh": -12, "par_mois": [-1] * 12},
                               {"poste": "chauffage", "cote": None, "kwh": 12, "par_mois": [1] * 12}],
                    "ecart_kwh": 0, "ecart_part": 0.0}


@pytest.mark.parametrize("abimer, attendu", [
    (lambda c: c["postes"][0].update(par_mois=[0] * 11), "11 valeurs, moins que 12"),
    (lambda c: c["postes"][0].update(par_mois=[0] * 13), "13 valeurs, plus que 12"),
    (lambda c: c["postes"][0].update(kwh=1.5), "kwh : float au lieu de integer"),
    (lambda c: c.pop("ecart_part"), "ecart_part : manque"),
])
def test_un_ecart_au_bilan_de_chaleur_est_dit(abimer, attendu):
    bilan = bilan_minimal()
    bilan["bilan_de_chaleur"] = {"sans": copy.deepcopy(BILAN_DE_CHALEUR)}
    abimer(bilan["bilan_de_chaleur"]["sans"])
    assert any(attendu in e for e in resultats.erreurs(bilan)), resultats.erreurs(bilan)


@pytest.mark.parametrize("abimer, attendu", [
    (lambda b: b.pop("chauffage_kwh"), "resultats.chauffage_kwh : manque"),
    (lambda b: b.update(chaleur=1), "resultats.chaleur : clé hors du format"),
    (lambda b: b["chauffage_kwh"].update(sans="beaucoup"), "resultats.chauffage_kwh.sans : str"),
    (lambda b: b["repris"].update(zones=True), "resultats.repris.zones : bool"),
    (lambda b: b["format"].update(version=2), "resultats.format.version : 2 au lieu de 1"),
    (lambda b: b["pieces"][0].update(rang=-1), "sous le minimum"),
    (lambda b: b["puissance"]["sans"]["pointe_de_froid"].__class__ and
     b["puissance"]["sans"].update(pointe_de_froid={"kw": 1.0}), "pointe_de_froid.quand : manque"),
    (lambda b: b["heures_au_dessus_de_26"]["0 | rdc | entier"].update(avec=[1]), "list au lieu de"),
])
def test_un_ecart_au_format_est_dit_la_ou_il_est(abimer, attendu):
    bilan = copy.deepcopy(bilan_minimal())
    abimer(bilan)
    assert any(attendu in e for e in resultats.erreurs(bilan)), resultats.erreurs(bilan)
    with pytest.raises(resultats.ResultatsHorsFormat, match="ne suit pas le format"):
        resultats.controler(bilan)


def test_le_compte_rendu_se_lit_d_un_bilan_au_format():
    texte = etude.presenter(bilan_minimal())
    assert "b.ifc, Bordeaux" in texte and "besoin de chauffage" in texte


def test_la_commande_controle_un_fichier(tmp_path, capsys):
    import json

    bon, mauvais = tmp_path / "bon.json", tmp_path / "mauvais.json"
    bon.write_text(json.dumps(bilan_minimal()), encoding="utf-8")
    b = bilan_minimal()
    del b["format"]
    mauvais.write_text(json.dumps(b), encoding="utf-8")
    assert resultats.main([str(bon)]) == 0 and resultats.main([str(mauvais)]) == 1
    assert "resultats.format : manque" in capsys.readouterr().out
