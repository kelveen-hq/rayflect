"""La trajectoire d'une plantation dans le temps, sans calcul : l'ombre mois par mois, les âges remis bout à bout."""

import pytest

from rayflect import etude, trajectoire, vegetation


def _chaleur(soleil_par_mois):
    return {"postes": [{"poste": "baies, soleil", "cote": "S", "kwh": round(sum(soleil_par_mois)),
                        "par_mois": soleil_par_mois}], "ecart_kwh": 0, "ecart_part": 0.0}


def test_l_ombre_est_la_part_du_soleil_des_baies_arretee():
    sans = _chaleur([100] * 12)
    avec = _chaleur([90] + [100] * 5 + [30] + [100] * 5)
    ombre = trajectoire.ombre_par_mois(avec, sans)
    assert ombre[trajectoire.JANVIER] == pytest.approx(0.10) and ombre[trajectoire.JUILLET] == pytest.approx(0.70)
    assert trajectoire.ombre_par_mois(avec, _chaleur([0] * 12))[0] is None       # rien à arrêter : pas de part


def test_l_etude_dit_de_quelle_plantation_et_de_quel_age_vient_chaque_scenario(tmp_path):
    fichier = tmp_path / "etude.toml"
    fichier.write_text('''usage = "bureau"
[batiment]
longueur_m = 20.0
largeur_m = 10.0
[[scenario]]
nom = "sans"
[[scenario]]
nom = "tilleuls"
annees = [10, 1]
[[scenario.element]]
type = "arbre"
est_m = 4.0
nord_m = -6.0
essence = "tilleul"
''', encoding="utf-8")
    lue = etude.lire(fichier)
    par_nom = {s.nom: s for s in lue.scenarios}
    assert par_nom["tilleuls, à 10 ans"].famille == "tilleuls" and par_nom["tilleuls, à 10 ans"].age == 10.0
    assert par_nom["sans"].famille is None


def test_la_trajectoire_range_les_ages_et_dit_la_taille_des_plantes():
    jeune, vieux = (vegetation.Arbre(4.0, -6.0, essence="tilleul", age_ans=a) for a in (1, 20))
    scenarios = [etude.Scenario("sans"),
                 etude.Scenario("tilleuls, à 20 ans", [vieux], famille="tilleuls", age=20.0),
                 etude.Scenario("tilleuls, à 1 an", [jeune], famille="tilleuls", age=1.0)]
    bilan = {"chauffage_kwh": {"sans": 1000, "tilleuls, à 20 ans": 1100, "tilleuls, à 1 an": 1010},
             "heures_au_dessus_de_26": {"0 | rdc | entier": {"sans": 500, "tilleuls, à 20 ans": 300, "tilleuls, à 1 an": 490}},
             "autonomie_300_lux": {"0 | rdc | entier": {"sans": 0.8, "tilleuls, à 20 ans": 0.6, "tilleuls, à 1 an": 0.8}},
             "confort_d_ete": {"pieces": {"0 | rdc | entier": {"sans": {"dh": 900}, "tilleuls, à 20 ans": {"dh": 400},
                                                               "tilleuls, à 1 an": {"dh": 880}}}},
             "bilan_de_chaleur": {"sans": _chaleur([100] * 12), "tilleuls, à 20 ans": _chaleur([80] * 6 + [20] + [80] * 5),
                                  "tilleuls, à 1 an": _chaleur([99] * 12)}}
    rendu = trajectoire.assembler(scenarios, bilan)
    points = rendu["tilleuls"]
    assert [p["age_ans"] for p in points] == [1.0, 20.0]
    assert points[1]["plantes"][0] == {"type": "arbre", "essence": "tilleul", "hauteur_m": vieux.hauteur_m,
                                       "couronne_m": vieux.diametre_m}
    assert points[1]["ombre_par_mois"][trajectoire.JUILLET] == pytest.approx(0.8) and points[1]["dh"] == 400
    texte = "\n".join(trajectoire.dire(rendu, {"dh": 900, "heures_au_dessus_de_26": 500, "chauffage_kwh": 1000,
                                               "autonomie_300_lux": 0.8}))
    assert "La plantation « tilleuls » dans le temps" in texte and "80 %" in texte and "sans" in texte
    assert trajectoire.assembler([etude.Scenario("sans")], bilan) == {}
