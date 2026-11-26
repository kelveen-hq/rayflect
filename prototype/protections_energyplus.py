"""Prototype : un local, 5 protections solaires, calculés par EnergyPlus à travers Honeybee.

Le local : une salle de 8 m × 6 m × 3 m, une seule façade vitrée à 40 %, plein sud, chauffée à 19 °C et
SANS climatisation. On lit la température ressentie heure par heure et le chauffage de l'année.

Usage :
    python prototype/protections_energyplus.py chemin/vers/meteo.epw [dossier_de_sortie]
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from honeybee.altnumber import no_limit
from honeybee.model import Model
from honeybee.room import Room
from honeybee.shade import Shade
from honeybee_energy.construction.windowshade import WindowConstructionShade
from honeybee_energy.material.shade import EnergyWindowMaterialBlind
from honeybee_energy.programtype import ProgramType
from honeybee_energy.lib.programtypes import program_type_by_identifier
from honeybee_energy.load.setpoint import Setpoint
from honeybee_energy.run import run_idf
from honeybee_energy.schedule.ruleset import ScheduleRuleset
from honeybee_energy.schedule.rule import ScheduleRule
from honeybee_energy.schedule.day import ScheduleDay
from honeybee_energy.simulation.control import SimulationControl
from honeybee_energy.simulation.parameter import SimulationParameter
import honeybee_energy.lib.scheduletypelimits as limites
from ladybug.dt import Date
from ladybug.epw import EPW
from ladybug.sql import SQLiteResult
from ladybug_geometry.geometry3d import Face3D, Point3D

LARGEUR_M, PROFONDEUR_M, HAUTEUR_M = 8.0, 6.0, 3.0
PART_VITREE = 0.40
CONSIGNE_CHAUFFAGE_C = 19.0
SEUIL_BSO_W_M2 = 150.0          # EN 15232, classe B
CASQUETTE_M = 1.0
PERGOLA_M = 2.5
TRANSMISSION_FEUILLAGE = (0.20, 0.70)   # été en feuilles, hiver sans feuilles : ordres de grandeur, à sourcer
FEUILLAISON = (Date(5, 1), Date(10, 15))

T_RESSENTIE = "Zone Operative Temperature"
CHAUFFAGE = "Zone Ideal Loads Supply Air Total Heating Energy"


def local(nom: str) -> tuple[Room, object]:
    """Le local et sa baie sud. Dans Honeybee, la face d'azimut 180° est celle dont la normale regarde le sud."""
    piece = Room.from_box(nom, LARGEUR_M, PROFONDEUR_M, HAUTEUR_M)
    sud = min(piece.faces, key=lambda f: abs(f.azimuth - 180.0) if f.normal.z == 0 else 999.0)
    sud.apertures_by_ratio(PART_VITREE)
    programme: ProgramType = program_type_by_identifier("Generic Office Program").duplicate()
    programme.setpoint = Setpoint(
        f"consignes_{nom}",
        ScheduleRuleset.from_constant_value(f"chauffage_{nom}", CONSIGNE_CHAUFFAGE_C, limites.temperature),
        ScheduleRuleset.from_constant_value(f"froid_{nom}", 50.0, limites.temperature),  # pas de climatisation
    )
    piece.properties.energy.program_type = programme
    piece.properties.energy.add_default_ideal_air()
    # Sans jours de dimensionnement dans la météo, la puissance n'est pas calculée : on ne la limite pas.
    air = piece.properties.energy.hvac.duplicate()
    air.economizer_type = "NoEconomizer"
    air.demand_controlled_ventilation = False
    air.heating_limit = no_limit
    air.cooling_limit = no_limit
    piece.properties.energy.hvac = air
    return piece, sud


def sans_protection(piece, sud):
    return []


def casquette(piece, sud):
    for baie in sud.apertures:
        baie.overhang(CASQUETTE_M)
    return []


def _bso(piece, sud, pilotage: str, seuil=None):
    lames = EnergyWindowMaterialBlind("lames_bso", slat_angle=45, solar_reflectance=0.5, visible_reflectance=0.5)
    for baie in sud.apertures:
        vitrage = baie.properties.energy.construction
        baie.properties.energy.construction = WindowConstructionShade(
            f"vitrage_bso_{pilotage}", vitrage, lames, "Exterior", pilotage, seuil)
    return []


