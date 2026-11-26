"""Le bâtiment commun : ce qui est lu, ce qui est refusé, ce qui est dit. Sans calcul.

Les exemples sont fictifs et écrits ici : un atelier non chauffé sous des bureaux, une façade sur rue au sud, un
pignon à l'ouest, un mur mitoyen à l'est.
"""

import copy
import json
import os
from pathlib import Path

import pytest

from rayflect.io import lecture_batiment_commun as commun, releve_par_chiffres

pytest.importorskip("honeybee")
from rayflect.io import releve_vers_honeybee as conversion  # noqa: E402


def _v(valeur, provenance="saisie", **plus):
    return {"valeur": valeur, "provenance": provenance, **plus}


def atelier_et_bureaux() -> dict:
    return {
        "schema": "batiment_commun", "version": 1, "id": "essai-1", "nom": "Bureaux sur atelier",
        "ecrit_par": {"outil": "essai"},
        "lieu": {"position": _v({"latitude": 44.84, "longitude": -0.58}, "dessinee")},
        "repere": {"axes": "x_droite_y_haut", "unite": "m", "nord_deg": _v(0, "dessinee")},
        "emprise_m": _v([[0, 0], [24, 0], [24, 12], [0, 12]], "dessinee"),
        "nombre_de_niveaux": _v(2),
        "hauteur_d_etage_m": _v(3.0, "supposee"),
        "niveaux": [{"ordre": 0, "nom": "Atelier", "usage": _v("stockage"), "chauffage": _v("aucun")},
                    {"ordre": 1, "nom": "Bureaux", "usage": _v("bureau")}],
        "facades": [
            {"id": "rue", "azimut_deg": _v(180, "deduite"), "segment_m": [[0, 0], [24, 0]],
             "vitrage_m2": _v(12.0, "dessinee"), "mitoyenne": _v(False)},
            {"id": "pignon", "azimut_deg": _v(270, "deduite"), "segment_m": [[0, 12], [0, 0]],
             "vitrage_m2": _v(6.0, "dessinee")},
            {"id": "voisin", "azimut_deg": _v(90, "deduite"), "segment_m": [[24, 0], [24, 12]],
             "mitoyenne": _v(True, "bd_topo")},
        ],
        "baies": [
            {"identifiant": "r1", "facade": "rue", "niveau": 1, "position_m": 2.0, "largeur_m": 2.0, "hauteur_m": 1.5,
             "allege_m": 0.9, "provenance": "dessinee", "type": "fenetre"},
            {"identifiant": "r2", "facade": "rue", "niveau": 1, "position_m": 12.0, "largeur_m": 2.0, "hauteur_m": 1.5,
             "allege_m": 0.9, "provenance": "dessinee"},
            {"identifiant": "r3", "facade": "rue", "niveau": 0, "position_m": 18.0, "largeur_m": 2.0,
             "hauteur_m": 3.0 * 0.5, "allege_m": 0.5, "provenance": "dessinee"},
        ],
        "enveloppe": {"periode": _v("1975_1988"), "inertie": _v(None, "supposee", je_ne_sais_pas=True)},
        "usage": _v("bureau"),
        "manques": ["la hauteur d'étage reste à mesurer"],
    }


@pytest.fixture()
def lu():
    return commun.depuis(atelier_et_bureaux(), "essai.json")


def test_les_niveaux_le_chauffage_et_la_mitoyennete_sont_lus(lu):
    assert [(n.nom, n.plancher_m, n.plafond_m, n.chauffe) for n in lu.niveaux] == [
        ("Atelier", 0.0, 3.0, False), ("Bureaux", 3.0, 6.0, True)]
    assert lu.niveaux[0].aire_emprise_m2 == 288.0 and (lu.latitude, lu.longitude, lu.nord_deg) == (44.84, -0.58, 0.0)
    assert lu.mitoyens_m == [((24.0, 0.0), (24.0, 12.0))]


