"""Contrôle : que change la ventilation mécanique, surtout pour le noyau ?

Un immeuble de bureaux de 3 niveaux, plateau de 40 m × 20 m, découpé en zones de façade et noyau, vitré à
30 %. On lit l'étage du milieu : le noyau, et la façade la plus chaude. Chaque VMC du catalogue est calculée
sans protection solaire, puis avec des BSO pilotés sur la chaleur.

Usage :
    python prototype/vmc_energyplus.py meteo.epw
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from honeybee_energy.run import run_idf  # noqa: E402
from honeybee_energy.simulation.control import SimulationControl  # noqa: E402
from honeybee_energy.simulation.parameter import SimulationParameter  # noqa: E402
from ladybug.epw import EPW  # noqa: E402
from ladybug.sql import SQLiteResult  # noqa: E402

from rayflect import hypotheses as hyp, protections_solaires as ps, ventilation  # noqa: E402
from rayflect.io import releve_vers_honeybee as conversion  # noqa: E402
from rayflect.io.lecture_ifc import Niveau, Releve  # noqa: E402

T_RESSENTIE = "Zone Operative Temperature"
CHAUFFAGE = "Zone Ideal Loads Supply Air Total Heating Energy"
CONTOUR = [(0, 0), (40, 0), (40, 20), (0, 20)]


def main(argv) -> int:
    if len(argv) < 2:
        print(__doc__)
        return 2
    chemin_epw = Path(argv[1]).resolve()
    epw = EPW(str(chemin_epw))
    releve = Releve("essai", "aucun", "essai", None, None, None, 0.0, niveaux=[
        Niveau(f"niveau {k}", 3.0 * k, emprise_m=CONTOUR, plancher_m=3.0 * k, plafond_m=3.0 * k + 3.0,
               aire_emprise_m2=800.0) for k in range(3)])
    choix = hyp.Hypotheses("bureau", "1975_1988")
    occupe = hyp.heures_occupees(hyp.USAGES["bureau"])
    print(f"{'ventilation':<38}{'protection':<14}{'noyau':>7}{'façade':>8}{'chauffage kWh':>15}")
    for vmc in ventilation.CATALOGUE:
        for nom_protection, protection in (("aucune", None), ("BSO chaleur", ps.BSO())):
            modele, rendu = conversion.convertir(releve, "b", conversion.PROFONDEUR_DE_FACADE_M)
            for piece in modele.rooms:
                for face in piece.faces:
                    if face.type.name == "Wall" and face.boundary_condition.name == "Outdoors":
                        face.apertures_by_ratio(0.30)
            hyp.appliquer(modele, choix)
            ventilation.poser(modele, vmc)
            if protection is not None:
                ps.poser(modele, protection)
            p = SimulationParameter()
            p.location = epw.location
            p.timestep = 4
            p.simulation_control = SimulationControl(False, False, False, False, True)
            p.output.reporting_frequency = "Hourly"
            p.output.add_output(T_RESSENTIE)
            p.output.add_output(CHAUFFAGE)
            dossier = Path("prototype/sorties/vmc").resolve() / f"{vmc.nom}_{nom_protection}".replace(" ", "_").replace(",", "")
            dossier.mkdir(parents=True, exist_ok=True)
            idf = dossier / "in.idf"
            idf.write_text(p.to_idf() + "\n\n" + modele.to.idf(modele), encoding="utf-8")
            sql, *_reste, err = run_idf(str(idf), str(chemin_epw), silent=True)
            if sql is None:
                print(f"{vmc.nom} : EnergyPlus n'a rien rendu, voir {err}")
                return 1
            r = SQLiteResult(sql)
            chauffage = sum(sum(c.values) for c in r.data_collections_by_output_name(CHAUFFAGE))
            etiquettes = {k.upper(): v for k, v in rendu.etiquettes.items()}
            noyau, facade = 0, 0
            for serie in r.data_collections_by_output_name(T_RESSENTIE):
                rang, _niveau, cote = etiquettes[str(serie.header.metadata["Zone"]).upper()]
                if rang != 1:
                    continue
                heures = sum(1 for t, o in zip(serie.values, occupe) if o and t > 26.0)
                if cote == "noyau":
                    noyau = heures
                else:
                    facade = max(facade, heures)
            print(f"{vmc.nom:<38}{nom_protection:<14}{noyau:>7}{facade:>8}{chauffage:>15.0f}")
    print("\nnoyau et façade : heures au-dessus de 26 °C en occupation, à l'étage du milieu ; "
          "façade : la plus chaude des 4")
    for vmc in ventilation.CATALOGUE:
        print(f"  - {vmc.justification()}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
