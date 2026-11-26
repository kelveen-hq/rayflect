"""La lecture d'un plan DXF : le contour, les baies, ce qui manque. Les plans sont dessinés par l'essai lui-même,
comme un dessinateur le ferait : murs à 2 traits interrompus aux ouvertures, fenêtres à 3 traits ou en blocs."""

import math
from collections import Counter

import pytest

ezdxf = pytest.importorskip("ezdxf")
pytest.importorskip("shapely")
from rayflect.io import lecture_dxf  # noqa: E402

EPAISSEUR = 0.3
FENETRES = {"S": [(2.0, 1.5), (8.0, 1.5), (14.0, 1.5)], "N": [(3.0, 2.0), (12.0, 2.0)], "E": [(4.0, 1.2)]}
PORTES = {"S": [(17.5, 1.0)]}


def dessiner(chemin, largeur=20.0, profondeur=10.0, par_metre=1000.0, insunits=4, fenetres=FENETRES,
             portes=PORTES, en_blocs=False, angle_deg=0.0, calque_murs="MURS", calque_baies="FENETRES",
             baie_interieure=False):
    """Un plateau rectangulaire, dessiné dans l'unité voulue et tourné de l'angle voulu."""
    document = ezdxf.new("R2010")
    document.header["$INSUNITS"] = insunits
    espace = document.modelspace()
    a = math.radians(angle_deg)

    def point(x, y):
        return ((x * math.cos(a) - y * math.sin(a)) * par_metre, (x * math.sin(a) + y * math.cos(a)) * par_metre)

    def trait(p, q, calque):
        espace.add_line(point(*p), point(*q), dxfattribs={"layer": calque})

    if en_blocs:
        bloc = document.blocks.new("FEN")
        for y in (0.0, EPAISSEUR / 2, EPAISSEUR):
            bloc.add_line((0, y * par_metre), (par_metre, y * par_metre))
    cotes = {"S": ((0, 0), (1, 0), largeur), "E": ((largeur, 0), (0, 1), profondeur),
             "N": ((largeur, profondeur), (-1, 0), largeur), "O": ((0, profondeur), (0, -1), profondeur)}
    for nom, ((x0, y0), (ux, uy), longueur) in cotes.items():
        nx, ny = -uy, ux                                    # vers l'intérieur

        def sur(s, d, x0=x0, y0=y0, ux=ux, uy=uy, nx=nx, ny=ny):
            return (x0 + s * ux + d * nx, y0 + s * uy + d * ny)

        ouvertures = sorted([(d, w, True) for d, w in fenetres.get(nom, [])]
                            + [(d, w, False) for d, w in portes.get(nom, [])])
        debut = 0.0
        for depart, large, vitree in ouvertures + [(longueur, 0.0, None)]:
            for d in (0.0, EPAISSEUR):
                trait(sur(debut, d), sur(depart, d), calque_murs)
            if vitree is not None:
                trait(sur(depart, 0), sur(depart, EPAISSEUR), calque_murs)
                trait(sur(depart + large, 0), sur(depart + large, EPAISSEUR), calque_murs)
            if vitree and en_blocs:
                espace.add_blockref("FEN", point(*sur(depart, 0)), dxfattribs={
                    "layer": calque_baies, "xscale": large,
                    "rotation": math.degrees(math.atan2(uy, ux)) + angle_deg})
            elif vitree:
                for d in (0.0, EPAISSEUR / 2, EPAISSEUR):
                    trait(sur(depart, d), sur(depart + large, d), calque_baies)
            debut = depart + large
    trait((8.0, EPAISSEUR), (8.0, profondeur - EPAISSEUR), calque_murs)      # une cloison
    if baie_interieure:
        trait((8.0, 4.0), (8.0, 5.0), calque_baies)
    espace.add_text("SALLE 1", dxfattribs={"layer": "TEXTES"}).set_placement(point(3, 5))
    espace.add_arc(point(17.5, 0), 1.0 * par_metre, 0, 90, dxfattribs={"layer": "PORTES"})
    document.saveas(str(chemin))
    return chemin


