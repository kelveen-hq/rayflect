"""Le sol sous le plancher, le vent sur les parois, la teinte des parois, l'air neuf hors occupation et le
fichier météo donné : ce que ces réglages lisent, ce qu'ils refusent, ce qu'ils écrivent."""

from types import SimpleNamespace

import pytest

from rayflect import etude, exterieur, hypotheses as hyp


def _meteo(par_mois):
    heures = []
    for valeur, jours in zip(par_mois, exterieur.JOURS_PAR_MOIS):
        heures += [float(valeur)] * (24 * jours)
    return SimpleNamespace(dry_bulb_temperature=SimpleNamespace(values=heures),
                           wind_speed=SimpleNamespace(values=[3.0] * 8760))


AIR = [5, 7, 10, 12, 16, 20, 23, 22, 19, 14, 9, 6]


def test_sans_reglage_le_sol_est_a_18_degres_et_le_dit():
    sol = exterieur.sol(_meteo(AIR))
    assert sol.temperatures_c == (18.0,) * 12 and "par défaut d'EnergyPlus" in sol.origine and sol.a_demander is None
    assert exterieur.texte_du_sol(sol).count("18.0") == 12
    assert "Site:GroundTemperature:BuildingSurface" in exterieur.texte_du_sol(sol)


def test_le_sol_se_donne_mois_par_mois_ou_par_une_constante():
    donne = exterieur.sol(_meteo(AIR), temperatures_c=[10, 10, 11, 13, 15, 17, 18, 18, 17, 15, 12, 11])
    assert donne.temperatures_c[0] == 10.0 and donne.temperatures_c[6] == 18.0 and "mois par mois" in donne.origine
    assert exterieur.sol(_meteo(AIR), loi="constante", temperature_c=15).temperatures_c == (15.0,) * 12


def test_le_sol_amorti_suit_l_air_avec_un_mois_de_retard_et_moins_d_ampleur():
    sol = exterieur.sol(_meteo(AIR), loi="air_amorti")
    assert max(sol.temperatures_c) - min(sol.temperatures_c) == pytest.approx(0.4 * (23 - 5), abs=0.11)
    assert sol.temperatures_c.index(max(sol.temperatures_c)) == AIR.index(23) + 1       # août, un mois après juillet
    assert sum(sol.temperatures_c) / 12 == pytest.approx(sum(a * j for a, j in zip(AIR, exterieur.JOURS_PAR_MOIS)) / 365,
                                                         abs=0.3)


@pytest.mark.parametrize("reglage, attendu", [
    (dict(temperatures_c=[10] * 11), "12 températures"),
    (dict(temperatures_c=[10] * 12, loi="constante"), "pas les 2"),
    (dict(loi="iso"), "n'est pas dans"),
    (dict(loi="air_amorti", temperature_c=12), "ne vaut qu'avec"),
    (dict(loi="constante", temperature_c=80), "n'est pas une température de sol"),
])
def test_un_sol_mal_regle_est_refuse_avec_la_raison(reglage, attendu):
    with pytest.raises(ValueError, match=attendu):
        exterieur.sol(_meteo(AIR), **reglage)


def test_le_vent_a_10_m_en_terrain_degage_est_celui_de_la_station_et_il_est_plus_faible_en_ville():
    assert exterieur.vent_a_la_hauteur(5.0, 10.0, "Country") == pytest.approx(5.0)
    assert exterieur.vent_a_la_hauteur(5.0, 10.0, "City") < exterieur.vent_a_la_hauteur(5.0, 10.0, "Suburbs") < 5.0
    assert exterieur.vent_a_la_hauteur(5.0, 20.0, "City") > exterieur.vent_a_la_hauteur(5.0, 10.0, "City")
    # Ville : 5 × (270 / 10)^0,14 × (10 / 460)^0,33
    assert exterieur.vent_a_la_hauteur(5.0, 10.0, "City") == pytest.approx(5.0 * 27.0 ** 0.14 * (10.0 / 460.0) ** 0.33)
    assert exterieur.echange_iso_6946(0.0) == 4.0 and exterieur.echange_iso_6946(2.5) == 14.0


def test_la_convection_iso_ecrit_un_planning_par_famille_de_parois(tmp_path):
    pytest.importorskip("honeybee")
    from honeybee.model import Model
    from honeybee.room import Room

    modele = Model("m", rooms=[Room.from_box("salle", 8, 6, 12)])
    texte = exterieur.texte_de_la_convection(modele, _meteo(AIR), tmp_path)
    assert texte.count("SurfaceProperty:ConvectionCoefficients:MultipleSurface") == 3
    for famille in ("AllExteriorWalls", "AllExteriorWindows", "AllExteriorRoofs"):
        assert f"{famille}, Outside, Schedule, , " in texte
    lignes = (tmp_path / "echange_exterieur.csv").read_text(encoding="utf-8").splitlines()
    assert len(lignes) == 8761
    murs, toit = (float(v) for v in lignes[1].split(","))
    assert murs == pytest.approx(4 + 4 * exterieur.vent_a_la_hauteur(3.0, 6.0), abs=0.001)
    assert toit == pytest.approx(4 + 4 * exterieur.vent_a_la_hauteur(3.0, 12.0), abs=0.001) and toit > murs
    with pytest.raises(ValueError, match="terrain inconnu"):
        exterieur.texte_de_la_convection(modele, _meteo(AIR), tmp_path, terrain="Montagne")


