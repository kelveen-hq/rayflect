"""La commande `rayflect` : tout ce que fait l'outil, depuis une seule entrée.

    rayflect modele mon_etude.toml        écrit un fichier d'étude à remplir
    rayflect etude mon_etude.toml         joue l'étude et affiche la comparaison des scénarios
    rayflect proposer mon_etude.toml      cherche les mesures qui tiennent ses objectifs ([objectifs])
    rayflect releve batiment.ifc          dit ce qui a été lu dans la maquette, et ce qui manque
    rayflect releve rdc.dxf etage.dxf     de même depuis des plans, un par niveau du bas vers le haut
    rayflect lieu "12 rue X, Ville"       dit où l'adresse a été trouvée, et ce qu'on sait du lieu : commune,
                                        altitude, zone climatique, température de base (un nom de ville suffit)
    rayflect cache                        dit où sont rangés les fichiers téléchargés
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


def duree_en_clair(secondes: float) -> str:
    """Un temps restant, arrondi comme on le dirait : il est estimé, pas mesuré."""
    if secondes < 10:
        return "quelques secondes"
    if secondes < 90:
        return f"environ {int(round(secondes / 10.0)) * 10} s"
    if secondes < 5400:
        return f"environ {int(round(secondes / 60.0))} min"
    return f"environ {secondes / 3600.0:.1f} h".replace(".", ",")


class Affichage:
    """Montre où en est le calcul : la liste des étapes, celle en cours, le pourcentage et le temps restant.

    Sur un écran, la ligne d'avancement se réécrit sur place. Vers un fichier ou un autre programme, une ligne
    est écrite à chaque étape, puis tous les 10 %.
    """
    PAS_HORS_ECRAN = 10         # en points de pourcentage

    def __init__(self, sortie=None, sur_place=None) -> None:
        self.sortie = sortie or sys.stdout
        self.sur_place = self.sortie.isatty() if sur_place is None else sur_place
        self._rang, self._dernier, self._largeur = 0, -1, 0

    def _effacer(self) -> None:
        if self.sur_place and self._largeur:
            self.sortie.write("\r" + " " * self._largeur + "\r")
            self._largeur = 0

    def dire(self, texte: str) -> None:
        self._effacer()
        print(texte, file=self.sortie, flush=True)

    @staticmethod
    def ligne(avancement) -> str:
        texte = f"  {int(avancement.part * 100)} % du calcul"
        if avancement.reste_s is not None and avancement.part < 1.0:
            texte += f", encore {duree_en_clair(avancement.reste_s)}"
        if len(avancement.en_cours) > 1:
            texte += " (" + ", ".join(f"{nom} en attente" if part is None else f"{nom} {int(part * 100)} %"
                                      for nom, part in avancement.en_cours.items()) + ")"
        return texte

    def suivre(self, avancement) -> None:
        if not self._rang:
            self.dire(f"{len(avancement.etapes)} étapes : " + " ; ".join(
                f"{rang}. {titre}" for rang, titre in enumerate(avancement.etapes, start=1)))
        if avancement.rang != self._rang:
            self._rang, self._dernier = avancement.rang, -1
            self.dire(f"étape {avancement.rang} sur {len(avancement.etapes)} : {avancement.etape}")
        if not avancement.en_cours:
            return
        ligne = self.ligne(avancement)
        if self.sur_place:
            self.sortie.write("\r" + ligne.ljust(self._largeur))
            self.sortie.flush()
            self._largeur = max(self._largeur, len(ligne))
        elif int(avancement.part * 100) // self.PAS_HORS_ECRAN > self._dernier:
            self._dernier = int(avancement.part * 100) // self.PAS_HORS_ECRAN
            print(ligne, file=self.sortie, flush=True)


def _etude(arguments) -> int:
    from rayflect import etude

    from rayflect import extensions

    for rate in extensions.charger():
        print(f"à savoir : {rate}", file=sys.stderr)
    fichier = Path(arguments.fichier).resolve()
    sortie = Path(arguments.sortie).resolve() if arguments.sortie else fichier.parent / "sorties" / fichier.stem
    affichage = Affichage()
    try:
        lue = etude.lire(fichier)
        plusieurs = arguments.climats.split(",") if arguments.climats else None
        if plusieurs or isinstance(lue.climat, list):
            rendus = etude.calculer_par_climat(lue, sortie, plusieurs, affichage.dire, affichage.suivre)
            print()
            print(etude.comparer_les_climats(rendus))
            print(f"\nrésultats écrits dans {sortie}, un dossier par climat")
            return 0
        bilan = etude.calculer(lue, sortie, affichage.dire, affichage.suivre)
    except etude.EtudeInvalide as erreur:
        affichage.dire("")
        print(f"ÉTUDE NON JOUÉE : {erreur}", file=sys.stderr)
        return 1
    print()
    print(etude.presenter(bilan))
    print(f"\nrésultats écrits dans {sortie}")
    return 0


def _proposer(arguments) -> int:
    from rayflect import etude, propositions

    fichier = Path(arguments.fichier).resolve()
    sortie = Path(arguments.sortie).resolve() if arguments.sortie else fichier.parent / "sorties" / f"{fichier.stem}_propositions"
    affichage = Affichage()
    try:
        rendu = etude.proposer(etude.lire(fichier), sortie, affichage.dire, affichage.suivre)
    except etude.EtudeInvalide as erreur:
        affichage.dire("")
        print(f"PROPOSITIONS NON CHERCHÉES : {erreur}", file=sys.stderr)
        return 1
    print()
    print(propositions.presenter(rendu))
    print(f"\nrésultats écrits dans {sortie}")
    return 0


def _modele(arguments) -> int:
    from rayflect import etude

    fichier = Path(arguments.fichier).resolve()
    if fichier.exists():
        print(f"{fichier} existe déjà : il n'est pas remplacé", file=sys.stderr)
        return 1
    fichier.write_text(etude.MODELE, encoding="utf-8")
    print(f"modèle d'étude écrit dans {fichier}")
    return 0


def _releve(arguments) -> int:
    from rayflect import etude
    from rayflect.io import releve

    try:
        fichiers = [Path(f).resolve() for f in arguments.maquette]
        lu = etude.relever(etude.Etude(maquette=fichiers[0], plan={"etages": fichiers[1:]}))
        print(releve.resume(lu))
        if arguments.dessin:
            if fichiers[0].suffix.lower() != ".dxf":
                print("--dessin ne vaut que pour un plan DXF", file=sys.stderr)
                return 1
            from rayflect.io import lecture_dxf

            for rang, fichier in enumerate(fichiers):
                sortie = Path(arguments.dessin).resolve()
                sortie = sortie.with_name(f"{sortie.stem}_{rang}{sortie.suffix}") if len(fichiers) > 1 else sortie
                sortie.write_text(lecture_dxf.dessin_de_controle(fichier, lu, rang), encoding="utf-8")
                print(f"dessin de contrôle du niveau {rang} : {sortie}")
    except (etude.EtudeInvalide, OSError) as erreur:
        print(f"MAQUETTE NON LUE : {erreur}", file=sys.stderr)
        return 1
    return 0


def _lieu(arguments) -> int:
    from rayflect import lieu

    try:
        trouve = lieu.geocoder(arguments.adresse)
    except lieu.LieuIntrouvable as erreur:
        print(f"LIEU À DEMANDER : {erreur}", file=sys.stderr)
        return 1
    lieu.completer(trouve)
    print(trouve.resume())
    for ligne in trouve.fiche():
        print(f"  {ligne}")
    for remarque in trouve.remarques:
        print(f"à savoir : {remarque}")
    return 0


def _cache(_arguments) -> int:
    from rayflect import cache

    print(cache.racine())
    return 0


def main(argv=None) -> int:
    for flux in (sys.stdout, sys.stderr):           # une console Windows ancienne ne sait pas écrire « é »
        if hasattr(flux, "reconfigure"):
            flux.reconfigure(encoding="utf-8", errors="replace")
    analyseur = argparse.ArgumentParser(prog="rayflect", description=__doc__,
                                        formatter_class=argparse.RawDescriptionHelpFormatter)
    commandes = analyseur.add_subparsers(dest="commande", required=True)
    c = commandes.add_parser("etude", help="joue une étude")
    c.add_argument("fichier")
    c.add_argument("--sortie", help="dossier des résultats (par défaut : sorties/ à côté du fichier d'étude)")
    c.add_argument("--climats", help="joue l'étude sous plusieurs climats et les compare, par exemple "
                                     "type,ete_le_plus_chaud,futur ou type,2003,2022")
    c.set_defaults(action=_etude)
    c = commandes.add_parser("proposer", help="cherche les mesures qui tiennent les objectifs de l'étude ([objectifs])")
    c.add_argument("fichier")
    c.add_argument("--sortie", help="dossier des résultats (par défaut : sorties/<étude>_propositions)")
    c.set_defaults(action=_proposer)
    c = commandes.add_parser("modele", help="écrit un fichier d'étude à remplir")
    c.add_argument("fichier")
    c.set_defaults(action=_modele)
    c = commandes.add_parser("releve", help="lit une maquette IFC, ou des plans DXF du bas vers le haut")
    c.add_argument("maquette", nargs="+")
    c.add_argument("--dessin", help="pour un plan DXF : écrit un SVG montrant le contour et les baies lus")
    c.set_defaults(action=_releve)
    c = commandes.add_parser("lieu", help="cherche une adresse")
    c.add_argument("adresse")
    c.set_defaults(action=_lieu)
    c = commandes.add_parser("cache", help="dit où est le cache")
    c.set_defaults(action=_cache)
    arguments = analyseur.parse_args(argv)
    return arguments.action(arguments)


if __name__ == "__main__":
    sys.exit(main())
