"""Le mur végétalisé de Rayflect face à la façade d'essai de Würzburg : les mêmes murs, la même météo, les mêmes périodes.

LA SOURCE [S : Weinläder, Reim, Ullerich, Körner et Weismann, « Thermal Characterization of Living Wall Systems »,
EuroSun 2024, ISES, doi 10.18086/eurosun.2024.01.13] : un conteneur de 6 × 3 × 3 m, murs de 10 cm de béton et 18 cm de
laine minérale (U = 0,2), la façade sud partagée en panneaux mesurés chacun par un fluxmètre sur la face intérieure.
Des enduits d'absorption 0,6 (moyen) et 0,24 (clair), des murs végétalisés à 5 cm de la façade, arrosés l'été et pas
l'hiver.

CE QU'ON COMPARE, aux mêmes périodes :
  - l'été, du 11 juillet au 5 septembre 2023, la pièce à 24 °C : les gains de chaleur par le mur (le flux qui entre)
    baissent de 38 à 48 % face à l'enduit moyen, de 5 à 17 % face à l'enduit clair (§3.1, 3.2, figure 6) ; l'enduit
    clair seul les baisse de 35 % (tableau 4 : 2,818 contre 4,335 MJ/m²) ;
  - l'hiver, du 22 novembre 2023 au 5 avril 2024 : l'U effectif (les pertes rapportées à l'écart de température) varie
    de −4 à +16 % face à l'enduit moyen (§3.3) ; l'enduit clair seul le monte de 19 % (§3.4).

CE QUI DIFFÈRE [H] : la météo est celle d'ERA5-Land à Würzburg (Open-Meteo), pas la station du banc à 50 m ; la pièce
est tenue à 24 °C l'été et à 21 °C l'hiver (la source donne 24 °C l'été, 21 °C pour ses mesures de printemps) ; le sol
et le toit du conteneur sont isolés comme les murs ; l'enduit fait 1,5 cm.

LE RÉSULTAT (24/11/2026, EnergyPlus 25.2). La météo d'ERA5 reproduit celle du banc (19,5 °C de moyenne l'été pour
20,1 mesurés ; 10,4 MJ/m² de soleil par jour sur la façade sud pour 8,9).
  - L'HIVER TIENT : U effectif du mur végétalisé +8 % face à l'enduit moyen (mesuré −4 à +16 %) ; de l'enduit clair
    +17 % (mesuré +19 %).
  - L'ÉTÉ NE TIENT PAS, et ce n'est pas le mur végétalisé qui est en cause d'abord : face à l'enduit moyen, l'enduit clair
    retire 86 % des gains de chaleur du mur dans le calcul, 35 % sur le banc. Le mur nu y est 2,4 fois plus sensible au
    soleil que mesuré. Moins isoler le mur ne change rien (82 à 86 % à U = 0,42 et 0,77) : sur le banc, une grande part
    des gains ne vient pas du soleil (2,8 MJ/m² pour l'enduit clair, 0,2 dans le calcul). Pistes non tranchées : la
    climatisation du banc et sa stratification (la source la signale), les cadres des panneaux, l'estimation de l'enduit
    clair faite sur une autre période (la source dit qu'elle le sous-estime).
  - Le mur végétalisé gagne PLUS que l'enduit clair dans le calcul (+66 % à U = 0,2), moins sur le banc (−5 à −17 %) :
    le modèle traite les modules comme un écran mince chauffé par le soleil, alors que le substrat abrite leur dos.
Conclusion : le mur végétalisé de Rayflect est validé l'hiver ; l'été, il ne l'est pas, et ses gains d'été sont sans
doute trop forts. Le régler sur ces mesures serait circulaire tant que l'écart du mur nu n'est pas compris.

Usage : python verification/mur_vegetal_wurzburg.py [dossier de sortie]   (ERA5 par Open-Meteo, mis en cache)
"""

from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

from honeybee.altnumber import no_limit
from honeybee.boundarycondition import Outdoors
from honeybee.model import Model
from honeybee.room import Room
from honeybee_energy.construction.opaque import OpaqueConstruction
from honeybee_energy.load.setpoint import Setpoint
from honeybee_energy.material.opaque import EnergyMaterial
from honeybee_energy.schedule.ruleset import ScheduleRuleset
from honeybee_energy.simulation.control import SimulationControl
from honeybee_energy.simulation.parameter import SimulationParameter
import honeybee_energy.lib.scheduletypelimits as limites
from ladybug.epw import EPW

