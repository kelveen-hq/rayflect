"""Le sens physique des variantes de conception et de la croissance des plantes, par EnergyPlus, à Denver.

Ce qui est vérifié est un SENS, pas une valeur : plus de vitrage au sud apporte plus de soleil, donc plus de
froid à fournir et plus de lumière ; un arbre qui grandit fait plus d'ombre d'année en année ; une plante
grimpante qui monte protège une part croissante du mur.
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

from rayflect import etude, hypotheses as hyp, variantes, vegetation  # noqa: E402

EPW_DENVER = EPW(str(DENVER))
BUREAU = hyp.Hypotheses("bureau", "1975_1988", fenetres_ouvrables=False, climatisation=True)


def calculer(dossier, nom, variante=None, plantes=()) -> dict:
    piece = Room.from_box("salle", 8, 6, 3)
    sud = next(f for f in piece.faces if f.type.name == "Wall" and abs(f.azimuth - 180.0) < 1.0)
    sud.apertures_by_ratio(0.3)
    modele = Model(nom, rooms=[piece])
    if variante is not None:
        variantes.poser(modele, variante)
    hyp.appliquer(modele, BUREAU)
    arbres = [p for p in plantes if isinstance(p, vegetation.Arbre)]
    if arbres:
        modele.add_shades(vegetation.masques(arbres))
    for plante in plantes:
        if not isinstance(plante, vegetation.Arbre):
            vegetation.poser(modele, plante)
    sortie = dossier / nom
    sortie.mkdir()
    reglages = etude._reglages(EPW_DENVER, False)
    idf = sortie / "in.idf"
    idf.write_text(reglages.to_idf() + "\n\n" + modele.to.idf(modele, schedule_directory=str(sortie / "plannings")),
                   encoding="utf-8")
    sql = run_idf(str(idf), str(DENVER), silent=True)[0]
    assert sql is not None, f"EnergyPlus n'a rien rendu pour {nom}"
    resultats = SQLiteResult(sql)
    return {"chauffage": sum(sum(c.values) for c in resultats.data_collections_by_output_name(etude.CHAUFFAGE)),
            "froid": sum(sum(c.values) for c in resultats.data_collections_by_output_name(etude.FROID))}


@pytest.fixture(scope="module")
def cas(tmp_path_factory):
    dossier = tmp_path_factory.mktemp("variantes")

    def tilleul(age):
        return [vegetation.Arbre(est_m=4.0, nord_m=-5.0, essence="tilleul", age_ans=age)]

    return {
        "base": calculer(dossier, "base"),
        "sud_double": calculer(dossier, "sud_double", variantes.Facade(orientations=("S",), baies_fois=2.0)),
        "sud_tout_vitre": calculer(dossier, "sud_tout_vitre", variantes.Facade(orientations=("S",), part_vitree=0.9)),
        "sud_ferme": calculer(dossier, "sud_ferme", variantes.Facade(orientations=("S",), part_vitree=0.0)),
        "tilleul_1": calculer(dossier, "tilleul_1", plantes=tilleul(1.0)),
        "tilleul_15": calculer(dossier, "tilleul_15", plantes=tilleul(15.0)),
        "tilleul_40": calculer(dossier, "tilleul_40", plantes=tilleul(40.0)),
        "vigne_1": calculer(dossier, "vigne_1", plantes=[vegetation.Grimpante(age_ans=1.0)]),
        "vigne_couvrante": calculer(dossier, "vigne_couvrante", plantes=[vegetation.Grimpante()]),
    }


def test_plus_de_vitrage_au_sud_demande_plus_de_froid(cas):
    assert cas["sud_ferme"]["froid"] < cas["base"]["froid"] < cas["sud_double"]["froid"] < cas["sud_tout_vitre"]["froid"]
    assert cas["sud_double"]["froid"] > 1.2 * cas["base"]["froid"]


def test_un_mur_sud_ferme_perd_les_apports_d_hiver(cas):
    """Le compromis : fermer le sud rafraîchit l'été et coûte du chauffage."""
    assert cas["sud_ferme"]["chauffage"] > cas["base"]["chauffage"]


def test_un_arbre_fait_plus_d_ombre_en_grandissant(cas):
    assert cas["tilleul_40"]["froid"] < cas["tilleul_15"]["froid"] < cas["tilleul_1"]["froid"] <= cas["base"]["froid"]
    assert cas["tilleul_40"]["froid"] < 0.9 * cas["base"]["froid"]


def test_un_arbre_caduc_coute_moins_de_chauffage_qu_il_n_evite_de_froid(cas):
    """Sans feuilles, il reste les branches : l'ombre d'hiver existe, et elle se paie en chauffage."""
    assert cas["tilleul_40"]["chauffage"] > cas["base"]["chauffage"]


def test_une_plante_grimpante_protege_davantage_une_fois_le_mur_couvert(cas):
    assert cas["vigne_couvrante"]["froid"] < cas["vigne_1"]["froid"] < cas["base"]["froid"]
