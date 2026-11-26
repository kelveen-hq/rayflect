"""La végétation : le feuillage mesurable, son calendrier, les arbres, la pergola, la plante grimpante."""

import math

import pytest

from rayflect import vegetation as veg


def test_la_transparence_suit_la_loi_de_beer_lambert():
    assert veg.transparence_depuis_l_indice(0.0) == 1.0
    assert veg.transparence_depuis_l_indice(2.0) == pytest.approx(math.exp(-veg.EXTINCTION * 2.0))
    assert veg.transparence_depuis_l_indice(2.0, extinction=0.5) == pytest.approx(math.exp(-1.0))
    assert veg.transparence_depuis_l_indice(4.0) < veg.transparence_depuis_l_indice(2.0)


def test_les_branches_comptent_l_hiver():
    feuillage = veg.Feuillage("essai", indice_foliaire=4.0, indice_de_bois=0.8)
    assert feuillage.transparence_sans_feuilles == pytest.approx(math.exp(-veg.EXTINCTION * 0.8))
    assert feuillage.transparence_en_feuilles == pytest.approx(math.exp(-veg.EXTINCTION * 4.8))


def test_un_indice_negatif_est_refuse():
    with pytest.raises(ValueError):
        veg.Feuillage("essai", -1.0)


def test_les_feuilles_sortent_et_tombent_progressivement():
    feuillage = veg.ARBRE_CADUC_DENSE
    annee = feuillage.transparences_de_l_annee()
    assert len(annee) == 365
    assert annee[10] == pytest.approx(feuillage.transparence_sans_feuilles)         # janvier
    assert annee[200] == pytest.approx(feuillage.transparence_en_feuilles)          # juillet
    sortie = annee[104:104 + feuillage.jours_de_feuillaison]                        # à partir du 15 avril
    assert all(a > b for a, b in zip(sortie, sortie[1:]))                           # de plus en plus sombre
    chute = annee[304 - feuillage.jours_de_chute:304]
    assert all(a < b for a, b in zip(chute, chute[1:]))                             # de plus en plus clair


def test_un_feuillage_persistant_ne_change_pas():
    assert len(set(veg.LIERRE.transparences_de_l_annee())) == 1


def test_le_catalogue_est_coherent():
    for feuillage in veg.CATALOGUE:
        assert 0.0 < feuillage.transparence_en_feuilles < feuillage.transparence_sans_feuilles <= 1.0
    assert veg.ARBRE_CADUC_DENSE.transparence_en_feuilles < veg.ARBRE_CADUC_CLAIR.transparence_en_feuilles


def test_le_tilleul_du_catalogue_retrouve_les_transparences_mesurees():
    """Konarska et al. 2014 : 1,3 à 5,3 % en feuilles, 40 à 52 % sans ; Larsson 2011 : 0,56 pour le tilleul nu."""
    assert 0.013 <= veg.ARBRE_CADUC_DENSE.transparence_en_feuilles <= 0.053
    assert 0.40 <= veg.ARBRE_CADUC_DENSE.transparence_sans_feuilles <= 0.59


def test_le_pin_du_catalogue_retrouve_la_transparence_mesuree():
    assert veg.ARBRE_PERSISTANT.transparence_en_feuilles == pytest.approx(0.22, abs=0.01)     # Larsson 2011


def test_un_arbre_impossible_est_refuse():
    with pytest.raises(ValueError):
        veg.Arbre(0, 0, hauteur_m=5, tronc_m=6)
    with pytest.raises(ValueError):
        veg.Arbre(0, 0, diametre_m=0)


def test_un_alignement_espace_ses_arbres():
    rangee = veg.alignement((0, -6), (16, -6), 8.0)
    assert [(a.est_m, a.nord_m) for a in rangee] == [(0.0, -6.0), (8.0, -6.0), (16.0, -6.0)]
    assert len(veg.alignement((0, 0), (0, 0))) == 1


def test_la_couronne_est_un_prisme_ferme_a_la_bonne_hauteur():
    pytest.importorskip("honeybee_energy")
    ombres = veg.masques([veg.Arbre(10, -6, hauteur_m=12, diametre_m=8, tronc_m=3)], z_du_sol_m=1.0)
    assert len(ombres) == veg.PANS + 2
    hauteurs = [p.z for o in ombres for p in o.geometry.vertices]
    assert (min(hauteurs), max(hauteurs)) == pytest.approx((4.0, 13.0))
    assert {round(math.hypot(p.x - 10, p.y + 6), 3) for o in ombres for p in o.geometry.vertices} == {4.0}


