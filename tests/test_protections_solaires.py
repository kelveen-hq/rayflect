"""Les protections paramétrables : elles se posent où on le demande et laissent un modèle valide."""

import pytest

pytest.importorskip("honeybee_energy")
from honeybee.model import Model  # noqa: E402
from honeybee.room import Room  # noqa: E402

from rayflect import protections_solaires as ps  # noqa: E402


@pytest.fixture()
def salle():
    piece = Room.from_box("salle", 8, 6, 3)
    for face in piece.faces:
        if face.type.name == "Wall":
            face.apertures_by_ratio(0.4)
    return Model("essai", rooms=[piece])


@pytest.mark.parametrize("azimut, attendu", [(0, "N"), (90, "E"), (135, "SE"), (180, "S"), (270, "O"), (359, "N")])
def test_secteur(azimut, attendu):
    assert ps.secteur(azimut) == attendu


def test_la_casquette_par_defaut_ne_va_qu_au_sud(salle):
    assert ps.poser(salle, ps.Casquette()) == 1
    assert [ps.secteur(b.azimuth) for b in salle.apertures if b.outdoor_shades] == ["S"]


def test_les_lames_verticales_par_defaut_vont_a_l_est_et_a_l_ouest(salle):
    assert ps.poser(salle, ps.LamesVerticales()) == 2
    assert sorted(ps.secteur(b.azimuth) for b in salle.apertures if b.outdoor_shades) == ["E", "O"]


def test_un_entraxe_plus_serre_donne_plus_de_lames(salle):
    ps.poser(salle, ps.LamesVerticales(0.4, 0.4, orientations=("E",)))
    larges = len(salle.shades)
    autre = Model("autre", rooms=[Room.from_box("salle2", 8, 6, 3)])
    for face in autre.rooms[0].faces:
        if face.type.name == "Wall":
            face.apertures_by_ratio(0.4)
    ps.poser(autre, ps.LamesVerticales(0.4, 0.2, orientations=("E",)))
    assert len(autre.shades) > 1.8 * larges


def test_les_lames_saisonnieres_n_existent_que_pendant_leur_saison(salle):
    ps.poser(salle, ps.LamesSaisonnieres(orientations=("S",)))
    calendriers = {o.properties.energy.transmittance_schedule.identifier for o in salle.shades}
    assert calendriers == {"lames_saison_chaude"}
    planning = salle.shades[0].properties.energy.transmittance_schedule
    valeurs = planning.values()
    assert valeurs[200 * 24] == 0.0        # juillet : la lame est là, rien ne passe
    assert valeurs[20 * 24] == 1.0         # janvier : la lame est effacée, tout passe


def test_deux_positions_donnent_deux_jeux_de_lames(salle):
    ps.poser(salle, ps.LamesSaisonnieres(ps.LamesVerticales(0.6, 0.6), ps.LamesVerticales(0.6, 0.6, 60),
                                        orientations=("E",)))
    calendriers = {o.properties.energy.transmittance_schedule.identifier for o in salle.shades}
    assert calendriers == {"lames_saison_chaude", "lames_saison_froide"}


@pytest.mark.parametrize("pilotage, attendu", [("chaleur", "OnIfHighZoneAirTemperature"),
                                               ("soleil", "OnIfHighSolarOnWindow"), ("toujours", "AlwaysOn")])
def test_le_bso_prend_le_pilotage_demande(salle, pilotage, attendu):
    assert ps.poser(salle, ps.BSO(pilotage, orientations=None)) == 4
    assert {b.properties.energy.construction.control_type for b in salle.apertures} == {attendu}


@pytest.mark.parametrize("protection", [ps.Casquette(), ps.Joues(), ps.LamesHorizontales(), ps.LamesVerticales(),
                                        ps.LamesSaisonnieres(), ps.BSO()])
def test_le_modele_reste_valide(salle, protection):
    ps.poser(salle, protection)
    assert salle.check_all(raise_exception=False) == ""


def test_protection_inconnue(salle):
    with pytest.raises(TypeError):
        ps.poser(salle, object())


