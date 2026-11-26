"""Le poids des hypothèses lourdes prises par défaut : dit quand elles manquent, tu quand elles sont données."""

from rayflect import etude, hypotheses as hyp


def _lourdes(parois=hyp.Parois(), donnees=(), usage=None):
    return hyp.hypotheses_lourdes_non_donnees("1975_1988", parois, "H2", donnees, usage or {})


def test_tout_par_defaut_cite_les_5_hypotheses_lourdes():
    lignes = _lourdes()
    assert len(lignes) == 5
    assert lignes[0].startswith("hypothèse prise par défaut, faute d'être donnée : l'étanchéité à l'air. Elle pèse lourd "
                                "(divisée par 2 ou doublée : chauffage de -18 à +38 %")
    assert all("[D : verification/poids_des_hypotheses.py" in ligne for ligne in lignes)
    assert any("l'inertie. Elle pèse lourd (légère plutôt que lourde : chauffage +15 %, degrés-heures +91 %" in ligne
               for ligne in lignes)


def test_une_hypothese_donnee_n_est_plus_citee():
    donnees = hyp.Parois(n50=3.0, u_mur=0.4, isolant_du_toit_cm=10.0, inertie="lourde")
    lignes = _lourdes(donnees, donnees=("n50", "u_mur", "isolant_du_toit_cm", "inertie"), usage={"apports_w_m2": 15.0})
    assert lignes == []


def test_le_plancher_ne_pese_pas_assez_pour_etre_cite():
    assert all("plancher" not in ligne for ligne in _lourdes())


def test_l_etude_garde_les_cles_de_parois_ecrites(tmp_path):
    fichier = tmp_path / "etude.toml"
    fichier.write_text('usage = "bureau"\n[batiment]\nlongueur_m = 10.0\nlargeur_m = 10.0\n[parois]\ninertie = "legere"\n',
                       encoding="utf-8")
    assert etude.lire(fichier).parois_donnees == ("inertie",)
