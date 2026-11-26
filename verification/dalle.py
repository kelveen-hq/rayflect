"""Les cas d'épreuve de la dalle sur terre-plein (cas GC de la norme), joués avec le sol calculé d'EnergyPlus.

Ce que l'essai prouve : que le sol calculé (objet Foundation:Kiva), tel qu'il est décrit ici, rend à travers une
dalle le flux de chaleur attendu. Les références sont des solutions numériques vérifiées, pas des statistiques
de programmes.

Le cas : un local dont seule la dalle échange. Murs et plafond sont adiabatiques, l'air est tenu à 30 °C, il
n'y a ni soleil ni rayonnement. Dehors, la température est constante à 10 °C (cas en régime permanent) ou suit
2 sinusoïdes, d'un an et de 24 h (cas harmoniques).

Tout est écrit par ce fichier : la météo (rien n'est téléchargé) et le fichier d'EnergyPlus. Honeybee ne sert
pas ici : il n'écrit pas de sol calculé.

Source [S4] : Neymark et Judkoff, « International Energy Agency Building Energy Simulation Test and Diagnostic
Method (IEA BESTEST) : In-Depth Diagnostic Cases for Ground Coupled Heat Transfer Related to Slab-on-Grade
Construction », rapport NREL/TP-550-43388, 2008 : tableaux 1-1 à 1-15 pour les cas, partie III pour les
solutions vérifiées, données ici dans l'ordre TRNSYS, FLUENT, MATLAB. Ces cas sont ceux de la section
« Ground-Coupled Slab-on-Grade Analytical Verification Tests » de l'ANSI/ASHRAE 140.

Usage :
    python verification/dalle.py [dossier_de_sortie] [cas,cas,...]
"""

from __future__ import annotations

import json
import math
import sqlite3
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from rayflect import moteur

HAUTEUR_M = 2.7
JOURS = (31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31)
HEURES = 8760
# [S4] une température de surface imposée s'imite par un échange très fort : 5 000 W/m2.K ou plus.
IMPOSEE = 5000.0
MUR_M, MASSE_VOLUMIQUE, CHALEUR_MASSIQUE = 0.24, 1490.0, 1800.0     # [S4] le mur de rive, le sol et la dalle
T_INTERIEURE_C, T_EXTERIEURE_C = 30.0, 10.0                         # [S4]
AMPLITUDE_DE_L_ANNEE_C, AMPLITUDE_DU_JOUR_C = 6.0, 2.0              # [S4 §1.3.1.2.3]
CHAUFFAGE = "Zone Ideal Loads Supply Air Total Heating Rate"
PLANCHER = "Surface Inside Face Conduction Heat Transfer Rate"
AIR = "Zone Mean Air Temperature"


@dataclass(frozen=True)
class Cas:
    harmonique: bool = False            # faux : dehors à 10 °C ; vrai : sinusoïdes d'un an et de 24 h autour de 10 °C
    longueur_m: float = 12.0
    largeur_m: float = 12.0
    conductivite: float = 1.9           # sol et dalle, W/m.K
    h_interieur: float = 100.0          # W/m2.K
    h_exterieur: float = 100.0
    profondeur_m: float = 15.0          # du sol profond, tenu à la température extérieure moyenne
    champ_lointain_m: float = 15.0
    reference: tuple = ()               # les 3 solutions vérifiées : W en permanent, kWh par an en harmonique
    reference_de_pointe_w: tuple = ()   # en harmonique, la pointe horaire

    @property
    def annees(self) -> int:
        """Le sol met des années à trouver son régime : le résultat se lit sur la dernière."""
        return 10 if self.harmonique else 2


