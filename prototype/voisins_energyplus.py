"""Contrôle : que changent les bâtiments voisins ?

Une salle de bureau de 8 m × 6 m × 3 m, vitrée au sud, à l'est et à l'ouest, posée au rez-de-chaussée d'un
point donné. On la calcule seule, puis entourée des bâtiments de la BD TOPO.

Usage :
    python prototype/voisins_energyplus.py latitude longitude meteo.epw [rayon_m]
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

from rayflect import environnement as env, hypotheses as hyp, lumiere, protections_solaires as ps  # noqa: E402

T_RESSENTIE = "Zone Operative Temperature"
CHAUFFAGE = "Zone Ideal Loads Supply Air Total Heating Energy"
SALLE = [(0.0, 0.0), (8.0, 0.0), (8.0, 6.0), (0.0, 6.0)]


def salle() -> Room:
    piece = Room.from_box("salle", 8, 6, 3)
    for face in piece.faces:
        if face.type.name == "Wall" and round(face.azimuth) in (90, 180, 270):
            face.apertures_by_ratio(0.40)
    return piece


def main(argv) -> int:
    if len(argv) < 4:
        print(__doc__)
        return 2
    latitude, longitude = float(argv[1]), float(argv[2])
    chemin_epw = Path(argv[3]).resolve()
    rayon = float(argv[4]) if len(argv) > 4 else 150.0
    epw = EPW(str(chemin_epw))
    tous, manques = env.lire(env.telecharger(latitude, longitude, rayon), latitude, longitude)
    voisins, bilan = env.filtrer(tous, SALLE)
    sol = env.altitude_du_site(tous)
    print(f"BD TOPO, {rayon:.0f} m autour du point : {len(tous)} bâtiments, {bilan}, "
          f"{len(env.masques(voisins, sol))} faces de masque")
    for manque in manques:
        print(f"  à savoir : {manque}")
    choix = hyp.Hypotheses("bureau", "1975_1988")
    occupe = hyp.heures_occupees(hyp.USAGES["bureau"])
    print(f"{'cas':<34}{'h > 26':>8}{'h > 28':>8}{'chauffage':>11}{'>= 300 lx':>11}{'calcul':>22}")
    for nom, entoure, protection in (("seule, sans protection", False, None),
                                     ("avec voisins, sans protection", True, None),
                                     ("seule, BSO sur la chaleur", False, ps.BSO()),
                                     ("avec voisins, BSO sur la chaleur", True, ps.BSO())):
        modele = Model("salle", rooms=[salle()], orphaned_shades=env.masques(voisins, sol) if entoure else [])
        hyp.appliquer(modele, choix)
        if protection is not None:
            ps.poser(modele, protection)
        lumiere.poser_les_capteurs(modele)
        p = SimulationParameter()
        p.location = epw.location
        p.timestep = 4
        p.simulation_control = SimulationControl(False, False, False, False, True)
        if entoure:
            env.regler_le_calcul_des_ombres(p, modele)
        p.output.reporting_frequency = "Hourly"
        for cle in (T_RESSENTIE, CHAUFFAGE, lumiere.ECLAIREMENT):
            p.output.add_output(cle)
        dossier = Path("prototype/sorties/voisins").resolve() / nom.replace(" ", "_").replace(",", "")
        dossier.mkdir(parents=True, exist_ok=True)
        idf = dossier / "in.idf"
        idf.write_text(p.to_idf() + "\n\n" + modele.to.idf(modele), encoding="utf-8")
        sql, *_reste, err = run_idf(str(idf), str(chemin_epw), silent=True)
        if sql is None:
            print(f"{nom} : EnergyPlus n'a rien rendu, voir {err}")
            return 1
        r = SQLiteResult(sql)
        t = [v for v, o in zip(r.data_collections_by_output_name(T_RESSENTIE)[0].values, occupe) if o]
        chauffage = sum(sum(c.values) for c in r.data_collections_by_output_name(CHAUFFAGE))
        jour = next(iter(lumiere.lire(r, occupe).values()))
        fin = [ligne for ligne in Path(err).read_text(errors="ignore").splitlines() if "Elapsed Time" in ligne]
        duree = fin[-1].split("=")[-1].strip() if fin else "?"
        print(f"{nom:<34}{sum(1 for v in t if v > 26):>8}{sum(1 for v in t if v > 28):>8}{chauffage:>11.0f}"
              f"{jour['autonomie_300_lux']:>11.0%}{duree:>22}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
