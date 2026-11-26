"""La croissance des plantes : un arbre suit la courbe de son essence, une plante grimpante monte le long du mur."""

import pytest

from rayflect import etude, vegetation as veg


def test_un_arbre_plante_a_la_taille_de_la_premiere_classe_d_age_de_sa_source():
    """Tilleul de Bavière à 10 ans d'arbre, l'âge d'une plantation : 5,8 m de haut, couronne de 3,3 m."""
    jeune = veg.Arbre(0, 0, essence="tilleul", age_ans=0)
    assert (jeune.hauteur_m, jeune.diametre_m) == (5.8, 3.3)
    assert jeune.feuillage is veg.ARBRE_CADUC_DENSE


@pytest.mark.parametrize("essence", sorted(veg.ESSENCES))
def test_un_arbre_ne_rapetisse_jamais_et_sa_couronne_tient_sous_sa_hauteur(essence):
    tailles = [veg.Arbre(0, 0, essence=essence, age_ans=age) for age in range(0, 121, 5)]
    for avant, apres in zip(tailles, tailles[1:]):
        # Une seule exception dans les sources : le platane de Bavière, 22,5 m à 70 ans puis 22,2 m à 80 ans.
        # La courbe retenue saute la classe de 70 ans.
        assert apres.hauteur_m >= avant.hauteur_m and apres.diametre_m >= avant.diametre_m
    assert all(0 < a.tronc_m < a.hauteur_m and a.tronc_m <= veg.TRONC_MAX_M for a in tailles)


def test_les_2_courbes_du_tilleul_encadrent_et_copenhague_redonne_les_valeurs_de_son_article():
    """Larsen et Kristoffersen 2002 écrivent : environ 7 m à 20 ans, 19,5 m à 101 ans."""
    lent = veg.ESSENCES["tilleul_lent"]
    assert veg._entre(lent.hauteur_m, 10) == pytest.approx(6.93, abs=0.01)
    assert veg._entre(lent.hauteur_m, 90) == pytest.approx(19.46, abs=0.01)
    for age in (0, 10, 30, 50):
        assert veg.Arbre(0, 0, essence="tilleul_lent", age_ans=age).hauteur_m < veg.Arbre(
            0, 0, essence="tilleul", age_ans=age).hauteur_m


def test_sans_age_l_arbre_d_une_essence_est_adulte_et_au_dela_de_la_courbe_c_est_dit():
    adulte = veg.Arbre(0, 0, essence="robinier")
    assert adulte.hauteur_m == 22.8 and "adulte" in veg.dire(adulte)[0]
    vieux = veg.a_l_age(adulte, 150)
    assert vieux.hauteur_m == 22.8 and any("s'arrête à 90 ans" in ligne for ligne in veg.dire(vieux))
    assert "Rötzer" in veg.dire(vieux)[0]


def test_un_arbre_sans_essence_ne_grandit_pas_et_le_dit():
    with pytest.raises(ValueError, match="essence"):
        veg.a_l_age(veg.Arbre(0, 0), 5)
    with pytest.raises(ValueError, match="essence"):
        veg.Arbre(0, 0, age_ans=5)
    with pytest.raises(ValueError, match="inconnue"):
        veg.Arbre(0, 0, essence="baobab")
    assert veg.dire(veg.Arbre(0, 0)) == []


def test_une_grimpante_monte_a_la_vitesse_de_son_feuillage_jusqu_a_sa_hauteur_maximale():
    assert veg.Grimpante().hauteur_couverte_m is None                   # sans âge : le mur est couvert
    assert veg.Grimpante(age_ans=2).hauteur_couverte_m == 3.0           # vigne vierge : 1,5 m par an
    assert veg.Grimpante(age_ans=40).hauteur_couverte_m == 15.0
    assert veg.Grimpante(feuillage=veg.LIERRE, age_ans=10).hauteur_couverte_m == 7.0
    assert veg.a_l_age(veg.Grimpante(age_ans=2), 6).hauteur_couverte_m == 9.0
    assert "3 m du sol" in veg.dire(veg.Grimpante(age_ans=2))[0]
    with pytest.raises(ValueError, match="pergola"):
        veg.a_l_age(veg.Pergola(), 3)


def test_une_grimpante_jeune_ne_couvre_que_le_bas_du_mur():
    pytest.importorskip("honeybee")
    from honeybee.model import Model
    from honeybee.room import Room

    jeune, couvrante = Model("a", rooms=[Room.from_box("s", 8, 6, 6)]), Model("b", rooms=[Room.from_box("t", 8, 6, 6)])
    veg.poser(jeune, veg.Grimpante(age_ans=2))
    veg.poser(couvrante, veg.Grimpante())
    assert sum(s.area for s in jeune.shades) == pytest.approx(28.0 * 3.0, rel=0.03)
    assert max(s.geometry.max.z for s in jeune.shades) == pytest.approx(3.0, abs=0.01)
    assert sum(s.area for s in couvrante.shades) == pytest.approx(28.0 * 6.0, rel=0.01)


def test_un_scenario_avec_des_annees_donne_un_scenario_par_age(tmp_path):
    fichier = tmp_path / "etude.toml"
    fichier.write_text('''maquette = "a.ifc"
[[scenario]]
nom = "sans"
[[scenario]]
nom = "tilleuls et vigne"
annees = [1, 15]
[[scenario.element]]
type = "arbre"
est_m = 6.0
nord_m = -8.0
essence = "tilleul"
[[scenario.element]]
type = "grimpante"
[[scenario.element]]
type = "casquette"
''', encoding="utf-8")
    lue = etude.lire(fichier)
    assert [s.nom for s in lue.scenarios] == ["sans", "tilleuls et vigne, à 1 an", "tilleuls et vigne, à 15 ans"]
    arbre, vigne, casquette = lue.scenarios[2].elements
    assert arbre.age_ans == 15 and arbre.hauteur_m == 9.85 and vigne.hauteur_couverte_m == 15.0
    assert casquette == lue.scenarios[1].elements[2]
    assert lue.scenarios[1].elements[0].hauteur_m == 6.08


def test_des_annees_sur_un_arbre_sans_essence_sont_refusees_avec_la_raison(tmp_path):
    fichier = tmp_path / "etude.toml"
    fichier.write_text('maquette = "a.ifc"\n[[scenario]]\nnom = "x"\nannees = [5]\n'
                       '[[scenario.element]]\ntype = "arbre"\nest_m = 1.0\nnord_m = 1.0\n', encoding="utf-8")
    with pytest.raises(etude.EtudeInvalide, match="essence"):
        etude.lire(fichier)