from rayflect import cache, hypotheses as hyp, moteur, vegetation
from rayflect.io import climats, meteo

LAT, LON = 49.770, 9.960                    # Würzburg [H : la position du banc à quelques km près]
FLUX = "Surface Inside Face Conduction Heat Transfer Rate per Area"
ETE = (191, 247)                            # du 11 juillet au 5 septembre, jours de l'année à partir de 0
HIVER_2023 = (325, 364)                     # du 22 novembre au 31 décembre 2023
HIVER_2024 = (0, 94)                        # du 1er janvier au 5 avril 2024 (le 29 février est retiré)
MESURE = {
    "ete_gains_mur_vegetal_face_au_moyen": (-0.48, -0.38),
    "ete_gains_mur_vegetal_face_au_clair": (-0.17, -0.05),
    "ete_gains_clair_face_au_moyen": (-0.35, -0.35),
    "hiver_u_mur_vegetal_face_au_moyen": (-0.04, 0.16),
    "hiver_u_clair_face_au_moyen": (0.19, 0.19),
}
LAINE_K = 0.038                             # [D] 18 cm de laine minérale qui donnent U = 0,2 avec 10 cm de béton


def _construction(absorption: float, laine_m: float = 0.18) -> OpaqueConstruction:
    enduit = EnergyMaterial(f"enduit_{absorption:g}", 0.015, 0.7, 1400, 1000, solar_absorptance=absorption)
    laine = EnergyMaterial(f"laine_minerale_{laine_m:g}", laine_m, LAINE_K, 30, 1030)
    beton = EnergyMaterial("beton_10", 0.10, hyp.BETON["k"], hyp.BETON["rho"], hyp.BETON["cp"])
    return OpaqueConstruction(f"mur_{absorption:g}_{laine_m:g}", [enduit, laine, beton])


def conteneur(absorption: float, mur_vegetal: bool, consigne_c: float, arrose: bool, laine_m: float = 0.18) -> Model:
    piece = Room.from_box("conteneur", 6.0, 3.0, 3.0)
    for face in piece.faces:
        if face.type.name == "Floor":
            face.boundary_condition = Outdoors(sun_exposure=False, wind_exposure=False)
        face.properties.energy.construction = _construction(absorption, laine_m)
    energie = piece.properties.energy
    energie.setpoint = Setpoint("thermostat",
                                ScheduleRuleset.from_constant_value("chaud", consigne_c - 0.05, limites.temperature),
                                ScheduleRuleset.from_constant_value("froid", consigne_c + 0.05, limites.temperature))
    energie.add_default_ideal_air()
    # Les réglages de l'air idéal des cas BESTEST (verification/bestest.py) : avec ceux par défaut et un thermostat,
    # EnergyPlus 25.2 plante à l'initialisation sur ce conteneur sans fenêtre (vu le 24/11/2026).
    air = energie.hvac.duplicate()
    air.economizer_type = "NoEconomizer"
    air.demand_controlled_ventilation = False
    air.sensible_heat_recovery = 0
    air.latent_heat_recovery = 0
    air.heating_limit = no_limit
    air.cooling_limit = no_limit
    energie.hvac = air
    modele = Model("wurzburg", rooms=[piece])
    if mur_vegetal:
        vegetation.poser_le_mur_vegetal(modele, vegetation.MurVegetal(orientations=("S",), systeme="bacs", arrose=arrose))
    return modele


def _parametres(epw: EPW) -> SimulationParameter:
    p = SimulationParameter()
    p.location = epw.location
    p.timestep = 6
    p.terrain_type = "Country"
    p.shadow_calculation.solar_distribution = "FullInteriorAndExterior"
    p.simulation_control = SimulationControl(do_zone_sizing=False, do_system_sizing=False, do_plant_sizing=False,
                                             run_for_sizing_periods=False, run_for_run_periods=True)
    p.output.reporting_frequency = "Hourly"
    p.output.add_output(FLUX)
    return p


