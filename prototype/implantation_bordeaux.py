"""Contrôle du calage sur la carte, avec de vraies données.

On prend un vrai bâtiment de la BD TOPO, on en fait une « maquette » (un volume par niveau de 3 m, vitré à
30 %), puis on fausse exprès sa position de plusieurs mètres, comme le ferait une maquette mal géolocalisée.
Le calage doit retrouver le décalage. On calcule ensuite le bâtiment seul, puis entouré de ses voisins.

Usage :
    python prototype/implantation_bordeaux.py latitude longitude meteo.epw [erreur_est_m] [erreur_nord_m]
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
from shapely.geometry import Point, Polygon  # noqa: E402

from rayflect import environnement as env, hypotheses as hyp, lumiere, protections_solaires as ps  # noqa: E402
from rayflect.io import releve_vers_honeybee as conversion  # noqa: E402
from rayflect.io.lecture_ifc import Niveau, Releve  # noqa: E402

T_RESSENTIE = "Zone Operative Temperature"
CHAUFFAGE = "Zone Ideal Loads Supply Air Total Heating Energy"
HAUTEUR_D_ETAGE_M = 3.0


def maquette_depuis_la_carte(voisin: env.Voisin, erreur_m) -> Releve:
    """Un relevé fabriqué à partir d'un bâtiment de la carte, déplacé de `erreur_m`."""
    forme = Polygon(voisin.contour_m).simplify(0.5)
    contour = [(x - erreur_m[0], y - erreur_m[1]) for x, y in list(forme.exterior.coords)[:-1]]
    if Polygon(contour).exterior.is_ccw is False:
        contour.reverse()
    n = max(1, int(round(voisin.hauteur_m / HAUTEUR_D_ETAGE_M)))
    niveaux = [Niveau(f"niveau {k}", k * HAUTEUR_D_ETAGE_M, emprise_m=contour, plancher_m=k * HAUTEUR_D_ETAGE_M,
                      plafond_m=(k + 1) * HAUTEUR_D_ETAGE_M, aire_emprise_m2=round(forme.area, 1)) for k in range(n)]
    return Releve("carte", "aucun", "BD TOPO", None, None, None, 0.0, niveaux=niveaux)


