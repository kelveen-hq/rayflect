"""Les bâtiments voisins : lecture des données, tri, et transformation en masques. Sans accès au réseau."""

import pytest

pytest.importorskip("shapely")
from rayflect import environnement as env  # noqa: E402

LAT, LON = 45.0, 0.0


def _carre(est, nord, cote=10.0):
    """Un carré dont le coin sud-ouest est à (est, nord) mètres du site, en longitude et latitude."""
    import math
    def degres(x, y):
        return [math.degrees(x / (env.RAYON_TERRE_M * math.cos(math.radians(LAT)))) + LON,
                math.degrees(y / env.RAYON_TERRE_M) + LAT]
    coins = [(est, nord), (est + cote, nord), (est + cote, nord + cote), (est, nord + cote), (est, nord)]
    return [[degres(x, y) for x, y in coins]]


def _batiment(identifiant, est, nord, **proprietes):
    return {"id": identifiant, "properties": proprietes,
            "geometry": {"type": "Polygon", "coordinates": _carre(est, nord)}}


CARTE = {"features": [
    _batiment("lui_meme", 0, 0, hauteur=9.0, altitude_minimale_sol=10.0),
    _batiment("voisin_haut", 20, 0, hauteur=30.0, altitude_minimale_sol=10.0),
    _batiment("voisin_bas_et_loin", 140, 0, hauteur=4.0, altitude_minimale_sol=10.0),
    _batiment("par_les_etages", 0, 30, nombre_d_etages=4, altitude_minimale_sol=12.0),
    _batiment("sans_hauteur", 0, 60),
]}
ETUDIE = [(0, 0), (10, 0), (10, 10), (0, 10)]


def test_des_degres_aux_metres():
    est, nord = env.vers_metres(LAT + 0.001, LON, LAT, LON)
    assert est == pytest.approx(0.0, abs=1e-6)
    assert nord == pytest.approx(111.19, abs=0.05)
    est, _ = env.vers_metres(LAT, LON + 0.001, LAT, LON)
    assert est == pytest.approx(111.19 * 0.7071, abs=0.05)


def test_lecture_des_hauteurs_et_des_manques():
    voisins, manques = env.lire(CARTE, LAT, LON)
    par_nom = {v.identifiant.rsplit("_", 1)[0]: v for v in voisins}
    assert set(par_nom) == {"lui_meme", "voisin_haut", "voisin_bas_et_loin", "par_les_etages"}
    assert par_nom["voisin_haut"].hauteur_m == 30.0
    assert par_nom["par_les_etages"].hauteur_m == 12.0 and par_nom["par_les_etages"].hauteur_supposee
    assert any("sans hauteur" in m for m in manques)
    assert any("nombre d'étages" in m for m in manques)


def test_le_contour_est_en_metres_autour_du_site():
    voisins, _ = env.lire(CARTE, LAT, LON)
    haut = next(v for v in voisins if v.identifiant.startswith("voisin_haut"))
    xs, ys = [p[0] for p in haut.contour_m], [p[1] for p in haut.contour_m]
    assert (min(xs), max(xs)) == pytest.approx((20.0, 30.0), abs=0.01)
    assert (min(ys), max(ys)) == pytest.approx((0.0, 10.0), abs=0.01)


def test_le_tri_ecarte_le_batiment_etudie_et_les_voisins_sans_effet():
    voisins, _ = env.lire(CARTE, LAT, LON)
    gardes, bilan = env.filtrer(voisins, ETUDIE)
    assert bilan == {"lui_meme": 1, "trop_bas_ou_loin": 1, "gardes": 2}
    assert sorted(v.identifiant.rsplit("_", 1)[0] for v in gardes) == ["par_les_etages", "voisin_haut"]


def test_un_voisin_devient_ses_murs_et_son_toit():
    pytest.importorskip("honeybee")
    voisins, _ = env.lire(CARTE, LAT, LON)
    haut = [v for v in voisins if v.identifiant.startswith("voisin_haut")]
    ombres = env.masques(haut, altitude_site_m=10.0)
    assert len(ombres) == 5                                  # 4 murs et 1 toit
    assert max(p.z for o in ombres for p in o.geometry.vertices) == pytest.approx(30.0)
    assert all(o.is_detached for o in ombres)


def test_un_voisin_plus_haut_sur_la_pente_monte_d_autant():
    pytest.importorskip("honeybee")
    voisins, _ = env.lire(CARTE, LAT, LON)
    pente = [v for v in voisins if v.identifiant.startswith("par_les_etages")]
    ombres = env.masques(pente, altitude_site_m=10.0)
    assert max(p.z for o in ombres for p in o.geometry.vertices) == pytest.approx(14.0)   # 2 m de pente + 12 m


