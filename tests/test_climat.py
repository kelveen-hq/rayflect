"""Le climat d'un lieu : zone climatique, température de base selon l'altitude, terrain proposé ; et ce que le
lieu apprend de l'IGN. Aucun essai ne sort sur le réseau : les réponses des services sont rejouées."""

import pytest

from rayflect import climat, etude, lieu


def test_les_96_departements_de_metropole_ont_une_zone_et_une_seule():
    departements = [d for zone in climat.ZONES.values() for d in zone]
    assert len(departements) == 96 == len(set(departements))
    attendus = {f"{n:02d}" for n in range(1, 96) if n != 20} | {"2A", "2B"}
    assert set(departements) == attendus
    assert set(climat.BASE_PAR_DEPARTEMENT) == attendus
    assert climat.zone("33") == "H2c" and climat.zone("75") == "H1a" and climat.zone("2a") == "H3"
    assert climat.zone("6") == "H3" and climat.zone("974") is None and climat.zone(None) is None


@pytest.mark.parametrize("departement, altitude, attendu", [
    ("33", 9, -5.0),            # Bordeaux
    ("75", 35, -5.0),           # Paris
    ("67", 143, -15.0),         # Strasbourg
    ("38", 212, -11.0),         # Grenoble : -10 au niveau de la mer, tranche de 201 à 400 m
    ("63", 400, -9.0),          # Clermont-Ferrand, à la limite haute de sa tranche
    ("63", 401, -11.0),
    ("2A", 119, -2.0),
    ("73", 1850, -25.0),        # une station de Savoie
    ("26", 300, -7.0),          # -6 au niveau de la mer : entre les colonnes -5 et -7
    ("33", None, -5.0),
])
def test_la_temperature_de_base_suit_le_departement_et_l_altitude(departement, altitude, attendu):
    valeur, origine = climat.temperature_de_base(departement, altitude)
    assert valeur == attendu and "à confirmer" in origine and f"département {departement}" in origine


def test_hors_de_la_grille_la_temperature_de_base_n_est_pas_inventee():
    assert climat.temperature_de_base("59", 1500) is None           # la grille s'arrête à 1 000 m pour -9 °C
    assert climat.temperature_de_base("33", 3000) is None
    assert climat.temperature_de_base("974", 10) is None and climat.temperature_de_base(None, 10) is None
    assert "entre les colonnes voisines" in climat.temperature_de_base("26", 300)[1]
    assert "altitude inconnue" in climat.temperature_de_base("33", None)[1]


def test_le_terrain_propose_suit_la_population_et_reste_une_proposition():
    assert climat.terrain_propose(267991)[0] == "City"
    assert climat.terrain_propose(20000)[0] == "Suburbs"
    assert climat.terrain_propose(800)[0] == "Country"
    assert climat.terrain_propose(None) is None


BORDEAUX = {"features": [{"geometry": {"coordinates": [-0.587877, 44.851939]}, "properties": {
    "label": "Bordeaux", "score": 0.96, "type": "municipality", "city": "Bordeaux", "citycode": "33063",
    "depcode": "33", "population": 267991, "context": "33, Gironde, Nouvelle-Aquitaine"}}]}


def test_une_ville_par_son_nom_donne_sa_commune_son_altitude_et_son_climat(monkeypatch):
    monkeypatch.setattr(lieu, "_demander", lambda adresse, delai_s: BORDEAUX)
    monkeypatch.setattr(lieu, "_altitude", lambda latitude, longitude, delai_s: {"elevations": [9.2]})
    monkeypatch.setattr(lieu, "_inverser", lambda *a: pytest.fail("la commune est déjà connue"))
    trouve = lieu.completer(lieu.geocoder("Bordeaux"))
    assert (trouve.commune, trouve.departement, trouve.population, trouve.altitude_m) == ("Bordeaux", "33", 267991, 9.2)
    fiche = trouve.fiche()
    assert fiche[0] == "commune : Bordeaux (33), 267991 habitants" and fiche[1] == "altitude : 9 m"
    assert fiche[2] == "zone climatique : H2c" and fiche[3].startswith("température extérieure de base : -5 °C")
    assert fiche[4].startswith("terrain proposé : City")