@pytest.fixture()
def plan(tmp_path):
    return dessiner(tmp_path / "rdc.dxf")


def test_le_contour_d_un_plateau_en_millimetres(plan):
    niveau = lecture_dxf.lire(plan).niveaux[0]
    assert niveau.aire_emprise_m2 == pytest.approx(200.0, abs=0.5)
    assert len(niveau.emprise_m) == 4
    xs, ys = zip(*niveau.emprise_m)
    assert (min(xs), max(xs), min(ys), max(ys)) == pytest.approx((0.0, 20.0, 0.0, 10.0), abs=0.02)


def test_les_baies_sont_trouvees_avec_leur_largeur_et_leur_cote(plan):
    releve = lecture_dxf.lire(plan)
    assert Counter(b.secteur for b in releve.baies) == {"S": 3, "N": 2, "E": 1}
    assert sorted(round(b.largeur_m, 2) for b in releve.baies) == [1.2, 1.5, 1.5, 1.5, 2.0, 2.0]
    sud = sorted((b for b in releve.baies if b.secteur == "S"), key=lambda b: b.centre_m[0])
    assert [b.centre_m[0] for b in sud] == pytest.approx([2.75, 8.75, 14.75], abs=0.02)
    assert all(b.centre_m[1] == pytest.approx(0.0, abs=0.02) and b.normale_xy == (0.0, -1.0) for b in sud)


def test_la_porte_ferme_le_contour_sans_devenir_une_baie(plan):
    releve = lecture_dxf.lire(plan)
    assert not any(17.0 < b.centre_m[0] < 19.0 and b.secteur == "S" for b in releve.baies)


def test_les_fenetres_en_blocs_donnent_le_meme_releve(tmp_path, plan):
    en_traits = lecture_dxf.lire(plan)
    en_blocs = lecture_dxf.lire(dessiner(tmp_path / "blocs.dxf", en_blocs=True, calque_baies="A-GLAZ"))
    assert sorted((b.secteur, round(b.largeur_m, 2)) for b in en_blocs.baies) == sorted(
        (b.secteur, round(b.largeur_m, 2)) for b in en_traits.baies)


def test_un_plan_tourne_garde_son_aire_et_ses_baies(tmp_path):
    releve = lecture_dxf.lire(dessiner(tmp_path / "tourne.dxf", angle_deg=30.0))
    assert releve.niveaux[0].aire_emprise_m2 == pytest.approx(200.0, abs=0.5)
    assert len(releve.baies) == 6
    assert sorted(round(b.largeur_m, 1) for b in releve.baies) == [1.2, 1.5, 1.5, 1.5, 2.0, 2.0]
    assert {round(b.azimut_deg) for b in releve.baies} == {150, 60, 330}    # sud, est et nord tournés de 30°


def test_le_nord_donne_fait_tourner_les_orientations(plan):
    releve = lecture_dxf.lire(plan, nord_deg=90.0)          # le nord est à droite du dessin
    assert Counter(b.secteur for b in releve.baies) == {"E": 3, "O": 2, "N": 1}
    assert not any("nord non donné" in m for m in releve.manques)


def test_ce_qu_un_plan_ne_dit_pas_est_a_demander(plan):
    manques = lecture_dxf.lire(plan).manques
    for attendu in ("hauteur d'étage non donnée", "allège des baies non donnée", "hauteur des baies non donnée",
                    "nord non donné", "position du site absente", "portes vitrées"):
        assert any(attendu in m for m in manques), attendu
    donne = lecture_dxf.lire(plan, hauteur_d_etage_m=3.2, allege_m=1.0, hauteur_de_baie_m=1.5, nord_deg=0).manques
    assert not any("non donné" in m for m in donne)


