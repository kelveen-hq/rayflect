"""Le moteur de calcul, EnergyPlus : sa version, ses réglages, et ce qu'il a écrit dans son journal.

Un calcul qui rend des chiffres n'est pas pour autant un calcul juste. EnergyPlus écrit dans `eplusout.err`
ce qu'il a remarqué, en 3 degrés : « Warning », « Severe », « Fatal ». Une erreur « Severe » laisse le calcul
aller au bout, avec un résultat qui peut être faux : elle arrête donc l'étude ici, et se lit en clair.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from dataclasses import dataclass, field
from importlib import metadata
from pathlib import Path
from typing import Callable, Dict, List, Optional, Sequence, Tuple

# [S] La version d'EnergyPlus avec laquelle le banc de vérification (verification/bestest.py) a été joué.
VERSION_VERIFIEE: Tuple[int, int] = (25, 2)

# [S] Les ombres se recalculent chaque jour. Le défaut d'EnergyPlus et de Honeybee est de 20 et 30 jours
# (objet ShadowCalculation, « Shading Calculation Update Frequency ») : la position du soleil d'un jour sert
# alors pour tout le mois. Mesuré sur les cas de la norme ANSI/ASHRAE 140 : à 30 jours, le froid et la pointe
# de froid du cas 950 s'écartent de 2,7 % et 2,5 % de l'EnergyPlus de référence ; à 1 jour, de moins de 0,1 %.
OMBRES_TOUS_LES_N_JOURS = 1
OMBRES_AU_PLUS_TOUS_LES_N_JOURS = 30       # [S] le défaut de Honeybee ; au-delà, le soleil d'un jour vaut pour une saison
CALCUL_LONG_S = 600.0                      # [H] au-delà de 10 minutes par scénario, l'outil dit comment raccourcir
# [H] EnergyPlus calcule un scénario sur un seul processeur, et les scénarios ne dépendent pas l'un de l'autre :
# plusieurs se lancent donc en même temps. La moitié des processeurs du poste, pour le laisser utilisable.
PART_DES_PROCESSEURS = 0.5
# [S] Lancés à 4 en même temps, les calculs vont chacun 1,7 à 1,9 fois moins vite que seuls (mesuré le
# 17/11/2026 sur un immeuble de bureaux de 6 niveaux, poste à 8 processeurs). Ne sert qu'à annoncer le temps
# restant d'un lot qui n'a pas commencé.
RALENTI_ENSEMBLE = 1.8

PAQUETS = ("rayflect", "honeybee-energy", "honeybee-core", "honeybee-schema", "ladybug-core",
           "ladybug-geometry", "numpy", "pandas")

_DEGRE = re.compile(r"^\s*\*\*\s*(Warning|Severe|Fatal)\s*\*\*\s?(.*)$")
_SUITE = re.compile(r"^\s*\*\*\s*~~~\s*\*\*\s?(.*)$")
# Ce qu'EnergyPlus écrit en calculant l'année : « Continuing Simulation at 03/02/2017 for ... », et à chaque
# recalcul des ombres « Updating Shadowing Calculations, Start Date=03/02/2017 ». Le jour de base, lui, n'a pas
# d'année dans sa date : il ne compte pas.
_OU_EN_EST_L_ANNEE = re.compile(r"(?:Simulation at |Start Date=)(\d\d)/(\d\d)/\d{4}")
_JOURS_AVANT_LE_MOIS = (0, 31, 59, 90, 120, 151, 181, 212, 243, 273, 304, 334)


class CalculFautif(ValueError):
    """EnergyPlus est absent, ou son journal porte une erreur grave. Le message dit laquelle."""


@dataclass(frozen=True)
class Journal:
    """Ce qu'EnergyPlus a écrit de son calcul."""
    graves: List[str] = field(default_factory=list)         # « Severe » : le résultat peut être faux
    fatales: List[str] = field(default_factory=list)        # « Fatal » : le calcul s'est arrêté
    avertissements: int = 0
    termine: bool = False                                   # « EnergyPlus Completed Successfully »

    @property
    def fautif(self) -> bool:
        return bool(self.graves or self.fatales) or not self.termine

    def dire(self, combien: int = 5) -> str:
        """Les erreurs, en clair, les fatales d'abord."""
        lignes = [f"fatale : {m}" for m in self.fatales] + [f"grave : {m}" for m in self.graves]
        if not lignes:
            return "le calcul ne s'est pas terminé" if not self.termine else "aucune erreur"
        reste = len(lignes) - combien
        return " | ".join(lignes[:combien]) + (f" | et {reste} autres" if reste > 0 else "")


