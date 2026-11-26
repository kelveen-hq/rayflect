"""La ventilation mécanique comme produit : la fiche, et ce qu'elle pose sur un modèle."""

import pytest

pytest.importorskip("honeybee_energy")
from honeybee.model import Model  # noqa: E402
from honeybee.room import Room  # noqa: E402

from rayflect import hypotheses as hyp, ventilation  # noqa: E402


@pytest.fixture()
def salle():
    piece = Room.from_box("salle", 8, 6, 3)
    piece.faces[3].apertures_by_ratio(0.4)
    modele = Model("essai", rooms=[piece])
    hyp.appliquer(modele, hyp.Hypotheses())
    return modele


def test_une_fiche_impossible_est_refusee():
    with pytest.raises(ValueError):
        ventilation.VMC("x", recuperation=1.2)
    with pytest.raises(ValueError):
        ventilation.VMC("x", surventilation_vol_h=-1)


def test_en_simple_flux_l_air_neuf_entre_directement_au_meme_debit_et_aux_memes_heures(salle):
    """Le système idéal soufflerait l'air neuf à la température de la pièce : il ne rafraîchirait jamais."""
    piece = salle.rooms[0]
    avant = piece.properties.energy.ventilation
    debit, heures = avant.flow_per_area * piece.floor_area, avant.schedule
    assert ventilation.poser(salle, ventilation.SIMPLE_FLUX) == 1
    energie = piece.properties.energy
    assert energie.hvac.sensible_heat_recovery == 0 and energie.ventilation is None
    (direct,) = energie.fans
    assert direct.flow_rate == pytest.approx(debit) and direct.control.schedule is heures
    assert direct.pressure_rise == 0.0                      # le ventilateur ne chauffe pas l'air
    assert direct.control.min_indoor_temperature == -100.0 and direct.control.delta_temperature == -100.0
    assert salle.check_all(raise_exception=False) == ""


def test_le_double_flux_pose_un_echangeur_et_garde_l_air_neuf_dans_le_systeme(salle):
    ventilation.poser(salle, ventilation.DOUBLE_FLUX)
    energie = salle.rooms[0].properties.energy
    assert energie.hvac.sensible_heat_recovery == ventilation.RENDEMENT_DOUBLE_FLUX
    assert energie.ventilation is not None and not energie.fans


def test_la_surventilation_pose_un_ventilateur_commande(salle):
    ventilation.poser(salle, ventilation.SIMPLE_FLUX_SURVENTILATION)
    piece = salle.rooms[0]
    (ventilateur,) = [f for f in piece.properties.energy.fans if f.identifier.startswith("surventilation")]
    assert len(piece.properties.energy.fans) == 2          # l'air neuf direct, et la surventilation
    assert ventilateur.flow_rate == pytest.approx(4.0 * piece.volume / 3600.0)
    assert ventilateur.control.min_indoor_temperature == ventilation.SIMPLE_FLUX_SURVENTILATION.seuil_interieur_c
    assert ventilateur.control.delta_temperature == 2.0
    planning = ventilateur.control.schedule.values()
    assert planning[23] == 1.0 and planning[3] == 1.0 and planning[12] == 0.0      # la nuit seulement
    assert salle.check_all(raise_exception=False) == ""


def test_la_justification_dit_tout():
    texte = ventilation.DOUBLE_FLUX_SURVENTILATION.justification()
    assert "73 %" in texte and "4 vol/h" in texte and "22 h à 6 h" in texte


def test_une_piece_non_chauffee_n_est_pas_equipee(salle):
    salle.rooms[0].properties.energy.hvac = None
    assert ventilation.poser(salle, ventilation.DOUBLE_FLUX_SURVENTILATION) == 0
