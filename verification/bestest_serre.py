"""Le cas 960 de la norme, la serre accolée, rejoué par notre chaîne.

Ce que l'essai prouve : que 2 pièces séparées par un mur, écrites par Honeybee, échangent dans EnergyPlus la
chaleur attendue par la norme, et que le soleil entré par un vitrage est bien réparti sur les parois.

Le cas [S1 §5.2.2.2.7 et table 5-12] : une pièce arrière légère de 8 x 6 x 2,7 m, sans baie, chauffée à 20 °C
et refroidie à 27 °C ; devant elle, au sud, une serre lourde de 8 x 2 x 2,7 m qui porte les 12 m2 de vitrage,
sans chauffage ni froid. Entre les 2, un mur de béton de 20 cm. Aucun échange d'air entre les 2 pièces,
0,5 vol/h d'infiltration dans chacune.

LA RÉPARTITION DU SOLEIL COMPTE ICI. Le cas se joue avec le soleil réparti sur les parois qu'il touche
(`FullInteriorAndExterior`). Avec `FullExterior`, tout le soleil entré tombe sur le sol : `calculer` le permet,
pour mesurer ce que ce réglage coûte dans une serre.

Sources : celles de `bestest.py`. [S2] tables B8-1 à B8-5 (5 programmes rendent ce cas) ; [S3] fichier
results/historical/OpenStudio_3_11_0.csv, résultats d'EnergyPlus 25.2.0, relus à leur source le 18/11/2026.

Usage :
    python verification/bestest_serre.py [dossier_de_sortie]
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from honeybee.aperture import Aperture
from honeybee.boundarycondition import Outdoors, Surface
from honeybee.model import Model
from honeybee.room import Room
from honeybee_energy.construction.opaque import OpaqueConstruction
from honeybee_energy.load.infiltration import Infiltration
from honeybee_energy.schedule.ruleset import ScheduleRuleset
import honeybee_energy.lib.scheduletypelimits as limites
from ladybug.epw import EPW
from ladybug.sql import SQLiteResult
from ladybug_geometry.geometry3d import Point3D, Vector3D

from rayflect import moteur

sys.path.insert(0, str(Path(__file__).resolve().parent))
import bestest  # noqa: E402

PROFONDEUR_DE_LA_SERRE_M = 2.0                  # [S1 §5.2.2.2.7]
MUR_COMMUN = (0.20, 0.510, 1400.0, 1000.0)      # [S1 table 5-12] épaisseur m, W/m.K, kg/m3, J/kg.K
REMONTEE_DES_BAIES_M = 0.3                      # [S1 §5.2.2.2.7.3 c] les baies du cas 900, remontées
TEMPERATURE = "Zone Mean Air Temperature"
# Par grandeur : (min, max) des programmes d'exemple de la norme [S2], puis EnergyPlus 25.2.0 [S3].
REFERENCES = {
    "chauffage_mwh": (2.5221, 2.8595, 2.70278), "froid_mwh": (0.7890, 0.9496, 0.902778),
    "pointe_de_chauffage_kw": (2.085, 2.3004, 2.26285), "pointe_de_froid_kw": (1.3385, 1.4799, 1.48004),
    "t_serre_max_c": (48.10, 53.18, 49.0823), "t_serre_min_c": (4.24, 8.02, 4.98973),
    "t_serre_moyenne_c": (26.80, 29.45, 27.4748),
}


def local() -> Model:
    mur_leger, toit, plancher_leger = bestest.parois("legere")
    mur_lourd, _toit, plancher_lourd = bestest.parois("lourde")
    isolant = plancher_lourd.materials[0].duplicate()        # même nom que l'isolant léger, autre résistance
    isolant.identifier = "isolant_plancher_lourd"
    plancher_lourd = OpaqueConstruction("plancher_lourd", [isolant, plancher_lourd.materials[1]])
    commun = OpaqueConstruction("mur_commun", [bestest._couche("beton_commun", *MUR_COMMUN, "Smooth")])

    serre = Room.from_box("serre", bestest.L, PROFONDEUR_DE_LA_SERRE_M, bestest.H, origin=Point3D(0, 0, 0))
    arriere = Room.from_box("arriere", bestest.L, bestest.P, bestest.H,
                            origin=Point3D(0, PROFONDEUR_DE_LA_SERRE_M, 0))
    Room.solve_adjacency([serre, arriere], 0.01)
    for piece, mur, plancher in ((serre, mur_lourd, plancher_lourd), (arriere, mur_leger, plancher_leger)):
        for face in piece.faces:
            if isinstance(face.boundary_condition, Surface):
                face.properties.energy.construction = commun
            elif face.type.name == "Floor":
                face.boundary_condition = Outdoors(sun_exposure=False, wind_exposure=False)
                face.properties.energy.construction = plancher
            elif face.type.name == "RoofCeiling":
                face.properties.energy.construction = toit
            else:
                face.properties.energy.construction = mur
    sud = [f for f in serre.faces if f.type.name == "Wall" and round(f.azimuth) == 180][0]
    verre = bestest.vitrage()
    for _cle, nom, rectangle in bestest.baies("sud"):
        baie = Aperture(nom, rectangle.move(Vector3D(0, 0, REMONTEE_DES_BAIES_M)))
        baie.properties.energy.construction = verre
        sud.add_aperture(baie)

    toujours = ScheduleRuleset.from_constant_value("toujours", 1.0, limites.fractional)
    du_cas_600 = bestest.local("600").rooms[0].properties.energy     # apports, consignes et air idéal de la pièce
    energie = arriere.properties.energy
    energie.electric_equipment = du_cas_600.electric_equipment
    energie.setpoint = du_cas_600.setpoint
    energie.hvac = du_cas_600.hvac
    for piece in (serre, arriere):
        piece.properties.energy.infiltration = Infiltration(f"infiltration_{piece.identifier}", 0.0001, toujours)
        piece.properties.energy.absolute_infiltration_ach(bestest.INFILTRATION_VOL_H)
    return Model("bestest_960", rooms=[serre, arriere])


def calculer(sortie: Path, repartition: str = "FullInteriorAndExterior") -> dict:
    meteo = bestest.reference.meteo_de_denver()
    reglages = bestest.parametres(EPW(str(meteo)))
    reglages.shadow_calculation.solar_distribution = repartition
    reglages.output.add_output(TEMPERATURE)
    modele = local()
    dossier = Path(sortie) / f"960_{repartition}"
    dossier.mkdir(parents=True, exist_ok=True)
    idf = dossier / "in.idf"
    idf.write_text(reglages.to_idf() + "\n\n" + modele.to.idf(modele), encoding="utf-8")
    try:
        sql, _journal = moteur.lancer(idf, meteo)
    except moteur.CalculFautif as erreur:
        raise RuntimeError(f"cas 960, {repartition} : {erreur}") from erreur
    resultats = SQLiteResult(sql)

    def serie(nom: str, piece: str):
        for collection in resultats.data_collections_by_output_name(nom):
            if piece.upper() in str(collection.header.metadata).upper():
                return collection.values
        raise RuntimeError(f"cas 960 : « {nom} » n'est pas rendu pour la pièce {piece}")

    chauffage, froid = serie(bestest.CHAUFFAGE, "arriere"), serie(bestest.FROID, "arriere")
    t = serie(TEMPERATURE, "serre")
    return {"chauffage_mwh": round(sum(chauffage) / 1000, 4), "froid_mwh": round(sum(froid) / 1000, 4),
            "pointe_de_chauffage_kw": round(max(chauffage), 4), "pointe_de_froid_kw": round(max(froid), 4),
            "t_serre_max_c": round(max(t), 3), "t_serre_min_c": round(min(t), 3),
            "t_serre_moyenne_c": round(sum(t) / len(t), 3)}


def main(argv: list[str]) -> int:
    sortie = Path(argv[1]).resolve() if len(argv) > 1 else Path("verification/sorties").resolve()
    rendu = {repartition: calculer(sortie, repartition) for repartition in ("FullInteriorAndExterior", "FullExterior")}
    for cle, (mini, maxi, eplus) in REFERENCES.items():
        valeur = rendu["FullInteriorAndExterior"][cle]
        print(f"960 {cle:24s} {valeur:8.3f}   plage {mini:8.3f} à {maxi:8.3f}  "
              f"{'dans' if mini <= valeur <= maxi else 'HORS'}   EnergyPlus de référence {eplus:8.3f}  "
              f"écart {100 * (valeur / eplus - 1):+.2f} %   soleil au sol : {rendu['FullExterior'][cle]:8.3f}")
    (sortie / "bestest_serre.json").write_text(json.dumps(rendu, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