def bso_automatique(piece, sud):
    return _bso(piece, sud, "OnIfHighSolarOnWindow", SEUIL_BSO_W_M2)


def bso_toujours_baisse(piece, sud):
    return _bso(piece, sud, "AlwaysOn")


def pergola_vegetale(piece, sud):
    """Un plan horizontal au-dessus de la baie, dont la transparence suit la feuillaison."""
    ete, hiver = TRANSMISSION_FEUILLAGE
    feuilles = ScheduleDay("jour_en_feuilles", [ete])
    nu = ScheduleDay("jour_sans_feuilles", [hiver])
    regle = ScheduleRule(feuilles, start_date=FEUILLAISON[0], end_date=FEUILLAISON[1])
    regle.apply_all = True
    calendrier = ScheduleRuleset("feuillaison", nu, [regle], limites.fractional)
    z = HAUTEUR_M
    plan = Face3D([Point3D(0, 0, z), Point3D(LARGEUR_M, 0, z),
                   Point3D(LARGEUR_M, -PERGOLA_M, z), Point3D(0, -PERGOLA_M, z)])
    ombre = Shade("pergola", plan)
    ombre.properties.energy.transmittance_schedule = calendrier
    return [ombre]


SCENARIOS = {
    "sans_protection": sans_protection,
    "casquette_1m": casquette,
    "bso_automatique": bso_automatique,
    "bso_toujours_baisse": bso_toujours_baisse,
    "pergola_vegetale": pergola_vegetale,
}


def parametres(epw: EPW) -> SimulationParameter:
    p = SimulationParameter()
    p.location = epw.location
    p.timestep = 4
    p.simulation_control = SimulationControl(
        do_zone_sizing=False, do_system_sizing=False, do_plant_sizing=False,
        run_for_sizing_periods=False, run_for_run_periods=True)
    p.output.reporting_frequency = "Hourly"
    p.output.add_output(T_RESSENTIE)
    p.output.add_output(CHAUFFAGE)
    return p


def calculer(nom: str, fabrique, chemin_epw: Path, sortie: Path) -> dict:
    epw = EPW(str(chemin_epw))
    piece, sud = local("salle")
    ombres = fabrique(piece, sud)
    modele = Model(nom, rooms=[piece], orphaned_shades=ombres)
    dossier = sortie / nom
    dossier.mkdir(parents=True, exist_ok=True)
    idf = dossier / "in.idf"
    idf.write_text(parametres(epw).to_idf() + "\n\n" + modele.to.idf(modele), encoding="utf-8")
    sql, _zsz, _rdd, _html, err = run_idf(str(idf), str(chemin_epw), silent=True)
    if sql is None:
        raise RuntimeError(f"{nom} : EnergyPlus n'a pas rendu de résultat, voir {err}")
    resultats = SQLiteResult(sql)
    temperature = resultats.data_collections_by_output_name(T_RESSENTIE)[0].values
    chauffage_kwh = sum(resultats.data_collections_by_output_name(CHAUFFAGE)[0].values)
    return {
        "scenario": nom,
        "heures": len(temperature),
        "heures_au_dessus_de_26": sum(1 for t in temperature if t > 26.0),
        "heures_au_dessus_de_28": sum(1 for t in temperature if t > 28.0),
        "temperature_max_c": round(max(temperature), 1),
        "chauffage_kwh": round(chauffage_kwh),
        "fichier_energyplus": str(idf),
    }


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print(__doc__)
        return 2
    chemin_epw = Path(argv[1]).resolve()
    sortie = Path(argv[2]).resolve() if len(argv) > 2 else Path("prototype/sorties").resolve()
    lignes = [calculer(nom, fabrique, chemin_epw, sortie) for nom, fabrique in SCENARIOS.items()]
    (sortie / "resultats.json").write_text(json.dumps(lignes, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"{'scénario':<22}{'h > 26 °C':>10}{'h > 28 °C':>10}{'T max':>8}{'chauffage kWh':>15}")
    for r in lignes:
        print(f"{r['scenario']:<22}{r['heures_au_dessus_de_26']:>10}{r['heures_au_dessus_de_28']:>10}"
              f"{r['temperature_max_c']:>8}{r['chauffage_kwh']:>15}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