CAS = {
    "GC30a": Cas(False, h_interieur=IMPOSEE, h_exterieur=IMPOSEE, profondeur_m=30, champ_lointain_m=20,
                 reference=(2642, 2585, 2695)),
    "GC30b": Cas(False, reference=(2533, 2504, 2570)),
    "GC30c": Cas(False, h_interieur=7.95, h_exterieur=IMPOSEE, champ_lointain_m=8, reference=(2137, 2123, 2154)),
    "GC60b": Cas(False, h_interieur=7.95, reference=(2113, 2104, 2128)),
    "GC65b": Cas(False, h_interieur=7.95, h_exterieur=11.95, reference=(1994, 1991, 2004)),
    "GC40a": Cas(True, h_interieur=IMPOSEE, h_exterieur=IMPOSEE, profondeur_m=30, champ_lointain_m=20,
                 reference=(23033, 22761, 23609), reference_de_pointe_w=(3087, 3042, 3174)),
    "GC40b": Cas(True, reference=(22099, 21932, 22513), reference_de_pointe_w=(2941, 2914, 3002)),
    "GC40c": Cas(True, h_interieur=7.95, h_exterieur=IMPOSEE, champ_lointain_m=8,
                 reference=(18649, 18598, 18873), reference_de_pointe_w=(2454, 2444, 2487)),
    "GC45b": Cas(True, longueur_m=36, largeur_m=4, reference=(32758, 32456, 33483),
                 reference_de_pointe_w=(4444, 4396, 4551)),
    "GC45c": Cas(True, longueur_m=36, largeur_m=4, h_interieur=7.95, h_exterieur=IMPOSEE, champ_lointain_m=8,
                 reference=(27004, 26906, 27392), reference_de_pointe_w=(3634, 3618, 3691)),
    "GC50b": Cas(True, longueur_m=80, largeur_m=80, reference=(277923, 277988, 281418),
                 reference_de_pointe_w=(34531, 34510, 35033)),
    "GC55b": Cas(True, profondeur_m=2, reference=(35075, 34879, 35491), reference_de_pointe_w=(4366, 4336, 4427)),
    "GC55c": Cas(True, h_interieur=7.95, h_exterieur=IMPOSEE, profondeur_m=5, champ_lointain_m=8,
                 reference=(20760, 20714, 20986), reference_de_pointe_w=(2710, 2703, 2744)),
    "GC70b": Cas(True, h_interieur=7.95, h_exterieur=11.95, reference=(17396, 17434, 17552),
                 reference_de_pointe_w=(2254, 2259, 2276)),
    "GC80b": Cas(True, conductivite=0.5, reference=(6029, 5939, 6151), reference_de_pointe_w=(776, 763, 794)),
    "GC80c": Cas(True, conductivite=0.85, h_interieur=7.95, h_exterieur=IMPOSEE, champ_lointain_m=8,
                 reference=(9192, 9137, 9314), reference_de_pointe_w=(1190, 1181, 1207)),
}


def meteo(cas: Cas, chemin: Path) -> None:
    """Une année de météo sans soleil ni pluie, à température constante ou harmonique. Le vent ne sert pas :
    les échanges sont imposés."""
    lignes = ["LOCATION,Banc,NA,NA,banc,999999,40.0,0.0,0.0,0.0", "DESIGN CONDITIONS,0",
              "TYPICAL/EXTREME PERIODS,0", "GROUND TEMPERATURES,0", "HOLIDAYS/DAYLIGHT SAVINGS,No,0,0,0",
              "COMMENTS 1,banc de dalle", "COMMENTS 2,sans soleil", "DATA PERIODS,1,1,Data,Sunday,1/1,12/31"]
    jour_de_l_annee = 0
    for mois, jours in enumerate(JOURS, start=1):
        for jour in range(1, jours + 1):
            jour_de_l_annee += 1
            for heure in range(1, 25):
                t = T_EXTERIEURE_C
                if cas.harmonique:          # [S4 §1.3.1.2.3] le minimum tombe le 15 janvier, à la 4e heure
                    t = (T_EXTERIEURE_C
                         - AMPLITUDE_DE_L_ANNEE_C * math.cos((jour_de_l_annee - 15) / 365.0 * 2 * math.pi)
                         - AMPLITUDE_DU_JOUR_C * math.cos((heure - 4) / 24.0 * 2 * math.pi))
                # Un ciel « noir » à la température de l'air : son rayonnement infrarouge vaut sigma T^4.
                infrarouge = 5.6697e-8 * (t + 273.15) ** 4
                lignes.append(",".join(str(v) for v in (
                    2001, mois, jour, heure, 0, "?9?9?9?9E0?9?9?9?9?9?9?9?9?9?9?9?9?9?9?9*9*9?9?9?9",
                    round(t, 3), round(t - 20.0, 3), 20, 101325, 0, 0, round(infrarouge, 1), 0, 0, 0, 0, 0, 0, 0,
                    180, 1.0, 10, 10, 20, 77777, 9, 999999999, 0, 0.0, 0, 88, 0.0, 0.0, 0.0)))
    chemin.write_text("\n".join(lignes) + "\n", encoding="utf-8")


