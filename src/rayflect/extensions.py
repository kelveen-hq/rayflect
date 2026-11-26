"""Le point d'extension : ajouter un type d'élément de scénario sans toucher à ce dépôt.

Un scénario est une liste d'éléments, chacun d'un `type` : casquette, BSO, arbre... Un autre paquet peut
déclarer le sien. Il donne 3 choses :

  - un NOM, celui qu'on écrit dans le fichier d'étude (`type = "mon_element"`) ;
  - une CLASSE, de préférence un `dataclass` : ses champs sont les paramètres lisibles dans le fichier ;
  - une fonction POSER(modele, element, contexte), appelée une fois par scénario, après les parois, l'usage et
    les protections du dépôt, juste avant l'écriture du fichier d'EnergyPlus. Elle peut modifier le modèle
    Honeybee, et rendre du texte au format d'EnergyPlus, ajouté tel quel à la fin du fichier (ou None).

Le `contexte` est un dictionnaire. Il porte au moins :
    "epw"       la météo de l'étude (ladybug.epw.EPW)
    "usage"     le nom de l'usage de l'étude
    "dossier"   le dossier du scénario (pathlib.Path), où écrire les fichiers que le calcul lira
    "rendu"     le compte rendu de la conversion ; `rendu.etiquettes` donne, par pièce, son rang de niveau
    "scenario"  le nom du scénario
    "a_dire"    une liste où ajouter ce que le compte rendu doit dire de l'élément posé
    "chemin_epw" le fichier de cette météo (pathlib.Path), pour qui relance un calcul
    "dire"      une fonction : dire(texte) fait passer un message à qui suit le calcul
    "reglages"  les réglages du calcul (honeybee_energy SimulationParameter), à lire ou à changer : demander une
                sortie de plus par `reglages.output.add_output(...)`, changer la répartition du soleil...

2 fonctions de plus, facultatives, pour ce que POSER ne peut pas faire :

  - RETOUCHER(texte, element, contexte) reçoit le fichier d'EnergyPlus entier, une fois assemblé, et rend le
    texte à écrire. C'est le seul endroit où le fichier se retouche : remplacer un objet, en retirer un.
  - LIRE(annee, element, contexte) reçoit les résultats du calcul et rend ce qu'il en tire (de quoi entrer dans
    un JSON), rangé au bilan sous "extensions". `annee.data_collections_by_output_name(nom)` rend les séries
    de l'année seule : le calcul joue aussi un jour de base, dont les 24 heures n'entrent dans aucun total.
    Ici, "dossier" et "scenario" sont ceux du scénario lu.

POUR QU'UN PAQUET SOIT TROUVÉ, il déclare un point d'entrée dans le groupe `rayflect.elements` :

    [project.entry-points."rayflect.elements"]
    mon_element = "mon_paquet.rayflect:declarer"

où `declarer()` appelle `extensions.enregistrer(...)`. La commande `rayflect` charge ces points d'entrée au
démarrage. Sans paquet, `enregistrer` s'appelle aussi à la main, avant `etude.lire`.

Le type `apport_horaire` de ce dépôt (rayflect.apports) est déclaré par ce même moyen : il sert d'exemple.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional

GROUPE = "rayflect.elements"


@dataclass(frozen=True)
class TypeEtendu:
    nom: str
    classe: type
    poser: Callable[[Any, Any, dict], Optional[str]]
    retoucher: Optional[Callable[[str, Any, dict], str]] = None
    lire: Optional[Callable[[Any, Any, dict], Any]] = None


_REGISTRE: Dict[str, TypeEtendu] = {}


def enregistrer(nom: str, classe: type, poser: Callable[[Any, Any, dict], Optional[str]],
                retoucher: Optional[Callable[[str, Any, dict], str]] = None,
                lire: Optional[Callable[[Any, Any, dict], Any]] = None) -> None:
    """Déclare un type d'élément. Le redéclarer à l'identique ne fait rien ; autrement, c'est refusé."""
    if not nom or not nom.replace("_", "").isalnum() or nom != nom.lower():
        raise ValueError(f"nom de type « {nom} » : des minuscules, des chiffres et des tirets bas")
    deja = _REGISTRE.get(nom)
    if deja is not None and (deja.classe is not classe or deja.poser is not poser
                             or deja.retoucher is not retoucher or deja.lire is not lire):
        raise ValueError(f"le type « {nom} » est déjà déclaré par {deja.classe.__module__}")
    _REGISTRE[nom] = TypeEtendu(nom, classe, poser, retoucher, lire)


def retirer(nom: str) -> None:
    _REGISTRE.pop(nom, None)


def types() -> Dict[str, TypeEtendu]:
    return dict(_REGISTRE)


def trouver(element) -> Optional[TypeEtendu]:
    """Le type étendu d'un élément, ou None s'il est d'un type du dépôt."""
    for fiche in _REGISTRE.values():
        if type(element) is fiche.classe:
            return fiche
    return None


def charger() -> List[str]:
    """Charge les types déclarés par les paquets installés. Rend ce qui n'a pas pu l'être, en clair."""
    from importlib.metadata import entry_points

    rates = []
    for point in entry_points(group=GROUPE):
        try:
            point.load()()
        except Exception as erreur:      # un paquet tiers défaillant ne doit pas empêcher l'outil de démarrer
            rates.append(f"extension « {point.name} » ({point.value}) non chargée : {erreur}")
    return rates
