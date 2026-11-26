"""Un essai de réponse thermique simulé : la boucle de sol rend-elle la conductivité qu'on lui a donnée ?

Sur un chantier, on mesure la conductivité du sol en injectant une puissance constante dans une sonde et en
suivant la température de l'eau : après les premières heures, elle monte comme le logarithme du temps, et sa
pente ne dépend que de la puissance par mètre et de la conductivité du sol (source linéaire infinie) :

    T(t) = T_sol + q . [ R_forage + ( ln(4 a t / r²) - 0,5772 ) / (4 pi k) ]      d'où      k = q / (4 pi pente)

    q : puissance par mètre de sonde ; a = k / capacité : la diffusivité du sol ; r : le rayon du forage.

Ce que l'essai prouve : que le montage de `rayflect.sondes` (pompe, champ, charge, lecture des résultats) est
bien branché, signes et unités compris, et que le modèle de sondes d'EnergyPlus suit la loi attendue pour une
sonde seule : la conductivité retrouvée sur la pente doit être celle donnée. Il le fait pour 3 sols.

Ce qu'il ne prouve pas : la résistance du forage, qui est rendue pour information (elle dépend du coulis et du
tube, et aucune valeur extérieure ne lui est comparée ici) ; l'influence des sondes entre elles dans un champ ;
la tenue sur 10 ans. Aucune mesure réelle n'est rejouée : l'essai en bac à sable de Beier et al. (2011) reste à
faire.

Usage :
    python verification/reponse_thermique.py [dossier_de_sortie]
"""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path

from rayflect import sondes

sys.path.insert(0, str(Path(__file__).resolve().parent))
import reference  # noqa: E402

PUISSANCE_W = 5000.0                    # injectée dans le sol, soit 50 W par mètre
PROFONDEUR_M = 100.0
SOL_C = 12.0
CAPACITE_MJ_M3_K = 2.2
CONDUCTIVITES = (1.5, 2.0, 3.0)
# La pente se lit entre ces 2 heures : après que le forage a fini de se charger, avant que les bouts de la
# sonde ne comptent (au bout d'un an, la chaleur n'a diffusé que sur quelques mètres pour 100 m de sonde).
HEURES_DE_LA_PENTE = (200, 4000)
EULER = 0.5772156649


def calculer(conductivite: float, sortie: Path) -> dict:
    fiche = sondes.Sondes(rangees=(1, 1), profondeur_m=PROFONDEUR_M, conductivite_du_sol_w_m_k=conductivite,
                          capacite_du_sol_mj_m3_k=CAPACITE_MJ_M3_K, antigel=0.0, annees=1)
    dossier = Path(sortie) / f"sondes_k{conductivite:g}".replace(".", "_")
    # Le sol est mis à la même température à toute profondeur et en toute saison : l'essai ne lit que la sonde.
    sondes.simuler(fiche, [-PUISSANCE_W] * sondes.HEURES, reference.meteo_de_denver(), dossier, sol=(SOL_C, 0.0))
    eau = sondes.lire_une_sortie(dossier / "eplusout.sql", sondes.EAU_MOYENNE)
    injectee = sondes.lire_une_sortie(dossier / "eplusout.sql", sondes.PUISSANCE_DU_SOL)
    debut, fin = HEURES_DE_LA_PENTE
    # Moindres carrés de la température sur le logarithme du temps (en secondes, au milieu de chaque heure).
    x = [math.log((h + 0.5) * 3600.0) for h in range(debut, fin)]
    y = eau[debut:fin]
    mx, my = sum(x) / len(x), sum(y) / len(y)
    pente = sum((a - mx) * (b - my) for a, b in zip(x, y)) / sum((a - mx) ** 2 for a in x)
    par_metre = PUISSANCE_W / PROFONDEUR_M
    retrouvee = par_metre / (4.0 * math.pi * pente)
    diffusivite = conductivite / (CAPACITE_MJ_M3_K * 1.0e6)
    rayon = sondes.DIAMETRE_DU_FORAGE_M / 2.0
    du_sol = (math.log(4.0 * diffusivite * math.exp(mx) / rayon ** 2) - EULER) / (4.0 * math.pi * conductivite)
    return {"conductivite_donnee": conductivite, "conductivite_retrouvee": round(retrouvee, 4),
            "ecart": round(retrouvee / conductivite - 1.0, 4),
            "puissance_moyenne_w": round(sum(injectee) / len(injectee), 1),
            "eau_au_bout_d_un_an_c": round(eau[-1], 2),
            "resistance_du_forage_m_k_w": round((my - SOL_C) / par_metre - du_sol, 4)}


def main(argv: list[str]) -> int:
    sortie = Path(argv[1]).resolve() if len(argv) > 1 else Path("verification/sorties").resolve()
    rendu = {}
    for conductivite in CONDUCTIVITES:
        r = rendu[f"{conductivite:g}"] = calculer(conductivite, sortie)
        print(f"sol à {conductivite:g} W/m.K : retrouvé {r['conductivite_retrouvee']:.3f} ({100 * r['ecart']:+.1f} %)   "
              f"eau à {r['eau_au_bout_d_un_an_c']:.1f} °C au bout d'un an   résistance du forage "
              f"{r['resistance_du_forage_m_k_w']:.3f} m.K/W")
    (sortie / "reponse_thermique.json").write_text(json.dumps(rendu, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
