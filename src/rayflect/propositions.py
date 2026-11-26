"""Partir du besoin, pas de la mesure : l'architecte fixe ses objectifs, Rayflect cherche les mesures qui les tiennent.

D'ordinaire, on propose une casquette et Rayflect la chiffre. Ici, c'est l'inverse :

    [objectifs]
    dh_max = 350                        # degrés-heures de la pièce la plus chaude (rayflect.confort)
    autonomie_min = 0.5                 # lumière du jour à 300 lux, pièce la moins éclairée
    chauffage_hausse_max = 0.05         # au plus 5 % de chauffage en plus que le bâtiment tel qu'il est
    carbone_max_kg = 5000               # carbone des matériaux ajoutés (rayflect.carbone)

    [propositions]                      # facultatif
    mesures = ["casquettes_au_sud", "fenetres_jour_et_nuit"]    # une partie de la palette ; toutes par défaut
    combinaisons = 3                    # jusqu'à 3 mesures ensemble (1 à 3)
    retenues = 4                        # les meilleures mesures seules que l'on combine

LA RECHERCHE, en 2 temps, pour rester dans un nombre de calculs raisonnable :
  1. chaque mesure de la palette, seule, face au bâtiment tel qu'il est ;
  2. les combinaisons des `retenues` meilleures : par 2, puis par 3.
Une palette de 9 mesures et 4 retenues font 9 + 6 + 4 = 19 calculs.

LE CLASSEMENT : d'abord le nombre d'objectifs tenus, puis l'écart qui reste aux autres (la somme des écarts relatifs à
leur cible), puis le carbone construit. Chaque proposition dit aussi ce qu'elle coûte sur les autres critères : une
protection solaire qui retire de la lumière, une mesure d'été qui ajoute du chauffage.

LA PALETTE est faite de mesures passives courantes, à des réglages courants [H] : chacune se lit et se change
dans PALETTE. Ce que Rayflect ne sait pas poser (un arbre, qui demande sa place) n'y est pas.
"""

from __future__ import annotations

import dataclasses
import itertools
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple


@dataclass(frozen=True)
class Mesure:
    cle: str
    nom: str
    elements: Tuple[dict, ...] = ()
    parois: Tuple[Tuple[str, Any], ...] = ()


PALETTE: Tuple[Mesure, ...] = (
    Mesure("casquettes_au_sud", "casquettes au sud",
           ({"type": "casquette", "profondeur_m": 0.8, "orientations": ["SE", "S", "SO"]},)),
    Mesure("lames_est_ouest", "lames verticales à l'est et à l'ouest", ({"type": "lames_verticales"},)),
    Mesure("bso_pilotes", "BSO pilotés sur la chaleur", ({"type": "bso", "pilotage": "chaleur"},)),
    Mesure("fenetres_jour_et_nuit", "fenêtres ouvertes jour et nuit, traversant",
           ({"type": "ouvrants", "heures": [0, 24], "traversant": True},)),
    Mesure("surventilation_de_nuit", "surventilation mécanique de nuit",
           ({"type": "ventilation", "surventilation_vol_h": 4.0},)),
    Mesure("toit_clair", "toit clair", ({"type": "toit"},)),
    Mesure("murs_clairs", "murs clairs", parois=(("absorption_des_murs", 0.4),)),        # [S] Th-Bât : teinte claire
    Mesure("vitrage_controle_solaire", "vitrage à contrôle solaire", parois=(("vitrage", "controle_solaire"),)),
    Mesure("isolation_exterieure", "14 cm d'isolant par l'extérieur",
           parois=(("isolation_des_murs", "exterieure"), ("isolant_des_murs_cm", 14.0))),
)
PAR_CLE = {m.cle: m for m in PALETTE}