def fichier(cas: Cas) -> str:
    """Le fichier d'EnergyPlus du cas."""
    longueur, largeur, hauteur = cas.longueur_m, cas.largeur_m, HAUTEUR_M

    def surface(nom, genre, condition, objet, sommets):
        return (f"BuildingSurface:Detailed,\n  {nom}, {genre}, {'dalle' if genre == 'Floor' else 'paroi'}, local, , "
                f"{condition}, {objet}, NoSun, NoWind, 0.0, 4,\n  "
                + ",\n  ".join(", ".join(f"{c:.3f}" for c in s) for s in sommets) + ";\n")

    murs = [("mur_sud", [(0, 0, hauteur), (0, 0, 0), (longueur, 0, 0), (longueur, 0, hauteur)]),
            ("mur_est", [(longueur, 0, hauteur), (longueur, 0, 0), (longueur, largeur, 0), (longueur, largeur, hauteur)]),
            ("mur_nord", [(longueur, largeur, hauteur), (longueur, largeur, 0), (0, largeur, 0), (0, largeur, hauteur)]),
            ("mur_ouest", [(0, largeur, hauteur), (0, largeur, 0), (0, 0, 0), (0, 0, hauteur)])]
    dalle = surface("dalle_du_local", "Floor", "Foundation", "sol_calcule",
                    [(longueur, largeur, 0), (longueur, 0, 0), (0, 0, 0), (0, largeur, 0)])
    plafond = surface("plafond", "Roof", "Adiabatic", "",
                      [(0, largeur, hauteur), (0, 0, hauteur), (longueur, 0, hauteur), (longueur, largeur, hauteur)])
    return f"""
Version, 25.2;
Timestep, 4;
Building, banc, 0, Country, 0.04, 0.4, FullExterior, 25, 6;
SimulationControl, No, No, No, No, Yes;
HeatBalanceAlgorithm, ConductionTransferFunction, 200, 0.1, 100000;
SurfaceConvectionAlgorithm:Inside, TARP;
SurfaceConvectionAlgorithm:Outside, DOE-2;
RunPeriod, annees, 1, 1, 2001, 12, 31, {2000 + cas.annees}, , No, No, No, No, No, No;
GlobalGeometryRules, UpperLeftCorner, Counterclockwise, Relative;
ScheduleTypeLimits, tout;
Schedule:Constant, consigne, tout, {T_INTERIEURE_C};

Material, terre, Rough, 0.05, {cas.conductivite}, {MASSE_VOLUMIQUE}, {CHALEUR_MASSIQUE}, 0.000001, 0.000001, 0.000001;
Material, mur_de_rive, Rough, {MUR_M}, {cas.conductivite}, {MASSE_VOLUMIQUE}, {CHALEUR_MASSIQUE}, 0.000001, 0.000001, 0.000001;
Material:NoMass, isolant_parfait, Rough, 1000, 0.000001, 0.000001, 0.000001;
Construction, dalle, terre;
Construction, paroi, isolant_parfait;
Construction, rive, mur_de_rive;

Zone, local, 0, 0, 0, 0, 1, 1, {hauteur}, {longueur * largeur * hauteur};
{dalle}
{plafond}
{''.join(surface(nom, 'Wall', 'Adiabatic', '', s) for nom, s in murs)}
SurfaceProperty:ConvectionCoefficients, dalle_du_local, Inside, Value, {cas.h_interieur}, , , Outside, Value, {cas.h_exterieur};
SurfaceProperty:ExposedFoundationPerimeter, dalle_du_local, ExposedPerimeterFraction, , 1.0;

Foundation:Kiva, sol_calcule, {T_INTERIEURE_C}, , , , , , , , , , , 0.0, 0.0, rive;
Foundation:Kiva:Settings, {cas.conductivite}, {MASSE_VOLUMIQUE}, {CHALEUR_MASSIQUE}, 0.0, 0.0, 0.03,
  {cas.champ_lointain_m}, GroundWater, {cas.profondeur_m}, 0.02, 1.5, Hourly;

HVACTemplate:Thermostat, thermostat, consigne, , consigne, ;
HVACTemplate:Zone:IdealLoadsAirSystem, local, thermostat;

Output:Variable, dalle_du_local, {PLANCHER}, Hourly;
Output:Variable, *, {CHAUFFAGE}, Hourly;
Output:Variable, *, {AIR}, Hourly;
Output:SQLite, Simple;
"""