def test_une_baie_se_place_le_long_de_sa_facade(lu):
    r1 = next(b for b in lu.baies if b.identifiant == "r1")
    # 2 m depuis le début du trait jusqu'au bord gauche, 2 m de large : le centre est à 3 m.
    assert r1.centre_m == pytest.approx((3.0, 0.0, 3.0 + 0.9 + 0.75))
    assert (r1.azimut_deg, r1.secteur, r1.normale_xy) == (180.0, "S", pytest.approx((0.0, -1.0)))
    assert (r1.niveau, r1.z_bas_m, r1.z_haut_m) == ("Bureaux", 3.9, 5.4)


def test_une_facade_vitree_sans_baie_est_repartie_et_c_est_dit(lu):
    pignon = [b for b in lu.baies if b.mur == "pignon"]
    assert sum(b.aire_m2 for b in pignon) == pytest.approx(6.0, abs=0.01)
    assert {b.niveau for b in pignon} == {"Atelier", "Bureaux"} and {b.secteur for b in pignon} == {"O"}
    assert all(b.centre_m[0] == 0.0 and 0.0 < b.centre_m[1] < 12.0 for b in pignon)
    assert any("pignon : 6 m² de vitrage sans baie décrite" in m for m in lu.manques)


def test_le_vitrage_annonce_et_les_baies_decrites_se_comparent(lu):
    # 12 m² annoncés sur la rue, 9 m² de baies décrites : seules les baies décrites sont reprises, et c'est dit.
    assert sum(b.aire_m2 for b in lu.baies if b.mur == "rue") == pytest.approx(9.0)
    assert any("rue : 12 m² de vitrage annoncés, 9.0 m² de baies décrites" in m for m in lu.manques)


def test_la_provenance_est_gardee_et_ce_que_personne_n_a_dit_se_demande(lu):
    assert lu.provenances["facades[voisin].mitoyenne"] == "bd_topo"
    assert lu.provenances["baies[r1]"] == "dessinee" and lu.provenances["emprise_m"] == "dessinee"
    assert any(m.startswith("hauteur_d_etage_m : 3.0 supposé") for m in lu.manques)
    assert any(m.startswith("enveloppe.inertie : inconnue") for m in lu.manques)
    assert "la hauteur d'étage reste à mesurer" in lu.manques          # les manques du fichier sont repris


def test_ce_qui_n_est_pas_lu_est_dit_avec_la_ligne_a_ecrire(lu):
    non_lus = "\n".join(lu.non_lus)
    assert "niveau 0 : usage « stockage »" in non_lus
    assert 'usage = "bureau"' in non_lus and 'periode = "1975_1988"' in non_lus
    assert "type de chaque baie" in non_lus or "type" in non_lus


def test_une_facade_sans_trait_prend_le_cote_qui_regarde_vers_son_azimut():
    donnees = atelier_et_bureaux()
    del donnees["facades"][0]["segment_m"]
    lu = commun.depuis(donnees)
    r1 = next(b for b in lu.baies if b.identifiant == "r1")
    assert r1.centre_m[1] == 0.0 and r1.secteur == "S"
    # Le nord tourné vers x : c'est le côté x = 0 qui regarde au sud, et la façade s'y pose.
    donnees["repere"]["nord_deg"] = _v(90, "dessinee")
    r1 = next(b for b in commun.depuis(donnees).baies if b.identifiant == "r1")
    assert r1.centre_m[0] == 0.0 and r1.secteur == "S"
    # Un azimut que ne regarde aucun côté : la façade n'est pas placée, ses baies sont écartées, c'est dit.
    donnees["facades"][0]["azimut_deg"] = _v(225, "deduite")
    lu = commun.depuis(donnees)
    assert any("aucun côté de l'emprise ne regarde vers 225°" in m for m in lu.manques)
    assert not any(b.identifiant == "r1" for b in lu.baies)


