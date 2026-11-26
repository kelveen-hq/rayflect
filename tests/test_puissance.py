"""La puissance à installer : la température de base, la séparation de l'année et du jour de base, les pointes."""

from types import SimpleNamespace

import pytest

from rayflect import etude, puissance


def _serie(valeurs):
    return SimpleNamespace(values=list(valeurs))


def _meteo(temperatures=None):
    temperatures = temperatures or [10.0] * 8760
    return SimpleNamespace(dry_bulb_temperature=SimpleNamespace(values=temperatures))


class _Resultats:
    def __init__(self, series):
        self.series = series

    def data_collections_by_output_name(self, nom):
        return self.series.get(nom, [])


def test_la_temperature_de_base_donnee_passe_avant_celle_de_la_meteo():
    base = puissance.base_du_lieu(_meteo(), -7)
    assert base.temperature_c == -7.0 and base.origine == "donnée" and base.a_demander is None


def test_sans_elle_la_temperature_de_base_vient_de_la_meteo_et_elle_est_demandee():
    """Dépassée 99,6 % des heures : la 36e heure la plus froide d'une année de 8 760 heures."""
    temperatures = [float(k) / 10.0 for k in range(8760)]
    base = puissance.base_du_lieu(_meteo(list(reversed(temperatures))))
    assert base.temperature_c == 3.5
    assert "année type" in base.origine and "température extérieure de base du lieu" in base.a_demander


def test_l_annee_et_le_jour_de_base_ne_se_melangent_pas():
    annee = puissance.Annee(_Resultats({"x": [_serie([1.0] * 8760), _serie([5.0] * 24), _serie([2.0] * 8760)]}))
    assert [len(s.values) for s in annee.data_collections_by_output_name("x")] == [8760, 8760]
    assert [len(s.values) for s in annee.du_jour_de_base("x")] == [24]
    assert annee.data_collections_by_output_name("absent") == []


def test_la_pointe_est_celle_du_batiment_entier_a_la_meme_heure():
    """2 zones dont les pointes ne tombent pas à la même heure : la pointe du bâtiment n'est pas leur somme."""
    zone_a, zone_b = [0.0] * 8760, [0.0] * 8760
    zone_a[100], zone_b[100] = 3.0, 1.0
    zone_a[5000], zone_b[5000] = 1.0, 3.5
    zone_b[200] = 3.9
    temperatures = [10.0] * 8760
    temperatures[5000] = 31.5
    lu = puissance.lire(
        puissance.Annee(_Resultats({"chaud": [_serie(zone_a), _serie(zone_b), _serie([4.0] * 24), _serie([2.5] * 24)]})),
        _meteo(temperatures), puissance.Base(-5.0, "donnée"), "chaud", "froid", 200.0)
    assert lu["pointe_de_chauffage"] == {"kw": 4.5, "quand": "28/7 à 8 h", "dehors_c": 31.5}
    assert lu["chauffage_au_jour_de_base_kw"] == 6.5 and lu["chauffage_au_jour_de_base_w_m2"] == 32
    assert lu["temperature_de_base_c"] == -5.0 and lu["pointe_de_froid"] is None


def test_sans_jour_de_base_la_puissance_de_base_est_absente_pas_nulle():
    lu = puissance.lire(puissance.Annee(_Resultats({"chaud": [_serie([1.0] * 8760)]})), _meteo(), None,
                        "chaud", "froid", 100.0)
    assert lu["chauffage_au_jour_de_base_kw"] is None and lu["chauffage_au_jour_de_base_w_m2"] is None


