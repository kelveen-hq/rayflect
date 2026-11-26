"""Les sondes géothermiques : la fiche, la charge sur le sol, le fichier de la boucle et le bilan. Sans calcul."""

import pytest

from rayflect import etude, sondes


def test_une_fiche_impossible_est_refusee():
    for faux in (dict(rangees=(0, 2)), dict(rangees=(2,)), dict(rangees=(2, 40)), dict(profondeur_m=5.0),
                 dict(froid="nappe"), dict(cop_chauffage=1.0), dict(annees=0), dict(annees=2.5), dict(antigel=0.9),
                 dict(conductivite_du_sol_w_m_k=0.0), dict(entraxe_m=True)):
        with pytest.raises(ValueError):
            sondes.Sondes(**faux)
    champ = sondes.Sondes(rangees=(2, 3), profondeur_m=80.0)
    assert champ.nombre == 6 and champ.longueur_m == 480.0


def test_la_charge_sur_le_sol_suit_la_machine():
    chauffage, froid = [4000.0, 0.0, 0.0], [0.0, 3000.0, 0.0]
    # Une pompe à chaleur de COP 4 prend au sol les 3 quarts de ce qu'elle donne ; le reste est de l'électricité.
    assert sondes.charge_sur_le_sol(chauffage, froid, sondes.Sondes()) == [3000.0, -3000.0, 0.0]
    # Une machine de froid rend au sol le froid fait, plus sa propre électricité.
    assert sondes.charge_sur_le_sol(chauffage, froid, sondes.Sondes(froid="machine", eer_froid=3.0))[1] == -4000.0
    assert sondes.charge_sur_le_sol(chauffage, froid, sondes.Sondes(froid="aucun"))[1] == 0.0
    assert sondes.charge_sur_le_sol(chauffage, froid, sondes.Sondes(cop_chauffage=2.0))[0] == 2000.0


def test_le_fichier_de_la_boucle_porte_le_champ_la_charge_et_les_annees(tmp_path):
    champ = sondes.Sondes(rangees=(2, 3), profondeur_m=120.0, entraxe_m=7.0, annees=8, debit_l_s_par_sonde=0.25)
    texte = sondes.texte(champ, tmp_path / "charge.csv", 13.5, 6.0)
    assert "grille, sonde, 2, 3, 7;" in texte and "sonde, 1, 120," in texte
    assert "annees, 1, 1, 2001, 12, 31, 2008," in texte
    assert "0.001500" in texte                                  # 6 sondes à 0,25 litre par seconde
    assert "sol, 2, 2000, 1100, 13.500, 6.000, 30;" in texte    # capacité de 2,2 MJ/m3.K répartie sur 2 000 kg/m3
    assert "eau_glycolee, PropyleneGlycol, , 0.25;" in texte and "UserDefinedFluidType, eau_glycolee" in texte
    assert str((tmp_path / "charge.csv").resolve()) in texte
    sans_antigel = sondes.texte(sondes.Sondes(antigel=0.0), tmp_path / "charge.csv", 13.5, 6.0)
    assert "Glycol" not in sans_antigel and "boucle, Water, , commande" in sans_antigel


def _retours(annees, mini, maxi, glisse=0.0):
    """Des retours du sol en dents de scie : `mini` en première moitié d'année, `maxi` ensuite."""
    suite = []
    for an in range(annees):
        suite += [mini + glisse * an] * 4380 + [maxi + glisse * an] * 4380
    return suite


def test_le_bilan_dit_la_derive_le_gel_et_le_geocooling():
    champ = sondes.Sondes(rangees=(1, 2), annees=3)
    chauffage = [6000.0] * 4380 + [0.0] * 4380
    froid = [0.0] * 4380 + [2000.0] * 4380
    rendu = sondes.bilan(champ, _retours(3, 4.0, 15.0, glisse=-1.5), chauffage, froid, 13.0)
    assert rendu["longueur_m"] == 200.0 and rendu["pris_au_sol_kwh_an"] == 19710 and rendu["rendu_au_sol_kwh_an"] == 8760
    assert rendu["pointe_prise_w_m"] == 22.5 and rendu["pointe_rendue_w_m"] == 10.0
    assert rendu["premiere_annee"]["retour_du_sol_min_c"] == 4.0 and rendu["derniere_annee"]["retour_du_sol_min_c"] == 1.0
    assert rendu["derive_du_retour_moyen_k"] == -3.0
    assert rendu["geocooling_part_du_froid_servie"] == 1.0          # 12 °C la dernière année : assez froid
    assert any("se refroidit de 3 K en 3 ans" in ligne for ligne in rendu["a_savoir"])
    assert not any("gèle" in ligne or "antigel" in ligne for ligne in rendu["a_savoir"])
    # La même boucle sans antigel, à 1 °C au plus froid : le champ est dit trop court.
    sans = sondes.bilan(sondes.Sondes(rangees=(1, 2), annees=3, antigel=0.0), _retours(3, 4.0, 15.0, glisse=-1.5),
                        chauffage, froid, 13.0)
    assert any("sans antigel" in ligne for ligne in sans["a_savoir"])
    # Un retour à 20 °C l'été : le géocooling ne sert plus rien, et c'est dit.
    chaud = sondes.bilan(champ, _retours(3, 8.0, 20.0), chauffage, froid, 13.0)
    assert chaud["geocooling_part_du_froid_servie"] == 0.0 and any("géocooling" in ligne for ligne in chaud["a_savoir"])
    assert chaud["derive_du_retour_moyen_k"] == 0.0
    lignes = sondes.dire(chaud)
    assert lignes[0].startswith("2 sondes, 200 m en tout") and any(ligne.startswith("À SAVOIR") for ligne in lignes)


def test_un_seul_champ_de_sondes_par_scenario(tmp_path):
    fichier = tmp_path / "etude.toml"
    element = '[[scenario.element]]\ntype = "sondes"\n'
    fichier.write_text('maquette = "a.ifc"\n[[scenario]]\nnom = "s"\n' + element + element, encoding="utf-8")
    with pytest.raises(etude.EtudeInvalide, match="un seul élément « sondes »"):
        etude.lire(fichier)


def test_une_charge_qui_n_est_pas_une_annee_est_refusee(tmp_path):
    with pytest.raises(ValueError, match="8760 attendues"):
        sondes.simuler(sondes.Sondes(), [0.0] * 24, tmp_path / "x.epw", tmp_path)


def test_l_etude_lit_des_sondes(tmp_path):
    fichier = tmp_path / "etude.toml"
    fichier.write_text('maquette = "a.ifc"\n[[scenario]]\nnom = "sondes"\n[[scenario.element]]\ntype = "sondes"\n'
                       'rangees = [2, 4]\nprofondeur_m = 90\nfroid = "machine"\n', encoding="utf-8")
    (scenario,) = etude.lire(fichier).scenarios
    assert scenario.elements == [sondes.Sondes(rangees=(2, 4), profondeur_m=90, froid="machine")]
    fichier.write_text('maquette = "a.ifc"\n[[scenario]]\nnom = "s"\n[[scenario.element]]\ntype = "sondes"\n'
                       'froid = "nappe"\n', encoding="utf-8")
    with pytest.raises(etude.EtudeInvalide, match="geocooling, machine, aucun"):
        etude.lire(fichier)
