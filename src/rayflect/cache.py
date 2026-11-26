"""Où ranger ce qui se télécharge : météo, cartes des voisins. Hors du dépôt, repris d'une étude à l'autre.

Par ordre : la variable d'environnement RAYFLECT_CACHE, sinon le dossier de cache de l'utilisateur
(%LOCALAPPDATA% sous Windows, $XDG_CACHE_HOME ou ~/.cache ailleurs). Tout peut être supprimé sans perte :
ce qui manque est redemandé à sa source.
"""

from __future__ import annotations

import os
from pathlib import Path

NOM = "rayflect"


def racine() -> Path:
    choisi = os.environ.get("RAYFLECT_CACHE")
    if choisi:
        return Path(choisi).expanduser().resolve()
    if os.name == "nt" and os.environ.get("LOCALAPPDATA"):
        return Path(os.environ["LOCALAPPDATA"]) / NOM / "cache"
    return Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache") / NOM


def dossier(nom: str) -> Path:
    """Le sous-dossier `nom` du cache, créé s'il manque."""
    chemin = racine() / nom
    chemin.mkdir(parents=True, exist_ok=True)
    # PIÈGE MESURÉ : le Python du Microsoft Store redirige en silence ce qu'il écrit sous %LOCALAPPDATA% vers
    # un dossier à lui. Lui s'y retrouve, EnergyPlus non : « Could not find weather file ». Le chemin réel,
    # lui, est lisible par tous les programmes.
    return Path(os.path.realpath(chemin))
