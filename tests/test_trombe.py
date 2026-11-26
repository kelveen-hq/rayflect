"""Le mur Trombe : la fiche, le mur qu'il équipe, et ce qu'il écrit pour EnergyPlus. Sans calcul."""

import pytest

pytest.importorskip("honeybee_energy")
from honeybee.model import Model  # noqa: E402
from honeybee.room import Room  # noqa: E402
from honeybee_energy.simulation.parameter import SimulationParameter  # noqa: E402

from rayflect import etude, hypotheses as hyp, trombe  # noqa: E402


@pytest.fixture()
def salle():
    """Une pièce de 8 m sur 6 et 3 m de haut, des baies au sud (allège de 1 m) et au nord."""
    piece = Room.from_box("salle", 8, 6, 3)
    piece.faces[1].apertures_by_ratio_rectangle(0.3, 1.5, 1.0, 2.0)     # nord
    piece.faces[3].apertures_by_ratio_rectangle(0.3, 1.5, 1.0, 2.0)     # sud
    modele = Model("essai", rooms=[piece])
    hyp.appliquer(modele, hyp.Hypotheses())
    return modele


def _contexte():
    return {"reglages": SimulationParameter(), "scenario": "essai"}


def test_une_fiche_impossible_est_refusee():
    for faux in (dict(vitrage="triple"), dict(hauteur_m=0.1), dict(epaisseur_m=1.0), dict(lame_m=0.0),
                 dict(absorption=1.2), dict(tablette_m=-0.1), dict(cadre_m=0.0), dict(ouverture_d_ete_c=5.0),
                 dict(niveaux=(-1,))):
        with pytest.raises(ValueError):
            trombe.MurTrombe(**faux)


def test_l_allege_du_sud_devient_le_mur_et_le_reste_du_mur_commence_au_dessus(salle):
    contexte = _contexte()
    sud = salle.rooms[0].faces[3]
    texte = trombe.poser(salle, trombe.MurTrombe(), contexte)
    assert contexte["reglages"].shadow_calculation.solar_distribution == trombe.SOLEIL_SUIVI_DEDANS
    # Le modèle garde son mur entier : la pièce reste fermée, son volume ne bouge pas.
    assert sud.geometry.min.z == 0.0 and salle.rooms[0].volume == pytest.approx(8 * 6 * 3)
    (pose,) = contexte["trombe"]["essai"]
    assert pose["aire_m2"] == pytest.approx(8 * 0.85) and pose["face"] == "trombe_0_cote_piece"
    assert (pose["mur"], pose["bas"], pose["haut"]) == (sud.identifier, 0.0, pytest.approx(0.85))
    # Une zone de lame réglée sur la convection des murs Trombe, 2 faces de mur qui se répondent, 1 vitre.
    assert "trombe_0_lame, , , , , , 1, 0.850, 1.0200, 1.2000, TrombeWall, , No;" in texte
    assert "trombe_0_cote_piece, Wall, trombe_mur_cote_piece, salle, , Surface, trombe_0_cote_lame" in texte
    assert "trombe_0_cote_lame, Wall, trombe_mur_cote_lame, trombe_0_lame, , Surface, trombe_0_cote_piece" in texte
    assert texte.count("FenestrationSurface:Detailed") == 1 and "trombe_0_vitre, Window, vitrage," in texte
    assert "Shading:Zone:Detailed" not in texte and "ZoneVentilation" not in texte
    assert any("1 allège, 6.8 m²" in ligne for ligne in contexte["a_dire"])


def test_c_est_dans_le_fichier_que_le_mur_d_origine_est_raccourci(salle):
    contexte = _contexte()
    trombe.poser(salle, trombe.MurTrombe(), contexte)
    avant = salle.to.idf(salle)
    apres = trombe.retoucher(avant, trombe.MurTrombe(), contexte)
    sud = salle.rooms[0].faces[3].identifier

    def sommets(texte, nom):
        bloc = texte.split(f" {nom},")[1].split(";")[0]
        return [tuple(float(v) for v in ligne.strip(" ,").split(",")) for ligne in bloc.splitlines()
                if ligne.count(",") >= 2 and "!" not in ligne]

    assert sorted(z for _x, _y, z in sommets(avant, sud)) == [0.0, 0.0, 3.0, 3.0]
    assert sorted(z for _x, _y, z in sommets(apres, sud)) == [0.85, 0.85, 3.0, 3.0]
    # Rien d'autre ne bouge : ni les autres murs, ni le reste du fichier.
    nord = salle.rooms[0].faces[1].identifier
    assert sommets(apres, nord) == sommets(avant, nord) and len(apres) == len(avant)
    with pytest.raises(ValueError, match="n'est pas dans le fichier"):
        trombe.retoucher("Version, 25.2;", trombe.MurTrombe(), contexte)


