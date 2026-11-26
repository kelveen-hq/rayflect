"""Le débit d'air des fenêtres ouvertes : EnergyPlus applique-t-il les formules que nous lui donnons ?

Ce que l'essai prouve : que les ouvrants écrits par `rayflect.aeration` donnent dans EnergyPlus, à chaque pas de
temps, le débit des formules de son en-tête, avec nos coefficients. Il le fait pour une pièce ventilée par une
seule façade, puis pour une pièce traversante. Il a servi à relever la règle qu'EnergyPlus applique à
l'efficacité du vent quand on le laisse la calculer (`aeration.efficacite_du_vent`).

Ce qu'il ne prouve pas : que ces formules disent le débit réel d'une fenêtre. Aucun cas normalisé ne porte sur
la ventilation par les fenêtres, et aucune mesure n'est rejouée ici.

Le local est celui des cas 600 (2 baies au sud) et 620 (1 baie à l'est, 1 à l'ouest) de la norme ANSI/ASHRAE
140, à Denver ; les fenêtres y restent ouvertes toute l'année, quelle que soit la température. Le débit se
recalcule à la main depuis ce qu'EnergyPlus rend lui-même : la température de la pièce au pas précédent (c'est
celle qu'il utilise), la température, la vitesse et la direction du vent à la hauteur de la pièce.

Usage :
    python verification/ouvrants.py [dossier_de_sortie]
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from ladybug.epw import EPW
from ladybug.sql import SQLiteResult

from rayflect import aeration, moteur

sys.path.insert(0, str(Path(__file__).resolve().parent))
import bestest  # noqa: E402

DEBIT = "Zone Ventilation Outdoor Density Volume Flow Rate"
DEDANS = "Zone Mean Air Temperature"
DEHORS = "Zone Outdoor Air Drybulb Temperature"
VENT = "Zone Outdoor Air Wind Speed"
DIRECTION = "Site Wind Direction"
CAS = {"une_facade": ("600", False), "traversant": ("620", True)}
TOUJOURS_OUVERT = dict(heures=(0, 24), seuil_interieur_c=-50.0, exterieur_minimal_c=-50.0, ecart_minimal_k=-100.0)


def calculer(cas: str, sortie: Path) -> dict:
    base, traversant = CAS[cas]
    meteo = bestest.reference.meteo_de_denver()
    reglages = bestest.parametres(EPW(str(meteo)))
    reglages.output.reporting_frequency = "Timestep"
    for nom in (DEBIT, DEDANS, DEHORS, VENT, DIRECTION):
        reglages.output.add_output(nom)
    modele = bestest.local(base)
    fiche = aeration.Ouvrants(traversant=traversant, **TOUJOURS_OUVERT)
    texte, _a_dire = aeration.poser(modele, fiche, None)
    dossier = Path(sortie) / f"ouvrants_{cas}"
    dossier.mkdir(parents=True, exist_ok=True)
    idf = dossier / "in.idf"
    idf.write_text(reglages.to_idf() + "\n\n" + modele.to.idf(modele) + texte, encoding="utf-8")
    try:
        sql, _journal = moteur.lancer(idf, meteo)
    except moteur.CalculFautif as erreur:
        raise RuntimeError(f"ouvrants, {cas} : {erreur}") from erreur
    resultats = SQLiteResult(sql)
    lu = {nom: resultats.data_collections_by_output_name(nom)[0].values for nom in (DEBIT, DEDANS, DEHORS, VENT, DIRECTION)}
    baies = [baie for face in modele.rooms[0].faces for baie in face.apertures]
    total_energyplus = total_formule = 0.0
    ecarts = []
    for pas in range(1, len(lu[DEBIT])):
        attendu = sum(aeration.debit_m3_s(
            baie.area * fiche.part_ouvrable, baie.geometry.max.z - baie.geometry.min.z, lu[DEDANS][pas - 1],
            lu[DEHORS][pas], lu[VENT][pas], aeration.efficacite_du_vent(traversant, baie.azimuth, lu[DIRECTION][pas]))
            for baie in baies)
        total_energyplus += lu[DEBIT][pas]
        total_formule += attendu
        if attendu > 1e-6:
            ecarts.append(abs(lu[DEBIT][pas] / attendu - 1.0))
    ecarts.sort()
    return {"pas_de_temps": len(ecarts), "debit_moyen_m3_s": round(total_energyplus / len(lu[DEBIT]), 4),
            "energyplus_sur_formule": round(total_energyplus / total_formule, 5),
            "ecart_median": round(ecarts[len(ecarts) // 2], 5),
            "ecart_a_95_pour_cent": round(ecarts[int(0.95 * len(ecarts))], 5)}


def main(argv: list[str]) -> int:
    sortie = Path(argv[1]).resolve() if len(argv) > 1 else Path("verification/sorties").resolve()
    rendu = {}
    for cas in CAS:
        rendu[cas] = calculer(cas, sortie)
        r = rendu[cas]
        print(f"{cas:12s} débit moyen {r['debit_moyen_m3_s']:.3f} m3/s   EnergyPlus / formule sur l'année "
              f"{r['energyplus_sur_formule']:.4f}   écart médian {100 * r['ecart_median']:.2f} %   "
              f"95 % des pas à moins de {100 * r['ecart_a_95_pour_cent']:.1f} %")
    (sortie / "ouvrants.json").write_text(json.dumps(rendu, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