def test_une_baie_placee_dans_l_espace_est_reprise_telle_quelle():
    donnees = atelier_et_bureaux()
    donnees["baies"] = [{"identifiant": "m1", "niveau": 1, "largeur_m": 1.2, "hauteur_m": 1.5, "aire_m2": 1.8,
                         "allege_m": 0.9, "azimut_deg": 180.0, "secteur": "S", "inclinaison_deg": 90,
                         "centre_m": [5.0, 0.0, 4.65], "normale_xy": [0, -1], "z_bas_m": 3.9, "z_haut_m": 5.4,
                         "mur": "Mur-01", "mur_exterieur": True, "provenance": "maquette"}]
    (baie,) = [b for b in commun.depuis(donnees).baies if b.identifiant == "m1"]
    assert (baie.centre_m, baie.normale_xy, baie.mur, baie.aire_m2) == ((5.0, 0.0, 4.65), (0, -1), "Mur-01", 1.8)


def test_sans_hauteur_d_etage_la_hauteur_du_batiment_se_partage():
    donnees = atelier_et_bureaux()
    del donnees["hauteur_d_etage_m"]
    donnees["hauteur_m"] = _v(7.0, "mesuree_lidar")
    lu = commun.depuis(donnees)
    assert lu.niveaux[1].plafond_m == pytest.approx(7.0)
    assert any("3.50 m, la hauteur du bâtiment (7 m) partagée en 2 niveaux" in m for m in lu.manques)


@pytest.mark.parametrize("abimer, attendu", [
    (lambda d: d.update(schema="autre"), "n'est pas un bâtiment commun"),
    (lambda d: d.update(version=2), "version 2"),
    (lambda d: d.update(empreinte_schema="0123456789abcdef"), "0123456789abcdef"),
    (lambda d: d.update(version=1, empreinte_schema="0000000000000000"), "6867d7997dbe0355, 920221dc9b39776b"),
    (lambda d: d["facades"][0]["azimut_deg"].pop("provenance"), "sans provenance"),
    (lambda d: d["facades"][0].update(azimut_deg=_v(400, "deduite")), "n'est pas un azimut"),
    (lambda d: d["baies"][0].update(niveau=5), "hors des 2 niveaux"),
    (lambda d: d.update(nombre_de_niveaux=_v(3)), "2 niveaux décrits pour nombre_de_niveaux = 3"),
    (lambda d: d.pop("emprise_m"), "aucune emprise"),
    (lambda d: d["repere"].update(axes="x_est_y_sud"), "repère"),
    (lambda d: d.update(usage={"valeur": None, "provenance": "supposee"}), "je_ne_sais_pas"),
])
def test_ce_qui_ne_peut_pas_etre_lu_est_refuse_en_disant_pourquoi(abimer, attendu):
    donnees = copy.deepcopy(atelier_et_bureaux())
    abimer(donnees)
    with pytest.raises(commun.BatimentNonLu, match=attendu):
        commun.depuis(donnees)


def test_un_fichier_qui_n_est_pas_du_json_est_refuse(tmp_path):
    fichier = tmp_path / "b.json"
    fichier.write_text("{pas du json", encoding="utf-8")
    with pytest.raises(commun.BatimentNonLu, match="pas du JSON"):
        commun.lire(fichier)
    fichier.write_text(json.dumps(atelier_et_bureaux()), encoding="utf-8")
    assert commun.lire(fichier).niveaux[0].chauffe is False


# --- La version du format suivie par ce lecteur

def test_l_empreinte_se_calcule_comme_celle_du_validateur_du_format():
    # Un schéma réduit : l'empreinte ignore sa propre clé et l'ordre des clés.
    schema = {"b": 1, "a": [1, 2], "x-empreinte": "peu importe"}
    assert commun.empreinte_du_schema(schema) == commun.empreinte_du_schema({"a": [1, 2], "b": 1})
    assert len(commun.empreinte_du_schema(schema)) == 16 and commun.EMPREINTE_LUE == "6867d7997dbe0355"


SCHEMA_DE_REFERENCE = os.environ.get("RAYFLECT_SCHEMA_BATIMENT_COMMUN")


@pytest.mark.skipif(not SCHEMA_DE_REFERENCE, reason="RAYFLECT_SCHEMA_BATIMENT_COMMUN ne désigne pas le schéma de "
                                                    "référence sur ce poste")
