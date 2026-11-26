"""Le fichier d'étude : ce qu'il lit, ce qu'il refuse et comment il le dit. Aucun calcul n'est lancé ici."""

import pytest

from rayflect import cache, cli, etude
from rayflect import protections_solaires as ps, vegetation


def _ecrire(tmp_path, texte):
    fichier = tmp_path / "etude.toml"
    fichier.write_text(texte, encoding="utf-8")
    return fichier


def test_le_modele_fourni_se_relit(tmp_path):
    lue = etude.lire(_ecrire(tmp_path, etude.MODELE))
    assert lue.maquette == (tmp_path / "batiment.ifc").resolve()
    assert lue.adresse == "1 place de la Bourse, Bordeaux" and lue.coordonnees is None
    assert [s.nom for s in lue.scenarios] == ["sans", "casquettes", "BSO pilotés"]
    casquette = lue.scenarios[1].elements[0]
    assert isinstance(casquette, ps.Casquette) and casquette.orientations == ("SE", "S", "SO")
    assert lue.scenarios[2].elements[0].pilotage == "chaleur"


def test_sans_scenario_les_6_par_defaut(tmp_path):
    lue = etude.lire(_ecrire(tmp_path, 'maquette = "a.ifc"\n'))
    assert len(lue.scenarios) == 6 and lue.scenarios[0].nom == "sans" and not lue.scenarios[0].elements


def test_la_reference_passe_en_premier(tmp_path):
    lue = etude.lire(_ecrire(tmp_path, '''maquette = "a.ifc"
[[scenario]]
nom = "toit clair"
[[scenario.element]]
type = "toit"
[[scenario]]
nom = "sans"
'''))
    assert [s.nom for s in lue.scenarios] == ["sans", "toit clair"]


def test_plusieurs_elements_dans_un_scenario_et_un_feuillage_du_catalogue(tmp_path):
    lue = etude.lire(_ecrire(tmp_path, '''maquette = "a.ifc"
[lieu]
latitude = 44.84
longitude = -0.57
[[scenario]]
nom = "pergola et panneaux"
[[scenario.element]]
type = "pergola"
feuillage = "vigne_vierge"
[[scenario.element]]
type = "photovoltaique"
couverture = 0.3
'''))
    pergola, panneaux = lue.scenarios[0].elements
    assert pergola.feuillage is vegetation.VIGNE_VIERGE and panneaux.couverture == 0.3
    assert lue.coordonnees == (44.84, -0.57)


@pytest.mark.parametrize("texte, attendu", [
    ('usage = "bureau"\n', "il manque la maquette"),
    ('maquette = "a.ifc"\nusage = "gare"\n', "usage inconnu"),
    ('maquette = "a.ifc"\nperiode = "1900"\n', "période inconnue"),
    ('maquette = "a.ifc"\nfenetres = "entrouvertes"\n', "fenêtres"),
    ('maquette = "a.ifc"\nmeteo = "x.epw"\n', "clés inconnues : meteo"),
    ('maquette = "a.ifc"\n[lieu]\nlatitude = 44.8\n', "vont ensemble"),
    ('maquette = "a.ifc"\n[[scenario]]\nnom = "x"\n[[scenario.element]]\ntype = "store banne"\n', "type d'élément inconnu"),
    ('maquette = "a.ifc"\n[[scenario]]\nnom = "x"\n[[scenario.element]]\ntype = "casquette"\nlargeur_m = 2\n',
     "n'a pas de paramètre largeur_m"),
    ('maquette = "a.ifc"\n[[scenario]]\nnom = "x"\n[[scenario.element]]\ntype = "pergola"\nfeuillage = "bambou"\n',
     "feuillage inconnu"),
    ('maquette = "a.ifc"\n[[scenario]]\nnom = "x"\n[[scenario]]\nnom = "x"\n', "même nom"),
    ('maquette = "a.ifc"\n[[scenario]]\n', "pas de nom"),
    ('maquette = \n', "TOML valide"),
])
def test_ce_qui_est_refuse_dit_quoi_corriger(tmp_path, texte, attendu):
    with pytest.raises(etude.EtudeInvalide, match=attendu):
        etude.lire(_ecrire(tmp_path, texte))


def test_une_maquette_absente_se_dit_avant_tout_calcul(tmp_path):
    pytest.importorskip("honeybee_energy")
    pytest.importorskip("ifcopenshell")
    with pytest.raises(etude.EtudeInvalide, match="maquette introuvable"):
        etude.calculer(etude.lire(_ecrire(tmp_path, 'maquette = "absente.ifc"\n')), tmp_path / "sortie")


def test_le_compte_rendu_montre_les_manques_avant_les_chiffres():
    bilan = {
        "maquette": "a.ifc", "lieu": "ici", "scenarios": ["sans", "BSO"], "heures_d_occupation": 2000,
        "repris": {"zones": 2, "baies": 10, "aire_reposee_m2": 20.0, "aire_relevee_m2": 21.0, "baies_ecartees": 1},
        "a_demander": ["lieu non confirmé"], "hypotheses": ["chauffage à 19 °C"],
        "heures_au_dessus_de_26": {"0 | RDC | entier": {"sans": 400, "BSO": 150}},
        "autonomie_300_lux": {"0 | RDC | entier": {"sans": 0.5, "BSO": 0.31}},
        "chauffage_kwh": {"sans": 1000, "BSO": 1010}, "production_pv_kwh": {},
    }
    texte = etude.presenter(bilan)
    assert texte.index("lieu non confirmé") < texte.index("Heures au-dessus de 26 °C")
    assert "400" in texte and "150" in texte and "31 %" in texte and "production PV" not in texte


