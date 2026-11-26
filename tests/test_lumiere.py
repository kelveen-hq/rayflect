"""La lumière du jour : le compte de l'autonomie, et la pose des capteurs."""

import pytest

pytest.importorskip("honeybee_energy")
from honeybee.model import Model  # noqa: E402
from honeybee.room import Room  # noqa: E402

from rayflect import lumiere  # noqa: E402


def test_autonomie_comptee_sur_les_heures_d_occupation_seulement():
    eclairement = [0, 500, 250, 400, 1000]
    occupe = [False, True, True, True, False]
    assert lumiere.autonomie(eclairement, occupe) == pytest.approx(2 / 3)
    assert lumiere.autonomie(eclairement, occupe, 100) == pytest.approx(1.0)


def test_autonomie_sans_occupation():
    assert lumiere.autonomie([500, 500], [False, False]) == 0.0


def test_le_niveau_vise_est_atteint_quand_il_est_egal():
    assert lumiere.autonomie([300.0], [True]) == 1.0


def test_un_capteur_au_centre_des_pieces_vitrees_seulement():
    vitree, aveugle = Room.from_box("vitree", 8, 6, 3), Room.from_box("aveugle", 8, 6, 3)
    aveugle.move(vitree.geometry.max - vitree.geometry.min)
    vitree.faces[3].apertures_by_ratio(0.4)
    modele = Model("essai", rooms=[vitree, aveugle])
    assert lumiere.poser_les_capteurs(modele) == ["vitree"]
    capteur = vitree.properties.energy.daylighting_control
    assert (capteur.sensor_position.x, capteur.sensor_position.y) == pytest.approx((4.0, 3.0))
    assert capteur.sensor_position.z == pytest.approx(lumiere.HAUTEUR_DU_PLAN_DE_TRAVAIL_M)
    assert capteur.illuminance_setpoint == lumiere.NIVEAU_VISE_LUX
    assert aveugle.properties.energy.daylighting_control is None


def _piece_vitree_au_sud():
    piece = Room.from_box("bureau", 8, 6, 3)
    sud = next(f for f in piece.faces if abs(f.normal.y + 1) < 1e-6)       # la façade qui regarde vers −y
    sud.apertures_by_ratio(0.4)
    return piece


def test_le_bord_de_baie_est_a_1_m_du_mur_le_plus_vitre():
    piece = _piece_vitree_au_sud()
    bord = lumiere.point_du_bord(piece)
    assert (bord.x, bord.y, bord.z) == pytest.approx((4.0, 1.0, lumiere.HAUTEUR_DU_PLAN_DE_TRAVAIL_M))
    assert lumiere.regard(piece) == pytest.approx(270.0)                     # vers l'ouest, le long de la façade sud
    etroite = Room.from_box("couloir", 8, 0.8, 3)
    next(f for f in etroite.faces if abs(f.normal.y + 1) < 1e-6).apertures_by_ratio(0.4)
    assert lumiere.point_du_bord(etroite).y == pytest.approx(0.5)            # 1 m ne tient pas : 0,5 m


def test_le_fichier_gagne_le_bord_et_l_eblouissement():
    piece = _piece_vitree_au_sud()
    modele = Model("essai", rooms=[piece])
    lumiere.poser_les_capteurs(modele)
    texte = lumiere.retoucher(modele.to.idf(modele), modele)
    assert texte.count("Daylighting:Controls,") == 1 and "bureau_Bord, 0.0, 300.0;" in texte
    assert "bureau_Sensor, 270.0, 22, ," in texte                          # le regard et l'indice maximal
    assert "Daylighting:ReferencePoint,\n  bureau_Bord, bureau, 4.000, 1.000, 0.800;" in texte


def test_l_exces_et_l_eblouissement_se_comptent_en_occupation():
    assert lumiere.part_au_dessus([4000, 2500, 3500, 100], [True, True, False, True], lumiere.EXCES_LUX) == pytest.approx(1 / 3)
    assert lumiere.part_au_dessus([30, 10], [False, False], lumiere.EBLOUISSEMENT_MAXIMAL) == 0.0
