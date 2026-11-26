"""Ce qui ne doit pas entrer dans le dépôt, contrôlé avant chaque commit.

3 contrôles sur les fichiers prêts à être commités :
  1. les données qu'on ne redistribue pas (maquettes, fichiers météo, sorties de calcul, documents) ;
  2. les fichiers trop gros pour être du code ;
  3. les mots interdits propres à chaque poste, lus dans `.git/info/motifs_interdits.txt` : une expression
     régulière par ligne, sans égard à la casse. Ce fichier n'est jamais versionné ni poussé : la liste de
     ce qu'un contributeur tient à ne pas divulguer ne se divulgue pas non plus.
     Un mot peut être permis dans certains fichiers seulement : `motif @sauf README.md,CONTRIBUER.md`.

Usage :
    python outils/controle_avant_commit.py          les fichiers prêts à être commités
    python outils/controle_avant_commit.py --tout   tous les fichiers suivis par git

Mise en place sur un poste, une fois :  git config core.hooksPath .githooks
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

EXTENSIONS_REFUSEES = (".epw", ".ifc", ".idf", ".sql", ".sqlite", ".dwg", ".dxf", ".rvt", ".skp",
                       ".pdf", ".docx", ".xlsx", ".pptx", ".zip")
TAILLE_MAXIMALE_OCTETS = 300_000


def _git(*arguments: str) -> bytes:
    return subprocess.run(("git",) + arguments, check=True, capture_output=True).stdout


def _fichiers(tout: bool) -> list:
    if tout:
        sortie = _git("ls-files", "-z")
    else:
        sortie = _git("diff", "--cached", "--name-only", "--diff-filter=ACMR", "-z")
    return [nom for nom in sortie.decode("utf-8").split("\0") if nom]


def _motifs() -> list:
    dossier = Path(_git("rev-parse", "--git-common-dir").decode("utf-8").strip())
    fichier = dossier / "info" / "motifs_interdits.txt"
    if not fichier.exists():
        return []
    motifs = []
    for ligne in fichier.read_text(encoding="utf-8").splitlines():
        ligne = ligne.strip()
        if not ligne or ligne.startswith("#"):
            continue
        motif, _, permis = ligne.partition(" @sauf ")
        motifs.append((re.compile(motif.strip(), re.IGNORECASE), {c.strip() for c in permis.split(",") if c.strip()}))
    return motifs


def controler(tout: bool = False) -> list:
    """La liste des refus, vide si tout peut entrer."""
    refus = []
    motifs = _motifs()
    for nom in _fichiers(tout):
        if nom.lower().endswith(EXTENSIONS_REFUSEES):
            refus.append(f"{nom} : ce type de fichier ne se redistribue pas depuis le dépôt")
            continue
        contenu = Path(nom).read_bytes() if tout else _git("show", f":{nom}")
        if len(contenu) > TAILLE_MAXIMALE_OCTETS:
            refus.append(f"{nom} : {len(contenu) // 1000} ko, trop gros pour du code")
            continue
        texte = contenu.decode("utf-8", errors="replace")
        for numero, ligne in enumerate(texte.splitlines(), 1):
            for motif, permis in motifs:
                if nom in permis:
                    continue
                if motif.search(ligne) or motif.search(nom):
                    refus.append(f"{nom}:{numero} : mot interdit sur ce poste ({motif.pattern})")
    return refus


def main(argv) -> int:
    for flux in (sys.stdout, sys.stderr):
        if hasattr(flux, "reconfigure"):
            flux.reconfigure(encoding="utf-8", errors="replace")
    refus = controler("--tout" in argv)
    for ligne in refus:
        print(f"REFUSÉ  {ligne}", file=sys.stderr)
    if refus:
        print(f"{len(refus)} refus : rien n'est commité.", file=sys.stderr)
    return 1 if refus else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