def test_le_cache_suit_la_variable_d_environnement(tmp_path, monkeypatch):
    monkeypatch.setenv("RAYFLECT_CACHE", str(tmp_path / "c"))
    assert cache.dossier("meteo") == (tmp_path / "c").resolve() / "meteo"
    assert cache.dossier("meteo").is_dir()


def test_la_commande_ecrit_un_modele_sans_ecraser(tmp_path, capsys):
    fichier = tmp_path / "e.toml"
    assert cli.main(["modele", str(fichier)]) == 0
    assert fichier.read_text(encoding="utf-8") == etude.MODELE
    assert cli.main(["modele", str(fichier)]) == 1
    assert "n'est pas remplacé" in capsys.readouterr().err


def test_la_commande_rend_1_sur_une_etude_fausse(tmp_path, capsys):
    assert cli.main(["etude", str(_ecrire(tmp_path, 'maquette = "a.ifc"\nusage = "gare"\n'))]) == 1
    assert "ÉTUDE NON JOUÉE" in capsys.readouterr().err


def test_la_climatisation_les_parois_et_l_energie_se_lisent(tmp_path):
    lue = etude.lire(_ecrire(tmp_path, '''maquette = "a.ifc"
climatisation = true
[parois]
isolation_des_murs = "interieure"
isolant_des_murs_cm = 10
vitrage = "triple"
[energie]
chauffage = "pac"
prix_electricite_eur_kwh = 0.2
'''))
    assert lue.climatisation and lue.parois.isolation_des_murs == "interieure" and lue.parois.vitrage == "triple"
    assert lue.energie.energie_de_chauffage == "electricite" and lue.energie.prix_electricite_eur_kwh == 0.2
    assert etude.lire(_ecrire(tmp_path, 'maquette = "a.ifc"\n')).energie is None


@pytest.mark.parametrize("texte, attendu", [
    ('maquette = "a.ifc"\n[parois]\nvitrage = "quadruple"\n', r"\[parois\] : vitrage inconnu"),
    ('maquette = "a.ifc"\n[parois]\nepaisseur = 3\n', r"\[parois\]"),
    ('maquette = "a.ifc"\n[energie]\nchauffage = "charbon"\n', r"\[energie\] : chauffage inconnu"),
])
def test_des_parois_ou_une_energie_fausses_disent_quoi_corriger(tmp_path, texte, attendu):
    with pytest.raises(etude.EtudeInvalide, match=attendu):
        etude.lire(_ecrire(tmp_path, texte))


def test_le_compte_rendu_montre_le_froid_l_energie_et_ce_qui_manque():
    bilan = {
        "maquette": "a.ifc", "lieu": "ici", "scenarios": ["sans", "BSO"], "heures_d_occupation": 2000,
        "repris": {"zones": 1, "baies": 4, "aire_reposee_m2": 8.0, "aire_relevee_m2": 8.0, "baies_ecartees": 0},
        "a_demander": [], "hypotheses": [], "heures_au_dessus_de_26": {"0 | RDC | entier": {"sans": 300, "BSO": 100}},
        "autonomie_300_lux": {}, "chauffage_kwh": {"sans": 9000, "BSO": 9100}, "froid_kwh": {"sans": 6000, "BSO": 3000},
        "production_pv_kwh": {}, "energie_comment": ["prix du kWh de gaz : 0.1000 €, donné"],
        "energie": {
            "sans": {"chauffage_kwh": 10000, "energie_de_chauffage": "gaz", "climatisation_kwh": 2000,
                     "kgco2": 2398, "euros": None},
            "BSO": {"chauffage_kwh": 10111, "energie_de_chauffage": "gaz", "climatisation_kwh": 1000,
                    "kgco2": 2359, "euros": None}},
    }
    texte = etude.presenter(bilan)
    assert "malgré la climatisation" in texte and "besoin de froid, kWh par an" in texte
    assert "chauffage (gaz), kWh" in texte and "2398" in texte and "à demander" in texte
    assert "prix du kWh de gaz" in texte


def test_des_noms_de_scenario_trop_longs_sont_numerotes_plutot_que_coupes():
    """« tilleuls, à 1 an » et « tilleuls, à 15 ans », coupés à la largeur de la colonne, se liraient pareil."""
    colonnes = ["sans", "tilleuls, à 1 an", "tilleuls, à 15 ans"]
    bilan = {
        "maquette": "a.dxf", "lieu": "ici", "scenarios": colonnes, "a_demander": [], "hypotheses": [],
        "repris": {"zones": 1, "baies": 2, "aire_reposee_m2": 3.0, "aire_relevee_m2": 3.0, "baies_ecartees": 0},
        "heures_d_occupation": 2600, "heures_au_dessus_de_26": {"0 | rdc | entier": {c: 1 for c in colonnes}},
        "autonomie_300_lux": {}, "chauffage_kwh": {c: 10 for c in colonnes}, "froid_kwh": {}, "energie": {},
        "production_pv_kwh": {}, "changements": {"tilleuls, à 1 an": ["tilleul à 1 an : 6 m de haut"]},
    }
    rendu = etude.presenter(bilan)
    assert "  (2) tilleuls, à 1 an" in rendu and "  (3) tilleuls, à 15 ans" in rendu
    assert "tilleuls, à 1 " not in rendu.split("Heures au-dessus")[1]
    assert "ce que change « tilleuls, à 1 an » :" in rendu
    bilan["scenarios"] = ["sans", "casquettes"]
    bilan["chauffage_kwh"] = {"sans": 10, "casquettes": 11}
    assert "scénarios comparés" not in etude.presenter(bilan)