def test_une_unite_non_ecrite_est_supposee_et_dite(tmp_path):
    releve = lecture_dxf.lire(dessiner(tmp_path / "sans_unite.dxf", insunits=0))
    assert releve.niveaux[0].aire_emprise_m2 == pytest.approx(200.0, abs=0.5)
    assert any("« mm » supposé" in m for m in releve.manques)
    en_metres = lecture_dxf.lire(dessiner(tmp_path / "m.dxf", par_metre=1.0, insunits=0))
    assert en_metres.niveaux[0].aire_emprise_m2 == pytest.approx(200.0, abs=0.5)
    assert any("« m » supposé" in m for m in en_metres.manques)


def test_une_baie_interieure_est_ecartee_et_dite(tmp_path):
    releve = lecture_dxf.lire(dessiner(tmp_path / "int.dxf", baie_interieure=True))
    assert len(releve.baies) == 6
    assert any("1 baies hors du contour" in m for m in releve.manques)


def test_2_niveaux_dont_un_repete(tmp_path, plan):
    etage = dessiner(tmp_path / "etage.dxf", fenetres={"S": [(5.0, 3.0)]}, portes={})
    releve = lecture_dxf.lire([plan, etage, etage], hauteur_d_etage_m=3.2, allege_m=1.0, hauteur_de_baie_m=1.4)
    assert [(n.plancher_m, n.plafond_m, n.n_baies) for n in releve.niveaux] == [(0.0, 3.2, 6), (3.2, 6.4, 1), (6.4, 9.6, 1)]
    haute = [b for b in releve.baies if b.niveau == releve.niveaux[2].nom][0]
    assert (haute.z_bas_m, haute.z_haut_m, haute.largeur_m) == (7.4, 8.8, 3.0)
    assert any("même repère" in m for m in releve.manques)


def test_des_calques_aux_noms_inconnus_se_nomment(tmp_path):
    fichier = dessiner(tmp_path / "noms.dxf", calque_murs="GO_01", calque_baies="MEN_EXT")
    with pytest.raises(lecture_dxf.PlanNonLu, match="GO_01, MEN_EXT"):
        lecture_dxf.lire(fichier)
    releve = lecture_dxf.lire(fichier, calques_murs=["GO_01"], calques_baies=["MEN_EXT"])
    assert len(releve.baies) == 6 and releve.niveaux[0].aire_emprise_m2 == pytest.approx(200.0, abs=0.5)
    with pytest.raises(lecture_dxf.PlanNonLu, match="calque absent : MURS"):
        lecture_dxf.lire(fichier, calques_murs=["MURS"])


def test_un_calque_d_emprise_passe_avant_les_murs(tmp_path):
    fichier = dessiner(tmp_path / "emprise.dxf")
    document = ezdxf.readfile(str(fichier))
    equerre = [(0, 0), (20000, 0), (20000, 10000), (12000, 10000), (12000, 16000), (0, 16000)]
    document.modelspace().add_lwpolyline(equerre, close=True, dxfattribs={"layer": "EMPRISE"})
    document.saveas(str(fichier))
    niveau = lecture_dxf.lire(fichier).niveaux[0]
    assert niveau.aire_emprise_m2 == pytest.approx(272.0, abs=0.1) and len(niveau.emprise_m) == 6


@pytest.mark.parametrize("arguments, attendu", [
    ({"hauteur_d_etage_m": 2.0, "allege_m": 1.0, "hauteur_de_baie_m": 1.5}, "ne tient pas"),
    ({"hauteur_d_etage_m": -3.0}, "n'est pas une hauteur"),
    ({"unite": "coudée"}, "unité inconnue"),
])
def test_des_parametres_impossibles_sont_refuses(plan, arguments, attendu):
    with pytest.raises(lecture_dxf.PlanNonLu, match=attendu):
        lecture_dxf.lire(plan, **arguments)


