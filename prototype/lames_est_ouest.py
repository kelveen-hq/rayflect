"""Contrôle : que font les protections sur une salle vitrée à l'est et à l'ouest ?

Une salle de bureau de 8 m × 6 m × 3 m, vitrée à 40 % sur ses 2 façades est et ouest. Pour chaque protection,
on lit les heures chaudes en occupation, le chauffage, et la lumière du jour au centre de la salle.

Usage :
    python prototype/lames_est_ouest.py meteo.epw
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from honeybee.model import Model  # noqa: E402
from honeybee.room import Room  # noqa: E402
from honeybee_energy.run import run_idf  # noqa: E402
from honeybee_energy.simulation.control import SimulationControl  # noqa: E402
from honeybee_energy.simulation.parameter import SimulationParameter  # noqa: E402
from ladybug.epw import EPW  # noqa: E402
from ladybug.sql import SQLiteResult  # noqa: E402

from rayflect import hypotheses as hyp, lumiere, protections_solaires as ps  # noqa: E402

T_RESSENTIE = "Zone Operative Temperature"
CHAUFFAGE = "Zone Ideal Loads Supply Air Total Heating Energy"
EO = ("E", "O")

SCENARIOS = {
    "sans protection": None,
    "casquette 0,8 m": ps.Casquette(0.8, orientations=EO),
    "joues 0,5 m": ps.Joues(0.5, orientations=EO),
    "lames horizontales 30/30": ps.LamesHorizontales(orientations=EO),
    "lames verticales 40/40": ps.LamesVerticales(orientations=EO),
    "lames verticales 40/20": ps.LamesVerticales(0.40, 0.20, orientations=EO),
    "grandes lames, été seul": ps.LamesSaisonnieres(ps.LamesVerticales(0.60, 0.30), None, orientations=EO),
    "grandes lames, sur le besoin": ps.LamesPilotees(ps.LamesVerticales(0.60, 0.30), orientations=EO),
    "grandes lames à 45°, besoin 23": ps.LamesPilotees(ps.LamesVerticales(0.60, 0.30, 45), 23.0, orientations=EO),
    "BSO sur la chaleur": ps.BSO("chaleur", orientations=EO),
    "BSO toujours baissé": ps.BSO("toujours", orientations=EO),
}


def salle() -> Model:
    piece = Room.from_box("salle", 8, 6, 3)
    for face in piece.faces:
        if face.type.name == "Wall" and round(face.azimuth) in (90, 270):
            face.apertures_by_ratio(0.40)
    return Model("salle_est_ouest", rooms=[piece])


def main(argv) -> int:
    if len(argv) < 2:
        print(__doc__)
        return 2
    chemin_epw = Path(argv[1]).resolve()
    epw = EPW(str(chemin_epw))
    choix = hyp.Hypotheses("bureau", "1975_1988")
    occupe = hyp.heures_occupees(hyp.USAGES["bureau"])
    sortie = Path("prototype/sorties/lames_est_ouest").resolve()
    print(f"{'protection':<32}{'h > 26':>8}{'h > 28':>8}{'chauffage':>11}{'>= 300 lx':>11}{'>= 100 lx':>11}{'médiane':>9}")
    for nom, protection in SCENARIOS.items():
        modele = salle()
        contexte = {}
        hyp.appliquer(modele, choix)
        if protection is not None:
            ps.poser(modele, protection, contexte)
        lumiere.poser_les_capteurs(modele)
        p = SimulationParameter()
        p.location = epw.location
        p.timestep = 4
        p.simulation_control = SimulationControl(False, False, False, False, True)
        p.output.reporting_frequency = "Hourly"
        for sortie_ep in (T_RESSENTIE, CHAUFFAGE, lumiere.ECLAIREMENT):
            p.output.add_output(sortie_ep)
        dossier = sortie / nom.replace(" ", "_").replace(",", "").replace("/", "_")
        dossier.mkdir(parents=True, exist_ok=True)
        idf = dossier / "in.idf"
        idf.write_text(p.to_idf() + "\n\n" + modele.to.idf(modele), encoding="utf-8")
        sql, *_reste, err = run_idf(str(idf), str(chemin_epw), silent=True)
        if sql is None:
            print(f"{nom} : EnergyPlus n'a rien rendu, voir {err}")
            return 1
        r = SQLiteResult(sql)
        t = [v for v, o in zip(r.data_collections_by_output_name(T_RESSENTIE)[0].values, occupe) if o]
        somme = lambda cle: sum(sum(c.values) for c in r.data_collections_by_output_name(cle))  # noqa: E731
        jour = next(iter(lumiere.lire(r, occupe).values()))
        print(f"{nom:<32}{sum(1 for v in t if v > 26):>8}{sum(1 for v in t if v > 28):>8}"
              f"{somme(CHAUFFAGE):>11.0f}{jour['autonomie_300_lux']:>11.0%}{jour['autonomie_100_lux']:>11.0%}"
              f"{jour['eclairement_median_lux']:>9}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