def test_la_piece_garde_ses_fuites_d_air(salle):
    piece = salle.rooms[0]
    avant = piece.properties.energy.infiltration.flow_per_exterior_area * piece.exposed_area
    trombe.poser(salle, trombe.MurTrombe(), _contexte())
    apres = piece.properties.energy.infiltration.flow_per_exterior_area * (piece.exposed_area - 8 * 0.85)
    assert apres == pytest.approx(avant)


def test_un_mur_sans_fenetre_garde_un_reste_au_dessus(salle):
    contexte = _contexte()
    trombe.poser(salle, trombe.MurTrombe(orientations=("E",), hauteur_m=6.0), contexte)
    (pose,) = contexte["trombe"]["essai"]
    assert pose["haut"] == pytest.approx(3.0 - trombe.RESTE_DE_MUR_M)


def test_avec_des_voisins_le_soleil_entre_sans_ramener_les_reflets():
    reglages = SimulationParameter()
    reglages.shadow_calculation.solar_distribution = "FullExterior"
    trombe.suivre_le_soleil_dedans(reglages)
    assert reglages.shadow_calculation.solar_distribution == "FullInteriorAndExterior"


def test_la_vitre_est_devant_le_mur_cote_dehors(salle):
    texte = trombe.poser(salle, trombe.MurTrombe(lame_m=0.2, cadre_m=0.05), _contexte())
    vitre = texte.split("trombe_0_vitre, Window")[1].split(";")[0]
    # La vitre est dans le plan y = -0,2, en retrait de 5 cm du bord de son mur porteur, coin haut gauche d'abord.
    assert ("0.0500, -0.2000, 0.8000,\n  0.0500, -0.2000, 0.0500,\n  7.9500, -0.2000, 0.0500,\n  "
            "7.9500, -0.2000, 0.8000") in vitre
    devant = texte.split("trombe_0_devant, Wall")[1].split(";")[0]
    # Le mur sud est en y = 0, le dehors vers les y négatifs : la vitre est à y = -0,2 ; vue du dehors, elle part
    # du haut à gauche (l'ouest), descend, puis va à droite.
    assert ("0.0000, -0.2000, 0.8500,\n  0.0000, -0.2000, 0.0000,\n  8.0000, -0.2000, 0.0000,\n  "
            "8.0000, -0.2000, 0.8500") in devant


def test_une_baie_qui_descend_bas_reduit_le_mur_ou_l_ecarte(salle):
    contexte = _contexte()
    trombe.poser(salle, trombe.MurTrombe(hauteur_m=2.0), contexte)
    assert contexte["trombe"]["essai"][0]["aire_m2"] == pytest.approx(8 * 0.95)      # 1 m d'allège, moins la marge
    porte_fenetre = Room.from_box("sejour", 8, 6, 3)
    porte_fenetre.faces[3].apertures_by_ratio_rectangle(0.5, 2.4, 0.1, 2.0)
    modele = Model("essai", rooms=[porte_fenetre])
    hyp.appliquer(modele, hyp.Hypotheses())
    with pytest.raises(ValueError, match="aucun mur droit"):
        trombe.poser(modele, trombe.MurTrombe(), _contexte())


def test_la_tablette_l_ouverture_d_ete_et_le_verre_simple_s_ecrivent(salle):
    texte = trombe.poser(salle, trombe.MurTrombe(tablette_m=0.4, ouverture_d_ete_c=24.0, vitrage="simple"), _contexte())
    assert "trombe_0_tablette, trombe_0_devant" in texte and "trombe_0_vitre, Window, trombe_vitre_simple," in texte
    assert "trombe_0_ouverte, trombe_0_lame, trombe_hors_saison_de_chauffe" in texte
    tablette = texte.split("trombe_0_tablette")[1].split(";")[0]
    assert "-0.5500, 0.8500" in tablette                    # 0,15 m de lame et 0,40 m de saillie, en haut de la vitre


def test_l_etude_lit_un_mur_trombe(tmp_path):
    fichier = tmp_path / "etude.toml"
    fichier.write_text('maquette = "a.ifc"\n[[scenario]]\nnom = "t"\n[[scenario.element]]\ntype = "mur_trombe"\n'
                       'orientations = ["S", "SE"]\ntablette_m = 0.4\n', encoding="utf-8")
    (scenario,) = etude.lire(fichier).scenarios
    assert scenario.elements == [trombe.MurTrombe(orientations=("S", "SE"), tablette_m=0.4)]


def test_un_seul_mur_trombe_par_scenario(tmp_path):
    fichier = tmp_path / "etude.toml"
    element = '[[scenario.element]]\ntype = "mur_trombe"\n'
    fichier.write_text('maquette = "a.ifc"\n[[scenario]]\nnom = "t"\n' + element + element, encoding="utf-8")
    with pytest.raises(etude.EtudeInvalide, match="un seul élément « mur_trombe »"):
        etude.lire(fichier)
