"""Où en est le calcul : ce qu'on lit d'EnergyPlus, et ce qu'on en montre. Sans lancer de calcul."""

import io

from rayflect import cli, etude, moteur

JOURNAL = """EnergyPlus Starting
Warming up {1}
Starting Simulation at 01/21 for JOUR_DE_BASE
Updating Shadowing Calculations, Start Date=01/21
Starting Simulation at 01/01/2017 for CUSTOMRUNPERIOD
Updating Shadowing Calculations, Start Date=01/21/2017
Continuing Simulation at 01/31/2017 for CUSTOMRUNPERIOD
Updating Shadowing Calculations, Start Date=07/02/2017
Continuing Simulation at 03/02/2017 for CUSTOMRUNPERIOD
Continuing Simulation at 12/27/2017 for CUSTOMRUNPERIOD
Writing final SQL reports
EnergyPlus Completed Successfully.
"""


def test_la_part_de_l_annee_se_lit_dans_ce_qu_ecrit_energyplus():
    suivi = moteur.Suivi()
    lues = [suivi.lire(ligne) for ligne in JOURNAL.splitlines()]
    assert lues[:5] == [None] * 5                   # le jour de base, sans année dans sa date, ne compte pas
    assert lues[5] == 20 / 365.0                    # le 21 janvier : 20 jours faits
    assert lues[6] == 30 / 365.0
    assert lues[7] == (181 + 1) / 365.0             # le 2 juillet : la moitié de l'année
    assert lues[8] is None                          # une date plus ancienne ne fait pas reculer
    assert 0.98 < lues[9] < 1.0                     # jamais 100 % avant que le calcul ait tout rendu
    assert lues[10] is None and lues[11] == 1.0


def test_un_temps_restant_se_dit_arrondi():
    assert cli.duree_en_clair(4) == "quelques secondes"
    assert cli.duree_en_clair(44) == "environ 40 s"
    assert cli.duree_en_clair(200) == "environ 3 min"
    assert cli.duree_en_clair(3000) == "environ 50 min"
    assert cli.duree_en_clair(9000) == "environ 2,5 h"


def _etude(noms):
    scenarios = [etude.Scenario(nom, [] if nom == "sans" else [object()]) for nom in noms]
    return etude.Etude(batiment={"longueur_m": 20.0}, scenarios=scenarios)


def test_les_etapes_se_listent_d_apres_les_scenarios():
    assert etude._Suivi(_etude(["sans", "a", "b", "c"]), 2, None).etapes == [
        "lire le bâtiment", "trouver le lieu et la météo", "calculer « sans », le bâtiment tel qu'il est",
        "calculer les 3 autres scénarios, 2 à la fois", "écrire le bilan"]
    assert etude._Suivi(_etude(["sans", "a"]), 4, None).etapes[3] == "calculer le scénario « a »"
    assert etude._Suivi(_etude(["a", "b"]), 4, None).etapes[2] == "calculer les 2 scénarios, 2 à la fois"
    assert len(etude._Suivi(_etude(["sans"]), 4, None).etapes) == 4


def test_l_avancement_compte_tous_les_scenarios_et_dit_qui_attend():
    rendus = []
    suivi = etude._Suivi(_etude(["sans", "a", "b", "c"]), 2, rendus.append)
    suivi.etape(1)
    suivi.etape(3, ["sans"])
    suivi.scenario("sans", 0.5)
    assert (rendus[-1].rang, rendus[-1].part, rendus[-1].en_cours) == (3, 0.125, {"sans": 0.5})
    assert rendus[-1].etape == "calculer « sans », le bâtiment tel qu'il est"
    suivi.etape(4, ["a", "b", "c"])
    assert rendus[-1].part == 0.25                              # le premier scénario est fait : 1 sur 4
    assert rendus[-1].en_cours == {"a": None, "b": None, "c": None} and rendus[-1].reste_s is None
    suivi.scenario("a", 0.0)
    suivi.scenario("b", 0.4)
    assert rendus[-1].en_cours == {"a": 0.0, "b": 0.4, "c": None}       # c attend qu'un processeur se libère
    assert rendus[-1].reste_s is not None and rendus[-1].reste_s >= 0.0
    suivi.scenario("b", 0.2)
    assert rendus[-1].en_cours["b"] == 0.4                      # un scénario ne recule pas
    suivi.etape(5)
    assert (rendus[-1].part, rendus[-1].reste_s, rendus[-1].en_cours) == (1.0, 0.0, {})


def test_hors_ecran_une_ligne_par_etape_puis_tous_les_10_pour_cent():
    ecrit = io.StringIO()
    affichage = cli.Affichage(ecrit, sur_place=False)
    etapes = ("lire le bâtiment", "calculer « sans », le bâtiment tel qu'il est", "écrire le bilan")
    affichage.suivre(etude.Avancement(etapes, 1, 0.0, None, {}))
    for centieme in range(0, 101):
        affichage.suivre(etude.Avancement(etapes, 2, centieme / 100.0, 120.0 if centieme > 5 else None,
                                          {"sans": centieme / 100.0}))
    affichage.dire("calculé : sans (12 s)")
    affichage.suivre(etude.Avancement(etapes, 3, 1.0, 0.0, {}))
    lignes = ecrit.getvalue().splitlines()
    assert lignes[0] == ("3 étapes : 1. lire le bâtiment ; 2. calculer « sans », le bâtiment tel qu'il est ; "
                         "3. écrire le bilan")
    assert lignes[1] == "étape 1 sur 3 : lire le bâtiment"
    assert lignes[2] == "étape 2 sur 3 : calculer « sans », le bâtiment tel qu'il est"
    assert lignes[3] == "  0 % du calcul" and lignes[4] == "  10 % du calcul, encore environ 2 min"
    assert len([ligne for ligne in lignes if "% du calcul" in ligne]) == 11
    assert lignes[-2:] == ["calculé : sans (12 s)", "étape 3 sur 3 : écrire le bilan"]


def test_sur_un_ecran_la_ligne_se_reecrit_sur_place_et_s_efface_avant_un_message():
    ecrit = io.StringIO()
    affichage = cli.Affichage(ecrit, sur_place=True)
    etapes = ("calculer les 2 scénarios, 2 à la fois", "écrire le bilan")
    affichage.suivre(etude.Avancement(etapes, 1, 0.31, 75.0, {"a": 0.5, "b": None}))
    affichage.dire("calculé : a (9 s)")
    texte = ecrit.getvalue()
    ligne = "  31 % du calcul, encore environ 80 s (a 50 %, b en attente)"
    assert "\r" + ligne in texte
    assert texte.endswith("\r" + " " * len(ligne) + "\rcalculé : a (9 s)\n")
