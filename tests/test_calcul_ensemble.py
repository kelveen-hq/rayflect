"""Lancer plusieurs calculs en même temps, et reconnaître l'année dans les résultats. Sans lancer de calcul."""

import threading

import pytest

from rayflect import etude, extensions, moteur, puissance


def test_les_resultats_reviennent_dans_l_ordre_du_lot():
    assert moteur.ensemble(lambda x: x * x, [3, 1, 2], 3) == [9, 1, 4]
    assert moteur.ensemble(lambda x: x * x, [3, 1, 2], 1) == [9, 1, 4]
    assert moteur.ensemble(lambda x: x, [], 4) == []


def test_les_calculs_tournent_bien_en_meme_temps():
    # Chacun attend l'autre : l'un après l'autre, la barrière ne s'ouvrirait jamais.
    barriere = threading.Barrier(2, timeout=10)
    assert moteur.ensemble(lambda x: barriere.wait() >= 0, [1, 2], 2) == [True, True]


def test_une_erreur_d_un_calcul_remonte_telle_quelle():
    def faire(x):
        if x == 2:
            raise etude.EtudeInvalide("scénario « 2 » : calcul fautif")
        return x

    with pytest.raises(etude.EtudeInvalide, match="scénario « 2 »"):
        moteur.ensemble(faire, [1, 2, 3], 3)


def test_le_poste_lance_au_moins_un_calcul():
    assert moteur.calculs_en_meme_temps() >= 1


def test_l_etude_dit_combien_de_calculs_lancer_ensemble_et_refuse_une_valeur_folle(tmp_path):
    base = 'usage = "bureau"\n{}[batiment]\nlongueur_m = 20.0\nlargeur_m = 10.0\nniveaux = 2\nhauteur_d_etage_m = 3.0\n'
    fichier = tmp_path / "etude.toml"
    fichier.write_text(base.format(""), encoding="utf-8")
    assert etude.lire(fichier).calculs_en_meme_temps is None
    fichier.write_text(base.format("calculs_en_meme_temps = 3\n"), encoding="utf-8")
    assert etude.lire(fichier).calculs_en_meme_temps == 3
    for folle in ("0", "-2", "1.5", "true", "500"):
        fichier.write_text(base.format(f"calculs_en_meme_temps = {folle}\n"), encoding="utf-8")
        with pytest.raises(etude.EtudeInvalide, match="calculs_en_meme_temps"):
            etude.lire(fichier)


class _Serie:
    def __init__(self, heures):
        self.values = [1.0] * heures


class _Resultats:
    def __init__(self, **longueurs):
        self._longueurs = longueurs

    def data_collections_by_output_name(self, nom):
        return [_Serie(n) for n in self._longueurs.get(nom, [])]


def test_l_annee_et_le_jour_de_base_se_reconnaissent():
    annee = puissance.Annee(_Resultats(chauffage=[8760, 24, 8760, 24], absente=[]))
    annee.verifier(("chauffage", "absente"))            # une sortie que le calcul n'a pas rendue n'est pas une faute
    assert [len(s.values) for s in annee.data_collections_by_output_name("chauffage")] == [8760, 8760]
    assert [len(s.values) for s in annee.du_jour_de_base("chauffage")] == [24, 24]
    puissance.Annee(_Resultats(chauffage=[8784])).verifier(("chauffage",))      # une année bissextile


def test_une_serie_qui_n_est_ni_l_annee_ni_le_jour_de_base_est_refusee():
    # Un calcul sur 6 mois se lirait comme un jour de base : ses kWh sortiraient des totaux sans rien dire.
    with pytest.raises(ValueError, match="4380 heures"):
        puissance.Annee(_Resultats(chauffage=[4380, 24])).verifier(("chauffage",))
    with pytest.raises(ValueError, match="pas rendu l'année"):
        puissance.Annee(_Resultats(chauffage=[24])).verifier(("chauffage",))


def test_un_type_etendu_peut_declarer_une_retouche_et_une_lecture():
    def poser(modele, element, contexte):
        return None

    def retoucher(texte, element, contexte):
        return texte

    try:
        extensions.enregistrer("essai_de_retouche", dict, poser, retoucher=retoucher)
        fiche = extensions.types()["essai_de_retouche"]
        assert fiche.retoucher is retoucher and fiche.lire is None
        extensions.enregistrer("essai_de_retouche", dict, poser, retoucher=retoucher)       # à l'identique : rien
        with pytest.raises(ValueError, match="déjà déclaré"):
            extensions.enregistrer("essai_de_retouche", dict, poser)                        # la retouche a changé
    finally:
        extensions.retirer("essai_de_retouche")
