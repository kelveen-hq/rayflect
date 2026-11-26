"""Les hypothèses d'usage : le compte des heures, les parois visées, et ce qui est posé sur un modèle."""

import pytest

pytest.importorskip("honeybee_energy")
from honeybee.model import Model  # noqa: E402
from honeybee.room import Room  # noqa: E402

from rayflect import hypotheses as hyp  # noqa: E402


def test_heures_d_occupation_d_un_bureau():
    # 260 jours ouvrés dans une année qui commence un dimanche, 10 heures par jour.
    masque = hyp.heures_occupees(hyp.USAGES["bureau"])
    assert len(masque) == 8760
    assert sum(masque) == 260 * 10
    assert not any(masque[:24])                 # le 1er janvier est un dimanche
    assert masque[24 + 9]                       # le lundi à 9 h


def test_une_ecole_est_fermee_l_ete():
    masque = hyp.heures_occupees(hyp.USAGES["enseignement"])
    assert not any(masque[200 * 24:240 * 24])   # de la mi-juillet à la fin août
    assert sum(masque) < 260 * 9


def test_un_logement_est_toujours_occupe():
    assert sum(hyp.heures_occupees(hyp.USAGES["logement"])) == 8760


@pytest.mark.parametrize("periode", list(hyp.PAROIS_PAR_PERIODE))
def test_la_paroi_construite_a_le_u_vise(periode):
    vise = hyp.PAROIS_PAR_PERIODE[periode]["u_mur"]
    paroi = hyp._paroi("mur", vise)
    assert 1.0 / (paroi.r_value + hyp.R_SURFACES) == pytest.approx(vise, rel=0.01)


def test_chaque_hypothese_est_dite_avec_son_origine():
    lignes = hyp.Hypotheses("enseignement", "1975_1988").justification()
    assert any("15 m³/h par élève" in ligne for ligne in lignes)
    assert any("[H]" in ligne for ligne in lignes)
    assert any("fenêtres ouvertes" in ligne for ligne in lignes)
    assert any("jamais ouvertes" in ligne for ligne in
               hyp.Hypotheses(fenetres_ouvrables=False).justification())


@pytest.fixture()
def boite():
    piece = Room.from_box("salle", 8, 6, 3)
    piece.faces[3].apertures_by_ratio(0.4)
    return Model("essai", rooms=[piece])


def test_les_hypotheses_sont_posees_sur_le_modele(boite):
    hyp.appliquer(boite, hyp.Hypotheses("bureau", "2006_2012"))
    energie = boite.rooms[0].properties.energy
    assert energie.people is None and energie.lighting is None
    # RE2020 : 0,1044 occupant/m² à 90 W, 10,72 W/m² d'équipements ; 25 m³/h par occupant (code du travail).
    assert energie.electric_equipment.watts_per_area == pytest.approx(20.1)
    assert energie.ventilation.flow_per_area * 3600 == pytest.approx(2.61)
    assert energie.window_vent_control is not None
    assert all(baie.is_operable for baie in boite.apertures)
    assert boite.check_all(raise_exception=False) == ""


def test_fenetres_fermees(boite):
    hyp.appliquer(boite, hyp.Hypotheses(fenetres_ouvrables=False))
    assert boite.rooms[0].properties.energy.window_vent_control is None
    assert not any(baie.is_operable for baie in boite.apertures)


def test_les_fuites_d_air_du_batiment_ne_dependent_pas_du_decoupage():
    """Le débit de fuite total doit être le même, que le plateau soit d'un seul tenant ou découpé en zones."""
    from rayflect.io import releve_vers_honeybee as conversion
    from rayflect.io.lecture_ifc import Niveau, Releve
    contour = [(0, 0), (40, 0), (40, 20), (0, 20)]
    releve = Releve("essai", "aucun", "essai", None, None, None, 0.0, niveaux=[
        Niveau(f"n{k}", 3.0 * k, emprise_m=contour, plancher_m=3.0 * k, plafond_m=3.0 * k + 3.0,
               aire_emprise_m2=800.0) for k in range(3)])

    def debit(profondeur):
        modele, _ = conversion.convertir(releve, "p", profondeur)
        hyp.appliquer(modele, hyp.Hypotheses("bureau", "1975_1988"))
        return sum(p.properties.energy.infiltration.flow_per_exterior_area * p.exposed_area
                   for p in modele.rooms if p.properties.energy.infiltration is not None)

    # 3CL : 1,5 m³/h par m² de parois sous 4 Pa, 0,07 n50 V en usage ; parois exposées : 4 murs et le toit.
    attendu = 0.07 * 1.5 / (4.0 / 50.0) ** (2.0 / 3.0) * (2 * (40 + 20) * 9.0 + 800.0) / 3600.0
    assert debit(None) == pytest.approx(attendu, rel=0.001)
    assert debit(conversion.PROFONDEUR_DE_FACADE_M) == pytest.approx(attendu, rel=0.001)