def calculer(nom: str, sortie: Path) -> dict:
    """Joue un cas. Rend le flux moyen, l'énergie et la pointe de la dernière année, et leur écart aux références."""
    from honeybee_energy.config import folders

    moteur.exiger_energyplus()
    cas = CAS[nom]
    dossier = Path(sortie) / nom
    dossier.mkdir(parents=True, exist_ok=True)
    meteo(cas, dossier / "meteo.epw")
    (dossier / "in.idf").write_text(fichier(cas), encoding="utf-8")
    subprocess.run([folders.energyplus_exe, "-x", "-w", str(dossier / "meteo.epw"), "-d", str(dossier),
                    str(dossier / "in.idf")], cwd=str(dossier), capture_output=True, text=True)
    journal = moteur.lire_le_journal(dossier / "eplusout.err")
    if journal.fautif:
        raise RuntimeError(f"cas {nom} : EnergyPlus a rendu un calcul fautif ({journal.dire()}). "
                           f"Journal : {dossier / 'eplusout.err'}")
    base = sqlite3.connect(dossier / "eplusout.sql")
    try:
        def serie(variable):
            return [v for (v,) in base.execute(
                "SELECT r.Value FROM ReportData r JOIN ReportDataDictionary d ON r.ReportDataDictionaryIndex = "
                "d.ReportDataDictionaryIndex WHERE d.Name = ? ORDER BY r.TimeIndex", (variable,))]

        chauffage, plancher, air = serie(CHAUFFAGE), serie(PLANCHER), serie(AIR)
    finally:
        base.close()
    if len(chauffage) != cas.annees * HEURES:
        raise RuntimeError(f"cas {nom} : {len(chauffage)} heures rendues, {cas.annees * HEURES} attendues")
    derniere, avant = chauffage[-HEURES:], chauffage[-2 * HEURES:-HEURES]
    rendu = {"flux_w": round(sum(derniere) / HEURES, 1), "energie_kwh": round(sum(derniere) / 1000.0),
             "pointe_w": round(max(derniere), 1),
             "plancher_w": round(-sum(plancher[-HEURES:]) / HEURES, 1),
             "derive_sur_1_an": round(sum(derniere) / max(1e-9, sum(avant)) - 1, 5),
             "air_c": round(sum(air[-HEURES:]) / HEURES, 3)}
    valeur = rendu["energie_kwh"] if cas.harmonique else rendu["flux_w"]
    rendu["ecart"] = round(valeur / (sum(cas.reference) / 3.0) - 1, 4)
    rendu["dans_la_plage"] = min(cas.reference) <= valeur <= max(cas.reference)
    if cas.harmonique:
        rendu["ecart_de_pointe"] = round(rendu["pointe_w"] / (sum(cas.reference_de_pointe_w) / 3.0) - 1, 4)
    return rendu


def main(argv: list[str]) -> int:
    sortie = Path(argv[1]).resolve() if len(argv) > 1 else Path("verification/sorties/dalle").resolve()
    noms = argv[2].split(",") if len(argv) > 2 else list(CAS)
    rendus = moteur.ensemble(lambda nom: calculer(nom, sortie), noms, moteur.calculs_en_meme_temps())
    rendu = dict(zip(noms, rendus))
    for nom in noms:
        print(nom, json.dumps(rendu[nom]), flush=True)
    (sortie / "dalle.json").write_text(json.dumps(rendu, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
