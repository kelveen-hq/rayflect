"""Les fenêtres qu'un scénario ouvre : la fiche, ce qu'elle écrit, et les débits de ses formules. Sans calcul."""

import pytest

pytest.importorskip("honeybee_energy")
from honeybee.model import Model  # noqa: E402
from honeybee.room import Room  # noqa: E402

from rayflect import aeration, etude, hypotheses as hyp, ventilation  # noqa: E402

USAGE = hyp.Hypotheses().l_usage()


@pytest.fixture()
def plateau():
    """Une pièce de 8 m sur 6, des baies au nord et au sud."""
    piece = Room.from_box("plateau", 8, 6, 3)
    piece.faces[1].apertures_by_ratio(0.4)          # nord
    piece.faces[3].apertures_by_ratio(0.4)          # sud
    modele = Model("essai", rooms=[piece])
    hyp.appliquer(modele, hyp.Hypotheses())
    return modele


def _ouvrants(texte: str):
    """Les champs de chaque ouvrant écrit, dans l'ordre : nom, pièce, aire, planning, efficacité du vent..."""
    return [[ligne.split("!-")[0].strip(" ,;") for ligne in bloc.strip().splitlines()]
            for bloc in texte.split("ZoneVentilation:WindandStackOpenArea,\n")[1:]]


def test_une_fiche_impossible_est_refusee():
    assert aeration.Ouvrants().part_ouvrable is None                 # celle de l'usage
    for faux in (dict(part_ouvrable=0.0), dict(part_ouvrable=1.2), dict(part_de_hauteur=0.0), dict(heures=(8, 8)),
                 dict(heures=(8, 25)), dict(heures=(8,)), dict(vent_maximal_m_s=0.0)):
        with pytest.raises(ValueError):
            aeration.Ouvrants(**faux)


def test_l_element_remplace_l_ouverture_de_l_etude_et_ferme_le_reste(plateau):
    piece = plateau.rooms[0]
    assert any(baie.properties.energy.vent_opening is not None for baie in plateau.apertures)   # celle de l'étude
    texte, dit = aeration.poser(plateau, aeration.Ouvrants(orientations=("S",), heures=(22, 6)), USAGE)
    assert all(baie.properties.energy.vent_opening is None for baie in plateau.apertures)
    assert {baie.is_operable for baie in plateau.apertures
            if aeration.secteur(baie.azimuth) == "S"} == {True}
    assert {baie.is_operable for baie in plateau.apertures if aeration.secteur(baie.azimuth) == "N"} == {False}
    ouvrants = _ouvrants(texte)
    sud = [baie for baie in plateau.apertures if aeration.secteur(baie.azimuth) == "S"]
    assert len(ouvrants) == len(sud)
    # La part ouvrante d'un bureau (RE2020) : la moitié des baies, 80 % de leur aire.
    assert sum(float(o[2]) for o in ouvrants) == pytest.approx(0.4 * sum(b.area for b in sud), abs=0.01)
    assert "de 22 h à 6 h" in dit[0] and "façades S" in dit[0]
    # Le planning des heures entre dans le fichier par la règle d'ouverture de la pièce.
    planning = piece.properties.energy.window_vent_control.schedule
    assert planning.identifier in texte
    assert planning.values()[23] == 1.0 and planning.values()[12] == 0.0
    assert plateau.check_all(raise_exception=False) == ""


def test_sans_heures_les_fenetres_suivent_l_occupation(plateau):
    aeration.poser(plateau, aeration.Ouvrants(), USAGE)
    planning = plateau.rooms[0].properties.energy.window_vent_control.schedule.values()
    lundi = 24                                       # l'année de calcul commence un dimanche
    assert planning[lundi + 10] == 1.0 and planning[lundi + 2] == 0.0 and planning[10] == 0.0


def test_le_traversant_demande_2_facades_et_le_dit(plateau):
    texte, dit = aeration.poser(plateau, aeration.Ouvrants(traversant=True), USAGE)
    assert all(o[4] == "Autocalculate" for o in _ouvrants(texte)) and any("traversante" in d for d in dit)
    # Des ouvrants d'un seul côté : la pièce ne peut pas être traversée, elle est comptée comme une seule façade.
    texte, dit = aeration.poser(plateau, aeration.Ouvrants(traversant=True, orientations=("S",)), USAGE)
    assert all(float(o[4]) == aeration.EFFICACITE_DU_VENT_UNE_FACADE for o in _ouvrants(texte))
    assert any("ouvrants d'un seul côté" in d for d in dit)


def test_sans_baie_a_ouvrir_tout_reste_ferme_et_c_est_dit(plateau):
    texte, dit = aeration.poser(plateau, aeration.Ouvrants(orientations=("E",)), USAGE)
    assert texte == "" and "aucune baie à ouvrir" in dit[0]
    assert plateau.rooms[0].properties.energy.window_vent_control is None


