"""Essais de vraisemblance : ce que la physique impose, vérifié sur plusieurs climats.

On ne compare pas ici à une valeur de référence. On vérifie des SENS : plus d'ombre donne moins d'heures
chaudes et plus de chauffage ; un climat plus chaud donne plus d'heures chaudes et moins de chauffage ; une
protection pilotée sur la chaleur ne coûte pas de chauffage. Un sens faux signale une erreur de signe, une
protection posée du mauvais côté, ou un composant qui n'agit pas.

La salle : un bureau de 8 m × 6 m × 3 m sous toiture, vitré à 40 % sur une façade, parois de 1975 à 1988.

Usage :
    python verification/vraisemblance.py [dossier_des_meteos]
"""

from __future__ import annotations

import json
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

from rayflect import hypotheses as hyp, lumiere, protections_solaires as ps, vegetation as veg  # noqa: E402
from rayflect import ventilation  # noqa: E402
from rayflect.io import meteo as meteo_du_lieu  # noqa: E402

REMARQUES: dict = {}

T_RESSENTIE = "Zone Operative Temperature"
CHAUFFAGE = "Zone Ideal Loads Supply Air Total Heating Energy"
CLIMATS = {"Lille": (50.63, 3.06), "Bordeaux": (44.84, -0.58), "Marseille": (43.30, 5.37)}
RANGEE = veg.alignement((-4.0, -6.0), (12.0, -6.0), 8.0)
TOUTES = None

# nom de la variante : ce qui la distingue de la salle de base (vitrée au sud, sans rien)
VARIANTES = {
    "base": {},
    "vitrée au nord": {"azimut": 0},
    "vitrée à l'est": {"azimut": 90},
    "vitrée à l'ouest": {"azimut": 270},
    "vitrée à 70 %": {"vitrage": 0.70},
    "casquette 0,5 m": {"protection": ps.Casquette(0.5)},
    "casquette 1,0 m": {"protection": ps.Casquette(1.0)},
    "casquette 1,5 m": {"protection": ps.Casquette(1.5)},
    "BSO toujours baissé": {"protection": ps.BSO("toujours")},
    "BSO sur la chaleur": {"protection": ps.BSO("chaleur")},
    "arbres clairs": {"arbres": [replace(a, feuillage=veg.ARBRE_CADUC_CLAIR) for a in RANGEE]},
    "arbres denses": {"arbres": [replace(a, feuillage=veg.ARBRE_CADUC_DENSE) for a in RANGEE]},
    "arbres persistants": {"arbres": [replace(a, feuillage=veg.ARBRE_PERSISTANT) for a in RANGEE]},
    "toit sombre": {"protection": ps.Toit(ps.TOIT_SOMBRE)},
    "toit clair": {"protection": ps.Toit(ps.TOIT_CLAIR_NEUF)},
    "photovoltaïque": {"protection": ps.PhotovoltaiqueEnToiture()},
    "double flux": {"vmc": ventilation.DOUBLE_FLUX},
    "surventilation": {"vmc": ventilation.SIMPLE_FLUX_SURVENTILATION},
    "fenêtres fermées": {"fenetres": False},
    "parois récentes": {"periode": "2013_2020"},
}


def meteo(nom: str, dossier: Path) -> Path:
    """Le fichier météo du climat, contrôlé, et réparé si son rayonnement du ciel est faux."""
    chemin, controle = meteo_du_lieu.preparer(*CLIMATS[nom], dossier)
    if not controle.bon:
        raise RuntimeError(f"météo de {nom} inutilisable : {controle.defauts}")
    REMARQUES[nom] = controle.remarques
    return chemin


