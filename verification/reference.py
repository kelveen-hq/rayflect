"""Les fichiers de référence de la vérification, pris à leur source au moment où l'on s'en sert.

Le dépôt ne redistribue pas le fichier météo de la norme : il est téléchargé chez son éditeur, rangé dans
`verification/meteo/` (hors du dépôt) et contrôlé par son empreinte. Un fichier dont l'empreinte diffère est
refusé : les plages de la norme ne valent que pour ce fichier précis.
"""

from __future__ import annotations

import hashlib
import urllib.request
from pathlib import Path

DOSSIER = Path(__file__).resolve().parent / "meteo"

# Denver, année type TMY3 : la météo des cas « thermal fabric » de l'ANSI/ASHRAE 140 (Table A1-1),
# dans sa version EPW publiée par le laboratoire NREL avec ses propres résultats.
DENVER = {
    "nom": "725650TYCST.epw",
    "adresse": "https://raw.githubusercontent.com/NatLabRockies/BESTEST-GSR/main/shared_resources/725650TYCST.epw",
    "sha256": "1d0402144460a26265555a18a9cdfe4f0f7d9b4f57d6194847af7959b518571f",
}


class ReferenceIndisponible(RuntimeError):
    """Le fichier de référence n'a pas pu être obtenu, ou n'est pas celui attendu."""


def _empreinte(chemin: Path) -> str:
    return hashlib.sha256(chemin.read_bytes()).hexdigest()


def meteo_de_denver(delai_s: float = 120.0) -> Path:
    """Le fichier météo de la norme, téléchargé une fois puis repris sur place."""
    chemin = DOSSIER / DENVER["nom"]
    if not chemin.exists():
        DOSSIER.mkdir(parents=True, exist_ok=True)
        try:
            with urllib.request.urlopen(DENVER["adresse"], timeout=delai_s) as reponse:
                contenu = reponse.read()
        except OSError as erreur:
            raise ReferenceIndisponible(
                f"météo de Denver introuvable à {DENVER['adresse']} : {erreur}. "
                f"La déposer à la main dans {chemin}") from erreur
        chemin.write_bytes(contenu)
    if _empreinte(chemin) != DENVER["sha256"]:
        raise ReferenceIndisponible(
            f"{chemin} n'est pas le fichier attendu (empreinte différente) : le supprimer pour le reprendre "
            f"à sa source")
    return chemin
