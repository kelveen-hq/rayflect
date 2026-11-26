"""Le bilan de chaleur poste par poste, sans calcul : les côtés, le rangement, le compte rendu."""

import pytest

from rayflect import bilan


@pytest.mark.parametrize("azimut, cote", [(0, "N"), (22.4, "N"), (22.6, "NE"), (90, "E"), (180, "S"), (200, "S"),
                                          (247.6, "O"), (270, "O"), (315, "NO"), (337.6, "N"), (360, "N"), (-90, "O")])
def test_le_cote_d_une_facade(azimut, cote):
    assert bilan.secteur(azimut) == cote


def test_les_sorties_sont_demandees_par_tableaux_mensuels():
    texte = bilan.texte_des_sorties()
    assert "Output:Variable" not in texte          # une sortie par mois casserait la lecture des heures
    assert texte.count("Output:Table:Monthly") == len(bilan.SORTIES)
    assert f"{bilan.TABLEAU}0,\n  2,\n  {bilan.CONDUCTION},\n  SumOrAverage;" in texte


def _mois(hiver: int, ete: int) -> list:
    """12 mois : `hiver` par mois de novembre à mars, `ete` de juin à août, rien sinon."""
    return [hiver if m in bilan.HIVER else ete if m in bilan.ETE else 0 for m in range(1, 13)]


def test_le_rangement_et_l_ecart():
    postes = {("chauffage", None): _mois(30, 0), ("murs", "S"): _mois(-10, 2), ("murs", "N"): _mois(-15, -1),
              ("baies, soleil", "S"): _mois(5, 8), ("apports intérieurs", None): _mois(4, 4),
              ("toiture", None): _mois(-14, -13), ("infiltrations", None): [0.1] * 12}
    rendu = bilan._rendre(postes)
    assert [(ligne["poste"], ligne["cote"]) for ligne in rendu["postes"]] == [
        ("murs", "N"), ("murs", "S"), ("baies, soleil", "S"), ("toiture", None), ("apports intérieurs", None),
        ("chauffage", None)]                        # les infiltrations, sous le kWh chaque mois, ne sont pas dites
    assert rendu["ecart_kwh"] == 1                  # la somme des postes : 1,2 kWh, dont les infiltrations
    assert 0 < rendu["ecart_part"] < 0.01


def test_le_compte_rendu_dit_les_principaux_postes_et_ce_qui_change():
    def rendre(soleil_sud: int) -> dict:
        return bilan._rendre({("chauffage", None): _mois(30, 0), ("murs", "N"): _mois(-20, -2),
                              ("baies, soleil", "S"): _mois(5, soleil_sud), ("toiture", None): _mois(-15, -soleil_sud),
                              ("apports intérieurs", None): _mois(0, 2)})
    lignes = bilan.dire({"sans": rendre(10), "casquette": rendre(4)}, ["sans", "casquette"])
    texte = "\n".join(lignes)
    assert "en hiver, la chaleur part surtout par : murs N (-100), toiture (-75)" in texte
    assert "en été, la chaleur vient surtout de : baies, soleil S (+30), apports intérieurs (+6)" in texte
    assert "« casquette » change surtout : baies, soleil S (-18), toiture (+18)" in texte
    assert "À VÉRIFIER" not in texte


def test_un_bilan_qui_ne_se_referme_pas_est_signale():
    ouvert = bilan._rendre({("chauffage", None): _mois(30, 0), ("murs", "N"): _mois(-20, 0)})
    texte = "\n".join(bilan.dire({"sans": ouvert}, ["sans"]))
    assert "À VÉRIFIER : le bilan ne se referme pas" in texte and "« sans »" in texte