# Les objectifs : (clé dans [objectifs], indicateur, sens, en clair). « max » : l'indicateur doit rester sous la cible.
OBJECTIFS = (
    ("dh_max", "dh", "max", "degrés-heures, pièce la plus chaude"),
    ("heures_au_dessus_de_26_max", "heures_26", "max", "heures au-dessus de 26 °C, pièce la plus chaude"),
    ("autonomie_min", "autonomie", "min", "lumière à 300 lux, pièce la moins éclairée"),
    ("exces_max", "exces", "max", "trop de lumière à 1 m de la baie, pièce la plus exposée"),
    ("eblouissement_max", "eblouissement", "max", "éblouissement à 1 m de la baie, pièce la plus exposée"),
    ("chauffage_hausse_max", "chauffage_hausse", "max", "hausse du chauffage face au bâtiment tel qu'il est"),
    ("carbone_max_kg", "carbone", "max", "carbone des matériaux ajoutés, kg CO2e"),
)
COMBINAISONS_MAX = 3


class PropositionsInvalides(ValueError):
    """Les objectifs ou la palette ne peuvent pas être suivis : le message dit quoi corriger."""


@dataclass
class Reglages:
    objectifs: Dict[str, float]
    mesures: Tuple[str, ...] = tuple(PAR_CLE)
    combinaisons: int = 2
    retenues: int = 4


def lire(objectifs: Optional[dict], propositions: Optional[dict] = None) -> Reglages:
    """Les tables [objectifs] et [propositions] du fichier d'étude."""
    objectifs, propositions = dict(objectifs or {}), dict(propositions or {})
    connus = {o[0] for o in OBJECTIFS}
    inconnus = sorted(set(objectifs) - connus)
    if inconnus:
        raise PropositionsInvalides(f"[objectifs] : clés inconnues : {', '.join(inconnus)}. "
                                    f"Connues : {', '.join(sorted(connus))}")
    if not objectifs:
        raise PropositionsInvalides(f"[objectifs] : au moins un objectif, parmi {', '.join(sorted(connus))}")
    for cle, valeur in objectifs.items():
        if isinstance(valeur, bool) or not isinstance(valeur, (int, float)) or valeur < 0:
            raise PropositionsInvalides(f"[objectifs] {cle} = {valeur!r} : un nombre positif")
    inconnus = sorted(set(propositions) - {"mesures", "combinaisons", "retenues"})
    if inconnus:
        raise PropositionsInvalides(f"[propositions] : clés inconnues : {', '.join(inconnus)}. Connues : mesures, "
                                    f"combinaisons, retenues")
    mesures = tuple(propositions.get("mesures", PAR_CLE))
    absentes = [m for m in mesures if m not in PAR_CLE]
    if absentes or not mesures:
        raise PropositionsInvalides(f"[propositions] mesures : {', '.join(absentes) or 'aucune'} ; la palette : "
                                    f"{', '.join(PAR_CLE)}")
    combinaisons, retenues = propositions.get("combinaisons", 2), propositions.get("retenues", 4)
    if combinaisons not in range(1, COMBINAISONS_MAX + 1) or isinstance(combinaisons, bool):
        raise PropositionsInvalides(f"[propositions] combinaisons = {combinaisons!r} : de 1 à {COMBINAISONS_MAX}")
    if not isinstance(retenues, int) or isinstance(retenues, bool) or retenues < 2:
        raise PropositionsInvalides(f"[propositions] retenues = {retenues!r} : un entier, 2 au moins")
    return Reglages({k: float(v) for k, v in objectifs.items()}, mesures, combinaisons, retenues)


def nom_de(cles: Sequence[str]) -> str:
    return " + ".join(PAR_CLE[c].nom for c in cles)


def scenario(cles: Sequence[str], element: Callable[[dict], Any], fabrique) -> Any:
    """Le scénario d'une combinaison de mesures : leurs éléments les uns après les autres, leurs parois réunies."""
    elements, parois = [], {}
    for c in cles:
        elements += [element(dict(e)) for e in PAR_CLE[c].elements]
        parois.update(dict(PAR_CLE[c].parois))
    return fabrique(nom_de(cles), elements, parois)


def _pire(par_piece: dict, nom: str, lire_, plus_haut: bool = True) -> Optional[float]:
    valeurs = [lire_(v[nom]) for v in (par_piece or {}).values() if v.get(nom) is not None]
    valeurs = [v for v in valeurs if v is not None]
    if not valeurs:
        return None
    return max(valeurs) if plus_haut else min(valeurs)


