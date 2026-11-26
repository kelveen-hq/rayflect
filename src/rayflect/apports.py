"""Un apport de chaleur donné heure par heure, lu dans un fichier.

Tout ce que l'outil ne sait pas modéliser lui-même peut lui être donné ainsi : la chaleur d'un procédé, celle
d'une salle de serveurs, ou l'effet d'un dispositif calculé par un autre logiciel. Le fichier dit, pour
chacune des 8 760 heures de l'année, la puissance apportée aux locaux, en watts. Une valeur négative est une
chaleur retirée.

    [[scenario.element]]
    type = "apport_horaire"
    fichier = "procede.csv"         # chemin relatif au fichier d'étude ; une ligne d'en-tête, puis 8 760 lignes
    colonne = "puissance_w"         # le nom de la colonne à lire
    niveau = 0                      # facultatif : le rang du niveau qui le reçoit ; sinon tout le bâtiment
    part_radiative = 0.5            # la part cédée par rayonnement aux parois ; le reste va à l'air

L'apport est réparti entre les pièces concernées au prorata de leur surface de plancher.

AU JOUR DE BASE du chauffage (rayflect.puissance), le fichier est lu à la date de ce jour, le 21 janvier.

CE QUE CELA SUPPOSE. L'apport ne dépend pas de ce qui se passe dans le bâtiment : il est le même que la pièce
soit à 19 ou à 30 °C. Pour un procédé, c'est exact. Pour un dispositif dont l'effet dépend de la température
intérieure, c'est une approximation, juste tant que le calcul qui a produit le fichier et celui-ci décrivent
le même bâtiment.

Ce type passe par le point d'extension du dépôt (rayflect.extensions), comme le ferait celui d'un autre
paquet : il en est l'exemple.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

from rayflect import extensions

HEURES = 8760
NOM = "apport_horaire"


@dataclass(frozen=True)
class ApportHoraire:
    fichier: str
    colonne: str
    niveau: Optional[int] = None
    part_radiative: float = 0.5         # [H] moitié par rayonnement, moitié à l'air

    def __post_init__(self) -> None:
        if not self.fichier or not self.colonne:
            raise ValueError("donner fichier et colonne")
        if isinstance(self.part_radiative, bool) or not 0.0 <= self.part_radiative <= 1.0:
            raise ValueError("part_radiative va de 0 à 1")
        if self.niveau is not None and (isinstance(self.niveau, bool) or not isinstance(self.niveau, int)
                                        or self.niveau < 0):
            raise ValueError("niveau est le rang d'un niveau : 0 pour le plus bas")


def lire_la_colonne(fichier, colonne: str) -> List[float]:
    """Les 8 760 valeurs d'une colonne. Lève ValueError en disant ce qui ne va pas dans le fichier."""
    chemin = Path(fichier)
    try:
        with open(chemin, newline="", encoding="utf-8-sig") as flux:
            entete = flux.readline()
            separateur = ";" if entete.count(";") > entete.count(",") else ","
            flux.seek(0)
            lignes = [ligne for ligne in csv.reader(flux, delimiter=separateur) if ligne]
    except OSError as erreur:
        raise ValueError(f"fichier d'apport illisible : {erreur}") from erreur
    if not lignes:
        raise ValueError(f"{chemin.name} est vide")
    noms = [n.strip() for n in lignes[0]]
    if colonne not in noms:
        raise ValueError(f"{chemin.name} n'a pas de colonne « {colonne} ». Il a : {', '.join(noms)}")
    rang = noms.index(colonne)
    valeurs = []
    for numero, ligne in enumerate(lignes[1:], start=2):
        try:
            valeurs.append(float(ligne[rang].replace(",", ".")))
        except (IndexError, ValueError):
            raise ValueError(f"{chemin.name}, ligne {numero} : « {colonne} » n'est pas un nombre") from None
    if len(valeurs) != HEURES:
        raise ValueError(f"{chemin.name} : {len(valeurs)} heures dans « {colonne} », {HEURES} attendues "
                         f"(une année de 365 jours, heure par heure)")
    return valeurs


def poser(modele, apport: ApportHoraire, contexte: dict) -> str:
    """Le texte d'EnergyPlus qui apporte cette chaleur aux pièces. Écrit le planning dans le dossier du scénario."""
    valeurs = lire_la_colonne(apport.fichier, apport.colonne)
    pieces = list(modele.rooms)
    if apport.niveau is not None:
        etiquettes = getattr(contexte.get("rendu"), "etiquettes", {})
        pieces = [p for p in pieces if etiquettes.get(p.identifier, (None,))[0] == apport.niveau]
        if not pieces:
            rangs = sorted({e[0] for e in etiquettes.values()})
            raise ValueError(f"apport horaire : aucun niveau de rang {apport.niveau}. Rangs du bâtiment : {rangs}")
    surface = sum(p.floor_area for p in pieces)
    if surface <= 0:
        raise ValueError("apport horaire : aucune pièce pour le recevoir")
    numero = contexte["n_apports_horaires"] = contexte.get("n_apports_horaires", 0) + 1
    ou = "tout le bâtiment" if apport.niveau is None else f"le niveau de rang {apport.niveau}"
    contexte.setdefault("a_dire", []).append(
        f"apport horaire « {apport.colonne} » de {Path(apport.fichier).name}, sur {ou} : "
        f"{sum(v for v in valeurs if v > 0) / 1000.0:.0f} kWh apportés et "
        f"{-sum(v for v in valeurs if v < 0) / 1000.0:.0f} kWh retirés dans l'année")
    dossier = Path(contexte["dossier"])
    dossier.mkdir(parents=True, exist_ok=True)
    planning = dossier / f"apport_horaire_{numero}.csv"
    with open(planning, "w", newline="", encoding="utf-8") as flux:
        ecrit = csv.writer(flux)
        ecrit.writerow(["apporte_w", "retire_w"])
        ecrit.writerows([round(max(v, 0.0), 3), round(max(-v, 0.0), 3)] for v in valeurs)
    base = f"apport_horaire_{numero}"
    texte = [f"\nScheduleTypeLimits,\n  {base}_watts, , , Continuous;\n"]
    for colonne, suffixe in ((1, "apporte"), (2, "retire")):
        texte.append(f"\nSchedule:File,\n  {base}_{suffixe}, {base}_watts, {planning.resolve()}, {colonne}, 1, "
                     f"{HEURES}, Comma, No, 60, No;\n")
    for piece in pieces:
        part = piece.floor_area / surface
        for suffixe, signe in (("apporte", 1.0), ("retire", -1.0)):
            texte.append(f"\nOtherEquipment,\n  {base}_{suffixe}_{piece.identifier}, None, {piece.identifier}, "
                         f"{base}_{suffixe}, EquipmentLevel, {signe * part:.6f}, , , 0, {apport.part_radiative}, 0;\n")
    return "".join(texte)


def declarer() -> None:
    extensions.enregistrer(NOM, ApportHoraire, poser)


declarer()
