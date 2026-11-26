"""Les entrées qui ouvrent l'outil à d'autres logiciels : le bâtiment par ses chiffres, l'usage réglé, l'apport
horaire lu dans un fichier, et le point d'extension par lequel un autre paquet déclare son propre élément."""

from dataclasses import dataclass

import pytest

from rayflect import apports, etude, extensions, hypotheses as hyp
from rayflect.io import releve_par_chiffres as chiffres


def _ecrire(tmp_path, texte, nom="etude.toml"):
    fichier = tmp_path / nom
    fichier.write_text(texte, encoding="utf-8")
    return fichier


# --- Le bâtiment par ses chiffres -------------------------------------------------------------------------

def test_un_pave_donne_ses_niveaux_et_son_vitrage_par_orientation():
    releve = chiffres.lire(30, 12, niveaux=3, hauteur_d_etage_m=3.2, vitrage_m2={"S": 60.0, "N": 30.0},
                           latitude=44.8, longitude=-0.6)
    assert [n.plancher_m for n in releve.niveaux] == [0.0, 3.2, 6.4]
    assert releve.vitrage_par_secteur() == {"S": pytest.approx(60.0, abs=0.1), "N": pytest.approx(30.0, abs=0.1)}
    assert all(n.aire_emprise_m2 == 360.0 for n in releve.niveaux)
    assert len(releve.manques) == 1 and "décrit par ses chiffres" in releve.manques[0]


@pytest.mark.parametrize("azimut, cotes", [(180, ("S", "N")), (270, ("O", "E")), (135, ("SE", "NO")), (0, ("N", "S"))])
def test_la_facade_avant_regarde_ou_on_le_dit_jusque_dans_le_modele(azimut, cotes):
    pytest.importorskip("honeybee")
    from rayflect import variantes
    from rayflect.io import releve_vers_honeybee

    avant, arriere = cotes
    releve = chiffres.lire(30, 12, niveaux=2, azimut_avant_deg=azimut, vitrage_m2={avant: 40.0, arriere: 10.0})
    modele, rendu = releve_vers_honeybee.convertir(releve, "pave")
    assert not rendu.baies_ecartees and rendu.ecart_azimut_max_deg < 1.0
    assert variantes.vitrage_par_secteur(modele) == {avant: pytest.approx(40.0, abs=0.1),
                                                     arriere: pytest.approx(10.0, abs=0.1)}
    assert modele.check_all(raise_exception=False) == ""


def test_des_baies_trop_nombreuses_deviennent_un_bandeau_et_l_exces_est_dit():
    bandeau = chiffres.lire(10, 8, vitrage_m2={"S": 20.0})
    assert len(bandeau.baies) == 1 and bandeau.baies[0].aire_m2 == pytest.approx(20.0, abs=0.05)
    assert bandeau.baies[0].z_haut_m <= 3.0 - chiffres.HAUTEUR_SOUS_PLAFOND_MIN_M + 1e-6
    plafonne = chiffres.lire(10, 8, vitrage_m2={"S": 100.0})
    assert plafonne.vitrage_par_secteur()["S"] < 30.0
    assert any("plafonnée" in m for m in plafonne.manques)


@pytest.mark.parametrize("arguments, attendu", [
    (dict(longueur_m=0, largeur_m=8), "longueur_m"),
    (dict(longueur_m=10, largeur_m=8, niveaux=1.5), "niveaux"),
    (dict(longueur_m=10, largeur_m=8, vitrage_m2={"SUD": 5}), "orientation inconnue SUD"),
    (dict(longueur_m=10, largeur_m=8, vitrage_m2={"SE": 5}), "aucune façade ne regarde vers SE"),
    (dict(longueur_m=10, largeur_m=8, vitrage_m2={"S": -5}), "n'est pas une aire"),
])
def test_des_chiffres_impossibles_sont_refuses_avec_la_raison(arguments, attendu):
    with pytest.raises(chiffres.ChiffresInvalides) as refus:
        chiffres.lire(**arguments)
    assert attendu in str(refus.value)


BATIMENT = '''[batiment]
longueur_m = 30.0
largeur_m = 12.0
niveaux = 3
vitrage_m2 = { S = 60.0, N = 30.0 }
[lieu]
latitude = 44.84
longitude = -0.57
'''


def test_une_etude_se_joue_sur_un_batiment_par_chiffres_sans_maquette(tmp_path):
    lue = etude.lire(_ecrire(tmp_path, BATIMENT))
    assert lue.maquette is None and lue.nom == "bâtiment décrit par ses chiffres"
    releve = etude.relever(lue)
    assert len(releve.niveaux) == 3 and (releve.latitude, releve.longitude) == (44.84, -0.57)