def test_le_schema_de_reference_est_celui_que_ce_lecteur_sait_lire():
    """Tombe si le format change sans que ce lecteur suive : lire ce qui a changé, puis mettre EMPREINTE_LUE à jour."""
    schema = json.loads(Path(SCHEMA_DE_REFERENCE).read_text(encoding="utf-8"))
    assert schema.get("x-empreinte") == commun.empreinte_du_schema(schema)
    assert commun.empreinte_du_schema(schema) == commun.EMPREINTE_LUE
    # Les empreintes acceptées en plus sont celles que le format déclare antérieures, et rien d'autre.
    assert set(commun.EMPREINTES_ACCEPTEES) - {commun.EMPREINTE_LUE} <= set(schema.get("x-empreintes-anterieures", []))


# --- Du relevé au modèle : le niveau non chauffé et le mur mitoyen

def _faces(modele, rang):
    piece = modele.rooms[rang]
    return {(f.type.name, f.boundary_condition.name) for f in piece.faces}, piece


def test_le_plancher_d_un_niveau_non_chauffe_devient_une_paroi_entre_les_2_zones(lu):
    modele, rendu = conversion.convertir(lu)
    assert rendu.non_chauffees == [modele.rooms[0].identifier]
    bas, atelier = _faces(modele, 0)
    haut, bureaux = _faces(modele, 1)
    assert ("Floor", "Ground") in bas and ("RoofCeiling", "Surface") in bas
    assert ("Floor", "Surface") in haut and ("RoofCeiling", "Outdoors") in haut
    plafond = next(f for f in atelier.faces if f.type.name == "RoofCeiling")
    assert plafond.boundary_condition.boundary_condition_objects[-1] == bureaux.identifier


def test_tous_chauffes_les_niveaux_restent_sans_echange_entre_eux():
    donnees = atelier_et_bureaux()
    del donnees["niveaux"][0]["chauffage"]
    modele, rendu = conversion.convertir(commun.depuis(donnees))
    assert rendu.non_chauffees == []
    assert ("RoofCeiling", "Adiabatic") in _faces(modele, 0)[0] and ("Floor", "Adiabatic") in _faces(modele, 1)[0]


def test_le_mur_mitoyen_n_echange_pas_avec_le_dehors_et_ne_recoit_pas_de_baie(lu):
    modele, rendu = conversion.convertir(lu)
    assert rendu.murs_mitoyens == 2 and rendu.aire_mitoyenne_m2 == pytest.approx(2 * 12 * 3.0)
    for piece in modele.rooms:
        est = [f for f in piece.faces if f.type.name == "Wall" and round(f.azimuth) == 90]
        assert [f.boundary_condition.name for f in est] == ["Adiabatic"] and not est[0].apertures
    assert rendu.baies_reposees == len(lu.baies) and not rendu.baies_ecartees
    assert modele.check_all(raise_exception=False) == ""


def test_le_batiment_par_ses_chiffres_dit_aussi_le_non_chauffe_et_le_mitoyen():
    r = releve_par_chiffres.lire(24, 12, niveaux=2, vitrage_m2={"S": 20}, niveaux_non_chauffes=[0], mitoyennes=["E"])
    assert [n.chauffe for n in r.niveaux] == [False, True] and r.mitoyens_m == [((24.0, 0.0), (24.0, 12.0))]
    assert r.n_murs_exterieurs == 6
    for faux, attendu in ((dict(niveaux_non_chauffes=[2]), "niveaux_non_chauffes"),
                          (dict(mitoyennes=["SE"]), "aucune façade ne regarde vers SE"),
                          (dict(mitoyennes=["S"]), "mitoyenne : elle ne porte pas de vitrage"),
                          (dict(mitoyennes="E"), "une liste d'orientations")):
        with pytest.raises(releve_par_chiffres.ChiffresInvalides, match=attendu):
            releve_par_chiffres.lire(24, 12, niveaux=2, vitrage_m2={"S": 20}, **faux)


def test_la_repartition_des_baies_n_a_pas_change():
    # 12 m² sur 24 m : 6 baies de 1,43 m, et sur 2 m : un bandeau plafonné.
    assert releve_par_chiffres.repartir(12.0, 24.0, 3.0) == (6, pytest.approx(12.0 / 6 / 1.4), 1.4, 1.0, False)
    nombre, large, haut, allege, plafonnee = releve_par_chiffres.repartir(12.0, 2.0, 3.0)
    assert (nombre, plafonnee) == (1, True) and allege + haut == pytest.approx(3.0 - 0.10)


