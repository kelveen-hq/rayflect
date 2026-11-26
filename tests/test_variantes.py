"""Les variantes de conception : ce qu'elles changent au modèle, et ce qu'elles disent quand la place manque."""

import pytest

pytest.importorskip("honeybee")
from honeybee.aperture import Aperture  # noqa: E402
from honeybee.model import Model  # noqa: E402
from honeybee.room import Room  # noqa: E402
from ladybug_geometry.geometry3d import Face3D, Point3D  # noqa: E402

from rayflect import etude, variantes  # noqa: E402


def _salle(baies_sud=((1.0, 2.5), (5.0, 6.5))):
    """Une salle de 8 m par 6 m et 3 m de haut, avec des baies de 1,2 m de haut sur son mur sud (y = 0)."""
    piece = Room.from_box("salle", 8, 6, 3)
    sud = next(f for f in piece.faces if f.type.name == "Wall" and abs(f.azimuth - 180.0) < 1.0)
    for k, (gauche, droite) in enumerate(baies_sud):
        sud.add_aperture(Aperture(f"baie_{k}", Face3D(
            [Point3D(gauche, 0, 1.0), Point3D(droite, 0, 1.0), Point3D(droite, 0, 2.2), Point3D(gauche, 0, 2.2)])))
    return Model("essai", rooms=[piece]), sud


def test_une_variante_demande_un_seul_des_2_reglages():
    with pytest.raises(ValueError):
        variantes.Facade()
    with pytest.raises(ValueError):
        variantes.Facade(baies_fois=2.0, part_vitree=0.5)
    with pytest.raises(ValueError):
        variantes.Facade(part_vitree=0.99)
    with pytest.raises(ValueError):
        variantes.Facade(baies_fois=1.5, orientations=("SUD",))


def test_agrandir_garde_les_baies_a_leur_place_et_multiplie_leur_aire():
    modele, sud = _salle()
    centres = sorted(round(b.center.x, 3) for b in sud.apertures)
    dit = variantes.poser(modele, variantes.Facade(orientations=("S",), baies_fois=1.5))
    assert sorted(round(b.center.x, 3) for b in sud.apertures) == centres
    assert sum(b.area for b in sud.apertures) == pytest.approx(2 * 1.5 * 1.2 * 1.5, rel=0.02)
    assert sorted(b.identifier for b in sud.apertures) == ["baie_0", "baie_1"]
    assert len(dit) == 1 and "3.6 m²" in dit[0] and "5.4 m²" in dit[0]
    assert modele.check_all(raise_exception=False) == ""


def test_une_baie_qui_bute_sur_le_plafond_se_rattrape_en_largeur():
    modele, sud = _salle(baies_sud=((3.0, 4.0),))
    variantes.poser(modele, variantes.Facade(baies_fois=4.0))
    baie = sud.apertures[0]
    assert baie.area == pytest.approx(4 * 1.2, rel=0.02)
    assert baie.geometry.max.z <= 3.0 - variantes.MARGE_M + 1e-6 and baie.geometry.min.z >= variantes.MARGE_M - 1e-6
    assert baie.center.x == pytest.approx(3.5, abs=0.01)


def test_des_baies_qui_se_toucheraient_sont_remplacees_par_un_vitrage_de_meme_aire_et_c_est_dit():
    modele, sud = _salle(baies_sud=((1.0, 3.5), (4.0, 6.5)))
    dit = variantes.poser(modele, variantes.Facade(baies_fois=2.0))
    assert sum(b.area for b in sud.apertures) == pytest.approx(2 * 2.5 * 1.2 * 2.0, rel=0.02)
    assert any("remplacées par un vitrage de même aire" in ligne for ligne in dit)


def test_une_aire_impossible_est_plafonnee_et_c_est_dit():
    modele, sud = _salle()
    dit = variantes.poser(modele, variantes.Facade(baies_fois=20.0))
    assert sud.aperture_ratio == pytest.approx(variantes.PART_VITREE_MAX, rel=0.02)
    assert any("plafonné" in ligne for ligne in dit)


def test_la_part_vitree_remplace_les_baies_du_cote_demande_seulement():
    modele, sud = _salle()
    variantes.poser(modele, variantes.Facade(orientations=("N",), part_vitree=0.4))
    nord = next(f for f in modele.rooms[0].faces if f.type.name == "Wall" and f.azimuth < 1.0)
    assert nord.aperture_ratio == pytest.approx(0.4, rel=0.02)
    assert len(sud.apertures) == 2
    assert variantes.vitrage_par_secteur(modele) == {"N": pytest.approx(9.6, rel=0.02), "S": pytest.approx(3.6)}
    variantes.poser(modele, variantes.Facade(orientations=("S",), part_vitree=0.0))
    assert not sud.apertures


def test_une_variante_sur_un_cote_sans_mur_le_dit():
    modele, _sud = _salle()
    assert "sans effet" in variantes.poser(modele, variantes.Facade(orientations=("SE",), part_vitree=0.5))[0]


def _ecrire(tmp_path, texte):
    fichier = tmp_path / "etude.toml"
    fichier.write_text(texte, encoding="utf-8")
    return fichier


def test_le_fichier_d_etude_lit_une_variante_de_facade_et_des_parois_par_scenario(tmp_path):
    lue = etude.lire(_ecrire(tmp_path, '''maquette = "a.ifc"
[parois]
vitrage = "double"
[[scenario]]
nom = "sud en bandeau, triple vitrage"
[scenario.parois]
vitrage = "triple"
[[scenario.element]]
type = "facade"
orientations = ["S"]
part_vitree = 0.6
[[scenario]]
nom = "triple vitrage seul"
[scenario.parois]
vitrage = "triple"
[[scenario]]
nom = "sans"
'''))
    assert [s.nom for s in lue.scenarios] == ["sans", "sud en bandeau, triple vitrage", "triple vitrage seul"]
    assert lue.scenarios[0].est_la_reference and not lue.scenarios[2].est_la_reference
    assert lue.scenarios[1].elements == [variantes.Facade(orientations=("S",), part_vitree=0.6)]
    assert lue.scenarios[2].parois == {"vitrage": "triple"} and lue.parois.vitrage == "double"


@pytest.mark.parametrize("fiche, attendu", [
    ('[scenario.parois]\nvitrage = "quadruple"\n', "vitrage inconnu"),
    ('[scenario.parois]\nepaisseur = 3\n', "[scenario.parois]"),
    ('couleur = "rouge"\n', "clés inconnues : couleur"),
    ('[[scenario.element]]\ntype = "facade"\n', "baies_fois ou part_vitree"),
    ('annees = [1, 5]\n[[scenario.element]]\ntype = "casquette"\n', "qui porte une plante"),
])
def test_un_scenario_mal_ecrit_est_refuse_avec_la_raison(tmp_path, fiche, attendu):
    with pytest.raises(etude.EtudeInvalide) as refus:
        etude.lire(_ecrire(tmp_path, 'maquette = "a.ifc"\n[[scenario]]\nnom = "x"\n' + fiche))
    assert attendu in str(refus.value)