def calculer(chemin_epw: Path, sortie: Path, azimut: int = 180, vitrage: float = 0.40, protection=None,
             arbres=None, vmc=None, fenetres: bool = True, periode: str = "1975_1988") -> dict:
    epw = EPW(str(chemin_epw))
    piece = Room.from_box("salle", 8, 6, 3)
    for face in piece.faces:
        if face.type.name == "Wall" and round(face.azimuth) % 360 == azimut:
            face.apertures_by_ratio(vitrage)
    modele = Model("salle", rooms=[piece])
    hyp.appliquer(modele, hyp.Hypotheses("bureau", periode, fenetres))
    if vmc is not None:
        ventilation.poser(modele, vmc)
    if arbres:
        # La rangée est plantée devant la façade vitrée, quelle que soit son orientation.
        modele.add_shades(veg.masques(arbres))
    if protection is not None:
        ps.poser(modele, replace(protection, orientations=TOUTES) if hasattr(protection, "orientations") else protection)
    lumiere.poser_les_capteurs(modele)
    p = SimulationParameter()
    p.location = epw.location
    p.timestep = 4
    p.simulation_control = SimulationControl(False, False, False, False, True)
    p.shadow_calculation.solar_distribution = "FullExterior"       # les mêmes réglages pour toutes les variantes
    p.shadow_calculation.calculation_method = "PolygonClipping"
    p.output.reporting_frequency = "Hourly"
    for cle in (T_RESSENTIE, CHAUFFAGE, lumiere.ECLAIREMENT, ps.PRODUCTION_PHOTOVOLTAIQUE):
        p.output.add_output(cle)
    sortie.mkdir(parents=True, exist_ok=True)
    idf = sortie / "in.idf"
    idf.write_text(p.to_idf() + "\n\n" + modele.to.idf(modele), encoding="utf-8")
    sql, *_reste, err = run_idf(str(idf), str(chemin_epw), silent=True)
    if sql is None:
        raise RuntimeError(f"EnergyPlus n'a rien rendu, voir {err}")
    r = SQLiteResult(sql)
    occupe = hyp.heures_occupees(hyp.USAGES["bureau"])
    temperatures = [v for v, o in zip(r.data_collections_by_output_name(T_RESSENTIE)[0].values, occupe) if o]
    jour = next(iter(lumiere.lire(r, occupe).values()))
    return {
        "chaud": sum(1 for v in temperatures if v > 26.0),
        "chauffage": round(sum(sum(c.values) for c in r.data_collections_by_output_name(CHAUFFAGE))),
        "lumiere": jour["autonomie_300_lux"],
        "production": round(sum(sum(c.values) for c in r.data_collections_by_output_name(ps.PRODUCTION_PHOTOVOLTAIQUE))),
    }


def attentes(r: dict) -> list:
    """Les sens attendus pour UN climat : (énoncé, tenu ou non, valeurs lues)."""
    def moins(a, b, cle):          # a strictement sous b
        return r[a][cle] < r[b][cle], f"{r[a][cle]} < {r[b][cle]}"

    def pas_plus(a, b, cle):       # a au plus b
        return r[a][cle] <= r[b][cle], f"{r[a][cle]} <= {r[b][cle]}"

    def pareil(a, b, cle, tolerance):
        ecart = abs(r[a][cle] - r[b][cle]) / max(1.0, r[b][cle])
        return ecart <= tolerance, f"{r[a][cle]} et {r[b][cle]}, écart {ecart:.1%}"

    liste = [
        ("le nord a moins d'heures chaudes que le sud", *moins("vitrée au nord", "base", "chaud")),
        ("le nord demande plus de chauffage que le sud", *moins("base", "vitrée au nord", "chauffage")),
        ("plus de vitrage au sud, plus d'heures chaudes", *moins("base", "vitrée à 70 %", "chaud")),
        ("une casquette de 0,5 m réduit les heures chaudes", *moins("casquette 0,5 m", "base", "chaud")),
        ("une casquette plus profonde les réduit davantage (1,0 m)", *moins("casquette 1,0 m", "casquette 0,5 m", "chaud")),
        # Au-delà d'un mètre, le gain s'épuise : à Lille, 51 heures restent avec 1,0 m comme avec 1,5 m (mesuré le
        # 22/11/2026). Le sens à tenir est qu'elle n'en ajoute pas.
        ("une casquette plus profonde ne les augmente pas (1,5 m)", *pas_plus("casquette 1,5 m", "casquette 1,0 m", "chaud")),
        ("une casquette coûte du chauffage", *moins("base", "casquette 1,0 m", "chauffage")),
        ("une casquette plus profonde en coûte davantage", *moins("casquette 1,0 m", "casquette 1,5 m", "chauffage")),
        ("un BSO toujours baissé réduit les heures chaudes", *moins("BSO toujours baissé", "base", "chaud")),
        ("un BSO toujours baissé coûte du chauffage", *moins("base", "BSO toujours baissé", "chauffage")),
        ("un BSO toujours baissé prive de lumière", *moins("BSO toujours baissé", "base", "lumiere")),
        ("un BSO sur la chaleur réduit les heures chaudes", *moins("BSO sur la chaleur", "base", "chaud")),
        ("un BSO sur la chaleur ne coûte pas de chauffage", *pareil("BSO sur la chaleur", "base", "chauffage", 0.01)),
        ("des arbres clairs réduisent les heures chaudes", *moins("arbres clairs", "base", "chaud")),
        ("des arbres denses les réduisent au moins autant", r["arbres denses"]["chaud"] <= r["arbres clairs"]["chaud"],
         f"{r['arbres denses']['chaud']} <= {r['arbres clairs']['chaud']}"),
        ("des arbres denses coûtent plus de chauffage que des clairs", *moins("arbres clairs", "arbres denses", "chauffage")),
        ("des arbres persistants en coûtent encore plus", *moins("arbres denses", "arbres persistants", "chauffage")),
        ("un toit clair réduit les heures chaudes", *moins("toit clair", "toit sombre", "chaud")),
        ("un toit clair coûte du chauffage", *moins("toit sombre", "toit clair", "chauffage")),
        ("le photovoltaïque produit", r["photovoltaïque"]["production"] > 0, f"{r['photovoltaïque']['production']} kWh"),
        ("le photovoltaïque ombre le toit : moins d'heures chaudes", *moins("photovoltaïque", "base", "chaud")),
        ("le double flux réduit le chauffage", *moins("double flux", "base", "chauffage")),
        ("le double flux ne change pas les heures chaudes", *pareil("double flux", "base", "chaud", 0.02)),
        ("la surventilation réduit les heures chaudes", *moins("surventilation", "base", "chaud")),
        ("la surventilation ne coûte pas de chauffage", *pareil("surventilation", "base", "chauffage", 0.01)),
        ("fenêtres fermées, plus d'heures chaudes", *moins("base", "fenêtres fermées", "chaud")),
        ("des parois récentes demandent moins de chauffage", *moins("parois récentes", "base", "chauffage")),
    ]
    return liste