def test_un_dwg_renvoie_vers_l_export_dxf(tmp_path):
    with pytest.raises(lecture_dxf.PlanNonLu, match="l'exporter en DXF"):
        lecture_dxf.lire(tmp_path / "plan.dwg")


def test_le_releve_d_un_plan_devient_un_batiment_calculable(tmp_path, plan):
    pytest.importorskip("honeybee_energy")
    from rayflect.io import releve_vers_honeybee

    etage = dessiner(tmp_path / "etage.dxf", fenetres={"S": [(5.0, 3.0)], "O": [(2.0, 1.0)]}, portes={})
    releve = lecture_dxf.lire([plan, etage], hauteur_d_etage_m=3.0, allege_m=0.9, hauteur_de_baie_m=1.35)
    modele, rendu = releve_vers_honeybee.convertir(releve, "plan")
    assert rendu.baies_reposees == 8 and not rendu.baies_ecartees
    assert rendu.aire_reposee_m2 == pytest.approx(rendu.aire_relevee_m2, rel=0.01)
    assert len(modele.rooms) == 2 and modele.check_all(raise_exception=False) in ("", [])
    par_cote = Counter(round(a.azimuth) % 360 for a in modele.apertures)
    assert par_cote == {180: 4, 0: 2, 90: 1, 270: 1}


def test_une_unite_ecrite_fausse_est_reperee_a_la_taille(tmp_path):
    """Vu sur un plan réel : le fichier se dit en millimètres, il est dessiné en pouces."""
    fichier = dessiner(tmp_path / "pouces.dxf", par_metre=1 / 0.0254, insunits=4)
    with pytest.raises(lecture_dxf.PlanNonLu, match="L'unité est sans doute fausse"):
        lecture_dxf.lire(fichier)
    assert lecture_dxf.lire(fichier, unite="pouce").niveaux[0].aire_emprise_m2 == pytest.approx(200.0, abs=0.5)


def test_un_calque_qui_mele_portes_et_fenetres_est_signale(tmp_path):
    releve = lecture_dxf.lire(dessiner(tmp_path / "meles.dxf", calque_baies="doorswindows"))
    assert len(releve.baies) == 6 and any("mêle portes et fenêtres" in m for m in releve.manques)


def test_plusieurs_calques_de_murs_sont_signales(tmp_path):
    fichier = dessiner(tmp_path / "murets.dxf")
    document = ezdxf.readfile(str(fichier))
    document.modelspace().add_line((20000, 0), (26000, 0), dxfattribs={"layer": "MURETS"})
    document.saveas(str(fichier))
    assert any("2 calques de murs (MURETS, MURS)" in m for m in lecture_dxf.lire(fichier).manques)
    seul = lecture_dxf.lire(fichier, calques_murs=["MURS"])
    assert not any("calques de murs" in m for m in seul.manques)
    assert seul.niveaux[0].aire_emprise_m2 == pytest.approx(200.0, abs=0.5)


def test_le_dessin_de_controle_montre_le_contour_et_chaque_baie(plan):
    releve = lecture_dxf.lire(plan)
    svg = lecture_dxf.dessin_de_controle(plan, releve)
    assert svg.startswith("<svg") and svg.count("<polygon") == 1
    assert svg.count('stroke="#1a1" stroke-width="0.25"') == len(releve.baies) == 6


# Ce qui suit vient d'une campagne sur 13 plans publics de provenances variées (15/11/2026).

def _ajouter(fichier, dessin):
    document = ezdxf.readfile(str(fichier))
    dessin(document, document.modelspace())
    document.saveas(str(fichier))
    return fichier


def test_les_abreviations_de_calque_sont_des_morceaux_entiers(tmp_path):
    assert lecture_dxf._correspond("A-WIN", lecture_dxf.MOTS_DES_BAIES, lecture_dxf.MORCEAUX_DES_BAIES)
    assert not lecture_dxf._correspond("DRAWING-FRAME", lecture_dxf.MOTS_DES_BAIES, lecture_dxf.MORCEAUX_DES_BAIES)
    releve = lecture_dxf.lire(dessiner(tmp_path / "awin.dxf", calque_murs="A-WALL", calque_baies="A-WIN"))
    assert len(releve.baies) == 6