def test_la_teinte_des_murs_et_du_toit_se_donne_et_se_lit_dans_les_hypotheses():
    pytest.importorskip("honeybee_energy")
    from honeybee.model import Model
    from honeybee.room import Room

    modele = Model("m", rooms=[Room.from_box("salle", 8, 6, 3)])
    choix = hyp.Hypotheses(parois=hyp.Parois(absorption_des_murs=0.65, absorption_du_toit=0.78))
    hyp.appliquer(modele, choix)
    faces = {f.type.name: f for f in modele.rooms[0].faces}
    assert faces["Wall"].properties.energy.construction.materials[0].solar_absorptance == 0.65
    assert faces["RoofCeiling"].properties.energy.construction.materials[0].solar_absorptance == 0.78
    lignes = choix.justification()
    assert "absorption solaire des murs : 0.65, donnée" in lignes and "absorption solaire du toit : 0.78, donnée" in lignes
    assert "absorption solaire des murs : 0.7, teinte moyenne [H]" in hyp.Hypotheses().justification()
    with pytest.raises(ValueError, match="absorption_du_toit"):
        hyp.Parois(absorption_du_toit=1.4)


def test_l_air_neuf_peut_demarrer_avant_l_occupation_et_ne_pas_se_couper():
    pytest.importorskip("honeybee_energy")
    from honeybee.model import Model
    from honeybee.room import Room

    coupe = Model("a", rooms=[Room.from_box("salle", 8, 6, 3)])
    hyp.appliquer(coupe, hyp.Hypotheses("bureau"))
    assert sorted(set(coupe.rooms[0].properties.energy.ventilation.schedule.values())) == [0.0, 1.0]
    regle = hyp.Hypotheses("bureau", reglages_d_usage=(
        ("air_neuf_avance_h", 2), ("air_neuf_maintien_h", 1), ("air_neuf_m3_h_m2", 2.0), ("air_neuf_reduit_m3_h_m2", 0.5)))
    modele = Model("b", rooms=[Room.from_box("salle2", 8, 6, 3)])
    hyp.appliquer(modele, regle)
    planning = modele.rooms[0].properties.energy.ventilation.schedule
    lundi = planning.values()[24:48]                       # l'année de calcul commence un dimanche
    assert lundi[5] == 0.25 and lundi[6] == 1.0 and lundi[18] == 1.0 and lundi[19] == 0.25
    assert set(planning.values()[:24]) == {0.25}           # le dimanche : le débit réduit
    assert list(planning.winter_designday_schedule.values) == [1.0]
    assert any("0.50 m³/h par m² le reste du temps, mis en marche 2 h avant" in ligne for ligne in regle.justification())
    assert any("coupé hors occupation" in ligne for ligne in hyp.Hypotheses("bureau").justification())
    with pytest.raises(ValueError, match="dépasse le débit en occupation"):
        hyp.usage_regle("bureau", {"air_neuf_reduit_m3_h_m2": 9.0})


def _ecrire(tmp_path, texte):
    fichier = tmp_path / "etude.toml"
    fichier.write_text(texte, encoding="utf-8")
    return fichier


def test_le_fichier_d_etude_lit_le_sol_la_convection_et_la_meteo_donnee(tmp_path):
    lue = etude.lire(_ecrire(tmp_path, '''maquette = "a.ifc"
convection_exterieure = "iso_6946"
[sol]
loi = "air_amorti"
[lieu]
meteo = "donnees/bordeaux_2019.epw"
[parois]
absorption_des_murs = 0.65
'''))
    assert lue.convection_exterieure == "iso_6946" and lue.sol == {"loi": "air_amorti"} and lue.terrain is None
    assert etude.lire(_ecrire(tmp_path, 'maquette = "a.ifc"\nterrain = "Country"\n')).terrain == "Country"
    assert lue.meteo == (tmp_path / "donnees" / "bordeaux_2019.epw").resolve()
    assert lue.parois.absorption_des_murs == 0.65
    simple = etude.lire(_ecrire(tmp_path, 'maquette = "a.ifc"\n'))
    assert simple.meteo is None and simple.sol == {} and simple.convection_exterieure == "energyplus"


@pytest.mark.parametrize("texte, attendu", [
    ('convection_exterieure = "doe2"\n', "convection_exterieure"),
    ('terrain = "Montagne"\n', "terrain"),
    ('[sol]\nprofondeur_m = 2\n', r"\[sol\] : clés inconnues : profondeur_m"),
])
def test_un_reglage_du_dehors_mal_ecrit_est_refuse_avec_la_raison(tmp_path, texte, attendu):
    with pytest.raises(etude.EtudeInvalide, match=attendu):
        etude.lire(_ecrire(tmp_path, 'maquette = "a.ifc"\n' + texte))