def indicateurs(bilan: dict, nom: str, reference: str) -> Dict[str, Optional[float]]:
    """Les indicateurs d'un scénario, lus dans le bilan d'une étude."""
    confort = (bilan.get("confort_d_ete") or {}).get("pieces") or {}
    lumiere = bilan.get("lumiere") or {}
    chauffage, chauffage_ref = bilan["chauffage_kwh"].get(nom), bilan["chauffage_kwh"].get(reference)
    return {
        "dh": _pire(confort, nom, lambda v: v["dh"]),
        "heures_26": _pire(bilan.get("heures_au_dessus_de_26") or {}, nom, lambda v: v),
        "autonomie": _pire(bilan.get("autonomie_300_lux") or {}, nom, lambda v: v, plus_haut=False),
        "exces": _pire(lumiere, nom, lambda v: v.get("bord_plus_de_3000_lux")),
        "eblouissement": _pire(lumiere, nom, lambda v: v.get("eblouissement_bord")),
        "chauffage_hausse": (chauffage / chauffage_ref - 1.0) if chauffage is not None and chauffage_ref else None,
        "carbone": float((bilan.get("carbone") or {}).get(nom, {}).get("kgco2e", 0.0)),
    }


def juger(ind: Dict[str, Optional[float]], objectifs: Dict[str, float]) -> Tuple[int, float, List[str]]:
    """(objectifs tenus, écart relatif cumulé aux autres, ce qui manque en clair)."""
    tenus, ecart, manque = 0, 0.0, []
    for cle, indicateur, sens, en_clair in OBJECTIFS:
        if cle not in objectifs:
            continue
        cible, valeur = objectifs[cle], ind.get(indicateur)
        if valeur is None:
            manque.append(f"{en_clair} : non calculé")
            ecart += 1.0
            continue
        bon = valeur <= cible if sens == "max" else valeur >= cible
        if bon:
            tenus += 1
        else:
            ecart += abs(valeur - cible) / max(abs(cible), 1e-6)
            manque.append(f"{en_clair} : {_dire(indicateur, valeur)} pour {_dire(indicateur, cible)}")
    return tenus, ecart, manque


def _dire(indicateur: str, valeur: Optional[float]) -> str:
    if valeur is None:
        return "?"
    if indicateur in ("autonomie", "exces", "eblouissement"):
        return f"{valeur * 100:.0f} %"
    if indicateur == "chauffage_hausse":
        return f"{valeur * 100:+.0f} %"
    return f"{valeur:.0f}"


def ranger(evaluees: Dict[Tuple[str, ...], dict], objectifs: Dict[str, float]) -> List[dict]:
    """Les propositions, la meilleure d'abord."""
    lignes = []
    for cles, ind in evaluees.items():
        tenus, ecart, manque = juger(ind, objectifs)
        lignes.append({"mesures": list(cles), "nom": nom_de(cles) if cles else "tel quel", "tenus": tenus,
                       "objectifs": len(objectifs), "ecart": round(ecart, 3), "manque": manque, "indicateurs": ind})
    # L'écart arrondi au centième : 2 propositions à 352 et 355 degrés-heures pour 350 se valent, le carbone les départage.
    return sorted(lignes, key=lambda e: (-e["tenus"], round(e["ecart"], 2), e["indicateurs"]["carbone"] or 0.0,
                                         len(e["mesures"])))


def a_combiner(rangees: List[dict], retenues: int, combinaisons: int) -> List[Tuple[str, ...]]:
    """Les combinaisons des meilleures mesures seules, sans 2 mesures du même type d'élément."""
    seules = [tuple(e["mesures"]) for e in rangees if len(e["mesures"]) == 1][:retenues]
    meilleures = [s[0] for s in seules]
    rendu = []
    for taille in range(2, combinaisons + 1):
        for cles in itertools.combinations(meilleures, taille):
            types = [e["type"] for c in cles for e in PAR_CLE[c].elements]
            if len(types) == len(set(types)):
                rendu.append(tuple(cles))
    return rendu