def test_le_tirage_d_une_facade_est_celui_de_l_integration_a_la_main():
    """Qt = Cd0 . (A / 3) . racine(g H dT / T) : 1 m² de 1,5 m de haut, 20 °C dedans, 10 °C dehors, sans vent."""
    attendu = 0.6 / 3.0 * (9.81 * 1.5 * 10.0 / 293.15) ** 0.5
    assert aeration.debit_m3_s(1.0, 1.5, 20.0, 10.0, 0.0, 0.025) == pytest.approx(attendu, rel=1e-9)
    assert aeration.debit_m3_s(1.0, 1.5, 10.0, 20.0, 0.0, 0.025) == pytest.approx(attendu, rel=1e-9)   # symétrique


def test_les_sens_que_la_physique_impose_au_debit():
    calme = aeration.debit_m3_s(1.0, 1.5, 26.0, 18.0, 0.0, 0.025)
    assert aeration.debit_m3_s(1.0, 1.5, 26.0, 18.0, 3.0, 0.025) > calme            # le vent ajoute
    assert aeration.debit_m3_s(1.0, 3.0, 26.0, 18.0, 0.0, 0.025) > calme            # un ouvrant plus haut tire plus
    assert aeration.debit_m3_s(1.0, 1.5, 26.0, 25.9, 0.0, 0.025) < 0.2 * calme      # sans écart, presque rien
    # En traversant, un ouvrant face au vent prend bien plus qu'une seule façade ; sous le vent, il ne prend rien.
    face = aeration.efficacite_du_vent(True, 180.0, 180.0)
    assert face == 0.55 and aeration.efficacite_du_vent(True, 180.0, 225.0) == pytest.approx(0.30)
    assert aeration.efficacite_du_vent(True, 180.0, 0.0) == 0.0 and aeration.efficacite_du_vent(True, 10.0, 350.0) > 0.4
    assert face > 20 * aeration.efficacite_du_vent(False)


def test_la_ventilation_d_un_scenario_se_traduit_en_fiche():
    assert ventilation.Mecanique().vmc() == ventilation.VMC("simple flux")
    fiche = ventilation.Mecanique(double_flux=True, surventilation_vol_h=6.0, heures_de_surventilation=(21, 7)).vmc()
    assert fiche.recuperation == ventilation.RENDEMENT_DOUBLE_FLUX and fiche.surventilation_vol_h == 6.0
    assert fiche.heures_de_surventilation == (21, 7)
    assert ventilation.Mecanique(double_flux=True, recuperation=0.85).vmc().recuperation == 0.85
    for faux in (dict(recuperation=0.8), dict(double_flux=True, recuperation=1.0), dict(surventilation_vol_h=-1.0),
                 dict(heures_de_surventilation=(6, 6))):
        with pytest.raises(ValueError):
            ventilation.Mecanique(**faux)


ENTETE = 'maquette = "a.ifc"\n[[scenario]]\nnom = "s"\n'


def test_l_etude_lit_les_ouvrants_et_la_ventilation_d_un_scenario(tmp_path):
    fichier = tmp_path / "etude.toml"
    fichier.write_text(ENTETE + '[[scenario.element]]\ntype = "ouvrants"\nheures = [22, 6]\ntraversant = true\n'
                       '[[scenario.element]]\ntype = "ventilation"\ndouble_flux = true\n', encoding="utf-8")
    (scenario,) = etude.lire(fichier).scenarios
    assert scenario.elements == [aeration.Ouvrants(heures=(22, 6), traversant=True),
                                 ventilation.Mecanique(double_flux=True)]
    assert not scenario.est_la_reference


@pytest.mark.parametrize("elements, attendu", [
    ('[[scenario.element]]\ntype = "ouvrants"\n[[scenario.element]]\ntype = "ouvrants"\n', "un seul élément « ouvrants »"),
    ('[[scenario.element]]\ntype = "ventilation"\n[[scenario.element]]\ntype = "ventilation"\n',
     "un seul élément « ventilation »"),
    ('[[scenario.element]]\ntype = "ouvrants"\npart_ouvrable = 2.0\n', "part_ouvrable"),
    ('[[scenario.element]]\ntype = "ventilation"\nrecuperation = 0.8\n', "double_flux = true"),
])
def test_ce_qui_est_refuse_dit_quoi_corriger(tmp_path, elements, attendu):
    fichier = tmp_path / "etude.toml"
    fichier.write_text(ENTETE + elements, encoding="utf-8")
    with pytest.raises(etude.EtudeInvalide, match=attendu):
        etude.lire(fichier)


def test_les_fenetres_posees_par_les_hypotheses_ont_le_meme_tirage(plateau):
    assert hyp.OUVERTURE_COEFFICIENT_DE_TIRAGE == pytest.approx(aeration.COEFFICIENT_DE_TIRAGE, abs=1e-4)
    ouvrants = [baie.properties.energy.vent_opening for baie in plateau.apertures]
    assert {o.discharge_coefficient for o in ouvrants} == {hyp.OUVERTURE_COEFFICIENT_DE_TIRAGE}