def flux_du_mur_sud(chemin_epw: Path, absorption: float, mur_vegetal: bool, consigne_c: float, arrose: bool,
                    dossier: Path, laine_m: float = 0.18) -> list:
    """Le flux de chaleur à la face intérieure du mur sud, heure par heure, en W/m² : positif quand il entre."""
    epw = EPW(str(chemin_epw))
    modele = conteneur(absorption, mur_vegetal, consigne_c, arrose, laine_m)
    dossier.mkdir(parents=True, exist_ok=True)
    idf = dossier / "in.idf"
    idf.write_text(_parametres(epw).to_idf() + "\n\n" + modele.to.idf(modele)
                   + vegetation.texte_des_murs_vegetaux(modele, epw, dossier), encoding="utf-8")
    sql, _journal = moteur.lancer(idf, chemin_epw)
    sud = next(f.identifier for f in modele.faces if round(f.azimuth) == 180 and f.type.name == "Wall").upper()
    connexion = sqlite3.connect(str(sql))
    try:
        lignes = connexion.execute(
            "SELECT r.Value FROM ReportData r JOIN ReportDataDictionary d USING (ReportDataDictionaryIndex) "
            "WHERE d.Name = ? AND UPPER(d.KeyValue) = ? ORDER BY r.TimeIndex", (FLUX, sud)).fetchall()
    finally:
        connexion.close()
    return [v for (v,) in lignes]


def _sur(flux: list, jours) -> list:
    return flux[jours[0] * 24:(jours[1] + 1) * 24]


def calculer(sortie: Path, laine_m: float = 0.18) -> dict:
    type_, _controle = meteo.preparer(LAT, LON, cache.dossier("meteo"))
    annees = {a: climats.annee_reelle(LAT, LON, a, type_, cache.dossier("meteo")).chemin for a in (2023, 2024)}
    cas = {"moyen": (0.6, False), "clair": (0.24, False), "mur_vegetal": (0.6, True)}
    ete, hiver = {}, {}
    for nom, (absorption, vegetal) in cas.items():
        flux = _sur(flux_du_mur_sud(annees[2023], absorption, vegetal, 24.0, True, sortie / f"ete_{nom}", laine_m), ETE)
        ete[nom] = sum(v for v in flux if v > 0) * 3600 / 1e6                         # MJ/m², les gains seuls
        f23 = _sur(flux_du_mur_sud(annees[2023], absorption, vegetal, 21.0, False, sortie / f"hiver23_{nom}", laine_m),
                   HIVER_2023)
        f24 = _sur(flux_du_mur_sud(annees[2024], absorption, vegetal, 21.0, False, sortie / f"hiver24_{nom}", laine_m),
                   HIVER_2024)
        hiver[nom] = -sum(v for v in f23 + f24 if v < 0) * 3600 / 1e6                  # MJ/m², les pertes seules
    # La pièce est à la même température dans les 3 cas, sous la même météo : le rapport des pertes est celui des U effectifs.
    calcul = {
        "ete_gains_mur_vegetal_face_au_moyen": ete["mur_vegetal"] / ete["moyen"] - 1,
        "ete_gains_mur_vegetal_face_au_clair": ete["mur_vegetal"] / ete["clair"] - 1,
        "ete_gains_clair_face_au_moyen": ete["clair"] / ete["moyen"] - 1,
        "hiver_u_mur_vegetal_face_au_moyen": hiver["mur_vegetal"] / hiver["moyen"] - 1,
        "hiver_u_clair_face_au_moyen": hiver["clair"] / hiver["moyen"] - 1,
    }
    rendu = {"ete_gains_mj_m2": {k: round(v, 3) for k, v in ete.items()},
             "hiver_pertes_mj_m2": {k: round(v, 3) for k, v in hiver.items()},
             "comparaison": {k: {"calcul": round(v, 3), "mesure": MESURE[k],
                                 "dans_la_mesure": MESURE[k][0] - 0.05 <= v <= MESURE[k][1] + 0.05}
                             for k, v in calcul.items()}}
    (sortie / "mur_vegetal_wurzburg.json").write_text(json.dumps(rendu, indent=2, ensure_ascii=False), encoding="utf-8")
    return rendu


def main(argv: list) -> int:
    sortie = Path(argv[1]).resolve() if len(argv) > 1 else Path("verification/sorties/mur_vegetal_wurzburg").resolve()
    rendu = calculer(sortie)
    print(f"gains d'été, MJ/m² : {rendu['ete_gains_mj_m2']}")
    print(f"pertes d'hiver, MJ/m² : {rendu['hiver_pertes_mj_m2']}")
    for cle, c in rendu["comparaison"].items():
        bas, haut = c["mesure"]
        print(f"{cle} : calcul {c['calcul'] * 100:+.0f} %, mesure {bas * 100:+.0f} à {haut * 100:+.0f} %"
              f"{'' if c['dans_la_mesure'] else '  <- hors de la mesure'}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