def test_une_face_de_couronne_porte_la_racine_de_la_transparence():
    """Un rayon traverse 2 faces : 2 fois la racine redonne la transparence de la couronne."""
    pytest.importorskip("honeybee_energy")
    feuillage = veg.Feuillage("essai", indice_foliaire=math.log(1 / 0.25) / veg.EXTINCTION)        # 25 % en feuilles
    ombre = veg.masques([veg.Arbre(0, 0, feuillage=feuillage)])[0]
    valeurs = ombre.properties.energy.transmittance_schedule.values()
    assert valeurs[200 * 24] == pytest.approx(0.5)      # juillet : 0,5 × 0,5 = 0,25
    assert valeurs[10 * 24] == pytest.approx(1.0)       # janvier : pas de bois, tout passe


def test_les_arbres_identiques_partagent_leur_calendrier():
    pytest.importorskip("honeybee_energy")
    ombres = veg.masques(veg.alignement((0, -6), (16, -6)))
    assert len({id(o.properties.energy.transmittance_schedule) for o in ombres}) == 1


@pytest.fixture()
def salle():
    pytest.importorskip("honeybee_energy")
    from honeybee.model import Model
    from honeybee.room import Room
    piece = Room.from_box("salle", 8, 6, 3)
    for face in piece.faces:
        if face.type.name == "Wall":
            face.apertures_by_ratio(0.3)
    return Model("essai", rooms=[piece])


def test_la_pergola_ne_va_qu_au_sud_et_porte_la_transparence_entiere(salle):
    assert veg.poser(salle, veg.Pergola()) == 1
    (baie,) = [b for b in salle.apertures if b.outdoor_shades]
    assert veg._secteur(baie.azimuth) == "S"
    valeurs = baie.outdoor_shades[0].properties.energy.transmittance_schedule.values()
    assert valeurs[200 * 24] == pytest.approx(veg.VIGNE_OU_GLYCINE.transparence_en_feuilles, abs=0.03)
    assert salle.check_all(raise_exception=False) == ""


def test_la_plante_grimpante_couvre_les_murs_et_laisse_les_baies(salle):
    crees = veg.poser(salle, veg.Grimpante())
    assert crees >= 4
    aire_des_murs_pleins = sum(f.punched_geometry.area for f in salle.rooms[0].faces if f.type.name == "Wall")
    assert sum(o.geometry.area for o in salle.shades) == pytest.approx(aire_des_murs_pleins, rel=0.01)
    assert salle.check_all(raise_exception=False) == ""


def test_une_plante_inconnue_est_refusee(salle):
    with pytest.raises(TypeError):
        veg.poser(salle, object.__new__(type("Autre", (), {"feuillage": veg.LIERRE, "orientations": None})))


def test_avec_du_feuillage_les_ombres_gardent_la_methode_geometrique():
    """La méthode par la carte graphique rend opaque tout masque à demi transparent : mesuré dans EnergyPlus."""
    pytest.importorskip("honeybee_energy")
    from honeybee.model import Model
    from honeybee.room import Room
    from honeybee.shade import Shade
    from honeybee_energy.simulation.parameter import SimulationParameter
    from ladybug_geometry.geometry3d import Face3D, Point3D
    from rayflect import environnement as env

    mur = Shade("mur_voisin", Face3D([Point3D(0, -9, 0), Point3D(8, -9, 0), Point3D(8, -9, 9), Point3D(0, -9, 9)]),
                is_detached=True)
    opaque = Model("opaque", rooms=[Room.from_box("salle", 8, 6, 3)], orphaned_shades=[mur])
    arbore = Model("arbore", rooms=[Room.from_box("salle2", 8, 6, 3)], orphaned_shades=veg.masques([veg.Arbre(4, -6)]))
    assert env.regler_le_calcul_des_ombres(SimulationParameter(), opaque) == "PixelCounting"
    assert env.regler_le_calcul_des_ombres(SimulationParameter(), arbore) == "PolygonClipping"