@pytest.mark.parametrize("ou, cle, valeur, attendu", [
    ("enveloppe", "periode", "1975_1988", 'à reporter par periode = "1975_1988"'),
    ("enveloppe", "periode", "avant_1975", "pas d'équivalent ici ; choisir periode parmi avant_1948, 1949_1974"),
    ("enveloppe", "inertie", "dure", "pas d'équivalent ici ; choisir inertie dans [parois] parmi lourde, legere"),
    ("enveloppe", "vitrage", "double", 'à reporter par vitrage = "double" dans [parois]'),
    ("chauffage", "systeme", "gaz", 'à reporter par chauffage = "gaz" dans [energie]'),
    ("chauffage", "systeme", "pac_air_eau", 'chauffage = "pac" dans [energie] ; le type de pompe à chaleur'),
    ("chauffage", "systeme", "aucun", "pas de table [energie]"),
    ("chauffage", "systeme", "geothermie", "pas d'équivalent ici ; choisir chauffage dans [energie] parmi gaz"),
])
def test_une_ligne_proposee_pour_l_etude_est_une_ligne_que_l_etude_accepte(ou, cle, valeur, attendu):
    donnees = atelier_et_bureaux()
    donnees.setdefault(ou, {})[cle] = _v(valeur)
    lignes = [ligne for ligne in commun.depuis(donnees).non_lus if ligne.startswith(f"{ou}.{cle} ")]
    assert len(lignes) == 1 and attendu in lignes[0], lignes


def test_chaque_ligne_proposee_se_relit_dans_un_fichier_d_etude(tmp_path):
    """Les lignes « à reporter par » de l'exemple, écrites telles quelles dans une étude, sont acceptées."""
    import re

    from rayflect import etude

    donnees = atelier_et_bureaux()
    donnees["enveloppe"].update(vitrage=_v("double"), inertie=_v("lourde"))
    donnees["chauffage"] = {"systeme": _v("pac_eau_eau")}
    premier, parois, energie = [], [], []
    for ligne in commun.depuis(donnees).non_lus:
        trouve = re.search(r"à reporter par (\w+ = \"\w+\")( dans \[(\w+)\])?", ligne)
        if trouve:
            {None: premier, "parois": parois, "energie": energie}[trouve.group(3)].append(trouve.group(1))
    assert len(premier) == 2 and len(parois) == 2 and energie == ['chauffage = "pac"']
    fichier = tmp_path / "etude.toml"
    fichier.write_text('maquette = "a.json"\n' + "\n".join(premier) + "\n[parois]\n" + "\n".join(parois)
                       + "\n[energie]\n" + "\n".join(energie) + "\n", encoding="utf-8")
    lue = etude.lire(fichier)
    assert (lue.usage, lue.periode, lue.parois.vitrage, lue.parois.inertie) == ("bureau", "1975_1988", "double", "lourde")
    assert lue.energie.chauffage == "pac"


@pytest.mark.parametrize("empreinte", ["6867d7997dbe0355", "920221dc9b39776b"])
def test_un_fichier_de_l_une_ou_l_autre_empreinte_se_lit(empreinte):
    donnees = atelier_et_bureaux()
    donnees["empreinte_schema"] = empreinte
    assert commun.depuis(donnees).niveaux[0].chauffe is False


def test_l_inertie_moyenne_se_demande_et_n_est_jamais_ramenee_a_lourde_ou_legere():
    donnees = atelier_et_bureaux()
    donnees["enveloppe"]["inertie"] = _v("moyenne")
    lu = commun.depuis(donnees)
    (manque,) = [m for m in lu.manques if m.startswith("inertie « moyenne »")]
    assert 'inertie = "lourde" ou "legere" dans [parois]' in manque
    # Aucune ligne « à reporter » ne la propose, ni comme moyenne, ni comme une autre valeur.
    assert not [ligne for ligne in lu.non_lus if ligne.startswith("enveloppe.inertie")]
