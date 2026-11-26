"""Le relevé IFC : les fonctions de géométrie, puis une maquette d'exemple quand elle est sur le poste."""

from pathlib import Path

import numpy as np
import pytest

pytest.importorskip("ifcopenshell")
from rayflect.io import lecture_ifc as ifc  # noqa: E402

EXEMPLES = Path(__file__).resolve().parents[1] / "prototype" / "ifc_exemples"


def test_latitude_en_degres_minutes_secondes():
    assert ifc._degres((49, 6, 1, 566000)) == pytest.approx(49.100435, abs=1e-6)
    assert ifc._degres((-71, -2, -0, -600000)) == pytest.approx(-71.0335, abs=1e-4)
    assert ifc._degres(None) is None


def test_azimut_avec_le_nord_sur_l_axe_y():
    nord = (0.0, 1.0)
    assert ifc._azimut((0, 1), nord) == pytest.approx(0)
    assert ifc._azimut((1, 0), nord) == pytest.approx(90)
    assert ifc._azimut((0, -1), nord) == pytest.approx(180)
    assert ifc._azimut((-1, 0), nord) == pytest.approx(270)


def test_azimut_avec_un_nord_tourne():
    # Le nord pointe vers l'axe X : une façade qui regarde l'axe X regarde le nord.
    assert ifc._azimut((1, 0), (1.0, 0.0)) == pytest.approx(0)
    assert ifc._azimut((0, -1), (1.0, 0.0)) == pytest.approx(90)


@pytest.mark.parametrize("azimut, attendu", [(0, "N"), (44, "NE"), (90, "E"), (180, "S"), (225, "SO"), (350, "N")])
def test_secteur(azimut, attendu):
    assert ifc.secteur(azimut) == attendu


def test_point_dans_un_volume():
    s = np.array([[0, 0, 0], [1, 0, 0], [1, 1, 0], [0, 1, 0], [0, 0, 1], [1, 0, 1], [1, 1, 1], [0, 1, 1]], float)
    f = np.array([[0, 2, 1], [0, 3, 2], [4, 5, 6], [4, 6, 7], [0, 1, 5], [0, 5, 4],
                  [1, 2, 6], [1, 6, 5], [2, 3, 7], [2, 7, 6], [3, 0, 4], [3, 4, 7]])
    cube = s[f]
    assert ifc._dans_le_volume(np.array([0.5, 0.5, 0.5]), cube)
    assert not ifc._dans_le_volume(np.array([1.5, 0.5, 0.5]), cube)
    assert not ifc._dans_le_volume(np.array([0.5, 0.5, -0.2]), cube)


@pytest.fixture(scope="module")
def maison():
    chemin = EXEMPLES / "AC20-FZK-Haus.ifc"
    if not chemin.exists():
        pytest.skip("maquette d'exemple absente")
    return ifc.lire(chemin)


def test_maison_d_exemple_site_et_niveaux(maison):
    assert maison.latitude == pytest.approx(49.1004, abs=1e-3)
    assert maison.nord_deg == pytest.approx(50.0, abs=0.5)
    assert [n.nom for n in maison.niveaux] == ["Erdgeschoss", "Dachgeschoss"]


def test_une_maquette_sans_fenetre_garde_ses_niveaux(tmp_path):
    """Le relevé s'arrêtait dès qu'aucune fenêtre n'était lisible, avant d'avoir relevé les niveaux."""
    import ifcopenshell
    source = EXEMPLES / "AC20-FZK-Haus.ifc"
    if not source.exists():
        pytest.skip("maquette d'exemple absente")
    modele = ifcopenshell.open(str(source))
    for fenetre in list(modele.by_type("IfcWindow")):
        modele.remove(fenetre)
    chemin = tmp_path / "sans_fenetre.ifc"
    modele.write(str(chemin))
    releve = ifc.lire(chemin)
    assert releve.baies == []
    assert [n.nom for n in releve.niveaux] == ["Erdgeschoss", "Dachgeschoss"]
    assert all(n.emprise_m for n in releve.niveaux)
    assert "aucune fenêtre déclarée" in releve.manques


def test_maison_d_exemple_baies(maison):
    assert len(maison.baies) == 11
    for baie in maison.baies:
        assert baie.taille_declaree_m == pytest.approx((baie.largeur_m, baie.hauteur_m), abs=0.02)
        assert baie.inclinaison_deg == pytest.approx(90, abs=1)
    assert maison.vitrage_par_secteur() == {"SO": 5.8, "SE": 4.8, "NE": 5.8, "NO": 7.2}