def test_un_trait_perdu_ne_fait_pas_d_epine_au_contour(tmp_path):
    fichier = _ajouter(dessiner(tmp_path / "epine.dxf"), lambda d, m: m.add_line(
        (5000, 0), (4000, -9000), dxfattribs={"layer": "MURS"}))
    niveau = lecture_dxf.lire(fichier).niveaux[0]
    assert niveau.aire_emprise_m2 == pytest.approx(200.0, abs=0.5) and len(niveau.emprise_m) == 4


def test_des_baies_restees_dehors_trahissent_un_contour_incomplet(tmp_path):
    """Une aile dont les murs sont sur un calque non reconnu : seules ses fenêtres disent qu'elle existe."""
    def aile(document, espace):
        for p, q in (((20000, 0), (30000, 0)), ((30000, 0), (30000, 10000)), ((30000, 10000), (20000, 10000))):
            espace.add_line(p, q, dxfattribs={"layer": "GO-BETON"})
        espace.add_line((30000, 4000), (30000, 6000), dxfattribs={"layer": "FENETRES"})

    fichier = _ajouter(dessiner(tmp_path / "aile.dxf", fenetres={"S": [(2.0, 1.5)]}, portes={}), aile)
    releve = lecture_dxf.lire(fichier)
    assert any("1 baies sont dessinées EN DEHORS" in m and "GO-BETON" in m for m in releve.manques)
    complet = lecture_dxf.lire(fichier, calques_murs=["MURS", "GO-BETON"])
    assert complet.niveaux[0].aire_emprise_m2 == pytest.approx(300.0, abs=1.0) and len(complet.baies) == 2
    assert not any("EN DEHORS" in m for m in complet.manques)


def test_une_grande_interruption_est_refermee_et_dite(tmp_path):
    fichier = dessiner(tmp_path / "trou.dxf", fenetres={}, portes={"S": [(8.0, 5.0)]})
    releve = lecture_dxf.lire(fichier)
    assert releve.niveaux[0].aire_emprise_m2 == pytest.approx(200.0, abs=1.0)
    assert any("contour refermé jusqu'à 6 m" in m for m in releve.manques)


def test_l_unite_se_donne_aussi_en_metres_par_unite_et_le_refus_propose_la_bonne(tmp_path):
    fichier = dessiner(tmp_path / "km.dxf", par_metre=0.001, insunits=6)       # dessiné en kilomètres
    with pytest.raises(lecture_dxf.PlanNonLu, match="aucune unité courante"):
        lecture_dxf.lire(fichier)
    assert lecture_dxf.lire(fichier, unite=1000).niveaux[0].aire_emprise_m2 == pytest.approx(200.0, abs=0.5)
    en_metres = dessiner(tmp_path / "m_dit_mm.dxf", par_metre=1.0, insunits=4)
    with pytest.raises(lecture_dxf.PlanNonLu, match="« m » donnerait 20 m"):
        lecture_dxf.lire(en_metres)


def test_un_bloc_a_l_echelle_nulle_ne_fait_pas_tomber_la_lecture(tmp_path):
    def casse(document, espace):
        bloc = document.blocks.new("CASSE")
        interieur = document.blocks.new("DEDANS")
        interieur.add_line((0, 0), (1, 0))
        bloc.add_blockref("DEDANS", (0, 0))
        espace.add_blockref("CASSE", (5000, 5000), dxfattribs={"layer": "MOBILIER", "xscale": 0, "yscale": 0, "zscale": 0})

    releve = lecture_dxf.lire(_ajouter(dessiner(tmp_path / "bloc.dxf"), casse))
    assert len(releve.baies) == 6