def test_ce_qui_est_donne_passe_avant_la_periode_et_chaque_valeur_dit_son_origine():
    retenu = hyp.parois_retenues("1975_1988", hyp.Parois(
        isolant_des_murs_cm=10.0, u_toit=0.2, vitrage="double_peu_emissif", g_vitrage=0.4))
    assert retenu["u_mur"][0] == pytest.approx(1.0 / (0.17 + 0.10 / 0.040 + 0.15 / 1.65), abs=0.001)
    assert "10 cm d'isolant" in retenu["u_mur"][1]
    assert retenu["u_toit"] == (0.2, "donné")
    # 3CL, zone H2 par défaut : 3 ans à 0,95, 5 à 0,95, 6 à 0,74, en moyenne pondérée.
    assert retenu["u_plancher"] == (pytest.approx((3 * 0.95 + 5 * 0.95 + 6 * 0.74) / 14, abs=0.001),
                                    "période 1975_1988, zone H2 supposée, méthode 3CL-DPE 2021 [S]")
    assert retenu["u_vitrage"] == (1.4, "vitrage double peu emissif, fenêtre PVC, 3CL [S]")
    assert retenu["g_vitrage"] == (0.4, "donné")
    assert retenu["q4pa"][0] == 1.5 and "n50" not in retenu
    assert hyp.parois_retenues("1975_1988", hyp.Parois(n50=4.0))["n50"] == (4.0, "donné")


def test_les_parois_par_defaut_suivent_la_zone_climatique_et_la_methode_3cl():
    # Les lignes du tableau des murs (3CL, p. 13), colonne « autres » chauffages.
    assert [hyp.parois_retenues("2001_2005", hyp.Parois(), z)["u_mur"][0] for z in ("H1a", "H2c", "H3")] == [
        0.4, 0.4, 0.47]
    assert hyp.parois_retenues("1989_2000", hyp.Parois(), "H1b")["u_toit"][0] == 0.4      # terrasse, H1
    assert hyp.parois_retenues("avant_1948", hyp.Parois())["u_plancher"][0] == 2.0
    assert "zone H3, méthode" in hyp.parois_retenues("2006_2012", hyp.Parois(), "H3")["u_mur"][1]
    # Une période plus récente n'est jamais moins isolée.
    periodes = list(hyp.PAROIS_PAR_PERIODE)
    for grandeur in ("u_mur", "u_toit", "u_plancher", "u_vitrage", "q4pa"):
        valeurs = [hyp.PAROIS_PAR_PERIODE[p][grandeur] for p in periodes]
        assert valeurs == sorted(valeurs, reverse=True), grandeur


def test_un_mur_sans_isolant_n_est_jamais_meilleur_que_sa_periode():
    assert hyp.parois_retenues("2013_2020", hyp.Parois(isolation_des_murs="aucune"))["u_mur"][0] == 2.5
    assert hyp.parois_retenues("avant_1948", hyp.Parois(isolation_des_murs="aucune"))["u_mur"][0] == 2.5


@pytest.mark.parametrize("place, inertie, couches", [
    ("exterieure", "lourde", ["isolant", "beton"]),
    ("interieure", "lourde", ["beton", "isolant", "plaque"]),
    ("exterieure", "legere", ["isolant", "plaque"]),
])
def test_l_ordre_des_couches_suit_la_place_de_l_isolant_a_u_egal(place, inertie, couches):
    paroi = hyp._paroi("mur", 0.4, place, inertie)
    assert [m.identifier.split("_")[0] for m in paroi.materials] == couches       # du dehors vers le dedans
    assert 1.0 / (paroi.r_value + hyp.R_SURFACES) == pytest.approx(0.4, rel=0.01)


@pytest.mark.parametrize("arguments, attendu", [
    ({"isolation_des_murs": "partout"}, "isolation des murs"),
    ({"inertie": "moyenne"}, "inertie"),
    ({"vitrage": "quadruple"}, "vitrage inconnu"),
    ({"u_mur": -1.0}, "u_mur"),
    ({"g_vitrage": 1.2}, "entre 0 et 1"),
    ({"isolation_des_murs": "aucune", "isolant_des_murs_cm": 8}, "il faut choisir"),
])
def test_des_parois_impossibles_sont_refusees(arguments, attendu):
    with pytest.raises(ValueError, match=attendu):
        hyp.Parois(**arguments)


def test_la_climatisation_pose_la_consigne_de_froid_et_le_dit(boite):
    hyp.appliquer(boite, hyp.Hypotheses(climatisation=True))
    froid = boite.rooms[0].properties.energy.setpoint.cooling_schedule
    assert froid.default_day_schedule.values[0] == 26.0
    assert any("climatisation à 26.0 °C" in ligne for ligne in hyp.Hypotheses(climatisation=True).justification())
    assert any("pas de climatisation" in ligne for ligne in hyp.Hypotheses().justification())
