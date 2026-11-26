"""Le lieu d'une étude : l'ordre de confiance, et ce qui est dit quand les sources se contredisent.

Aucun essai ne sort sur le réseau : la réponse du géocodeur est rejouée.
"""

from types import SimpleNamespace

import pytest

from rayflect import lieu

BOURSE = {"features": [{"geometry": {"coordinates": [-0.569808, 44.840994]},
                        "properties": {"label": "1 Place de la Bourse 33000 Bordeaux", "score": 0.97,
                                       "type": "housenumber"}}]}


def _reponse(monkeypatch, reponse):
    monkeypatch.setattr(lieu, "_demander", lambda adresse, delai_s: reponse)


def _maquette(latitude, longitude):
    return SimpleNamespace(latitude=latitude, longitude=longitude)


def test_une_adresse_donne_un_lieu(monkeypatch):
    _reponse(monkeypatch, BOURSE)
    trouve = lieu.geocoder("1 place de la Bourse  Bordeaux")
    assert (trouve.latitude, trouve.longitude) == (44.840994, -0.569808)
    assert trouve.origine == "adresse" and not trouve.remarques


def test_une_adresse_inconnue_se_demande(monkeypatch):
    _reponse(monkeypatch, {"features": []})
    with pytest.raises(lieu.LieuIntrouvable, match="non reconnue"):
        lieu.geocoder("nulle part")


def test_une_ressemblance_faible_est_refusee(monkeypatch):
    _reponse(monkeypatch, {"features": [{"geometry": {"coordinates": [2.0, 48.0]},
                                         "properties": {"label": "Rue X", "score": 0.3, "type": "street"}}]})
    with pytest.raises(lieu.LieuIntrouvable, match="30 %"):
        lieu.geocoder("rue ixe")


def test_une_adresse_a_la_commune_pres_est_signalee(monkeypatch):
    _reponse(monkeypatch, {"features": [{"geometry": {"coordinates": [-0.57, 44.84]},
                                         "properties": {"label": "Bordeaux", "score": 0.9,
                                                        "type": "municipality"}}]})
    assert "à la commune seulement" in lieu.geocoder("Bordeaux").remarques[0]


def test_un_geocodeur_muet_renvoie_vers_les_coordonnees(monkeypatch):
    def panne(adresse, delai_s):
        raise OSError("hors ligne")
    monkeypatch.setattr(lieu, "_demander", panne)
    with pytest.raises(lieu.LieuIntrouvable, match="latitude et longitude"):
        lieu.geocoder("1 place de la Bourse Bordeaux")


def test_l_adresse_passe_avant_la_maquette_et_l_ecart_est_dit(monkeypatch):
    _reponse(monkeypatch, BOURSE)
    choisi = lieu.choisir(adresse="1 place de la Bourse Bordeaux", releve=_maquette(48.8566, 2.3522))
    assert choisi.origine == "adresse"
    assert "km de là" in choisi.remarques[0] and "ignorée" in choisi.remarques[0]


def test_une_maquette_au_bon_endroit_ne_dit_rien(monkeypatch):
    _reponse(monkeypatch, BOURSE)
    assert not lieu.choisir(adresse="1 place de la Bourse Bordeaux", releve=_maquette(44.8412, -0.5695)).remarques


def test_les_coordonnees_passent_avant_la_maquette():
    choisi = lieu.choisir(coordonnees=(44.84, -0.57), releve=_maquette(48.8566, 2.3522))
    assert choisi.origine == "coordonnées" and (choisi.latitude, choisi.longitude) == (44.84, -0.57)


def test_la_maquette_seule_sert_de_repli_non_confirme():
    choisi = lieu.choisir(releve=_maquette(44.84, -0.57))
    assert choisi.origine == "maquette" and "non confirmé" in choisi.remarques[0]


@pytest.mark.parametrize("releve", [None, _maquette(None, None), _maquette(0.0, 0.0)])
def test_sans_rien_le_lieu_se_demande(releve):
    with pytest.raises(lieu.LieuIntrouvable, match="À demander"):
        lieu.choisir(releve=releve)


def test_des_coordonnees_hors_du_globe_sont_refusees():
    with pytest.raises(lieu.LieuIntrouvable, match="hors du globe"):
        lieu.choisir(coordonnees=(144.8, -0.57))


def test_la_distance_paris_bordeaux():
    assert lieu.distance_m((48.8566, 2.3522), (44.8378, -0.5792)) == pytest.approx(499_000, rel=0.01)