@pytest.mark.parametrize("texte, attendu", [
    ('maquette = "a.ifc"\n' + BATIMENT, "il faut choisir"),
    ('usage = "bureau"\n', "il manque la maquette"),
])
def test_une_maquette_ou_des_chiffres_mais_pas_les_2(tmp_path, texte, attendu):
    with pytest.raises(etude.EtudeInvalide, match=attendu):
        etude.lire(_ecrire(tmp_path, texte))


def test_un_chiffre_inconnu_du_batiment_est_refuse_a_la_lecture_du_releve(tmp_path):
    lue = etude.lire(_ecrire(tmp_path, BATIMENT.replace("niveaux = 3", "etages = 3")))
    with pytest.raises(etude.EtudeInvalide, match=r"\[batiment\].*etages"):
        etude.relever(lue)


# --- L'usage réglé ----------------------------------------------------------------------------------------

def test_l_usage_garde_ses_valeurs_sauf_celles_que_l_etude_donne():
    regle = hyp.usage_regle("bureau", {"apports_w_m2": 12.0, "heures": [8, 19]})
    assert regle.apports_w_m2 == 12.0 and regle.heures == (8, 19) and regle.source_apports == hyp.DONNE
    assert regle.air_neuf_m3_h_m2 == hyp.USAGES["bureau"].air_neuf_m3_h_m2
    assert hyp.usage_regle("bureau") == hyp.USAGES["bureau"]
    choix = hyp.Hypotheses("bureau", reglages_d_usage=(("chauffage_c", 20.0), ("chauffage_reduit_c", 16.0)))
    assert choix.les_consignes()[:3] == (20.0, 26.0, 16.0)
    assert any("chauffage à 20.0 °C, réduit à 16 °C hors occupation" in ligne for ligne in choix.justification())
    assert sum(hyp.heures_occupees(regle)) == 11 * 260             # 260 jours ouvrés dans une année qui commence un dimanche


@pytest.mark.parametrize("reglages, attendu", [
    ({"apports": 3}, "réglages inconnus : apports"),
    ({"apports_w_m2": -1}, "apports_w_m2"),
    ({"heures": [18, 8]}, "heures"),
    ({"chauffage_reduit_c": 22.0}, "dépasse la consigne"),
    ({"ferme_l_ete": 1}, "vrai ou faux"),
])
def test_un_reglage_d_usage_impossible_est_refuse_avec_la_raison(tmp_path, reglages, attendu):
    with pytest.raises(ValueError, match=attendu):
        hyp.usage_regle("bureau", reglages)
    table = "\n".join(f"{c} = {str(v).lower() if isinstance(v, bool) else v}" for c, v in reglages.items())
    with pytest.raises(etude.EtudeInvalide, match=r"\[usage_regle\]"):
        etude.lire(_ecrire(tmp_path, 'maquette = "a.ifc"\n[usage_regle]\n' + table + "\n"))


def test_un_reduit_baisse_la_consigne_hors_occupation_et_pas_au_jour_de_base():
    pytest.importorskip("honeybee_energy")
    from honeybee.model import Model
    from honeybee.room import Room

    modele = Model("m", rooms=[Room.from_box("salle", 8, 6, 3)])
    hyp.appliquer(modele, hyp.Hypotheses("bureau", reglages_d_usage=(("chauffage_reduit_c", 15.0),)))
    chauffage = modele.rooms[0].properties.energy.setpoint.heating_schedule
    assert sorted(set(chauffage.values())) == [15.0, 19.0]
    assert list(chauffage.winter_designday_schedule.values) == [19.0]


# --- L'apport horaire -------------------------------------------------------------------------------------

def _csv(tmp_path, valeurs, nom="apport.csv", entete="heure,puissance_w"):
    fichier = tmp_path / nom
    fichier.write_text(entete + "\n" + "\n".join(f"{k},{v}" for k, v in enumerate(valeurs)) + "\n", encoding="utf-8")
    return fichier


def test_une_colonne_se_lit_avec_ses_8760_heures_et_ses_valeurs_negatives(tmp_path):
    valeurs = [100.0 if k % 2 else -50.5 for k in range(8760)]
    assert apports.lire_la_colonne(_csv(tmp_path, valeurs), "puissance_w") == valeurs
    point_virgule = tmp_path / "fr.csv"
    point_virgule.write_text("heure;puissance_w\n" + "\n".join(f"{k};1,5" for k in range(8760)), encoding="utf-8")
    assert apports.lire_la_colonne(point_virgule, "puissance_w")[:2] == [1.5, 1.5]


@pytest.mark.parametrize("valeurs, colonne, attendu", [
    ([1.0] * 8760, "watts", "pas de colonne « watts ». Il a : heure, puissance_w"),
    ([1.0] * 100, "puissance_w", "100 heures"),
    ([1.0] * 5 + ["x"] + [1.0] * 8754, "puissance_w", "ligne 7"),
])
def test_un_fichier_d_apport_mal_fait_dit_ce_qui_ne_va_pas(tmp_path, valeurs, colonne, attendu):
    with pytest.raises(ValueError) as refus:
        apports.lire_la_colonne(_csv(tmp_path, valeurs), colonne)
    assert attendu in str(refus.value)
    with pytest.raises(ValueError, match="illisible"):
        apports.lire_la_colonne(tmp_path / "absent.csv", "puissance_w")


