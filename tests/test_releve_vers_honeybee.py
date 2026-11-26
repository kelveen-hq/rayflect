"""Du relevé au bâtiment Honeybee, sur la maison d'exemple quand elle est sur le poste."""

from pathlib import Path

import pytest

pytest.importorskip("ifcopenshell")
pytest.importorskip("honeybee_energy")
from rayflect.io import lecture_ifc, releve_vers_honeybee as conversion  # noqa: E402

MAISON = Path(__file__).resolve().parents[1] / "prototype" / "ifc_exemples" / "AC20-FZK-Haus.ifc"


@pytest.fixture(scope="module")
def converti():
    if not MAISON.exists():
        pytest.skip("maquette d'exemple absente")
    releve = lecture_ifc.lire(MAISON)
    modele, rendu = conversion.convertir(releve, "maison")
    return releve, modele, rendu


def test_un_volume_par_niveau_et_un_modele_sans_defaut(converti):
    _releve, modele, rendu = converti
    assert len(modele.rooms) == 2
    assert rendu.niveaux_ecartes == []
    assert modele.check_all(raise_exception=False) == ""


def test_toutes_les_baies_sont_reposees_a_leur_aire(converti):
    releve, modele, rendu = converti
    assert rendu.baies_reposees == len(releve.baies) == len(modele.apertures)
    assert rendu.aire_reposee_m2 == pytest.approx(rendu.aire_relevee_m2, rel=0.01)
    assert rendu.baies_ecartees == []


def test_chaque_baie_regarde_ou_la_maquette_le_dit(converti):
    releve, modele, rendu = converti
    assert rendu.ecart_azimut_max_deg < 1.0
    aires = {}
    for baie in modele.apertures:
        cle = lecture_ifc.secteur(baie.azimuth)
        aires[cle] = round(aires.get(cle, 0.0) + baie.area, 1)
    assert aires == pytest.approx(releve.vitrage_par_secteur(), abs=0.1)


def test_le_rez_de_chaussee_est_sur_le_sol_et_le_toit_dehors(converti):
    _releve, modele, _rendu = converti
    bas, haut = modele.rooms
    assert [f.boundary_condition.name for f in bas.faces if f.type.name == "Floor"] == ["Ground"]
    assert [f.boundary_condition.name for f in bas.faces if f.type.name == "RoofCeiling"] == ["Adiabatic"]
    assert [f.boundary_condition.name for f in haut.faces if f.type.name == "RoofCeiling"] == ["Outdoors"]


# --- Le découpage d'un plateau en zones de façade et noyau, sans maquette ---

from rayflect.io.lecture_ifc import Niveau, Releve  # noqa: E402


def _plateau(contour, niveaux=1):
    from shapely.geometry import Polygon
    aire = round(Polygon(contour).area, 1)
    return Releve("essai", "aucun", "essai", None, None, None, 0.0, niveaux=[
        Niveau(f"n{k}", 3.0 * k, emprise_m=contour, plancher_m=3.0 * k, plafond_m=3.0 * k + 3.0,
               aire_emprise_m2=aire) for k in range(niveaux)])


RECTANGLE = [(0, 0), (40, 0), (40, 20), (0, 20)]
EN_L = [(0, 0), (40, 0), (40, 15), (15, 15), (15, 40), (0, 40)]
A_PANS = [(0, 0), (20, 0), (22, 1), (40, 1), (40, 20), (21, 20), (20, 21), (0, 21)]


def test_sans_profondeur_un_volume_par_niveau():
    modele, rendu = conversion.convertir(_plateau(RECTANGLE, 2), "p")
    assert len(modele.rooms) == 2 and rendu.zones == 2


def test_un_rectangle_donne_4_facades_et_un_noyau():
    modele, rendu = conversion.convertir(_plateau(RECTANGLE), "p", conversion.PROFONDEUR_DE_FACADE_M)
    noms = sorted(piece.identifier.split("_n0_")[1] for piece in modele.rooms)
    assert noms == ["facade_E_0", "facade_N_0", "facade_O_0", "facade_S_0", "noyau_0"]
    assert sum(piece.floor_area for piece in modele.rooms) == pytest.approx(800.0, rel=0.001)
    assert modele.check_all(raise_exception=False) == ""


def test_le_noyau_n_a_aucune_paroi_exterieure_en_etage_courant():
    modele, _rendu = conversion.convertir(_plateau(RECTANGLE, 3), "p", conversion.PROFONDEUR_DE_FACADE_M)
    noyau = next(p for p in modele.rooms if "_n1_noyau" in p.identifier)
    assert noyau.exposed_area == 0.0
    assert {f.type.name for f in noyau.faces} == {"AirBoundary", "Floor", "RoofCeiling"}


def test_les_murs_exterieurs_sont_les_memes_avec_et_sans_zones():
    def dehors(modele):
        return sum(f.area for p in modele.rooms for f in p.faces
                   if f.type.name == "Wall" and f.boundary_condition.name == "Outdoors")
    for contour in (RECTANGLE, EN_L, A_PANS):
        entier, _ = conversion.convertir(_plateau(contour), "p")
        decoupe, _ = conversion.convertir(_plateau(contour), "p", conversion.PROFONDEUR_DE_FACADE_M)
        assert dehors(decoupe) == pytest.approx(dehors(entier), rel=0.001)
        assert sum(p.floor_area for p in decoupe.rooms) == pytest.approx(entier.rooms[0].floor_area, rel=0.001)


