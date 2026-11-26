"""Les cas de ventilation de nuit de la norme (650, 950, 650FF, 950FF), rejoués par notre chaîne.

Ce que l'essai prouve : qu'un débit d'air programmé dans la journée et un thermostat qui change d'heure en
heure, écrits par Honeybee, donnent dans EnergyPlus les résultats attendus par la norme. Ce sont les cas qui
touchent à la fraîcheur de la nuit et à l'inertie.

Le cas [S1 §5.2.2.1.5, §5.2.2.2.6, §5.2.2.3.2.1, §5.2.2.3.5] :
  - le local du cas 600 (léger) ou 900 (lourd) ;
  - un ventilateur de 18 h à 7 h, 1 700 m3/h, en plus de l'infiltration de 0,5 vol/h, sans chaleur ;
  - chauffage toujours coupé ; froid à 27 °C de 7 h à 18 h, coupé le reste du temps ;
  - 650FF et 950FF : ni chauffage ni froid, on lit la température de l'air.
Écriture, comme [S3] : un seul débit d'air de 0,4902 m3/s (1 700 + 64,8 m3/h) modulé par un horaire, 1 la nuit
et 0,0367 le jour (l'infiltration seule).

Sources : celles de `bestest.py`. [S2] tables B8-2, B8-4 et B8-5 ; [S3] fichier
results/historical/OpenStudio_3_11_0.csv, résultats d'EnergyPlus 25.2.0, relus à leur source le 18/11/2026.

Usage :
    python verification/bestest_nuit.py [dossier_de_sortie]
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from honeybee_energy.load.infiltration import Infiltration
from honeybee_energy.load.setpoint import Setpoint
from honeybee_energy.schedule.day import ScheduleDay
from honeybee_energy.schedule.ruleset import ScheduleRuleset
import honeybee_energy.lib.scheduletypelimits as limites
from ladybug.epw import EPW
from ladybug.sql import SQLiteResult

from rayflect import moteur

sys.path.insert(0, str(Path(__file__).resolve().parent))
import bestest  # noqa: E402

VENTILATEUR_M3_H = 1700.0                                   # [S1 §5.2.2.1.5]
INFILTRATION_M3_H = 64.8                                    # 0,5 vol/h de 129,6 m3
DEBIT_TOTAL_M3_S = 0.4902                                   # [S3] : les 2 débits ensemble
PART_DE_JOUR = INFILTRATION_M3_H / (VENTILATEUR_M3_H + INFILTRATION_M3_H)
HEURES_DE_JOUR = (7, 18)                                    # le ventilateur tourne de 18 h à 7 h
CONSIGNE_DE_FROID_C = 27.0
TEMPERATURE = "Zone Mean Air Temperature"
BASES = {"650": "600", "950": "900", "650FF": "600", "950FF": "900"}
# Par grandeur : (min, max) des programmes d'exemple de la norme [S2], puis EnergyPlus 25.2.0 [S3].
REFERENCES = {
    "650": {"froid_mwh": (4.186, 4.945, 4.83889), "pointe_de_froid_kw": (5.045, 6.290, 6.14135)},
    "950": {"froid_mwh": (0.586, 0.707, 0.694444), "pointe_de_froid_kw": (2.054, 2.388, 2.37002)},
    "650FF": {"t_max_c": (61.13, 66.85, 62.5791), "t_min_c": (-17.76, -16.70, -17.0741),
              "t_moyenne_c": (17.60, 18.93, 18.4821)},
    "950FF": {"t_max_c": (36.13, 37.10, 36.691), "t_min_c": (-13.36, -12.50, -12.811),
              "t_moyenne_c": (14.35, 15.00, 14.8046)},
}


def _horaire(nom: str, la_nuit: float, le_jour: float, limite) -> ScheduleRuleset:
    debut, fin = HEURES_DE_JOUR
    valeurs = [le_jour if debut <= heure < fin else la_nuit for heure in range(24)]
    return ScheduleRuleset(nom, ScheduleDay.from_values_at_timestep(f"{nom}_jour", valeurs), None, limite)


def local(cas: str):
    modele = bestest.local(BASES[cas])
    energie = modele.rooms[0].properties.energy
    energie.infiltration = Infiltration("air_de_nuit", 0.0001, _horaire("air", 1.0, PART_DE_JOUR, limites.fractional))
    energie.absolute_infiltration(DEBIT_TOTAL_M3_S)
    if cas.endswith("FF"):
        energie.hvac = None
        energie.setpoint = None
    else:
        # Des consignes hors d'atteinte coupent le chauffage toute l'année, et le froid la nuit.
        energie.setpoint = Setpoint(
            "thermostat", ScheduleRuleset.from_constant_value("chauffage", -100.0, limites.temperature),
            _horaire("froid", 100.0, CONSIGNE_DE_FROID_C, limites.temperature))
    return modele


def calculer(cas: str, sortie: Path) -> dict:
    meteo = bestest.reference.meteo_de_denver()
    reglages = bestest.parametres(EPW(str(meteo)))
    reglages.output.add_output(TEMPERATURE)
    modele = local(cas)
    dossier = Path(sortie) / cas
    dossier.mkdir(parents=True, exist_ok=True)
    idf = dossier / "in.idf"
    idf.write_text(reglages.to_idf() + "\n\n" + modele.to.idf(modele), encoding="utf-8")
    try:
        sql, _journal = moteur.lancer(idf, meteo)
    except moteur.CalculFautif as erreur:
        raise RuntimeError(f"cas {cas} : {erreur}") from erreur
    resultats = SQLiteResult(sql)
    if cas.endswith("FF"):
        t = resultats.data_collections_by_output_name(TEMPERATURE)[0].values
        return {"t_max_c": round(max(t), 3), "t_min_c": round(min(t), 3), "t_moyenne_c": round(sum(t) / len(t), 3)}
    froid = resultats.data_collections_by_output_name(bestest.FROID)[0].values          # kWh par heure
    chauffage = resultats.data_collections_by_output_name(bestest.CHAUFFAGE)[0].values
    return {"froid_mwh": round(sum(froid) / 1000.0, 4), "pointe_de_froid_kw": round(max(froid), 4),
            "chauffage_mwh": round(sum(chauffage) / 1000.0, 4)}


def main(argv: list[str]) -> int:
    sortie = Path(argv[1]).resolve() if len(argv) > 1 else Path("verification/sorties").resolve()
    rendu = {}
    for cas in BASES:
        rendu[cas] = calculer(cas, sortie)
        for cle, (mini, maxi, eplus) in REFERENCES[cas].items():
            valeur = rendu[cas][cle]
            print(f"{cas:6s} {cle:20s} {valeur:9.3f}   plage {mini:8.3f} à {maxi:8.3f}  "
                  f"{'dans' if mini <= valeur <= maxi else 'HORS'}   EnergyPlus de référence {eplus:8.3f}  "
                  f"écart {100 * (valeur / eplus - 1):+.2f} %")
    (sortie / "bestest_nuit.json").write_text(json.dumps(rendu, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