def entre_climats(tous: dict) -> list:
    def ordre(cle, croissant):
        valeurs = [tous[c]["base"][cle] for c in ("Lille", "Bordeaux", "Marseille")]
        tenu = valeurs == sorted(valeurs, reverse=not croissant) and len(set(valeurs)) == 3
        return tenu, " ; ".join(f"{c} {v}" for c, v in zip(("Lille", "Bordeaux", "Marseille"), valeurs))
    return [
        ("du nord au sud, de plus en plus d'heures chaudes", *ordre("chaud", True)),
        ("du nord au sud, de moins en moins de chauffage", *ordre("chauffage", False)),
        ("le photovoltaïque produit plus à Marseille qu'à Lille",
         tous["Marseille"]["photovoltaïque"]["production"] > tous["Lille"]["photovoltaïque"]["production"],
         f"{tous['Marseille']['photovoltaïque']['production']} > {tous['Lille']['photovoltaïque']['production']} kWh"),
    ]


def campagne(dossier_meteo: Path, sortie: Path, climats=tuple(CLIMATS), variantes=None) -> tuple:
    """(résultats par climat et variante, liste des attentes avec leur climat)."""
    variantes = variantes or VARIANTES
    tous, bilan = {}, []
    for climat in climats:
        chemin = meteo(climat, dossier_meteo)
        tous[climat] = {nom: calculer(chemin, sortie / climat / "".join(c if c.isalnum() else "_" for c in nom), **reglages)
                        for nom, reglages in variantes.items()}
        bilan += [(climat, *attente) for attente in attentes(tous[climat])]
    if set(climats) >= {"Lille", "Bordeaux", "Marseille"}:
        bilan += [("les 3 climats", *attente) for attente in entre_climats(tous)]
    return tous, bilan


def main(argv) -> int:
    dossier_meteo = Path(argv[1]).resolve() if len(argv) > 1 else Path("prototype/meteo").resolve()
    sortie = Path("verification/sorties/vraisemblance").resolve()
    tous, bilan = campagne(dossier_meteo, sortie)
    (sortie / "resultats.json").write_text(json.dumps(tous, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"{'variante':<22}" + "".join(f"{c + ' chaud':>16}{'chauffage':>11}" for c in tous))
    for nom in VARIANTES:
        print(f"{nom:<22}" + "".join(f"{tous[c][nom]['chaud']:>16}{tous[c][nom]['chauffage']:>11}" for c in tous))
    for climat, remarques in REMARQUES.items():
        for remarque in remarques:
            print(f"  météo de {climat} : {remarque}")
    tenues = sum(1 for _c, _e, tenu, _v in bilan if tenu)
    print(f"\n{tenues} attentes tenues sur {len(bilan)}")
    for climat, enonce, tenu, valeurs in bilan:
        if not tenu:
            print(f"  NON TENUE, {climat} : {enonce} ({valeurs})")
    return 0 if tenues == len(bilan) else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
