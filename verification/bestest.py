"""Les cas d'épreuve BESTEST « thermal fabric » rejoués par notre chaîne : Honeybee écrit, EnergyPlus calcule.

Ce que l'essai prouve : que NOTRE façon de décrire un local, ses vitrages et ses masques donne, une fois
passée dans EnergyPlus, les résultats attendus par la norme. EnergyPlus lui-même est déjà vérifié par ses
auteurs ; ce qui est contrôlé ici, c'est la traduction.

Norme : ANSI/ASHRAE 140-2020 et 140-2023, section « Building Thermal Envelope and Fabric Load Tests ».
Sources des valeurs :
  [S1] addendum a à la 140-2017, texte normatif de la mise à jour (ashrae.org, 140_2017_a_20200901.pdf) ;
  [S2] classeur RESULTS5-2A.xlsx, annexe informative B8 de la 140-2020, tables B8-1 et B8-2 ;
  [S3] dépôt NREL/BESTEST-GSR, résultats d'EnergyPlus 25.2.0 et météo 725650TYCST.epw.
Les plages de [S2] sont des statistiques d'exemple de 6 programmes, pas des critères d'acceptation.

Usage :
    python verification/bestest.py [dossier_de_sortie]
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from honeybee.altnumber import no_limit
from honeybee.aperture import Aperture
from honeybee.boundarycondition import Outdoors
from honeybee.model import Model
from honeybee.room import Room
from honeybee.shade import Shade
from honeybee_energy.construction.opaque import OpaqueConstruction
from honeybee_energy.construction.shade import ShadeConstruction
from honeybee_energy.construction.window import WindowConstruction
from honeybee_energy.load.equipment import ElectricEquipment
from honeybee_energy.load.infiltration import Infiltration
from honeybee_energy.load.setpoint import Setpoint
from honeybee_energy.material.gas import EnergyWindowMaterialGas
from honeybee_energy.material.glazing import EnergyWindowMaterialGlazing
from honeybee_energy.material.opaque import EnergyMaterial, EnergyMaterialNoMass
from honeybee_energy.schedule.ruleset import ScheduleRuleset
from honeybee_energy.simulation.control import SimulationControl
from honeybee_energy.simulation.parameter import SimulationParameter
import honeybee_energy.lib.scheduletypelimits as limites
from ladybug.epw import EPW
from ladybug.sql import SQLiteResult
from ladybug_geometry.geometry3d import Face3D, Point3D

from rayflect import moteur

sys.path.insert(0, str(Path(__file__).resolve().parent))
import reference  # noqa: E402    la météo de [S1] Table A1-1, version EPW de [S3], prise à sa source

# Le local [S1 §5.2.1.3] : 8 m d'est en ouest, 6 m du nord au sud, 2,7 m de haut. Origine au coin sud-ouest.
L, P, H = 8.0, 6.0, 2.7
ALLEGE, HAUT_BAIE = 0.2, 2.2            # baies de 2 m de haut, 0,5 m sous le toit
ABSORPTION_SOLAIRE, EMISSIVITE = 0.6, 0.9   # [S1] Table 5-5
APPORTS_W, PART_RADIATIVE = 200.0, 0.6      # [S1 §5.2.1.7]
INFILTRATION_VOL_H = 0.5                    # [S1 §5.2.1.6], EnergyPlus corrige lui-même l'altitude
CONSIGNES_C = (20.0, 27.0)                  # [S1 §5.2.1.13]
SAILLIE_M = 1.0                             # [S1 §5.2.2.1.1.1], casquettes et joues

CHAUFFAGE = "Zone Ideal Loads Supply Air Total Heating Energy"
FROID = "Zone Ideal Loads Supply Air Sensible Cooling Energy"

# (chauffage min, max), (froid min, max) en MWh par an : [S2], tables B8-1 et B8-2.
PLAGES = {
    "600": ((3.993, 4.504), (5.432, 6.162)),
    "610": ((4.066, 4.592), (4.117, 4.382)),
    "620": ((4.094, 4.719), (3.841, 4.404)),
    "630": ((4.356, 5.139), (2.573, 3.074)),
    "900": ((1.379, 1.814), (2.267, 2.714)),
    "910": ((1.648, 2.163), (1.191, 1.490)),
    "920": ((2.956, 3.607), (2.549, 3.128)),
    "930": ((3.524, 4.384), (1.654, 2.161)),
}
# Chauffage, froid en MWh par an, par EnergyPlus 25.2.0 sur les modèles du laboratoire NREL : [S3].
ENERGYPLUS_NREL = {
    "600": (4.325, 6.042), "610": (4.375, 4.344), "620": (4.483, 4.069), "630": (4.781, 2.842),
    "900": (1.661, 2.492), "910": (1.953, 1.386), "920": (3.331, 2.733), "930": (3.989, 1.922),
}
# masse, baies, masques
CAS = {
    "600": ("legere", "sud", False), "610": ("legere", "sud", True),
    "620": ("legere", "est_ouest", False), "630": ("legere", "est_ouest", True),
    "900": ("lourde", "sud", False), "910": ("lourde", "sud", True),
    "920": ("lourde", "est_ouest", False), "930": ("lourde", "est_ouest", True),
}


def _couche(nom, epaisseur, k, rho, cp, rugosite="Rough"):
    return EnergyMaterial(nom, epaisseur, k, rho, cp, rugosite, EMISSIVITE, ABSORPTION_SOLAIRE)


def parois(masse: str):
    """Mur, toit, plancher, de l'extérieur vers l'intérieur : [S1] Table 5-2 (léger) et Table 5-27 (lourd)."""
    bardage = _couche("bardage_bois", 0.009, 0.14, 530, 900)
    toit = OpaqueConstruction("toit", [
        _couche("support_toit", 0.019, 0.14, 530, 900),
        _couche("laine_toit", 0.1118, 0.04, 12, 840),
        _couche("platre_toit", 0.010, 0.16, 950, 840, "Smooth")])
    if masse == "legere":
        mur = OpaqueConstruction("mur_leger", [
            bardage, _couche("laine_mur", 0.066, 0.04, 12, 840),
            _couche("platre_mur", 0.012, 0.16, 950, 840, "Smooth")])
        isolant = EnergyMaterialNoMass("isolant_plancher", 1.003 / 0.04, "Rough", EMISSIVITE, ABSORPTION_SOLAIRE)
        plancher = OpaqueConstruction("plancher_leger", [
            isolant, _couche("parquet", 0.025, 0.14, 650, 1200, "Smooth")])
    else:
        mur = OpaqueConstruction("mur_lourd", [
            bardage, _couche("mousse_mur", 0.0615, 0.04, 10, 1400),
            _couche("bloc_beton", 0.100, 0.51, 1400, 1000, "Smooth")])
        isolant = EnergyMaterialNoMass("isolant_plancher", 1.007 / 0.04, "Rough", EMISSIVITE, ABSORPTION_SOLAIRE)
        plancher = OpaqueConstruction("plancher_lourd", [
            isolant, _couche("dalle_beton", 0.080, 1.13, 1400, 1000, "Smooth")])
    return mur, toit, plancher


def vitrage() -> WindowConstruction:
    """Double vitrage clair, lame d'air de 12 mm : [S1] Table 5-10."""
    def vitre(nom):
        return EnergyWindowMaterialGlazing(nom, 0.003048, 0.834, 0.075, 0.834, 0.075, 0, 0.84, 0.84, 1.0)
    return WindowConstruction("double_clair", [
        vitre("vitre_ext"), EnergyWindowMaterialGas("lame_air", 0.012, "Air"), vitre("vitre_int")])