def main(argv) -> int:
    if len(argv) < 4:
        print(__doc__)
        return 2
    latitude, longitude = float(argv[1]), float(argv[2])
    chemin_epw = Path(argv[3]).resolve()
    erreur = (float(argv[4]) if len(argv) > 4 else 14.0, float(argv[5]) if len(argv) > 5 else -9.0)
    epw = EPW(str(chemin_epw))
    carte = env.telecharger(latitude, longitude, 250.0)
    tous, _manques = env.lire(carte, latitude, longitude)
    # Le bâtiment étudié : celui de la carte le plus proche du point, entre 200 et 3 000 m² au sol.
    candidats = [v for v in tous if 200.0 < Polygon(v.contour_m).area < 3000.0]
    etudie = min(candidats, key=lambda v: Polygon(v.contour_m).distance(Point(0, 0)))
    releve = maquette_depuis_la_carte(etudie, erreur)
    print(f"bâtiment étudié : {etudie.identifiant}, {Polygon(etudie.contour_m).area:.0f} m² au sol, "
          f"{etudie.hauteur_m} m de haut, {len(releve.niveaux)} niveaux")
    print(f"erreur de position donnée exprès à la maquette : {erreur[0]} m vers l'est, {erreur[1]} m vers le nord")

    choix = hyp.Hypotheses("bureau", "1975_1988")
    occupe = hyp.heures_occupees(hyp.USAGES["bureau"])
    zones = "sans_zones" not in argv
    cas = (("seul", False), ("avec voisins", True)) if "seul" not in argv else (("seul", False),)
    print(f"{'cas':<16}{'niveau et côté':<26}{'h > 26':>8}{'chauffage':>11}{'>= 300 lx':>11}")
    for nom, entoure in cas:
        modele, rendu = conversion.convertir(releve, "etudie", conversion.PROFONDEUR_DE_FACADE_M if zones else None)
        etiquettes = {}
        for piece in modele.rooms:
            dehors = [f for f in piece.faces if f.type.name == "Wall" and f.boundary_condition.name == "Outdoors"]
            for face in dehors:
                face.apertures_by_ratio(0.30)
            etage = piece.identifier.split("_niveau_")[1].split("_")[0]
            if "_noyau_" in piece.identifier:
                cote = "noyau"
            elif zones and dehors:
                cote = "façade " + ps.secteur(max(dehors, key=lambda f: f.area).azimuth)
            else:
                cote = "plateau entier"
            etiquettes[piece.identifier.upper()] = (int(etage), cote)
        hyp.appliquer(modele, choix)
        lumiere.poser_les_capteurs(modele)
        p = SimulationParameter()
        p.location = epw.location
        p.timestep = 4
        p.simulation_control = SimulationControl(False, False, False, False, True)
        if entoure:
            bilan = env.entourer(modele, rendu.emprise_m, latitude, longitude, carte=carte)
            env.regler_le_calcul_des_ombres(p, modele)
            c = bilan["calage"]
            print(f"  calage : décalage retrouvé {c.decalage_m}, recouvrement {c.recouvrement:.0%}, "
                  f"bâtiment reconnu {c.batiment}, sûr : {c.sur}")
            print(f"  voisins : {bilan['tri']}, {bilan['faces_de_masque']} faces de masque")
            for manque in bilan["manques"]:
                print(f"  à savoir : {manque}")
        p.output.reporting_frequency = "Hourly"
        for cle in (T_RESSENTIE, CHAUFFAGE, lumiere.ECLAIREMENT):
            p.output.add_output(cle)
        dossier = Path("prototype/sorties/implantation").resolve() / nom.replace(" ", "_")
        dossier.mkdir(parents=True, exist_ok=True)
        idf = dossier / "in.idf"
        idf.write_text(p.to_idf() + "\n\n" + modele.to.idf(modele), encoding="utf-8")
        sql, *_reste, err = run_idf(str(idf), str(chemin_epw), silent=True)
        if sql is None:
            print(f"{nom} : EnergyPlus n'a rien rendu, voir {err}")
            return 1
        r = SQLiteResult(sql)
        chauffage = sum(sum(s.values) for s in r.data_collections_by_output_name(CHAUFFAGE))
        jour = lumiere.lire(r, occupe)
        # Par niveau et par côté : la zone la plus chaude et la moins éclairée de ce côté-là.
        par_cote = {}
        for serie in r.data_collections_by_output_name(T_RESSENTIE):
            zone = str(serie.header.metadata.get("Zone", "?"))
            etage, cote = etiquettes.get(zone.upper(), (-1, "?"))
            t = [v for v, o in zip(serie.values, occupe) if o]
            ligne = par_cote.setdefault((etage, cote), {"chaud": 0, "jour": None})
            ligne["chaud"] = max(ligne["chaud"], sum(1 for v in t if v > 26))
            lumiere_zone = jour.get(zone, {}).get("autonomie_300_lux")
            if lumiere_zone is not None:
                ligne["jour"] = lumiere_zone if ligne["jour"] is None else min(ligne["jour"], lumiere_zone)
        dernier = max(e for e, _c in par_cote)
        for (etage, cote), ligne in sorted(par_cote.items()):
            if etage not in (0, dernier // 2, dernier):
                continue
            clair = f"{ligne['jour']:.0%}" if ligne["jour"] is not None else "sans baie"
            print(f"{nom:<16}{f'niveau {etage}, {cote}':<26}{ligne['chaud']:>8}{'':>11}{clair:>11}")
        print(f"{nom:<16}{'bâtiment':<26}{'':>8}{chauffage:>11.0f}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
