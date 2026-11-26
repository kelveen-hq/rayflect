"""La puissance à installer, par EnergyPlus, sur une salle de bureau à Denver.

Ce qui est vérifié : le jour de base ne change rien à l'année ; la puissance de chauffage suit l'écart de
température et retrouve un calcul à la main des déperditions quand la consigne est tenue sur la température
ressentie ; un meilleur vitrage la réduit ; une
protection solaire réduit la pointe de froid et laisse le chauffage de base où il est.
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

from rayflect import etude, hypotheses as hyp, protections_solaires as ps, puissance  # noqa: E402

EPW_DENVER = EPW(str(DENVER))
CONSIGNE_C = 19.0


def calculer(dossier, nom, base_c=None, parois=None, protection=None, consigne="base") -> dict:
    piece = Room.from_box("salle", 8, 6, 3)
    sud = next(f for f in piece.faces if f.type.name == "Wall" and abs(f.azimuth - 180.0) < 1.0)
    sud.apertures_by_ratio(0.5)
    modele = Model(nom, rooms=[piece])
    choix = hyp.Hypotheses("bureau", "1975_1988", fenetres_ouvrables=False, climatisation=True,
                           parois=parois or hyp.Parois())
    hyp.appliquer(modele, choix)
    if protection is not None:
        ps.poser(modele, protection, {"epw": EPW_DENVER, "usage": "bureau"})
    reglages = etude._reglages(EPW_DENVER, False)
    base = None
    if base_c is not None:
        base = puissance.base_du_lieu(EPW_DENVER, base_c)
        puissance.ajouter_le_jour_de_base(reglages, EPW_DENVER, base)
    sortie = dossier / nom
    sortie.mkdir()
    idf = sortie / "in.idf"
    reglage = "" if consigne == "air" else puissance.consigne_ressentie(modele, consigne == "ressentie")
    idf.write_text(reglages.to_idf() + "\n\n" + modele.to.idf(modele, schedule_directory=str(sortie / "plannings"))
                   + reglage, encoding="utf-8")
    sql = run_idf(str(idf), str(DENVER), silent=True)[0]
    assert sql is not None, f"EnergyPlus n'a rien rendu pour {nom}"
    annee = puissance.Annee(SQLiteResult(sql))
    lu = puissance.lire(annee, EPW_DENVER, base, etude.CHAUFFAGE, etude.FROID, modele.floor_area)
    lu["chauffage_kwh"] = sum(sum(s.values) for s in annee.data_collections_by_output_name(etude.CHAUFFAGE))
    lu["froid_kwh"] = sum(sum(s.values) for s in annee.data_collections_by_output_name(etude.FROID))
    # Les déperditions à la main : parois vers le dehors au U de catalogue, et air neuf à plein débit.
    dehors = [f for f in piece.faces if f.boundary_condition.name == "Outdoors"]
    par_les_parois = sum(f.properties.energy.construction.u_factor * (f.area - sum(b.area for b in f.apertures))
                         + sum(b.properties.energy.construction.u_factor * b.area for b in f.apertures)
                         for f in dehors)
    air_neuf_m3_s = piece.properties.energy.ventilation.flow_per_area * piece.floor_area
    lu["w_par_k_a_la_main"] = par_les_parois + 1.2 * 1005.0 * air_neuf_m3_s
    return lu


@pytest.fixture(scope="module")
def cas(tmp_path_factory):
    dossier = tmp_path_factory.mktemp("puissance")
    return {
        "sans_jour": calculer(dossier, "sans_jour", consigne="air"),
        "air_au_jour_de_base": calculer(dossier, "air_au_jour_de_base", -10.0, consigne="air"),
        "ressentie": calculer(dossier, "ressentie", -10.0, consigne="ressentie"),
        "moins_10": calculer(dossier, "moins_10", -10.0),
        "zero": calculer(dossier, "zero", 0.0),
        "triple": calculer(dossier, "triple", -10.0, parois=hyp.Parois(vitrage="triple")),
        "bso": calculer(dossier, "bso", -10.0, protection=ps.BSO("chaleur")),
    }


def test_le_jour_de_base_ne_change_pas_l_annee(cas):
    assert cas["moins_10"]["chauffage_kwh"] == pytest.approx(cas["sans_jour"]["chauffage_kwh"], rel=1e-6)
    assert cas["moins_10"]["froid_kwh"] == pytest.approx(cas["sans_jour"]["froid_kwh"], rel=1e-6)
    assert cas["moins_10"]["pointe_de_froid"] == cas["sans_jour"]["pointe_de_froid"]
    assert cas["sans_jour"]["chauffage_au_jour_de_base_kw"] is None


def test_la_puissance_de_chauffage_suit_l_ecart_de_temperature(cas):
    rapport = cas["moins_10"]["chauffage_au_jour_de_base_kw"] / cas["zero"]["chauffage_au_jour_de_base_kw"]
    assert rapport == pytest.approx((CONSIGNE_C + 10.0) / (CONSIGNE_C - 0.0), rel=0.10)


def test_la_puissance_de_base_se_recoupe_avec_les_deperditions_calculees_a_la_main(cas):
    """Consigne tenue sur la température ressentie : EnergyPlus retrouve le calcul à la main à 10 % près."""
    a_la_main_kw = cas["moins_10"]["w_par_k_a_la_main"] * (CONSIGNE_C + 10.0) / 1000.0
    assert cas["moins_10"]["chauffage_au_jour_de_base_kw"] == pytest.approx(a_la_main_kw, rel=0.10)


def test_tenir_l_air_seul_au_jour_de_base_demande_moins_et_laisse_la_piece_froide(cas):
    assert cas["air_au_jour_de_base"]["chauffage_au_jour_de_base_kw"] < 0.9 * cas["moins_10"]["chauffage_au_jour_de_base_kw"]


def test_la_consigne_ressentie_toute_l_annee_augmente_les_2_besoins(cas):
    assert cas["ressentie"]["chauffage_kwh"] > 1.1 * cas["moins_10"]["chauffage_kwh"]
    assert cas["ressentie"]["froid_kwh"] > 1.1 * cas["moins_10"]["froid_kwh"]
    assert cas["ressentie"]["chauffage_au_jour_de_base_kw"] == pytest.approx(
        cas["moins_10"]["chauffage_au_jour_de_base_kw"], rel=0.01)


def test_le_jour_de_base_demande_plus_que_la_pointe_de_l_annee_type(cas):
    """Sans soleil ni apports internes, à une température que l'année type atteint à peine."""
    assert cas["moins_10"]["chauffage_au_jour_de_base_kw"] > 0.9 * cas["moins_10"]["pointe_de_chauffage"]["kw"]


def test_un_meilleur_vitrage_reduit_la_puissance_de_chauffage(cas):
    assert cas["triple"]["chauffage_au_jour_de_base_kw"] < 0.95 * cas["moins_10"]["chauffage_au_jour_de_base_kw"]


def test_une_protection_solaire_reduit_la_pointe_de_froid_et_pas_le_chauffage_de_base(cas):
    # Mesuré le 22/11/2026 : -13 % (-25 % avant que le facteur solaire des fenêtres ne soit celui de la 3CL, plus
    # bas : la protection a moins de soleil à arrêter).
    assert cas["bso"]["pointe_de_froid"]["kw"] < 0.9 * cas["moins_10"]["pointe_de_froid"]["kw"]
    assert cas["bso"]["chauffage_au_jour_de_base_kw"] == pytest.approx(
        cas["moins_10"]["chauffage_au_jour_de_base_kw"], rel=0.03)
