"""Le poids des hypothèses prises par défaut : chacune divisée par 2 puis doublée, sur des bureaux à Bordeaux.

Une hypothèse qu'on ne donne pas est prise par défaut, sourcée (rayflect.hypotheses). Ce banc dit combien elle pèse :
de combien le chauffage et les degrés-heures bougent quand on la divise par 2 ou la double [H : un facteur 2, l'ordre
de l'incertitude d'une valeur par défaut sur un bâtiment qu'on ne connaît pas]. L'inertie passe de lourde à légère.
Le compte rendu d'une étude cite ces poids pour chaque hypothèse lourde qu'elle n'a pas reçue (etude._hypotheses_lourdes).

LE CAS : des bureaux de 20 × 10 m sur 2 niveaux, de 1975 à 1988, à Bordeaux (année type de PVGIS), 24 m² de vitrage
au sud, 8 au nord, 10 à l'ouest ; le cas de la consolidation des hypothèses.

Usage : python verification/poids_des_hypotheses.py [dossier de sortie]   (année type de PVGIS, mise en cache)
"""

from __future__ import annotations

import dataclasses
import json
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from rayflect import etude, hypotheses as hyp, lieu as lieux

LONGUEUR, LARGEUR, NIVEAUX, HAUTEUR = 20.0, 10.0, 2, 3.0
ETUDE = f'''usage = "bureau"
periode = "1975_1988"
ombres_tous_les_n_jours = 30
calculs_en_meme_temps = 1
[lieu]
latitude = 44.841
longitude = -0.570
[batiment]
longueur_m = {LONGUEUR}
largeur_m = {LARGEUR}
niveaux = {NIVEAUX}
hauteur_d_etage_m = {HAUTEUR}
vitrage_m2 = {{ S = 24.0, N = 8.0, O = 10.0 }}
[[scenario]]
nom = "tel quel"
'''


def _n50_equivalent(q4pa: float) -> float:
    """Le n50 qui donne au bâtiment les infiltrations de la perméabilité par défaut (même formule 3CL)."""
    volume = LONGUEUR * LARGEUR * NIVEAUX * HAUTEUR
    exposee = 2 * (LONGUEUR + LARGEUR) * NIVEAUX * HAUTEUR + LONGUEUR * LARGEUR      # murs et toit, sans le plancher bas
    return hyp.debit_de_fuite_m3_s_par_m2(q4pa) * 3600.0 * exposee / (hyp.COEFFICIENT_DE_PROTECTION_E * volume)


def variantes(defaut: dict, apports: float) -> dict:
    """{nom : (parois changées, usage changé)}."""
    n50 = _n50_equivalent(defaut["q4pa"][0])
    rendu = {"etancheite_x0.5": ({"n50": n50 * 0.5}, {}), "etancheite_x2": ({"n50": n50 * 2}, {}),
             "apports_x0.5": ({}, {"apports_w_m2": apports * 0.5}), "apports_x2": ({}, {"apports_w_m2": apports * 2}),
             "inertie_legere": ({"inertie": "legere"}, {})}
    for cle in ("u_mur", "u_toit", "u_plancher"):
        rendu[f"{cle}_x0.5"] = ({cle: defaut[cle][0] * 0.5}, {})
        rendu[f"{cle}_x2"] = ({cle: defaut[cle][0] * 2}, {})
    return rendu


def _indicateurs(bilan: dict) -> dict:
    pieces = bilan["confort_d_ete"]["pieces"]
    return {"chauffage_kwh": bilan["chauffage_kwh"]["tel quel"],
            "dh": max(v["tel quel"]["dh"] for v in pieces.values())}


def calculer(sortie: Path) -> dict:
    lieux.completer = lambda lieu, *a, **k: lieu
    sortie.mkdir(parents=True, exist_ok=True)
    (sortie / "etude.toml").write_text(ETUDE, encoding="utf-8")
    base = etude.lire(sortie / "etude.toml")
    defaut = hyp.parois_retenues("1975_1988", hyp.Parois(), "H2")
    apports = hyp.USAGES["bureau"].apports_w_m2

    def jouer(nom, parois, usage):
        lue = dataclasses.replace(base, parois=dataclasses.replace(base.parois, **parois),
                                  reglages_d_usage={**base.reglages_d_usage, **usage})
        return nom, _indicateurs(etude.calculer(lue, sortie / nom, dire=lambda _t: None))

    cas = {"defaut": ({}, {})} | variantes(defaut, apports)
    with ThreadPoolExecutor(max_workers=4) as file:
        rendus = dict(file.map(lambda e: jouer(e[0], *e[1]), cas.items()))
    ref = rendus["defaut"]
    poids = {nom: {cle: round(v / ref[cle] - 1.0, 3) if ref[cle] else None for cle, v in ind.items()}
             for nom, ind in rendus.items() if nom != "defaut"}
    rendu = {"defaut": ref, "poids": poids, "n50_equivalent": round(_n50_equivalent(defaut["q4pa"][0]), 3)}
    (sortie / "poids_des_hypotheses.json").write_text(json.dumps(rendu, indent=2, ensure_ascii=False), encoding="utf-8")
    return rendu


def main(argv: list) -> int:
    sortie = Path(argv[1]).resolve() if len(argv) > 1 else Path("verification/sorties/poids_des_hypotheses").resolve()
    rendu = calculer(sortie)
    print(f"par défaut : {rendu['defaut']} ; n50 équivalent {rendu['n50_equivalent']}")
    for nom, p in rendu["poids"].items():
        print(f"{nom:<20} chauffage {p['chauffage_kwh'] * 100:+.0f} %   degrés-heures {p['dh'] * 100:+.0f} %")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
