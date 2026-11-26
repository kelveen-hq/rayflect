"""Des maquettes de bâtiments réels, quand elles sont sur le poste : ce que la campagne du 15/11/2026 a obtenu.

Chacune a révélé un défaut que les maquettes de démonstration ne montraient pas. Les nombres attendus sont
ceux obtenus après correction : un essai qui baisse signale une régression.
"""

from pathlib import Path

import pytest

pytest.importorskip("ifcopenshell")
pytest.importorskip("honeybee_energy")
from rayflect.io import lecture_ifc, releve_vers_honeybee as conversion  # noqa: E402

EXEMPLES = Path(__file__).resolve().parents[1] / "prototype" / "ifc_exemples"

# fichier : (volumes d'un seul tenant, baies reposées, part minimale de l'aire vitrée reposée)
ATTENDU = {
    "DigitalHub-bureaux-Aix": (2, 47, 0.99),            # bureaux, Revit 2019 ; un étage à −0,15 m passait pour enterré
    "Esplanades-logements-Tallinn": (5, 294, 0.98),     # logements, Archicad 22 ; géométrie posée 14 m au-dessus du zéro
    "TalTech-bureaux-Tallinn": (4, 57, 0.85),           # bureaux, Revit 2023 ; géométrie posée 29 m sous le zéro
    "Zenodo-gabarit-francais": (2, 44, 0.60),           # Revit 2021 français ; aucun local, murs du rez-de-chaussée ouverts
}


@pytest.fixture(scope="module", params=list(ATTENDU))
def cas(request):
    chemin = EXEMPLES / f"{request.param}.ifc"
    if not chemin.exists():
        pytest.skip("maquette absente du poste")
    return request.param, lecture_ifc.lire(chemin)


def test_la_maquette_donne_un_batiment_valide(cas):
    nom, releve = cas
    volumes, baies, part = ATTENDU[nom]
    modele, rendu = conversion.convertir(releve, nom)
    assert len(modele.rooms) == volumes
    assert rendu.baies_reposees >= baies
    assert rendu.aire_reposee_m2 >= part * rendu.aire_relevee_m2
    assert rendu.ecart_azimut_max_deg < 3.0
    assert modele.check_all(raise_exception=False) == ""


def test_la_maquette_se_decoupe_en_zones_valides(cas):
    nom, releve = cas
    modele, rendu = conversion.convertir(releve, nom, "linteau")
    assert rendu.baies_reposees >= ATTENDU[nom][1]
    assert modele.check_all(raise_exception=False) == ""
    assert "règle européenne" in rendu.profondeur_de_facade
    for piece in modele.rooms:
        if "_noyau_" in piece.identifier:
            assert sum(f.area for f in piece.faces
                       if f.type.name == "Wall" and f.boundary_condition.name == "Outdoors") == pytest.approx(0, abs=0.01)


def test_aucun_etage_hors_sol_n_est_pris_pour_un_sous_sol(cas):
    """L'altitude déclarée d'un niveau et celle de sa géométrie ne partent pas du même zéro."""
    nom, releve = cas
    _modele, rendu = conversion.convertir(releve, nom)
    enterres = [ligne for ligne in rendu.niveaux_ecartes if "enterré" in ligne]
    hors_sol = [n for n in releve.niveaux if n.altitude_m >= -0.5 and n.emprise_m and n.n_baies]
    assert all(not any(n.nom in ligne for ligne in enterres) for n in hors_sol)


def test_les_baies_sont_a_la_hauteur_de_leur_niveau(cas):
    _nom, releve = cas
    alleges = [b.allege_m for b in releve.baies if b.allege_m is not None and b.inclinaison_deg > 60]
    assert alleges and sorted(alleges)[len(alleges) // 2] < 3.0       # et non 14 m ou −29 m
