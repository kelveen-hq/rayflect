"""D'une maquette IFC à un résultat, sans fichier d'étude : tout se dit sur la ligne de commande.

Pour une étude qu'on veut rejouer ou partager, préférer `rayflect etude fichier.toml`.

Usage :
    python prototype/ifc_energyplus.py maquette.ifc [usage] [periode] [fenetres] [options...]
    usage    : bureau, enseignement ou logement
    periode  : voir rayflect.hypotheses, par exemple 1975_1988
    fenetres : fermees, ouvrables ou nuit
    options, dans l'ordre qu'on veut :
      zones    découpe les grands plateaux en zones de façade et noyau
      voisins  entoure le bâtiment de ceux de la BD TOPO (France seulement)
      rapide   ne calcule que 3 scénarios au lieu de 6
      double_flux     ventilation avec récupération de chaleur
      surventilation  surventilation mécanique de nuit
    le lieu, par ordre de confiance :
      adresse="12 rue X, Ville"   adresse en France, passée au géocodeur de l'IGN
      point=44.84,-0.57           latitude et longitude
      sinon, la position écrite dans la maquette, signalée comme non confirmée
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from rayflect import etude as etudes  # noqa: E402

OPTIONS = ("zones", "voisins", "rapide", "double_flux", "surventilation")


def main(argv) -> int:
    if len(argv) < 2:
        print(__doc__)
        return 2
    options = {a for a in argv[2:] if a in OPTIONS}
    adresse = next((a[len("adresse="):] for a in argv[2:] if a.startswith("adresse=")), None)
    point = next((a[len("point="):] for a in argv[2:] if a.startswith("point=")), None)
    reste = [a for a in argv[2:] if a not in options and not a.startswith(("adresse=", "point="))]
    maquette = Path(argv[1]).resolve()
    scenarios = etudes.scenarios_par_defaut()
    if "rapide" in options:
        scenarios = [s for s in scenarios if s.nom in etudes.SCENARIOS_RAPIDES]
    try:
        etude = etudes.Etude(
            maquette=maquette, usage=reste[0] if len(reste) > 0 else "bureau",
            periode=reste[1] if len(reste) > 1 else "1975_1988",
            fenetres=reste[2] if len(reste) > 2 else "ouvrables",
            zones="zones" in options, voisins="voisins" in options, adresse=adresse,
            coordonnees=tuple(float(v) for v in point.split(",")) if point else None,
            double_flux="double_flux" in options, surventilation="surventilation" in options,
            scenarios=scenarios)
        sortie = Path("prototype/sorties") / "_".join(
            [maquette.stem, etude.usage, etude.periode, etude.fenetres] + sorted(options))
        bilan = etudes.calculer(etude, sortie)
    except (etudes.EtudeInvalide, ValueError) as erreur:
        print(f"ÉTUDE NON JOUÉE : {erreur}")
        return 1
    print()
    print(etudes.presenter(bilan))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