def test_les_lames_pilotees_sont_commandees_sur_la_temperature_de_la_piece(salle):
    fiche = ps.LamesPilotees(ps.LamesVerticales(0.60, 0.30, 45), 23.0, orientations=("E", "O"))
    assert ps.poser(salle, fiche) == 2
    equipees = [b for b in salle.apertures if ps.secteur(b.azimuth) in ("E", "O")]
    for baie in equipees:
        construction = baie.properties.energy.construction
        assert construction.control_type == "OnIfHighZoneAirTemperature"
        assert construction.setpoint == 23.0
        lame = construction.shade_material
        assert (lame.slat_orientation, lame.slat_width, lame.slat_separation) == ("Vertical", 0.60, 0.30)
        assert lame.slat_angle == 45.0
    assert not salle.shades                      # aucune géométrie fixe : la lame est un store d'EnergyPlus
    assert salle.check_all(raise_exception=False) == ""


def test_des_lames_pilotees_horizontales(salle):
    ps.poser(salle, ps.LamesPilotees(orientations=("S",)))
    sud = [b for b in salle.apertures if ps.secteur(b.azimuth) == "S"][0]
    assert sud.properties.energy.construction.shade_material.slat_orientation == "Horizontal"


# --- L'enveloppe : balcons, couleur du toit, photovoltaïque ---

def test_le_balcon_est_une_dalle_en_haut_du_mur(salle):
    assert ps.poser(salle, ps.Balcon(1.5, orientations=("S",))) == 1
    (dalle,) = salle.shades
    assert {round(p.z, 2) for p in dalle.geometry.vertices} == {3.0}
    assert dalle.geometry.area == pytest.approx(8.0 * 1.5)
    assert min(p.y for p in dalle.geometry.vertices) == pytest.approx(-1.5)     # il déborde vers le sud


def test_la_couleur_du_toit_change_son_absorption_et_rien_d_autre(salle):
    from rayflect import hypotheses as hyp
    hyp.appliquer(salle, hyp.Hypotheses())
    toit = next(f for f in salle.rooms[0].faces if f.type.name == "RoofCeiling")
    mur = next(f for f in salle.rooms[0].faces if f.type.name == "Wall")
    u_avant = toit.properties.energy.construction.u_factor
    assert ps.poser(salle, ps.Toit(ps.TOIT_CLAIR_NEUF)) == 1
    assert toit.properties.energy.construction.materials[0].solar_absorptance == ps.TOIT_CLAIR_NEUF
    assert toit.properties.energy.construction.u_factor == pytest.approx(u_avant)
    assert mur.properties.energy.construction.materials[0].solar_absorptance != ps.TOIT_CLAIR_NEUF


def test_le_vieillissement_d_un_toit_blanc():
    """Sleiman et al. 2011 : un revêtement de réflectance 0,80 neuf tombe à 0,656 après 3 ans."""
    assert ps.absorption_apres_3_ans(0.20) == pytest.approx(1.0 - 0.656, abs=0.001)
    assert ps.absorption_apres_3_ans(0.20) == pytest.approx(ps.TOIT_CLAIR_VIEILLI, abs=0.01)
    assert ps.TOIT_CLAIR_NEUF < ps.TOIT_CLAIR_VIEILLI < ps.TOIT_COURANT < ps.TOIT_SOMBRE < ps.TOIT_NOIR


def test_une_absorption_impossible_est_refusee():
    with pytest.raises(ValueError):
        ps.Toit(0.0)
    with pytest.raises(ValueError):
        ps.PhotovoltaiqueEnToiture(couverture=1.5)


def test_le_photovoltaique_couvre_la_part_demandee_du_toit(salle):
    assert ps.poser(salle, ps.PhotovoltaiqueEnToiture(couverture=0.5, hauteur_m=0.3)) == 1
    (panneau,) = salle.shades
    assert panneau.geometry.area == pytest.approx(0.5 * 48.0, rel=0.01)
    assert {round(p.z, 2) for p in panneau.geometry.vertices} == {3.3}
    assert panneau.geometry.normal.z > 0
    assert panneau.properties.energy.pv_properties.rated_efficiency == 0.20
    assert salle.check_all(raise_exception=False) == ""