def test_le_tableau_ne_montre_le_froid_que_s_il_y_en_a():
    sans = {"a": {"chauffage_au_jour_de_base_kw": 20.0, "chauffage_au_jour_de_base_w_m2": 50,
                  "pointe_de_chauffage": {"kw": 14.0, "quand": "28/12 à 8 h", "dehors_c": -2.0},
                  "pointe_de_froid": None}}
    rendu = "\n".join(puissance.tableau(sans, ["a"], {"a": "a"}))
    assert "chauffage au jour de base, kW" in rendu and "28/12 à 8 h" in rendu and "froid" not in rendu
    sans["a"]["pointe_de_froid"] = {"kw": 15.1, "quand": "31/7 à 14 h", "dehors_c": 32.8}
    rendu = "\n".join(puissance.tableau(sans, ["a"], {"a": "a"}))
    assert "pointe de froid, kW" in rendu and "32.8" in rendu
    assert any("pas de climatisation" in ligne for ligne in puissance.expliquer(puissance.Base(-5.0, "donnée"), False))
    assert not any("pas de climatisation" in ligne for ligne in puissance.expliquer(puissance.Base(-5.0, "donnée"), True))


def _ecrire(tmp_path, texte):
    fichier = tmp_path / "etude.toml"
    fichier.write_text(texte, encoding="utf-8")
    return fichier


def test_la_consigne_ressentie_vaut_au_jour_de_base_et_le_reste_de_l_annee_sur_demande():
    pytest.importorskip("honeybee_energy")
    from honeybee.model import Model
    from honeybee.room import Room

    from rayflect import hypotheses as hyp

    modele = Model("m", rooms=[Room.from_box("salle", 8, 6, 3), Room.from_box("reserve", 4, 4, 3)])
    hyp.appliquer(modele, hyp.Hypotheses())
    modele.rooms[1].properties.energy.hvac = None           # une pièce non chauffée n'a pas de thermostat
    au_jour_de_base = puissance.consigne_ressentie(modele)
    assert "For: WinterDesignDay, Until: 24:00, 0.5" in au_jour_de_base
    assert "For: AllOtherDays, Until: 24:00, 0.0" in au_jour_de_base
    assert au_jour_de_base.count("ZoneControl:Thermostat:OperativeTemperature") == 1
    assert "salle Thermostat" in au_jour_de_base and "reserve" not in au_jour_de_base
    assert "For: AllOtherDays, Until: 24:00, 0.5" in puissance.consigne_ressentie(modele, toute_l_annee=True)


def test_le_fichier_d_etude_lit_la_consigne_et_refuse_celle_qu_il_ne_connait_pas(tmp_path):
    assert etude.lire(_ecrire(tmp_path, 'maquette = "a.ifc"\n')).consigne == "air"
    assert etude.lire(_ecrire(tmp_path, 'maquette = "a.ifc"\nconsigne = "ressentie"\n')).consigne == "ressentie"
    with pytest.raises(etude.EtudeInvalide, match="consigne"):
        etude.lire(_ecrire(tmp_path, 'maquette = "a.ifc"\nconsigne = "moyenne"\n'))
    lignes = puissance.expliquer(puissance.Base(-5.0, "donnée"), True, "ressentie")
    assert any("comme au jour de base" in ligne for ligne in lignes)


def test_le_fichier_d_etude_lit_la_temperature_de_base(tmp_path):
    assert etude.lire(_ecrire(tmp_path, 'maquette = "a.ifc"\n')).temperature_de_base_c is None
    lue = etude.lire(_ecrire(tmp_path, 'maquette = "a.ifc"\n[dimensionnement]\ntemperature_de_base_c = -5\n'))
    assert lue.temperature_de_base_c == -5


@pytest.mark.parametrize("table, attendu", [
    ("temperature_de_base_c = 40\n", "n'est pas une température"),
    ('temperature_de_base_c = "froid"\n', "n'est pas une température"),
    ("temperature = -5\n", "clés inconnues : temperature"),
])
def test_un_dimensionnement_mal_ecrit_est_refuse_avec_la_raison(tmp_path, table, attendu):
    with pytest.raises(etude.EtudeInvalide) as refus:
        etude.lire(_ecrire(tmp_path, 'maquette = "a.ifc"\n[dimensionnement]\n' + table))
    assert attendu in str(refus.value)
