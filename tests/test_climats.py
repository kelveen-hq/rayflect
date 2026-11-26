"""Les climats autres que l'année type, sans réseau : les réponses d'Open-Meteo sont posées dans le cache à la main."""

import datetime
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "verification"))
import reference  # noqa: E402

from rayflect import etude  # noqa: E402
from rayflect.io import climats, meteo  # noqa: E402

try:
    DENVER = Path(reference.meteo_de_denver())
except reference.ReferenceIndisponible as erreur:
    pytest.skip(f"météo de référence indisponible : {erreur}", allow_module_level=True)

LAT, LON = 39.74, -104.99


def _fuseau() -> float:
    return climats._fuseau(DENVER.read_text(encoding="utf-8", errors="replace").splitlines())


def _archive(dossier: Path, annee: int, temperature=lambda t: 20.0) -> None:
    """Une réponse d'ERA5 en temps universel, du 31 décembre de la veille au 1er janvier du lendemain."""
    debut = datetime.datetime(annee - 1, 12, 31)
    heures = int((datetime.datetime(annee + 1, 1, 2) - debut).total_seconds() // 3600)
    temps = [debut + datetime.timedelta(hours=k) for k in range(heures)]
    horaire = {"time": [t.strftime("%Y-%m-%dT%H:00") for t in temps]}
    for nom in climats.HORAIRES:
        horaire[nom] = [50.0] * heures
    horaire["temperature_2m"] = [temperature(t) for t in temps]
    horaire["dew_point_2m"] = [5.0] * heures
    horaire["shortwave_radiation"] = [300.0 if 10 <= t.hour <= 22 else 0.0 for t in temps]
    (dossier / f"era5s_{LAT:.3f}_{LON:.3f}_{annee}.json").write_text(
        json.dumps({"latitude": LAT, "longitude": LON, "hourly": horaire}), encoding="utf-8")


def test_une_annee_reelle_prend_l_heure_locale_de_l_annee_type(tmp_path):
    # La température vaut l'heure universelle du jour : on retrouve le décalage du fuseau de l'année type.
    _archive(tmp_path, 2021, temperature=lambda t: float(t.hour))
    climat = climats.annee_reelle(LAT, LON, 2021, DENVER, tmp_path)
    lignes = climat.chemin.read_text(encoding="utf-8").splitlines()[meteo.LIGNES_D_EN_TETE:]
    assert len(lignes) == 8760 and meteo.controler(climat.chemin).bon
    premiere = lignes[0].split(",")
    # La 1re ligne finit à 1 h locale ; en temps universel : 1 h − fuseau.
    assert premiere[0] == "2021" and float(premiere[climats.C_TEMPERATURE]) == (1 - _fuseau()) % 24
    assert any("année réelle 2021" in r for r in climat.remarques)


def test_une_annee_bissextile_perd_son_29_fevrier(tmp_path):
    marque = 33.0
    _archive(tmp_path, 2020, temperature=lambda t: marque if (t.month, t.day) == (2, 29) else 10.0)
    climat = climats.annee_reelle(LAT, LON, 2020, DENVER, tmp_path)
    lignes = climat.chemin.read_text(encoding="utf-8").splitlines()[meteo.LIGNES_D_EN_TETE:]
    assert len(lignes) == 8760
    # Le 29 février en heure locale est retiré ; il n'en reste que les instants que le fuseau fait tomber le 29 en
    # temps universel, la veille au soir : |fuseau| + 1 au plus (minuit compris).
    restes = sum(1 for ligne in lignes if float(ligne.split(",")[climats.C_TEMPERATURE]) == marque)
    assert restes <= abs(_fuseau()) + 1


def test_une_annee_hors_d_era5_est_refusee(tmp_path):
    with pytest.raises(climats.ClimatIndisponible, match="ERA5 couvre"):
        climats.annee_reelle(LAT, LON, 1900, DENVER, tmp_path)


def test_l_ete_le_plus_chaud(tmp_path):
    jusqu_a = datetime.date.today().year - 1
    jours = [datetime.date(2000, 1, 1) + datetime.timedelta(days=k)
             for k in range((datetime.date(jusqu_a, 12, 31) - datetime.date(2000, 1, 1)).days + 1)]
    temperatures = [25.0 if j.year == 2003 and j.month in (6, 7, 8) else 20.0 for j in jours]
    (tmp_path / f"era5s_etes_{LAT:.3f}_{LON:.3f}_2000_{jusqu_a}.json").write_text(json.dumps(
        {"daily": {"time": [j.isoformat() for j in jours], "temperature_2m_mean": temperatures}}), encoding="utf-8")
    moyennes = climats.etes(LAT, LON, tmp_path)
    assert max(moyennes, key=moyennes.get) == 2003 and moyennes[2003] == pytest.approx(25.0)
    _archive(tmp_path, 2003)
    climat = climats.ete_le_plus_chaud(LAT, LON, DENVER, tmp_path)
    assert climat.nom == "l'été le plus chaud (2003)"
    assert climat.remarques[0].startswith("l'été le plus chaud depuis 2000 : 2003 (25.0 °C)")


def test_la_deformation_de_belcher():
    # Un mois de janvier en dents de scie : 0 la nuit, 10 le jour ; moyenne 5, amplitude 10.
    jour = [0.0] * 12 + [10.0] * 12
    annee = jour * 365
    decale = climats.deformer(annee, [2.0] * 12, [2.0] * 12, [2.0] * 12)
    assert decale[:24] == [2.0] * 12 + [12.0] * 12                   # même écart partout : un simple décalage
    etire = climats.deformer(annee, [2.0] * 12, [3.0] * 12, [1.0] * 12)
    # α = (3 − 1) / 10 = 0,2 : le jour monte de 3, la nuit de 1, la moyenne de 2.
    assert etire[0] == pytest.approx(1.0) and etire[12] == pytest.approx(13.0)
    assert sum(etire[:24]) / 24 == pytest.approx(7.0)


def _cmip6(dossier: Path, base, ecart_ete: float, soleil_ete: float = 1.0, humidite_ete: float = 0.0) -> None:
    """Les réponses de l'API climatique pour les années de départ et pour l'horizon : 2 modèles complets, un sans
    rien, et un 4e sans soleil."""
    for annees, futur in ((base, False), (climats.FUTUR, True)):
        jours = [datetime.date(annees[0], 1, 1) + datetime.timedelta(days=k)
                 for k in range((datetime.date(annees[1], 12, 31) - datetime.date(annees[0], 1, 1)).days + 1)]
        ete = [futur and j.month in (6, 7, 8) for j in jours]
        quotidien = {"time": [j.isoformat() for j in jours]}
        for modele in climats.MODELES[:2] + climats.MODELES[3:4]:
            for grandeur in ("mean", "max", "min"):
                quotidien[f"temperature_2m_{grandeur}_{modele}"] = [15.0 + (ecart_ete if e else 0.0) for e in ete]
            quotidien[f"relative_humidity_2m_mean_{modele}"] = [70.0 + (humidite_ete if e else 0.0) for e in ete]
            quotidien[f"wind_speed_10m_mean_{modele}"] = [3.0] * len(jours)
            if modele != climats.MODELES[3]:
                quotidien[f"shortwave_radiation_sum_{modele}"] = [20.0 * (soleil_ete if e else 1.0) for e in ete]
        quotidien[f"temperature_2m_mean_{climats.MODELES[2]}"] = [None] * len(jours)     # un modèle sans données
        (dossier / f"cmip6_{LAT:.3f}_{LON:.3f}_{annees[0]}_{annees[1]}.json").write_text(
            json.dumps({"daily": quotidien}), encoding="utf-8")


def test_le_climat_futur_decale_l_ete_des_modeles(tmp_path):
    _en_tete, donnees = climats._type(DENVER)
    annees = sorted({int(d[climats.C_ANNEE]) for d in donnees})
    base = (annees[0], annees[-1])
    _cmip6(tmp_path, base, 2.0, soleil_ete=1.1, humidite_ete=-5.0)
    ecarts = climats.ecarts_des_modeles(LAT, LON, base, tmp_path)
    assert set(ecarts) == set(climats.MODELES[:2] + climats.MODELES[3:4])     # le modèle vide est écarté
    assert "soleil" not in ecarts[climats.MODELES[3]]                       # celui-ci ne donne pas le soleil
    e = climats.ensemble(ecarts)
    assert e["soleil"][6] == pytest.approx(1.1) and e["soleil_modeles"][6] == 2   # la moyenne de ceux qui le donnent
    assert e["humidite"][6] == pytest.approx(-5.0) and e["vent"][6] == pytest.approx(1.0)
    climat = climats.futur(LAT, LON, DENVER, tmp_path)
    lignes = [ligne.split(",") for ligne in climat.chemin.read_text(encoding="utf-8").splitlines()[meteo.LIGNES_D_EN_TETE:]]
    juillet = slice(climats.JOURS_AVANT[6] * 24, climats.JOURS_AVANT[7] * 24)
    janvier = slice(0, 31 * 24)

    def colonne(source, c, tranche):
        return [float(d[c]) for d in source[tranche]]

    assert sum(colonne(lignes, climats.C_TEMPERATURE, juillet)) / 744 - \
        sum(colonne(donnees, climats.C_TEMPERATURE, juillet)) / 744 == pytest.approx(2.0, abs=0.06)
    assert colonne(lignes, climats.C_TEMPERATURE, janvier) == pytest.approx(colonne(donnees, climats.C_TEMPERATURE, janvier),
                                                                            abs=0.06)
    assert sum(colonne(lignes, climats.C_GLOBAL, juillet)) == pytest.approx(
        1.1 * sum(colonne(donnees, climats.C_GLOBAL, juillet)), rel=0.01)
    assert sum(colonne(lignes, climats.C_HUMIDITE, juillet)) / 744 < sum(colonne(donnees, climats.C_HUMIDITE, juillet)) / 744 - 4
    assert meteo.controler(climat.chemin).bon
    assert any("+2.0 °C en moyenne des modèles" in r and "soleil +10 %" in r for r in climat.remarques)


def test_le_futur_chaud_decale_l_ete_le_plus_chaud(tmp_path):
    jusqu_a = datetime.date.today().year - 1
    jours = [datetime.date(2000, 1, 1) + datetime.timedelta(days=k)
             for k in range((datetime.date(jusqu_a, 12, 31) - datetime.date(2000, 1, 1)).days + 1)]
    (tmp_path / f"era5s_etes_{LAT:.3f}_{LON:.3f}_2000_{jusqu_a}.json").write_text(json.dumps(
        {"daily": {"time": [j.isoformat() for j in jours],
                   "temperature_2m_mean": [25.0 if j.year == 2003 and j.month in (6, 7, 8) else 20.0 for j in jours]}}),
        encoding="utf-8")
    _archive(tmp_path, 2003)
    _cmip6(tmp_path, (2003 - climats.FENETRE_AUTOUR, 2003 + climats.FENETRE_AUTOUR), 1.5)
    climat = climats.futur_chaud(LAT, LON, DENVER, tmp_path)
    assert climat.nom == f"l'été 2003 en {climats.FUTUR[0]}-{climats.FUTUR[1]}"
    lignes = [ligne.split(",") for ligne in climat.chemin.read_text(encoding="utf-8").splitlines()[meteo.LIGNES_D_EN_TETE:]]
    juillet = slice(climats.JOURS_AVANT[6] * 24, climats.JOURS_AVANT[7] * 24)
    assert sum(float(d[climats.C_TEMPERATURE]) for d in lignes[juillet]) / 744 == pytest.approx(21.5, abs=0.06)
    assert lignes[0][climats.C_ANNEE] == "2003" and meteo.controler(climat.chemin).bon


@pytest.mark.parametrize("valeur, bon", [("type", True), ("futur", True), ("ete_le_plus_chaud", True), (2003, True),
                                         ("2022", True), ("chaud", False), (True, False), (20.5, False)])
def test_les_noms_de_climat(valeur, bon):
    assert climats.nom_valide(valeur) is bon


def test_l_etude_lit_son_climat(tmp_path):
    base = 'usage = "bureau"\n[batiment]\nlongueur_m = 20.0\nlargeur_m = 10.0\n[lieu]\nlatitude = 44.8\nlongitude = -0.6\n'
    fichier = tmp_path / "etude.toml"
    fichier.write_text(base + 'climat = ["type", 2003, "futur"]\n', encoding="utf-8")
    assert etude.lire(fichier).climat == ["type", 2003, "futur"]
    fichier.write_text(base + 'climat = "chaud"\n', encoding="utf-8")
    with pytest.raises(etude.EtudeInvalide, match="climat = 'chaud'"):
        etude.lire(fichier)
    fichier.write_text(base, encoding="utf-8")
    assert etude.lire(fichier).climat == "type"


def test_la_comparaison_des_climats():
    def bilan(nom: str, chauffage: int, dh: int) -> dict:
        return {"scenarios": ["sans"], "meteo": f"{nom}.epw", "meteo_a_savoir": [f"climat : {nom}"],
                "chauffage_kwh": {"sans": chauffage}, "froid_kwh": {},
                "heures_au_dessus_de_26": {"0 | rdc | entier": {"sans": 300}},
                "confort_d_ete": {"pieces": {"0 | rdc | entier": {"sans": {"dh": dh}}}}}
    texte = etude.comparer_les_climats({"type": {**bilan("x", 1000, 400), "meteo_a_savoir": []},
                                        "futur": bilan("climat 2040-2049", 900, 800)})
    assert "année type" in texte and "climat 2040-2049" in texte
    assert "sans" in texte and "1000" in texte and "800" in texte