def test_les_petits_pans_d_un_meme_cote_sont_reunis():
    modele, _rendu = conversion.convertir(_plateau(A_PANS), "p", conversion.PROFONDEUR_DE_FACADE_M)
    facades = [p for p in modele.rooms if "_facade_" in p.identifier]
    assert len(facades) <= 6                     # 8 pans de mur, mais 4 côtés principaux
    assert modele.check_all(raise_exception=False) == ""


def test_avec_cloisons_les_zones_sont_separees_par_des_murs():
    modele, _rendu = conversion.convertir(_plateau(RECTANGLE), "p", conversion.PROFONDEUR_DE_FACADE_M, cloisons=True)
    types = {f.type.name for p in modele.rooms for f in p.faces}
    assert "AirBoundary" not in types
    assert any(f.boundary_condition.name == "Surface" for p in modele.rooms for f in p.faces)


def test_un_plateau_etroit_reste_d_un_seul_tenant():
    modele, rendu = conversion.convertir(_plateau([(0, 0), (30, 0), (30, 8), (0, 8)]), "p",
                                         conversion.PROFONDEUR_DE_FACADE_M)
    assert len(modele.rooms) == 1 and rendu.zones == 1


@pytest.mark.parametrize("contour", [RECTANGLE, EN_L, A_PANS])
def test_un_noyau_ne_touche_jamais_l_exterieur(contour):
    """Un découpage où le noyau déborde jusqu'à une façade lui donnerait les fenêtres de cette façade."""
    modele, _rendu = conversion.convertir(_plateau(contour, 3), "p", conversion.PROFONDEUR_DE_FACADE_M)
    for piece in modele.rooms:
        murs_dehors = sum(f.area for f in piece.faces
                          if f.type.name == "Wall" and f.boundary_condition.name == "Outdoors")
        if "_noyau_" in piece.identifier:
            assert murs_dehors == 0.0
        else:
            assert murs_dehors > 0.0


def test_le_cote_d_une_bande_est_celui_de_son_mur():
    modele, rendu = conversion.convertir(_plateau(RECTANGLE), "p", conversion.PROFONDEUR_DE_FACADE_M)
    for piece in modele.rooms:
        _rang, _niveau, cote = rendu.etiquettes[piece.identifier]
        if cote == "noyau":
            continue
        mur = max((f for f in piece.faces if f.type.name == "Wall" and f.boundary_condition.name == "Outdoors"),
                  key=lambda f: f.area)
        assert cote == "façade " + lecture_ifc.secteur(mur.azimuth)


def test_les_bureaux_d_exemple_en_zones():
    chemin = MAISON.parent / "AC11-Institute-Var-2-IFC.ifc"
    if not chemin.exists():
        pytest.skip("maquette d'exemple absente")
    releve = lecture_ifc.lire(chemin)
    modele, rendu = conversion.convertir(releve, "bureaux", conversion.PROFONDEUR_DE_FACADE_M)
    assert rendu.baies_reposees == 162
    vitrage = {}
    for piece in modele.rooms:
        rang, _niveau, cote = rendu.etiquettes[piece.identifier]
        if rang == 1:
            vitrage[cote] = round(piece.exterior_aperture_area, 1)
    assert vitrage["noyau"] == 0.0
    assert vitrage["façade N"] > 30.0 and vitrage["façade S"] > 30.0
    assert modele.check_all(raise_exception=False) == ""


def test_un_dernier_niveau_sans_baie_est_traite_comme_des_combles():
    chemin = MAISON.parent / "AC11-Institute-Var-2-IFC.ifc"
    if not chemin.exists():
        pytest.skip("maquette d'exemple absente")
    modele, rendu = conversion.convertir(lecture_ifc.lire(chemin), "bureaux")
    assert len(modele.rooms) == 3                                    # rez-de-chaussée et 2 étages
    assert any("combles" in ligne and "Dachgeschoss" in ligne for ligne in rendu.niveaux_ecartes)
    dernier = modele.rooms[-1]
    assert [f.boundary_condition.name for f in dernier.faces if f.type.name == "RoofCeiling"] == ["Outdoors"]


def test_sans_aucune_baie_relevee_aucun_niveau_n_est_retire():
    """Un relevé sans fenêtres du tout (un bâtiment pris sur la carte) garde tous ses niveaux."""
    modele, rendu = conversion.convertir(_plateau(RECTANGLE, 3), "p")
    assert len(modele.rooms) == 3 and rendu.niveaux_ecartes == []


# --- La profondeur de façade selon la règle européenne du linteau ---

def test_la_regle_du_linteau_redonne_les_exemples_officiels():
    assert conversion.profondeur_selon_le_linteau(2.2, 0.8) == pytest.approx(3.5)    # exemple du guide dena
    assert conversion.profondeur_selon_le_linteau(2.0, 0.8) == pytest.approx(3.0)    # exemple de la fiche RT2012
    assert conversion.profondeur_selon_le_linteau(0.5, 0.8) == 0.0


def test_sans_baie_la_profondeur_retombe_sur_la_valeur_americaine():
    _modele, rendu = conversion.convertir(_plateau(RECTANGLE), "p", "linteau")
    assert "américaine" in rendu.profondeur_de_facade
    assert rendu.zones == 5


def test_la_profondeur_vient_des_linteaux_de_la_maquette(converti):
    releve, _modele, _rendu = converti
    assert conversion.profondeur_du_releve(releve) == pytest.approx(3.0, abs=0.01)   # linteaux à 2,0 m