def test_l_apport_se_repartit_au_prorata_des_surfaces_ou_va_au_niveau_demande(tmp_path):
    pytest.importorskip("honeybee")
    from rayflect.io import releve_vers_honeybee

    releve = chiffres.lire(20, 10, niveaux=2, vitrage_m2={"S": 20.0})
    modele, rendu = releve_vers_honeybee.convertir(releve, "pave")
    fichier = _csv(tmp_path, [1000.0] * 4380 + [-400.0] * 4380)
    contexte = {"dossier": tmp_path / "scenario", "rendu": rendu}
    texte = apports.poser(modele, apports.ApportHoraire(str(fichier), "puissance_w"), contexte)
    assert texte.count("OtherEquipment,") == 4 and texte.count("Schedule:File,") == 2
    assert texte.count(" 0.500000,") == 2 and texte.count(" -0.500000,") == 2
    ecrit = (tmp_path / "scenario" / "apport_horaire_1.csv").read_text(encoding="utf-8").splitlines()
    assert ecrit[0] == "apporte_w,retire_w" and ecrit[1] == "1000.0,0.0" and ecrit[-1] == "0.0,400.0" and len(ecrit) == 8761
    haut = apports.poser(modele, apports.ApportHoraire(str(fichier), "puissance_w", niveau=1), contexte)
    assert haut.count("OtherEquipment,") == 2 and " 1.000000," in haut and "apport_horaire_2" in haut
    with pytest.raises(ValueError, match="aucun niveau de rang 5"):
        apports.poser(modele, apports.ApportHoraire(str(fichier), "puissance_w", niveau=5), contexte)


def test_le_fichier_d_etude_lit_un_apport_horaire_et_trouve_son_fichier_a_cote_de_lui(tmp_path):
    lue = etude.lire(_ecrire(tmp_path, BATIMENT + '''[[scenario]]
nom = "sans"
[[scenario]]
nom = "avec le procédé"
[[scenario.element]]
type = "apport_horaire"
fichier = "donnees/procede.csv"
colonne = "puissance_w"
niveau = 0
'''))
    apport = lue.scenarios[1].elements[0]
    assert apport == apports.ApportHoraire(str((tmp_path / "donnees" / "procede.csv").resolve()), "puissance_w", 0)
    assert extensions.trouver(apport).nom == "apport_horaire"


# --- Le point d'extension ---------------------------------------------------------------------------------

@dataclass(frozen=True)
class _Brasseur:
    """Un élément d'essai, comme en déclarerait un autre paquet."""
    puissance_w: float = 50.0


def _poser_le_brasseur(modele, brasseur, contexte):
    contexte.setdefault("brasseurs", []).append((contexte["scenario"], brasseur.puissance_w))
    return f"\n! brasseur de {brasseur.puissance_w:g} W\n"


@pytest.fixture
def brasseur():
    extensions.enregistrer("brasseur_d_air", _Brasseur, _poser_le_brasseur)
    yield
    extensions.retirer("brasseur_d_air")


def test_un_type_declare_par_un_autre_paquet_se_lit_dans_une_etude(tmp_path, brasseur):
    lue = etude.lire(_ecrire(tmp_path, BATIMENT + '''[[scenario]]
nom = "brassé"
[[scenario.element]]
type = "brasseur_d_air"
puissance_w = 75.0
'''))
    pose = lue.scenarios[-1].elements[0]
    assert pose == _Brasseur(75.0) and extensions.trouver(pose).poser is _poser_le_brasseur
    assert "brasseur_d_air" in etude.types_connus() and "casquette" in etude.types_connus()
    with pytest.raises(etude.EtudeInvalide, match="n'a pas de paramètre debit"):
        etude.element({"type": "brasseur_d_air", "debit": 3})


def test_un_type_inconnu_reste_refuse_et_un_nom_ne_se_prend_pas_2_fois(tmp_path, brasseur):
    with pytest.raises(etude.EtudeInvalide, match="type d'élément inconnu : « ventilateur »"):
        etude.element({"type": "ventilateur"})
    extensions.enregistrer("brasseur_d_air", _Brasseur, _poser_le_brasseur)        # à l'identique : rien
    with pytest.raises(ValueError, match="déjà déclaré"):
        extensions.enregistrer("brasseur_d_air", dict, _poser_le_brasseur)
    with pytest.raises(ValueError, match="minuscules"):
        extensions.enregistrer("Brasseur", _Brasseur, _poser_le_brasseur)
    assert extensions.trouver(object()) is None
    assert extensions.charger() == []                       # aucun paquet d'extension installé ici
