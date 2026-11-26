"""La campagne d'essais : des formes au hasard dans le découpage, et les sens que la physique impose.

Les essais marqués « lent » lancent EnergyPlus des dizaines de fois : `pytest -m lent` pour les jouer.
"""

import sys
from pathlib import Path

import pytest

pytest.importorskip("honeybee_energy")
from shapely.geometry import Polygon  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "verification"))
import formes  # noqa: E402

from rayflect.io import releve_vers_honeybee as conversion  # noqa: E402
from rayflect.io.lecture_ifc import Niveau, Releve  # noqa: E402

FORMES = formes.tirer(70)


def _murs_dehors(piece) -> float:
    return sum(f.area for f in piece.faces if f.type.name == "Wall" and f.boundary_condition.name == "Outdoors")


@pytest.mark.parametrize("rang", range(len(FORMES)), ids=lambda k: f"{k}-{FORMES[k][0]}")
def test_une_forme_au_hasard_se_decoupe_sans_rien_perdre(rang):
    _famille, contour = FORMES[rang]
    aire = Polygon(contour).area
    releve = Releve("essai", "aucun", "essai", None, None, None, 0.0, niveaux=[
        Niveau(f"n{k}", 3.0 * k, emprise_m=contour, plancher_m=3.0 * k, plafond_m=3.0 * k + 3.0,
               aire_emprise_m2=round(aire, 1)) for k in range(2)])
    entier, _ = conversion.convertir(releve, "p")
    decoupe, _ = conversion.convertir(releve, "p", conversion.PROFONDEUR_DE_FACADE_M)
    assert decoupe.check_all(raise_exception=False) == ""
    assert sum(p.floor_area for p in decoupe.rooms) == pytest.approx(2 * aire, rel=0.005)
    assert sum(map(_murs_dehors, decoupe.rooms)) == pytest.approx(sum(map(_murs_dehors, entier.rooms)), rel=0.005)
    for piece in decoupe.rooms:
        if "_noyau_" in piece.identifier:
            assert _murs_dehors(piece) == pytest.approx(0.0, abs=0.01)
        elif "_facade_" in piece.identifier:
            assert _murs_dehors(piece) > 0.01


def test_le_tirage_est_reproductible():
    assert formes.tirer(14) == formes.tirer(14)
    assert {famille for famille, _ in formes.tirer(14)} == set(formes.FAMILLES)


@pytest.mark.lent
def test_les_sens_que_la_physique_impose_sur_3_climats(tmp_path):
    from honeybee_energy.config import folders
    if not folders.energyplus_exe:
        pytest.skip("EnergyPlus n'est pas installé")
    import vraisemblance
    meteos = Path(__file__).resolve().parents[1] / "prototype" / "meteo"
    _tous, bilan = vraisemblance.campagne(meteos, tmp_path)
    non_tenues = [f"{climat} : {enonce} ({valeurs})" for climat, enonce, tenu, valeurs in bilan if not tenu]
    assert len(bilan) == 84
    assert non_tenues == []
