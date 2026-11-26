"""L'apport horaire, par EnergyPlus, sur une salle de bureau climatisée à Denver.

Ce qui est vérifié : une chaleur apportée baisse le chauffage et monte le froid, une chaleur retirée fait
l'inverse, et le bilan d'énergie se retrouve. Un kilowatt apporté toute l'année, c'est 8 760 kWh : la somme
du chauffage évité et du froid ajouté doit en être proche, le reste partant par les parois.
Sauté si Honeybee, EnergyPlus ou le fichier météo de référence manque.
"""

import sys
from pathlib import Path

import pytest

pytest.importorskip("honeybee_energy")
from honeybee_energy.config import folders  # noqa: E402

if not folders.energyplus_exe:
    pytest.skip("EnergyPlus n'est pas installé", allow_module_level=True)

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "verification"))
import reference  # noqa: E402

try:
    DENVER = reference.meteo_de_denver()
except reference.ReferenceIndisponible as erreur:
    pytest.skip(f"météo de référence indisponible : {erreur}", allow_module_level=True)

from honeybee.model import Model  # noqa: E402
from honeybee.room import Room  # noqa: E402
from honeybee_energy.run import run_idf  # noqa: E402
from ladybug.epw import EPW  # noqa: E402
from ladybug.sql import SQLiteResult  # noqa: E402

from rayflect import apports, etude, hypotheses as hyp  # noqa: E402

EPW_DENVER = EPW(str(DENVER))


def calculer(dossier, nom, watts=None) -> dict:
    piece = Room.from_box("salle", 8, 6, 3)
    sud = next(f for f in piece.faces if f.type.name == "Wall" and abs(f.azimuth - 180.0) < 1.0)
    sud.apertures_by_ratio(0.3)
    modele = Model(nom, rooms=[piece])
    hyp.appliquer(modele, hyp.Hypotheses("bureau", "1975_1988", fenetres_ouvrables=False, climatisation=True))
    sortie = dossier / nom
    sortie.mkdir()
    ajout = ""
    if watts is not None:
        fichier = sortie / "donne.csv"
        fichier.write_text("puissance_w\n" + "\n".join([str(watts)] * 8760) + "\n", encoding="utf-8")
        ajout = apports.poser(modele, apports.ApportHoraire(str(fichier), "puissance_w"), {"dossier": sortie})
    idf = sortie / "in.idf"
    idf.write_text(etude._reglages(EPW_DENVER, False).to_idf() + "\n\n"
                   + modele.to.idf(modele, schedule_directory=str(sortie / "plannings")) + ajout, encoding="utf-8")
    sql = run_idf(str(idf), str(DENVER), silent=True)[0]
    assert sql is not None, f"EnergyPlus n'a rien rendu pour {nom}"
    resultats = SQLiteResult(sql)
    return {"chauffage": sum(sum(c.values) for c in resultats.data_collections_by_output_name(etude.CHAUFFAGE)),
            "froid": sum(sum(c.values) for c in resultats.data_collections_by_output_name(etude.FROID))}


@pytest.fixture(scope="module")
def cas(tmp_path_factory):
    dossier = tmp_path_factory.mktemp("apports")
    return {"sans": calculer(dossier, "sans"), "neutre": calculer(dossier, "neutre", 0.0),
            "apporte": calculer(dossier, "apporte", 1000.0), "retire": calculer(dossier, "retire", -300.0)}


def test_un_apport_nul_ne_change_rien(cas):
    assert cas["neutre"]["chauffage"] == pytest.approx(cas["sans"]["chauffage"], rel=1e-4)
    assert cas["neutre"]["froid"] == pytest.approx(cas["sans"]["froid"], rel=1e-4)


def test_une_chaleur_apportee_baisse_le_chauffage_et_monte_le_froid(cas):
    assert cas["apporte"]["chauffage"] < cas["sans"]["chauffage"]
    assert cas["apporte"]["froid"] > cas["sans"]["froid"]


def test_une_chaleur_retiree_fait_l_inverse(cas):
    assert cas["retire"]["chauffage"] > cas["sans"]["chauffage"]
    assert cas["retire"]["froid"] < cas["sans"]["froid"]


def test_le_kilowatt_apporte_se_retrouve_dans_le_bilan(cas):
    """8 760 kWh apportés : chauffage évité plus froid ajouté en rendent entre 60 et 100 %."""
    retrouve = (cas["sans"]["chauffage"] - cas["apporte"]["chauffage"]) + (cas["apporte"]["froid"] - cas["sans"]["froid"])
    assert 0.60 * 8760 < retrouve <= 8760 * 1.001
