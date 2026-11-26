"""Le mur végétalisé, sans calcul : ce qu'il pose sur le modèle et dans le fichier d'EnergyPlus."""

import pytest

pytest.importorskip("honeybee_energy")
from honeybee.model import Model  # noqa: E402
from honeybee.room import Room  # noqa: E402

from rayflect import carbone, etude, vegetation  # noqa: E402


class _Serie:
    def __init__(self, valeur):
        self.values = [valeur] * 8760


class _Epw:
    """Une année toute pareille, aux grandeurs que lit rayflect.evaporation."""
    from ladybug.location import Location
    location = Location(latitude=44.8, longitude=-0.6, time_zone=1)
    dry_bulb_temperature, dew_point_temperature = _Serie(10.0), _Serie(5.0)
    atmospheric_station_pressure, wind_speed = _Serie(101300.0), _Serie(2.0)
    direct_normal_radiation, diffuse_horizontal_radiation, global_horizontal_radiation = _Serie(0.0), _Serie(50.0), _Serie(100.0)


def _bureau():
    piece = Room.from_box("bureau", 8, 6, 3)
    sud = next(f for f in piece.faces if abs(f.normal.y + 1) < 1e-6)
    sud.apertures_by_ratio(0.3)
    return Model("essai", rooms=[piece]), piece, sud


def test_les_valeurs_viennent_des_mesures():
    assert vegetation.MurVegetal().resistance == pytest.approx(0.155)
    assert vegetation.MurVegetal(lame_d_air="fermee").resistance == pytest.approx(0.35)
    assert vegetation.MurVegetal(resistance_m2k_w=0.52).resistance == 0.52
    for faux in ({"lame_d_air": "ouverte"}, {"resistance_m2k_w": 0.0}, {"ecart_au_mur_m": 1.0}):
        with pytest.raises(ValueError):
            vegetation.MurVegetal(**faux)


def test_le_mur_plein_est_couvert_et_les_baies_restent():
    modele, piece, sud = _bureau()
    dits = vegetation.poser_le_mur_vegetal(modele, vegetation.MurVegetal(orientations=("S",)))
    plein = sud.punched_geometry.area
    assert dits[0].startswith(f"mur végétalisé : {plein:.0f} m² de murs pleins couverts (S)")
    ombres = [o for o in modele.shades if "_mur_vegetal_" in o.identifier]
    assert sum(o.area for o in ombres) == pytest.approx(plein, rel=1e-3)        # le plein, pas les baies
    assert all(o.center.y == pytest.approx(-0.05, abs=1e-6) for o in ombres)    # à 5 cm devant le mur
    construction = sud.properties.energy.construction
    assert construction.materials[0].r_value == pytest.approx(0.155)            # la lame de modules, dehors
    assert sud.user_data["mur_vegetal"] is True
    nord = next(f for f in piece.faces if abs(f.normal.y - 1) < 1e-6)
    assert not (nord.user_data or {}).get("mur_vegetal")                        # une autre façade n'est pas touchée


def test_le_mur_couvert_voit_le_dos_des_modules(tmp_path):
    modele, _piece, sud = _bureau()
    assert vegetation.texte_des_murs_vegetaux(modele, _Epw, tmp_path) == ""      # rien sans mur couvert
    vegetation.poser_le_mur_vegetal(modele, vegetation.MurVegetal(orientations=("S",)))
    texte = vegetation.texte_des_murs_vegetaux(modele, _Epw, tmp_path)
    assert "rayflect_air_dehors_0, , modules_0.csv, 1, 0, 8760" in texte        # le nom seul, sans chemin accentué
    assert f"modules_devant_0, {sud.identifier}, , dos_des_modules_0, , ;" in texte
    assert "dos_des_modules_0, 0.0, , 0.0, , dos_des_modules, 1.0, rayflect_air_dehors_0;" in texte
    temperatures = [float(t) for t in (tmp_path / "modules_0.csv").read_text(encoding="ascii").split()]
    assert len(temperatures) == 8760 and all(t > 10.0 for t in temperatures[:24])  # le soleil diffus les chauffe
    assert "eau évaporée" in vegetation.dire_l_eau_des_murs(modele, _Epw)[0]


def test_le_mur_vegetal_s_ecrit_dans_une_etude_et_dit_son_carbone():
    assert isinstance(etude.element({"type": "mur_vegetal", "orientations": ["S", "O"]}), vegetation.MurVegetal)
    rendu = carbone.chiffrer([carbone.Mesure("mur_vegetal", 48.0, "m² de protection")], carbone.Reglages())
    assert rendu["kgco2e"] == 0 and rendu["non_chiffres"][0].startswith("mur_vegetal : les modules")
