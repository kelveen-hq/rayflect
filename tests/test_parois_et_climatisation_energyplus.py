"""Le sens physique de la climatisation et des parois, par EnergyPlus, sur une salle de bureau à Denver.

Ce qui est vérifié est un SENS, pas une valeur : refroidir crée un besoin de froid, un store le réduit, un
isolant posé à l'intérieur cache la masse du mur, un meilleur vitrage réduit le chauffage.
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

from rayflect import etude, hypotheses as hyp, protections_solaires as ps  # noqa: E402

EPW_DENVER = EPW(str(DENVER))
OCCUPE = hyp.heures_occupees(hyp.USAGES["bureau"])


def calculer(dossier, nom, choix, protection=None) -> dict:
    piece = Room.from_box("salle", 8, 6, 3)
    sud = min(piece.faces, key=lambda f: abs(f.azimuth - 180.0) if f.type.name == "Wall" else 999.0)
    sud.apertures_by_ratio(0.5)
    modele = Model(nom, rooms=[piece])
    hyp.appliquer(modele, choix)
    if protection is not None:
        ps.poser(modele, protection, {"epw": EPW_DENVER, "usage": "bureau"})
    sortie = dossier / nom
    sortie.mkdir()
    idf = sortie / "in.idf"
    idf.write_text(etude._reglages(EPW_DENVER, False).to_idf() + "\n\n"
                   + modele.to.idf(modele, schedule_directory=str(sortie / "plannings")), encoding="utf-8")
    sql = run_idf(str(idf), str(DENVER), silent=True)[0]
    assert sql is not None, f"EnergyPlus n'a rien rendu pour {nom}"
    resultats = SQLiteResult(sql)
    temperatures = list(resultats.data_collections_by_output_name(etude.T_RESSENTIE)[0].values)
    return {
        "chauffage": sum(sum(c.values) for c in resultats.data_collections_by_output_name(etude.CHAUFFAGE)),
        "froid": sum(sum(c.values) for c in resultats.data_collections_by_output_name(etude.FROID)),
        "heures_chaudes": sum(1 for t, o in zip(temperatures, OCCUPE) if o and t > 26.0),
        "pointe": max(temperatures),
    }


@pytest.fixture(scope="module")
def cas(tmp_path_factory):
    dossier = tmp_path_factory.mktemp("parois")

    def bureau(**arguments):
        return hyp.Hypotheses("bureau", "1975_1988", fenetres_ouvrables=False, **arguments)

    murs = dict(isolant_des_murs_cm=10.0)
    return {
        "libre": calculer(dossier, "libre", bureau()),
        "climatise": calculer(dossier, "climatise", bureau(climatisation=True)),
        "climatise_bso": calculer(dossier, "climatise_bso", bureau(climatisation=True), ps.BSO("chaleur")),
        "ite": calculer(dossier, "ite", bureau(parois=hyp.Parois(isolation_des_murs="exterieure", **murs))),
        "iti": calculer(dossier, "iti", bureau(parois=hyp.Parois(isolation_des_murs="interieure", **murs))),
        "legere": calculer(dossier, "legere", bureau(parois=hyp.Parois(inertie="legere", **murs))),
        "u_fort": calculer(dossier, "u_fort", bureau(parois=hyp.Parois(u_vitrage=5.0, g_vitrage=0.6))),
        "u_faible": calculer(dossier, "u_faible", bureau(parois=hyp.Parois(u_vitrage=0.9, g_vitrage=0.6))),
        "g_fort": calculer(dossier, "g_fort", bureau(parois=hyp.Parois(u_vitrage=2.0, g_vitrage=0.85))),
        "g_faible": calculer(dossier, "g_faible", bureau(parois=hyp.Parois(u_vitrage=2.0, g_vitrage=0.30))),
    }


def test_sans_climatisation_aucun_froid_n_est_fourni(cas):
    assert cas["libre"]["froid"] == 0.0 and cas["libre"]["heures_chaudes"] > 100


def test_la_climatisation_cree_un_besoin_de_froid_et_tient_la_temperature(cas):
    assert cas["climatise"]["froid"] > 500.0
    assert cas["climatise"]["pointe"] < cas["libre"]["pointe"] - 3.0
    # La consigne tient l'AIR à 26 °C. La température ressentie, qui compte aussi les parois et le vitrage
    # chauds, la dépasse encore : c'est ce que les protections solaires corrigent en bâtiment climatisé.
    assert 0 < cas["climatise"]["heures_chaudes"] < cas["libre"]["heures_chaudes"]
    assert cas["climatise"]["chauffage"] == pytest.approx(cas["libre"]["chauffage"], rel=0.02)


def test_un_bso_reduit_le_besoin_de_froid(cas):
    assert cas["climatise_bso"]["froid"] < 0.8 * cas["climatise"]["froid"]
    assert cas["climatise_bso"]["heures_chaudes"] < 0.8 * cas["climatise"]["heures_chaudes"]


def test_un_isolant_a_l_interieur_cache_la_masse_du_mur(cas):
    assert cas["iti"]["pointe"] > cas["ite"]["pointe"]
    assert cas["legere"]["pointe"] > cas["ite"]["pointe"]


def test_un_vitrage_qui_isole_mieux_reduit_le_chauffage(cas):
    assert cas["u_faible"]["chauffage"] < 0.8 * cas["u_fort"]["chauffage"]


def test_un_vitrage_qui_arrete_le_soleil_rafraichit_l_ete_et_coute_du_chauffage(cas):
    """Les 2 effets vont en sens contraire : c'est pourquoi un type de vitrage ne se juge pas sur son seul U."""
    assert cas["g_faible"]["heures_chaudes"] < cas["g_fort"]["heures_chaudes"]
    assert cas["g_faible"]["pointe"] < cas["g_fort"]["pointe"]
    assert cas["g_faible"]["chauffage"] > 1.2 * cas["g_fort"]["chauffage"]
