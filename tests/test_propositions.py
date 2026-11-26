"""Les propositions automatiques, sans calcul : les objectifs, le jugement, le classement, les combinaisons."""

import pytest

from rayflect import etude, propositions
from rayflect.propositions import PropositionsInvalides


def test_la_palette_se_pose_dans_une_etude():
    for mesure in propositions.PALETTE:
        sc = propositions.scenario([mesure.cle], etude.element, etude.Scenario)
        assert sc.nom == mesure.nom and len(sc.elements) == len(mesure.elements)
        assert sc.parois == dict(mesure.parois)
        etude.hyp.Parois(**sc.parois)                                       # des parois que l'étude accepte


def test_une_combinaison_reunit_elements_et_parois():
    sc = propositions.scenario(["casquettes_au_sud", "murs_clairs", "isolation_exterieure"], etude.element, etude.Scenario)
    assert sc.nom == "casquettes au sud + murs clairs + 14 cm d'isolant par l'extérieur"
    assert sc.parois == {"absorption_des_murs": 0.4, "isolation_des_murs": "exterieure", "isolant_des_murs_cm": 14.0}


@pytest.mark.parametrize("objectifs, propositions_, attendu", [
    ({}, {}, "au moins un objectif"),
    ({"dh": 350}, {}, "clés inconnues : dh"),
    ({"dh_max": -1}, {}, "un nombre positif"),
    ({"dh_max": 350}, {"mesures": ["mur_vegetal"]}, "mur_vegetal"),
    ({"dh_max": 350}, {"combinaisons": 4}, "de 1 à 3"),
    ({"dh_max": 350}, {"retenues": 1}, "2 au moins"),
])
def test_des_objectifs_faux_sont_refuses(objectifs, propositions_, attendu):
    with pytest.raises(PropositionsInvalides, match=attendu):
        propositions.lire(objectifs, propositions_)


def _ind(**valeurs):
    base = {"dh": 500.0, "heures_26": 300.0, "autonomie": 0.6, "exces": 0.3, "eblouissement": 0.1,
            "chauffage_hausse": 0.0, "carbone": 0.0}
    base.update(valeurs)
    return base


def test_juger_compte_les_objectifs_tenus_et_l_ecart():
    objectifs = {"dh_max": 350.0, "autonomie_min": 0.5, "chauffage_hausse_max": 0.05}
    tenus, ecart, manque = propositions.juger(_ind(dh=420.0, autonomie=0.55, chauffage_hausse=0.10), objectifs)
    assert tenus == 1 and ecart == pytest.approx(70 / 350 + 0.05 / 0.05)
    assert manque == ["degrés-heures, pièce la plus chaude : 420 pour 350",
                      "hausse du chauffage face au bâtiment tel qu'il est : +10 % pour +5 %"]


def test_ranger_met_d_abord_ce_qui_tient_le_plus():
    objectifs = {"dh_max": 350.0, "autonomie_min": 0.5}
    rangees = propositions.ranger({
        (): _ind(dh=800.0),
        ("bso_pilotes",): _ind(dh=300.0, autonomie=0.3, carbone=900.0),
        ("casquettes_au_sud",): _ind(dh=340.0, carbone=1000.0),
        ("fenetres_jour_et_nuit",): _ind(dh=330.0, carbone=0.0),
    }, objectifs)
    assert [e["nom"] for e in rangees] == ["fenêtres ouvertes jour et nuit, traversant", "casquettes au sud",
                                           "BSO pilotés sur la chaleur", "tel quel"]
    assert rangees[0]["tenus"] == 2 and rangees[-1]["tenus"] == 1


def test_les_combinaisons_ne_doublent_pas_un_type_d_element():
    rangees = [{"mesures": [c], "nom": c} for c in ("fenetres_jour_et_nuit", "surventilation_de_nuit", "bso_pilotes",
                                                   "casquettes_au_sud", "toit_clair")]
    combos = propositions.a_combiner(rangees, retenues=4, combinaisons=3)
    assert ("fenetres_jour_et_nuit", "surventilation_de_nuit") in combos      # ouvrants et ventilation : 2 types
    assert len(combos) == 6 + 4 and all("toit_clair" not in c for c in combos)  # le 5e n'est pas retenu


def test_le_compte_rendu_dit_ce_qui_tient_et_ce_qui_manque():
    objectifs = {"dh_max": 350.0}
    rendu = {"objectifs": objectifs, "propositions": propositions.ranger({(): _ind(dh=800.0)}, objectifs),
             "tiennent_tout": []}
    texte = propositions.presenter(rendu)
    assert "aucune ne tient tous les objectifs ; la plus proche, « tel quel », manque :" in texte
    assert "degrés-heures, pièce la plus chaude : au plus 350" in texte


def test_proposer_refuse_plusieurs_climats_et_la_climatisation(tmp_path):
    lue = etude.Etude(batiment={"longueur_m": 10.0, "largeur_m": 10.0}, objectifs={"dh_max": 350}, climat=["type", "futur"])
    with pytest.raises(etude.EtudeInvalide, match="un seul climat"):
        etude.proposer(lue, tmp_path)
    lue = etude.Etude(batiment={"longueur_m": 10.0, "largeur_m": 10.0}, objectifs={"dh_max": 350}, climatisation=True)
    with pytest.raises(etude.EtudeInvalide, match="climatisation = false"):
        etude.proposer(lue, tmp_path)


def test_un_nom_de_scenario_long_donne_un_dossier_court_et_unique():
    court = etude.nom_de_dossier("casquettes au sud")
    assert court == "casquettes_au_sud"
    long_ = propositions.nom_de(["fenetres_jour_et_nuit", "surventilation_de_nuit", "lames_est_ouest"])
    autre = propositions.nom_de(["fenetres_jour_et_nuit", "surventilation_de_nuit", "bso_pilotes"])
    assert len(etude.nom_de_dossier(long_)) == etude.NOM_DE_DOSSIER_MAX
    assert etude.nom_de_dossier(long_) != etude.nom_de_dossier(autre)