def test_l_altitude_du_site_est_celle_du_batiment_le_plus_proche():
    voisins, _ = env.lire(CARTE, LAT, LON)
    assert env.altitude_du_site(voisins) == 10.0


EN_L = [(0, 0), (20, 0), (20, 8), (8, 8), (8, 15), (0, 15)]


def _voisin(nom, contour, est=0.0, nord=0.0, hauteur=12.0):
    return env.Voisin(nom, tuple((x + est, y + nord) for x, y in contour), hauteur)


def test_le_calage_retrouve_un_batiment_decale():
    carte = [_voisin("cible", EN_L, 23.5, -11.0), _voisin("autre", [(0, 0), (20, 0), (20, 15), (0, 15)], 70, 60)]
    calage = env.caler(EN_L, carte, recherche_m=100)
    assert calage.sur and calage.batiment == "cible"
    assert calage.decalage_m == pytest.approx((23.5, -11.0), abs=0.01)
    assert calage.recouvrement == pytest.approx(1.0)


def test_le_calage_tient_avec_une_emprise_imparfaite():
    # La maquette est un peu plus grande que la carte (débords, isolation) et son contour est simplifié.
    maquette = [(-0.3, -0.3), (20.3, -0.3), (20.3, 8.3), (8.3, 8.3), (8.3, 15.3), (-0.3, 15.3)]
    calage = env.caler(maquette, [_voisin("cible", EN_L, 6.0, 4.0)], recherche_m=100)
    assert calage.sur
    assert calage.decalage_m == pytest.approx((6.0, 4.0), abs=0.5)
    assert 0.85 < calage.recouvrement < 1.0


def test_le_calage_ne_conclut_pas_quand_rien_ne_ressemble():
    carre = [(0, 0), (5, 0), (5, 5), (0, 5)]
    calage = env.caler(carre, [_voisin("grand", EN_L, 10, 10)], recherche_m=100)
    assert not calage.sur


def test_le_calage_ne_cherche_pas_au_dela_de_sa_distance():
    calage = env.caler(EN_L, [_voisin("loin", EN_L, 300.0, 0.0)], recherche_m=40)
    assert not calage.sur and calage.batiment is None


def test_deplacer_les_voisins():
    deplaces = env.deplacer([_voisin("a", EN_L, 10, 10)], -10, -10)
    assert deplaces[0].contour_m == tuple((float(x), float(y)) for x, y in EN_L)


def test_entourer_cale_puis_ecarte_le_batiment_etudie():
    pytest.importorskip("honeybee")
    from honeybee.model import Model
    from honeybee.room import Room
    modele = Model("essai", rooms=[Room.from_box("salle", 10, 10, 3)])
    # La carte place le bâtiment étudié 12 m plus à l'est que la maquette, avec un voisin haut juste à côté.
    carte = {"features": [_batiment("lui_meme", 12, 0, hauteur=9.0, altitude_minimale_sol=10.0),
                          _batiment("voisin_haut", 32, 0, hauteur=30.0, altitude_minimale_sol=10.0)]}
    bilan = env.entourer(modele, ETUDIE, LAT, LON, carte=carte)
    assert bilan["calage"].sur
    assert bilan["calage"].decalage_m == pytest.approx((12.0, 0.0), abs=0.5)
    assert bilan["tri"] == {"lui_meme": 1, "trop_bas_ou_loin": 0, "gardes": 1}
    assert len(modele.shades) == 5
    # Ramené dans le repère de la maquette, le voisin commence 20 m à l'est de l'origine.
    assert min(p.x for o in modele.shades for p in o.geometry.vertices) == pytest.approx(20.0, abs=0.6)


def test_entourer_dit_quand_la_maquette_n_est_pas_reconnue():
    pytest.importorskip("honeybee")
    from honeybee.model import Model
    from honeybee.room import Room
    modele = Model("essai", rooms=[Room.from_box("salle", 10, 10, 3)])
    carte = {"features": [_batiment("voisin_haut", 40, 0, hauteur=30.0, altitude_minimale_sol=10.0)]}
    bilan = env.entourer(modele, [(0, 0), (3, 0), (3, 3), (0, 3)], LAT, LON, carte=carte)
    assert not bilan["calage"].sur
    assert any("à confirmer" in manque for manque in bilan["manques"])
