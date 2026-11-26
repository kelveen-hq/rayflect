"""Le contrôle et la réparation d'un fichier météo, sur le fichier de référence de la norme."""

import shutil
import sys
from pathlib import Path

import pytest

pytest.importorskip("ladybug")
from rayflect.io import meteo  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "verification"))
import reference  # noqa: E402

try:
    DENVER = reference.meteo_de_denver()
except reference.ReferenceIndisponible as erreur:
    pytest.skip(f"météo de référence indisponible : {erreur}", allow_module_level=True)


def _moyenne_du_ciel(chemin) -> float:
    return sum(float(d[meteo.COLONNE_CIEL]) for d in meteo._donnees(chemin)) / 8760.0


@pytest.fixture()
def casse(tmp_path):
    """Le fichier de Denver, avec un rayonnement du ciel faux : le défaut vu sur un fichier de PVGIS."""
    chemin = tmp_path / "casse.epw"
    lignes = DENVER.read_text(encoding="utf-8", errors="replace").splitlines()
    for k in range(meteo.LIGNES_D_EN_TETE, len(lignes)):
        champs = lignes[k].split(",")
        champs[meteo.COLONNE_CIEL] = "13.2"
        lignes[k] = ",".join(champs)
    chemin.write_text("\n".join(lignes) + "\n", encoding="utf-8")
    return chemin


def test_un_fichier_sain_passe_le_controle():
    controle = meteo.controler(DENVER)
    assert controle.bon
    assert any("année type" in r for r in controle.remarques)


def test_un_ciel_faux_est_vu(casse):
    controle = meteo.controler(casse)
    assert not controle.bon
    assert "rayonnement du ciel faux" in controle.defauts[0]


def test_un_fichier_tronque_est_refuse(tmp_path):
    court = tmp_path / "court.epw"
    court.write_text("\n".join(DENVER.read_text(encoding="utf-8", errors="replace").splitlines()[:500]) + "\n",
                     encoding="utf-8")
    assert "au lieu de 8 760" in meteo.controler(court).defauts[0]


def test_la_reparation_retrouve_le_ciel_a_moins_de_10_pour_cent(casse):
    repare = meteo.reparer_le_ciel(casse)
    assert meteo.controler(repare).bon
    assert _moyenne_du_ciel(repare) == pytest.approx(_moyenne_du_ciel(DENVER), rel=0.10)
    assert len(meteo._donnees(repare)) == 8760


def test_la_reparation_ne_touche_ni_la_temperature_ni_le_soleil(casse):
    repare = meteo.reparer_le_ciel(casse)
    for colonne in (meteo.COLONNE_TEMPERATURE, meteo.COLONNE_SOLEIL):
        assert [d[colonne] for d in meteo._donnees(repare)] == [d[colonne] for d in meteo._donnees(DENVER)]


def test_la_rosee_par_magnus():
    assert meteo._rosee(20.0, 100.0) == pytest.approx(20.0, abs=0.01)
    assert meteo._rosee(20.0, 50.0) == pytest.approx(9.3, abs=0.2)


def test_preparer_repare_et_le_dit(casse, tmp_path, monkeypatch):
    monkeypatch.setattr(meteo, "telecharger_pvgis", lambda latitude, longitude, dossier: casse)
    chemin, controle = meteo.preparer(39.83, -104.65, tmp_path)
    assert chemin != casse and controle.bon
    assert "recalculé" in controle.remarques[0]


def test_preparer_laisse_un_fichier_sain(tmp_path, monkeypatch):
    copie = tmp_path / "sain.epw"
    shutil.copy(DENVER, copie)
    monkeypatch.setattr(meteo, "telecharger_pvgis", lambda latitude, longitude, dossier: copie)
    chemin, controle = meteo.preparer(39.83, -104.65, tmp_path)
    assert chemin == copie and controle.bon
