"""Contrôle : la bibliothèque de composants, comparés sur une même salle.

Une salle de bureau de 8 m × 6 m × 3 m sous toiture, vitrée à 40 % au sud. Chaque composant est posé seul :
protections construites, végétation, toiture. On lit les heures chaudes en occupation, le chauffage, la
lumière du jour, et la production quand il y a du photovoltaïque.

Usage :
    python prototype/composants_energyplus.py meteo.epw [periode]
"""

from __future__ import annotations

import sys
from dataclasses import replace
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
from rayflect import vegetation as veg  # noqa: E402

T_RESSENTIE = "Zone Operative Temperature"
CHAUFFAGE = "Zone Ideal Loads Supply Air Total Heating Energy"
RANGEE = veg.alignement((-4.0, -6.0), (12.0, -6.0), 8.0)


def arbres(feuillage):
    return [replace(a, feuillage=feuillage) for a in RANGEE]


# nom : (famille, ce qu'on pose)
COMPOSANTS = {
    "rien": ("", None),
    "casquette de 0,8 m": ("construit", ps.Casquette()),
    "balcon de 1,5 m": ("construit", ps.Balcon()),
    "lames horizontales fixes": ("construit", ps.LamesHorizontales()),
    "grandes lames pilotées": ("construit", ps.LamesPilotees(orientations=ps.SUD)),
    "BSO sur la chaleur": ("construit", ps.BSO()),
    "pergola, vigne ou glycine": ("végétal", veg.Pergola()),
    "pergola, feuillage persistant": ("végétal", veg.Pergola(feuillage=veg.LIERRE)),
    "vigne vierge sur les murs": ("végétal", veg.Grimpante()),
    "lierre sur les murs": ("végétal", veg.Grimpante(feuillage=veg.LIERRE)),
    "3 arbres caducs denses à 6 m": ("végétal", arbres(veg.ARBRE_CADUC_DENSE)),
    "3 arbres caducs clairs à 6 m": ("végétal", arbres(veg.ARBRE_CADUC_CLAIR)),
    "3 arbres persistants à 6 m": ("végétal", arbres(veg.ARBRE_PERSISTANT)),
    "toit sombre": ("toiture", ps.Toit(ps.TOIT_SOMBRE)),
    "toit clair vieilli": ("toiture", ps.Toit(ps.TOIT_CLAIR_VIEILLI)),
    "toit clair neuf": ("toiture", ps.Toit(ps.TOIT_CLAIR_NEUF)),
    "photovoltaïque sur 50 % du toit": ("toiture", ps.PhotovoltaiqueEnToiture()),
}


def main(argv) -> int:
    if len(argv) < 2:
        print(__doc__)
        return 2
    chemin_epw = Path(argv[1]).resolve()
    periode = argv[2] if len(argv) > 2 else "1975_1988"
    epw = EPW(str(chemin_epw))
    choix = hyp.Hypotheses("bureau", periode)
    occupe = hyp.heures_occupees(hyp.USAGES["bureau"])
    print(f"parois de la période {periode}")
    print(f"{'composant':<34}{'famille':<11}{'h > 26':>7}{'h > 28':>7}{'chauffage':>10}{'>= 300 lx':>10}{'production':>11}")
    for nom, (famille, objet) in COMPOSANTS.items():
        piece = Room.from_box("salle", 8, 6, 3)
        for face in piece.faces:
            if face.type.name == "Wall" and round(face.azimuth) == 180:
                face.apertures_by_ratio(0.40)
        modele = Model("salle", rooms=[piece])
        hyp.appliquer(modele, choix)
        if isinstance(objet, list):
            modele.add_shades(veg.masques(objet))
        elif isinstance(objet, (veg.Pergola, veg.Grimpante)):
            veg.poser(modele, objet)
        elif objet is not None:
            ps.poser(modele, objet)
        lumiere.poser_les_capteurs(modele)
        p = SimulationParameter()
        p.location = epw.location
        p.timestep = 4
        p.simulation_control = SimulationControl(False, False, False, False, True)
        # LES MÊMES RÉGLAGES POUR TOUS LES CAS. Comparer un cas calculé avec les reflets du sol à un autre
        # calculé sans fausse l'écart de 2 à 3 % : assez pour faire baisser le chauffage sous une vigne.
        p.shadow_calculation.solar_distribution = "FullExterior"
        p.shadow_calculation.calculation_method = "PolygonClipping"
        p.output.reporting_frequency = "Hourly"
        for cle in (T_RESSENTIE, CHAUFFAGE, lumiere.ECLAIREMENT, ps.PRODUCTION_PHOTOVOLTAIQUE):
            p.output.add_output(cle)
        dossier = Path("prototype/sorties/composants").resolve() / periode / "".join(
            c if c.isalnum() else "_" for c in nom)
        dossier.mkdir(parents=True, exist_ok=True)
        idf = dossier / "in.idf"
        idf.write_text(p.to_idf() + "\n\n" + modele.to.idf(modele), encoding="utf-8")
        sql, *_reste, err = run_idf(str(idf), str(chemin_epw), silent=True)
        if sql is None:
            print(f"{nom} : EnergyPlus n'a rien rendu, voir {err}")
            continue
        r = SQLiteResult(sql)
        t = [v for v, o in zip(r.data_collections_by_output_name(T_RESSENTIE)[0].values, occupe) if o]
        chauffage = sum(sum(c.values) for c in r.data_collections_by_output_name(CHAUFFAGE))
        jour = next(iter(lumiere.lire(r, occupe).values()))
        production = sum(sum(c.values) for c in r.data_collections_by_output_name(ps.PRODUCTION_PHOTOVOLTAIQUE))
        print(f"{nom:<34}{famille:<11}{sum(1 for v in t if v > 26):>7}{sum(1 for v in t if v > 28):>7}"
              f"{chauffage:>10.0f}{jour['autonomie_300_lux']:>10.0%}"
              f"{(f'{production:.0f} kWh' if production else ''):>11}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