def lire_le_journal(chemin) -> Journal:
    """Lit `eplusout.err`. Un journal absent ou illisible est un calcul qui ne s'est pas terminé."""
    chemin = Path(chemin) if chemin else None
    if chemin is None or not chemin.is_file():
        return Journal()
    messages: List[Tuple[str, List[str]]] = []
    termine = False
    for ligne in chemin.read_text(encoding="utf-8", errors="replace").splitlines():
        if "EnergyPlus Completed Successfully" in ligne:
            termine = True
        trouve = _DEGRE.match(ligne)
        if trouve:
            messages.append((trouve.group(1), [trouve.group(2).strip()]))
            continue
        suite = _SUITE.match(ligne)
        if suite and messages:
            messages[-1][1].append(suite.group(1).strip())
    en_clair = {degre: [" ".join(m for m in morceaux if m) for d, morceaux in messages if d == degre]
                for degre in ("Warning", "Severe", "Fatal")}
    return Journal(en_clair["Severe"], en_clair["Fatal"], len(en_clair["Warning"]), termine)


def version_energyplus() -> Optional[Tuple[int, ...]]:
    """La version de l'EnergyPlus installé sur le poste, ou None s'il est introuvable."""
    from honeybee_energy.config import folders

    if not folders.energyplus_exe:
        return None
    return tuple(folders.energyplus_version) if folders.energyplus_version else None


def remarque_sur_la_version(version: Optional[Tuple[int, ...]]) -> Optional[str]:
    """Ce qu'il faut savoir quand la version n'est pas celle du banc de vérification. None : rien à dire."""
    if version is not None and tuple(version[:2]) == VERSION_VERIFIEE:
        return None
    lue = ".".join(map(str, version)) if version else "inconnue"
    attendue = ".".join(map(str, VERSION_VERIFIEE))
    return (f"EnergyPlus {lue} est installé ; l'outil est vérifié avec la version {attendue}. Les résultats "
            f"n'ont pas été contrôlés avec cette version")


def exiger_energyplus() -> Tuple[int, ...]:
    """La version installée. Lève `CalculFautif` quand EnergyPlus est introuvable."""
    from honeybee_energy.config import folders

    if not folders.energyplus_exe:
        raise CalculFautif("EnergyPlus est introuvable sur ce poste. L'installer (version "
                           f"{'.'.join(map(str, VERSION_VERIFIEE))}), voir docs/INSTALLATION.md")
    return tuple(folders.energyplus_version or ())


def versions() -> Dict[str, str]:
    """Ce qui a produit le résultat : EnergyPlus, Python et les paquets dont le calcul dépend."""
    version = version_energyplus()
    connues = {"energyplus": ".".join(map(str, version)) if version else "inconnue",
               "python": ".".join(map(str, sys.version_info[:3]))}
    for paquet in PAQUETS:
        try:
            connues[paquet] = metadata.version(paquet)
        except metadata.PackageNotFoundError:
            pass
    return connues


def reglages_en_clair(reglages) -> Dict[str, object]:
    """Les réglages du calcul qui pèsent sur le résultat, tels qu'ils partent vers EnergyPlus."""
    ombres = reglages.shadow_calculation
    return {"pas_de_temps_par_heure": reglages.timestep,
            "ombres_recalculees_tous_les_n_jours": ombres.calculation_frequency,
            "methode_des_ombres": ombres.calculation_method,
            "repartition_du_soleil": ombres.solar_distribution,
            "terrain": reglages.terrain_type}