def test_un_point_par_ses_coordonnees_retrouve_sa_commune_par_le_geocodage_inverse(monkeypatch):
    monkeypatch.setattr(lieu, "_inverser", lambda latitude, longitude, delai_s: {"features": [{"properties": {
        "city": "Strasbourg", "citycode": "67482", "context": "67, Bas-Rhin, Grand Est"}}]})
    monkeypatch.setattr(lieu, "_altitude", lambda latitude, longitude, delai_s: {"elevations": [143.0]})
    trouve = lieu.completer(lieu.Lieu(48.5734, 7.7521, "point donné", "coordonnées"))
    assert (trouve.commune, trouve.departement, trouve.altitude_m) == ("Strasbourg", "67", 143.0)
    assert "zone climatique : H1b" in trouve.fiche()


def test_un_service_muet_ou_un_point_hors_de_france_ne_bloque_rien_et_c_est_dit(monkeypatch):
    def en_panne(*_arguments):
        raise OSError("délai dépassé")

    monkeypatch.setattr(lieu, "_inverser", en_panne)
    monkeypatch.setattr(lieu, "_altitude", en_panne)
    muet = lieu.completer(lieu.Lieu(48.0, 2.0, "point", "coordonnées"))
    assert muet.commune is None and muet.altitude_m is None and len(muet.remarques) == 2 and muet.fiche() == []
    monkeypatch.setattr(lieu, "_inverser", lambda *a: {"features": []})
    monkeypatch.setattr(lieu, "_altitude", lambda *a: {"elevations": [-99999.0]})
    en_mer = lieu.completer(lieu.Lieu(40.0, -30.0, "point", "coordonnées"))
    assert any("hors de France" in r for r in en_mer.remarques) and any("couverture" in r for r in en_mer.remarques)


NANTES = {"features": [{"geometry": {"coordinates": [-1.55107, 47.21594]}, "properties": {
    "label": "12 Rue de Strasbourg 44000 Nantes", "score": 0.71, "type": "housenumber", "city": "Nantes",
    "citycode": "44109", "postcode": "44000", "context": "44, Loire-Atlantique, Pays de la Loire"}}]}


def test_une_adresse_trouvee_dans_une_autre_ville_que_celle_demandee_est_signalee(monkeypatch):
    """Mesuré le 17/11/2026 : « 12 rue de la Paix, Strasbourg » rend une rue de Strasbourg... à Nantes."""
    monkeypatch.setattr(lieu, "_demander", lambda adresse, delai_s: NANTES)
    trompe = lieu.geocoder("12 rue de la Paix, Strasbourg")
    assert any(r.startswith("LIEU À VÉRIFIER : l'adresse trouvée est à Nantes") for r in trompe.remarques)
    for juste in ("12 rue de Strasbourg, Nantes", "12 rue de strasbourg NANTES", "12 rue de Strasbourg 44000"):
        assert not any("À VÉRIFIER" in r for r in lieu.geocoder(juste).remarques), juste
    monkeypatch.setattr(lieu, "_demander", lambda adresse, delai_s: BORDEAUX)
    assert not any("À VÉRIFIER" in r for r in lieu.geocoder("bordeaux").remarques)


def test_le_terrain_n_est_pas_pose_d_office_et_se_donne_dans_l_etude(tmp_path):
    fichier = tmp_path / "etude.toml"
    fichier.write_text('maquette = "a.ifc"\n', encoding="utf-8")
    sans = etude.lire(fichier)
    assert sans.terrain is None and sans.le_terrain == "City"
    fichier.write_text('maquette = "a.ifc"\nterrain = "Country"\n', encoding="utf-8")
    assert etude.lire(fichier).le_terrain == "Country"