def _rect(points) -> Face3D:
    return Face3D([Point3D(*p) for p in points])


def baies(orientation: str):
    """(nom, rectangle) vus de l'extérieur, sens inverse des aiguilles : [S1 §5.2.1.3 et §5.2.2.1.2.1]."""
    a, h = ALLEGE, HAUT_BAIE
    if orientation == "sud":
        return [("sud", f"baie_sud_{i}", _rect([(x, 0, a), (x + 3, 0, a), (x + 3, 0, h), (x, 0, h)]))
                for i, x in enumerate((0.5, 4.5))]
    return [("est", "baie_est", _rect([(L, 1.5, a), (L, 4.5, a), (L, 4.5, h), (L, 1.5, h)])),
            ("ouest", "baie_ouest", _rect([(0, 4.5, a), (0, 1.5, a), (0, 1.5, h), (0, 4.5, h)]))]


def masques(orientation: str):
    """Casquette de 1 m au niveau du toit ; à l'est et à l'ouest, 2 joues de 1 m du sol au toit en plus."""
    s = SAILLIE_M
    if orientation == "sud":
        formes = {"casquette_sud": [(0, 0, H), (L, 0, H), (L, -s, H), (0, -s, H)]}
    else:
        formes = {}
        for cote, x0, x1 in (("est", L, L + s), ("ouest", 0.0, -s)):
            formes[f"casquette_{cote}"] = [(x0, 1.5, H), (x0, 4.5, H), (x1, 4.5, H), (x1, 1.5, H)]
            for y in (1.5, 4.5):
                formes[f"joue_{cote}_{int(y * 10)}"] = [(x0, y, 0), (x1, y, 0), (x1, y, H), (x0, y, H)]
    noir = ShadeConstruction("masque_noir", 0.0, 0.0)       # [S1 §5.2.2.1.1.2] : absorbe tout
    ombres = []
    for nom, points in formes.items():
        ombre = Shade(nom, _rect(points))
        ombre.properties.energy.construction = noir
        ombres.append(ombre)
    return ombres


