"""Les versions dont l'outil dépend sont déclarées, et le poste d'essai est décrit par un fichier de verrouillage."""

import re
import tomllib
from importlib import metadata
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
PROJET = tomllib.loads((RACINE / "pyproject.toml").read_text(encoding="utf-8"))["project"]
DECLAREES = PROJET["dependencies"] + [d for groupe in PROJET["optional-dependencies"].values() for d in groupe]
VERROU = dict(ligne.strip().split("==") for ligne in (RACINE / "verrouillage.txt").read_text(encoding="utf-8").splitlines()
              if "==" in ligne and not ligne.startswith("#"))


def _nombres(version):
    return tuple(int(n) for n in re.findall(r"\d+", version)[:3])


def test_chaque_dependance_declare_un_plancher():
    # Sans plancher, « pip install » peut poser une version que personne n'a essayée.
    assert DECLAREES and all(re.fullmatch(r"[a-z0-9-]+>=[0-9.]+", d) for d in DECLAREES), DECLAREES


def test_le_verrouillage_respecte_les_planchers_declares():
    for declaree in DECLAREES:
        nom, plancher = declaree.split(">=")
        assert nom in VERROU, f"{nom} manque à verrouillage.txt"
        assert _nombres(VERROU[nom]) >= _nombres(plancher), f"{nom} {VERROU[nom]} est sous le plancher {plancher}"


def test_le_poste_respecte_les_planchers_declares():
    # Ce qui est installé ici est au moins ce qui est déclaré : sinon les essais ne prouvent rien du plancher.
    for declaree in DECLAREES:
        nom, plancher = declaree.split(">=")
        try:
            installee = metadata.version(nom)
        except metadata.PackageNotFoundError:
            continue                                # un groupe facultatif non installé
        assert _nombres(installee) >= _nombres(plancher), f"{nom} {installee} est sous le plancher {plancher}"
