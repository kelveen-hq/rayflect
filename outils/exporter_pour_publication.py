"""Une copie du dépôt prête à être publiée : les fichiers d'aujourd'hui, sans l'historique.

L'historique de travail peut porter ce qu'on ne redistribue pas (un fichier de données retiré depuis, un
brouillon). La copie publiée repart donc d'un seul commit, fait des seuls fichiers suivis aujourd'hui.

Ce que fait la commande, dans l'ordre :
  1. refuse de partir si le dépôt a des changements non commités ;
  2. passe le contrôle avant commit sur tous les fichiers suivis ;
  3. recopie ces fichiers dans le dossier donné, qui doit être absent ou vide ;
  4. y crée un dépôt neuf avec un seul commit, signé du nom et de l'adresse donnés ;
  5. vérifie que la copie ne contient que ce commit et les mêmes fichiers.

Elle ne pousse rien : l'ajout du dépôt distant et l'envoi restent des gestes faits à la main.

Usage :
    python outils/exporter_pour_publication.py <dossier> --auteur "Nom" --adresse "adresse publique"
        [--message "Premier dépôt public"]

L'adresse entre dans le commit et sera lisible de tous : donner une adresse faite pour cela.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]


def _git(*arguments: str, dans: Path = RACINE, **environnement) -> str:
    import os

    return subprocess.run(("git",) + arguments, cwd=dans, check=True, capture_output=True,
                          env={**os.environ, **environnement}).stdout.decode("utf-8")


def exporter(dossier: Path, auteur: str, adresse: str, message: str) -> list:
    """Crée la copie. Rend la liste des fichiers publiés. Lève RuntimeError avec la raison d'un refus."""
    if _git("status", "--porcelain").strip():
        raise RuntimeError("le dépôt a des changements non commités : les commiter ou les écarter d'abord")
    controle = subprocess.run([sys.executable, str(RACINE / "outils" / "controle_avant_commit.py"), "--tout"],
                              cwd=RACINE, capture_output=True)
    if controle.returncode != 0:
        raise RuntimeError("le contrôle avant commit refuse des fichiers :\n" + controle.stderr.decode("utf-8", "replace"))
    dossier = dossier.resolve()
    if RACINE == dossier or RACINE in dossier.parents:
        raise RuntimeError("le dossier de la copie ne peut pas être dans le dépôt lui-même")
    if dossier.exists() and any(dossier.iterdir()):
        raise RuntimeError(f"{dossier} existe et n'est pas vide")
    dossier.mkdir(parents=True, exist_ok=True)
    fichiers = [nom for nom in _git("ls-files", "-z").split("\0") if nom]
    for nom in fichiers:
        cible = dossier / nom
        cible.parent.mkdir(parents=True, exist_ok=True)
        cible.write_bytes(subprocess.run(("git", "show", f"HEAD:{nom}"), cwd=RACINE, check=True,
                                         capture_output=True).stdout)
    identite = dict(GIT_AUTHOR_NAME=auteur, GIT_AUTHOR_EMAIL=adresse, GIT_COMMITTER_NAME=auteur,
                    GIT_COMMITTER_EMAIL=adresse)
    _git("init", "--quiet", "--initial-branch=main", dans=dossier)
    _git("add", "--all", dans=dossier)
    for nom in fichiers:                        # le bit d'exécution ne survit pas à une recopie sous Windows
        if _git("ls-files", "--stage", "--", nom).startswith("100755"):
            _git("update-index", "--chmod=+x", "--", nom, dans=dossier)
    _git("commit", "--quiet", "--no-verify", "-m", message, dans=dossier, **identite)
    if int(_git("rev-list", "--count", "HEAD", dans=dossier)) != 1:
        raise RuntimeError("la copie porte plus d'un commit")
    publies = sorted(nom for nom in _git("ls-files", "-z", dans=dossier).split("\0") if nom)
    if publies != sorted(fichiers):
        raise RuntimeError("la copie ne porte pas les mêmes fichiers que le dépôt")
    return publies


def main(argv=None) -> int:
    for flux in (sys.stdout, sys.stderr):
        if hasattr(flux, "reconfigure"):
            flux.reconfigure(encoding="utf-8", errors="replace")
    analyseur = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    analyseur.add_argument("dossier")
    analyseur.add_argument("--auteur", required=True)
    analyseur.add_argument("--adresse", required=True)
    analyseur.add_argument("--message", default="Premier dépôt public")
    arguments = analyseur.parse_args(argv)
    try:
        publies = exporter(Path(arguments.dossier), arguments.auteur, arguments.adresse, arguments.message)
    except (RuntimeError, subprocess.CalledProcessError) as erreur:
        print(f"EXPORT REFUSÉ : {erreur}", file=sys.stderr)
        return 1
    print(f"{len(publies)} fichiers dans {Path(arguments.dossier).resolve()}, 1 commit signé {arguments.auteur} "
          f"<{arguments.adresse}>")
    print("Rien n'est poussé. Pour publier : y ajouter le dépôt distant, puis pousser la branche main.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