def dire_les_reglages(clairs: Dict[str, object], connues: Dict[str, str]) -> str:
    """Les mêmes réglages, en une phrase pour le compte rendu."""
    n = clairs["ombres_recalculees_tous_les_n_jours"]
    chaque = "chaque jour" if n == 1 else f"tous les {n} jours"
    return (f"calcul : EnergyPlus {connues.get('energyplus', 'inconnue')}, {clairs['pas_de_temps_par_heure']} pas "
            f"par heure, ombres recalculées {chaque} (méthode {clairs['methode_des_ombres']}, soleil "
            f"{clairs['repartition_du_soleil']}) [S]")


def calculs_en_meme_temps() -> int:
    """Combien de calculs lancer en même temps sur ce poste, quand l'étude ne le dit pas."""
    return max(1, int((os.cpu_count() or 1) * PART_DES_PROCESSEURS))


def ensemble(faire: Callable, lot: Sequence, a_la_fois: int) -> List:
    """`faire(x)` pour chaque x du lot, `a_la_fois` en même temps. Rend les résultats dans l'ordre du lot.

    EnergyPlus est un programme à part : des fils d'exécution suffisent à en lancer plusieurs. La première
    erreur, dans l'ordre du lot, est relevée telle quelle, une fois tous les calculs rendus.
    """
    lot = list(lot)
    if a_la_fois <= 1 or len(lot) <= 1:
        return [faire(x) for x in lot]
    from concurrent.futures import ThreadPoolExecutor

    with ThreadPoolExecutor(max_workers=min(a_la_fois, len(lot))) as fils:
        attendus = [fils.submit(faire, x) for x in lot]
    return [attendu.result() for attendu in attendus]


class Suivi:
    """Lit ce qu'EnergyPlus écrit pendant qu'il calcule, et en tire la part de l'année déjà calculée."""

    def __init__(self) -> None:
        self.part = 0.0

    def lire(self, ligne: str) -> Optional[float]:
        """La part de l'année calculée, de 0 à 1, si cette ligne l'a fait avancer ; sinon None."""
        if "EnergyPlus Completed Successfully" in ligne:
            part = 1.0
        else:
            trouve = _OU_EN_EST_L_ANNEE.search(ligne)
            if not trouve:
                return None
            mois, jour = int(trouve.group(1)), int(trouve.group(2))
            if not 1 <= mois <= 12:
                return None
            part = min(0.99, (_JOURS_AVANT_LE_MOIS[mois - 1] + jour - 1) / 365.0)   # 1 : le calcul a tout rendu
        if part <= self.part:
            return None
        self.part = part
        return part


def lancer(idf, epw, suivre: Optional[Callable[[float], None]] = None):
    """Lance EnergyPlus sur le fichier. Rend (résultats SQL, journal). Lève `CalculFautif` si le calcul est fautif.

    Fautif : rien n'est rendu, le calcul ne s'est pas terminé, ou son journal porte une erreur grave.
    `suivre(part)` est appelée à mesure que l'année se calcule, avec la part faite, de 0 à 1.
    Ce qu'EnergyPlus écrit à l'écran est lu ici et n'est pas affiché : son journal reste dans le dossier.
    """
    from honeybee_energy.config import folders
    from honeybee_energy.run import output_energyplus_files, prepare_idf_for_simulation

    try:
        dossier = prepare_idf_for_simulation(str(idf), str(epw))
    except (OSError, AssertionError) as erreur:
        raise CalculFautif(f"le calcul n'a pas pu être lancé : {erreur}") from erreur
    # La même commande que Honeybee (honeybee_energy.run) : « -x » développe les objets HVACTemplate.
    commande = [folders.energyplus_exe, "-i", folders.energyplus_idd_path, "-w", os.path.abspath(str(epw)), "-x"]
    suivi = Suivi()
    with subprocess.Popen(commande, cwd=dossier, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                          encoding="utf-8", errors="replace") as calcul:
        for ligne in calcul.stdout:
            part = suivi.lire(ligne)
            if part is not None and suivre is not None:
                suivre(part)
    sql, *_reste, err = output_energyplus_files(dossier)
    journal = lire_le_journal(err)
    if sql is None or journal.fautif:
        raise CalculFautif(f"EnergyPlus a rendu un calcul fautif ({journal.dire()}). Journal : {err}")
    return sql, journal
