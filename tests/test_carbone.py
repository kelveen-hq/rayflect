"""Le carbone construit, sans calcul : les facteurs, les réglages qui les changent, les mesures, le retour."""

import pytest

from rayflect import carbone, etude
from rayflect.carbone import Mesure


def test_chaque_materiau_dit_sa_source():
    for cle, m in carbone.MATERIAUX.items():
        assert m.kgco2e_par_kg > 0 and m.source.startswith(("[S]", "[H]")), cle
        assert (m.masse_kg_m2 is None) == (m.masse_source == ""), cle
    assert carbone.MATERIAUX["laine_minerale"].source.startswith("[H]")    # ni lue ni sourcée : elle le dit


def test_une_casquette_selon_son_materiau():
    mesures = [Mesure("casquette", 10.0, "m² de protection")]
    alu = carbone.chiffrer(mesures, carbone.Reglages())
    bois = carbone.chiffrer(mesures, carbone.Reglages(materiaux={"casquette": "bois"}))
    beton = carbone.chiffrer(mesures, carbone.Reglages(materiaux={"casquette": "beton_arme"}))
    assert alu["kgco2e"] == round(10 * 8.1 * 5.193)
    assert bois["kgco2e"] == round(10 * 13.5 * 0.263) < alu["kgco2e"] < beton["kgco2e"] == round(10 * 360 * 0.155)


def test_les_valeurs_se_changent():
    mesures = [Mesure("casquette", 10.0, "m² de protection")]
    recycle = carbone.chiffrer(mesures, carbone.Reglages(facteurs={"aluminium": 2.0}, masses_kg_m2={"aluminium": 5.0}))
    assert recycle["kgco2e"] == 100
    assert recycle["lignes"][0]["sources"] == ["[U] donné dans l'étude", "[U] donnée dans l'étude"]
    donne = carbone.chiffrer(mesures, carbone.Reglages(), donne_kg=950.0)
    assert donne["kgco2e"] == 950 and donne["lignes"][0]["sources"] == ["[U] carbone_kg du scénario"]


def test_les_reglages_d_un_scenario_s_ajoutent_a_ceux_de_l_etude():
    de_l_etude = carbone.Reglages(facteurs={"aluminium": 2.0}, materiaux={"casquette": "bois"})
    propre = de_l_etude.avec({"materiaux": {"casquette": "beton"}})
    assert propre.materiau("casquette") == "beton" and propre.facteur("aluminium")[0] == 2.0
    assert de_l_etude.materiau("casquette") == "bois"                      # l'étude ne change pas


@pytest.mark.parametrize("table, attendu", [
    ({"facteurs": {"plomb": 1.0}}, "matériau « plomb » inconnu"),
    ({"facteurs": {"aluminium": -1}}, "un nombre positif"),
    ({"materiaux": {"casquette": "carton"}}, "matériau inconnu"),
    ({"prix": 1}, "clés inconnues : prix"),
])
def test_un_reglage_faux_est_refuse(table, attendu):
    with pytest.raises(ValueError, match=attendu):
        carbone.lire_les_reglages(table)


def test_le_reste_des_mesures():
    rendu = carbone.chiffrer([Mesure("bso", 20.0, "m² de baies équipées"), Mesure("isolant", 2.0, "m³ d'isolant"),
                              Mesure("facade", 4.0, "m² de vitrage ajoutés"), Mesure("photovoltaique", 1.0, "toit"),
                              Mesure("arbre", 3.0, "arbres"), Mesure("ouvrants", 1.0, ""),
                              Mesure("casquette", 0.0, "m² de protection")], carbone.Reglages(), production_kwh=1000.0)
    parties = {ligne["element"]: ligne["kgco2e"] for ligne in rendu["lignes"]}
    assert parties["bso"] == round(20 * 5.0 * 5.193)
    assert parties["isolant"] == round(2 * 30 * 1.28)
    assert parties["facade, vitrage"] == round(4 * 20 * 1.26) and parties["facade, cadres"] == round(4 * 5 * 5.193)
    assert parties["photovoltaique"] == round(1000 * 30 * 0.0439)
    assert "casquette" not in parties                                       # rien posé, rien compté
    assert rendu["non_chiffres"] == ["arbre : une plantation", "ouvrants : aucun matériau ajouté"]


def test_le_retour_compte_le_photovoltaique():
    carbones = {"sans": carbone.chiffrer([], carbone.Reglages()),
                "pv": carbone.chiffrer([Mesure("photovoltaique", 1.0, "toit")], carbone.Reglages(), production_kwh=1000.0),
                "casquette": carbone.chiffrer([Mesure("casquette", 10.0, "m²")], carbone.Reglages())}
    carbone.evite(carbones, ["sans", "pv", "casquette"], {"sans": 1000.0, "pv": 1000.0, "casquette": 1100.0},
                  {"pv": 1000.0}, 0.064)
    assert carbones["pv"]["co2_evite_kg_par_an"] == 64 and carbones["pv"]["retour_ans"] == pytest.approx(1317 / 64, abs=0.1)
    assert carbones["casquette"]["co2_evite_kg_par_an"] == -100 and carbones["casquette"]["retour_ans"] is None
    texte = "\n".join(carbone.dire(carbones, ["sans", "pv", "casquette"]))
    assert "« pv » : 1317 kg CO2e" in texte and "remboursé en 20.6 ans" in texte and "pas de retour" in texte


def test_l_etude_lit_le_carbone(tmp_path):
    fichier = tmp_path / "etude.toml"
    fichier.write_text('''usage = "bureau"
[batiment]
longueur_m = 20.0
largeur_m = 10.0
[carbone]
facteurs = { aluminium = 2.3 }
[[scenario]]
nom = "bois"
[scenario.carbone]
materiaux = { casquette = "bois" }
[[scenario.element]]
type = "casquette"
[[scenario]]
nom = "donné"
carbone_kg = 950
''', encoding="utf-8")
    lue = etude.lire(fichier)
    assert lue.carbone.facteurs == {"aluminium": 2.3}
    par_nom = {s.nom: s for s in lue.scenarios}
    assert par_nom["bois"].carbone == {"materiaux": {"casquette": "bois"}} and par_nom["donné"].carbone_kg == 950
    fichier.write_text('usage = "bureau"\n[batiment]\nlongueur_m = 20.0\nlargeur_m = 10.0\n[carbone]\nfacteurs = { or = 1 }\n',
                       encoding="utf-8")
    with pytest.raises(etude.EtudeInvalide, match="matériau « or » inconnu"):
        etude.lire(fichier)


def test_un_vitrage_remplace_compte_son_verre_et_une_teinte_n_est_pas_chiffree():
    rendu = carbone.chiffrer([Mesure("vitrage", 10.0, "m² de vitrage remplacés"), Mesure("teinte", 1.0, "")],
                             carbone.Reglages())
    assert rendu["lignes"][0]["element"] == "vitrage remplacé" and rendu["kgco2e"] == round(10 * 20 * 1.26)
    assert rendu["non_chiffres"] == ["teinte : une peinture de façade"]