def proposer(etude_, sortie, reglages: Reglages, calculer: Callable, element: Callable[[dict], Any], fabrique,
             dire: Callable[[str], None] = print) -> dict:
    """Cherche les mesures qui tiennent les objectifs. Écrit propositions.json et propositions.txt dans `sortie`."""
    sortie = Path(sortie)
    reference = fabrique("tel quel", [], {})
    seules = [(c,) for c in reglages.mesures]
    dire(f"propositions : {len(seules)} mesures seules d'abord")
    bilan = calculer(dataclasses.replace(etude_, scenarios=[reference] + [scenario(c, element, fabrique) for c in seules]),
                     sortie / "mesures_seules")
    evaluees = {(): indicateurs(bilan, "tel quel", "tel quel")}
    evaluees.update({c: indicateurs(bilan, nom_de(c), "tel quel") for c in seules})
    rangees = ranger(evaluees, reglages.objectifs)
    combos = a_combiner(rangees, reglages.retenues, reglages.combinaisons) if reglages.combinaisons > 1 else []
    if combos:
        dire(f"propositions : {len(combos)} combinaisons des {reglages.retenues} meilleures")
        bilan2 = calculer(dataclasses.replace(etude_, scenarios=[reference] + [scenario(c, element, fabrique) for c in combos]),
                          sortie / "combinaisons")
        evaluees.update({c: indicateurs(bilan2, nom_de(c), "tel quel") for c in combos})
        rangees = ranger(evaluees, reglages.objectifs)
    rendu = {"objectifs": reglages.objectifs, "propositions": rangees,
             "tiennent_tout": [e["nom"] for e in rangees if e["tenus"] == e["objectifs"]]}
    sortie.mkdir(parents=True, exist_ok=True)
    (sortie / "propositions.json").write_text(json.dumps(rendu, indent=2, ensure_ascii=False), encoding="utf-8")
    (sortie / "propositions.txt").write_text(presenter(rendu), encoding="utf-8")
    return rendu


def presenter(rendu: dict) -> str:
    """Le compte rendu des propositions : les objectifs, le classement, ce qui tient tout, ce qui manque."""
    objectifs = rendu["objectifs"]
    lignes = ["Propositions : les mesures qui tiennent les objectifs", "objectifs :"]
    for cle, indicateur, sens, en_clair in OBJECTIFS:
        if cle in objectifs:
            lignes.append(f"  - {en_clair} : {'au plus' if sens == 'max' else 'au moins'} {_dire(indicateur, objectifs[cle])}")
    colonnes = [("dh", "degrés-heures"), ("heures_26", "heures au-dessus de 26 °C"), ("autonomie", "lumière"),
                ("exces", "trop de lumière"), ("eblouissement", "éblouissement"), ("chauffage_hausse", "chauffage"),
                ("carbone", "carbone kg CO2e")]
    lignes.append("")
    for k, e in enumerate(rendu["propositions"], 1):
        ind = e["indicateurs"]
        lignes.append(f"{k}. {e['nom']} : {e['tenus']} objectifs sur {e['objectifs']}")
        lignes.append("     " + " ; ".join(f"{t} {_dire(c, ind.get(c))}" for c, t in colonnes))
    lignes.append("")
    if rendu["tiennent_tout"]:
        lignes.append("tiennent tous les objectifs : " + " ; ".join(rendu["tiennent_tout"]))
    else:
        meilleure = rendu["propositions"][0]
        lignes.append(f"aucune ne tient tous les objectifs ; la plus proche, « {meilleure['nom']} », manque :")
        lignes += [f"  - {m}" for m in meilleure["manque"]]
    lignes.append("  - chaque ligne dit aussi ce que la mesure coûte ailleurs : la lumière qu'une protection retire, le "
                  "chauffage qu'une mesure d'été ajoute, le carbone de ses matériaux")
    lignes.append("  - la palette et ses réglages sont des mesures courantes [H] (rayflect.propositions.PALETTE) : à "
                  "ajuster au projet, puis à rejouer en scénarios détaillés")
    return "\n".join(lignes)