def local(cas: str) -> Model:
    masse, orientation, avec_masques = CAS[cas]
    piece = Room.from_box(f"cas{cas}", L, P, H)
    mur, toit, plancher = parois(masse)
    faces = {"sud": None, "est": None, "ouest": None}
    for face in piece.faces:
        nom_type = face.type.name
        if nom_type == "Floor":
            # [S1 §5.2.1.5] plancher surélevé : air extérieur dessous, ni soleil ni vent.
            face.boundary_condition = Outdoors(sun_exposure=False, wind_exposure=False)
            face.properties.energy.construction = plancher
        elif nom_type == "RoofCeiling":
            face.properties.energy.construction = toit
        else:
            face.properties.energy.construction = mur
            cle = {180: "sud", 90: "est", 270: "ouest"}.get(round(face.azimuth))
            if cle:
                faces[cle] = face
    verre = vitrage()
    for cle, nom, rectangle in baies(orientation):
        baie = Aperture(nom, rectangle)
        baie.properties.energy.construction = verre
        faces[cle].add_aperture(baie)

    toujours = ScheduleRuleset.from_constant_value("toujours", 1.0, limites.fractional)
    energie = piece.properties.energy
    energie.electric_equipment = ElectricEquipment("apports", APPORTS_W / (L * P), toujours, PART_RADIATIVE)
    energie.infiltration = Infiltration("infiltration", 0.0001, toujours)
    energie.absolute_infiltration_ach(INFILTRATION_VOL_H)
    energie.setpoint = Setpoint(
        "thermostat",
        ScheduleRuleset.from_constant_value("chauffage", CONSIGNES_C[0], limites.temperature),
        ScheduleRuleset.from_constant_value("froid", CONSIGNES_C[1], limites.temperature))
    energie.add_default_ideal_air()
    air = energie.hvac.duplicate()
    air.economizer_type = "NoEconomizer"
    air.demand_controlled_ventilation = False
    air.sensible_heat_recovery = 0
    air.latent_heat_recovery = 0
    air.heating_limit = no_limit
    air.cooling_limit = no_limit
    energie.hvac = air
    return Model(f"bestest_{cas}", rooms=[piece],
                 orphaned_shades=masques(orientation) if avec_masques else [])


def parametres(epw: EPW) -> SimulationParameter:
    p = SimulationParameter()
    p.location = epw.location
    p.terrain_type = "Country"
    p.timestep = 6
    p.shadow_calculation.solar_distribution = "FullInteriorAndExterior"
    p.shadow_calculation.calculation_frequency = moteur.OMBRES_TOUS_LES_N_JOURS     # le réglage de l'outil
    p.simulation_control = SimulationControl(
        do_zone_sizing=False, do_system_sizing=False, do_plant_sizing=False,
        run_for_sizing_periods=False, run_for_run_periods=True)
    p.output.reporting_frequency = "Hourly"
    p.output.add_output(CHAUFFAGE)
    p.output.add_output(FROID)
    return p


def calculer(cas: str, sortie: Path, meteo: Path = None) -> dict:
    meteo = meteo or reference.meteo_de_denver()
    epw = EPW(str(meteo))
    modele = local(cas)
    dossier = sortie / cas
    dossier.mkdir(parents=True, exist_ok=True)
    idf = dossier / "in.idf"
    idf.write_text(parametres(epw).to_idf() + "\n\n" + modele.to.idf(modele), encoding="utf-8")
    try:
        sql, _journal = moteur.lancer(idf, meteo)
    except moteur.CalculFautif as erreur:
        raise RuntimeError(f"cas {cas} : {erreur}") from erreur
    resultats = SQLiteResult(sql)
    chauffage = sum(resultats.data_collections_by_output_name(CHAUFFAGE)[0].values) / 1000.0
    froid = sum(resultats.data_collections_by_output_name(FROID)[0].values) / 1000.0
    return {"cas": cas, "chauffage_mwh": round(chauffage, 3), "froid_mwh": round(froid, 3)}


def dans(valeur: float, plage) -> bool:
    return plage[0] <= valeur <= plage[1]


def main(argv: list[str]) -> int:
    sortie = Path(argv[1]).resolve() if len(argv) > 1 else Path("verification/sorties").resolve()
    lignes = [calculer(cas, sortie) for cas in CAS]
    (sortie / "bestest.json").write_text(json.dumps(lignes, indent=2), encoding="utf-8")
    print(f"{'cas':<5}{'chauffage':>10}{'plage':>16}{'NREL':>8}{'froid':>9}{'plage':>16}{'NREL':>8}")
    for r in lignes:
        (c0, c1), (f0, f1) = PLAGES[r["cas"]]
        nc, nf = ENERGYPLUS_NREL[r["cas"]]
        print(f"{r['cas']:<5}{r['chauffage_mwh']:>10.3f}{f'{c0:.3f}-{c1:.3f}':>16}{nc:>8.3f}"
              f"{r['froid_mwh']:>9.3f}{f'{f0:.3f}-{f1:.3f}':>16}{nf:>8.3f}"
              f"  {'' if dans(r['chauffage_mwh'], (c0, c1)) else 'CHAUFFAGE HORS PLAGE '}"
              f"{'' if dans(r['froid_mwh'], (f0, f1)) else 'FROID HORS PLAGE'}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
