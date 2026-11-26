"""Des BSO manœuvrés par de vrais occupants, pour EnergyPlus.

Le modèle d'occupants (`services.analysis.bso_model.PiloteBSOManuel`) rend, heure par heure, la PART des BSO
baissés d'une façade pour une population de comportements tirée de la littérature : ceux qui baissent dès
le soleil, ceux qui manœuvrent de temps en temps, ceux qui ne touchent jamais à rien.

EnergyPlus veut autre chose : pour chaque fenêtre, baissé ou levé, heure par heure. La passerelle :
  1. les fenêtres d'une façade sont réparties entre les comportements, au prorata de leurs parts ;
  2. pour chaque comportement, le modèle donne la part baissée f(h) de son groupe ;
  3. dans un groupe de n fenêtres, la fenêtre de rang j est baissée quand f(h) dépasse (j + 0,5) / n :
     à chaque heure, la part de fenêtres baissées du groupe suit f(h), sans tirage au hasard.

Le calcul est donc reproductible : mêmes entrées, mêmes plannings.
"""

from __future__ import annotations

from typing import Dict, List, Optional, Sequence, Tuple

from honeybee_energy.construction.windowshade import WindowConstructionShade
from honeybee_energy.material.shade import EnergyWindowMaterialBlind
from honeybee_energy.schedule.fixedinterval import ScheduleFixedInterval
import honeybee_energy.lib.scheduletypelimits as limites
from ladybug.sunpath import Sunpath

from .config.system_constants import SYSTEM_DEFAULTS
from .hypotheses import Usage
from .services.analysis.bso_model import (
    COMPORTEMENTS_FIXES, PiloteBSOManuel, irradiance_directe_facade, population_bso_manuel)

CONSIGNE_FROID_C = 26.0     # la pièce est « chaude » à cette consigne moins `bso_manuel_ecart_chaud_k`


def _secteur(azimut_deg: float) -> str:
    return ("N", "NE", "E", "SE", "S", "SO", "O", "NO")[int(((azimut_deg + 22.5) % 360.0) // 45.0)]


def repartir(n_baies: int, population: Sequence[Tuple[str, float]]) -> List[Tuple[str, int]]:
    """Le nombre de baies de chaque comportement : au prorata, les restes aux plus grosses parts décimales."""
    exact = [(nom, part * n_baies) for nom, part in population]
    compte = {nom: int(valeur) for nom, valeur in exact}
    manque = n_baies - sum(compte.values())
    for nom, valeur in sorted(exact, key=lambda e: e[1] - int(e[1]), reverse=True)[:manque]:
        compte[nom] += 1
    return [(nom, compte[nom]) for nom, _ in population if compte[nom] > 0]


def soleil_direct_sur_facade(epw, azimut_deg: float) -> List[float]:
    """L'éclairement direct sur une façade verticale, pour les 8 760 heures du fichier météo (W/m²)."""
    course = Sunpath.from_location(epw.location)
    direct = epw.direct_normal_radiation.values
    eclairement = []
    for heure in range(8760):
        soleil = course.calculate_sun_from_hoy(heure + 0.5)
        eclairement.append(irradiance_directe_facade(direct[heure], soleil.altitude, soleil.azimuth, azimut_deg))
    return eclairement


def parts_baissees(usage: Usage, residentiel: bool, comportement: str, soleil: Sequence[float],
                   temperature_c: Optional[Sequence[float]] = None, premier_jour_lundi_0: int = 6) -> List[float]:
    """La part baissée, heure par heure, d'un groupe de fenêtres qui a toutes le même comportement."""
    if comportement in COMPORTEMENTS_FIXES:
        return [1.0 if comportement == "toujours_baisse" else 0.0] * 8760
    pilote = PiloteBSOManuel(residentiel, range(usage.heures[0], usage.heures[1]),
                             population=((comportement, 1.0),))
    seuil_chaud = CONSIGNE_FROID_C - SYSTEM_DEFAULTS.bso_manuel_ecart_chaud_k
    parts = []
    for heure in range(8760):
        jour = heure // 24
        ouvre = (jour + premier_jour_lundi_0) % 7 < 5
        if usage.ferme_l_ete and 187 <= jour <= 242:
            ouvre = False if not residentiel else ouvre
        chaud = bool(temperature_c is not None and heure > 0 and temperature_c[heure - 1] >= seuil_chaud)
        parts.append(pilote.pas(heure % 24, ouvre, soleil[heure], chaud)[0])
    return parts


def plannings(usage: Usage, residentiel: bool, n_baies: int, soleil: Sequence[float],
              temperature_c: Optional[Sequence[float]] = None) -> List[Tuple[str, Tuple[int, ...]]]:
    """Un planning annuel (0 levé, 1 baissé) par baie de la façade, avec le comportement qui le produit."""
    resultat = []
    for comportement, n in repartir(n_baies, population_bso_manuel(residentiel)):
        parts = parts_baissees(usage, residentiel, comportement, soleil, temperature_c)
        for rang in range(n):
            seuil = (rang + 0.5) / n
            resultat.append((comportement, tuple(1 if p > seuil else 0 for p in parts)))
    return resultat


def poser(modele, epw, usage: Usage, residentiel: bool,
          temperatures_c: Optional[Dict[str, Sequence[float]]] = None,
          orientations: Optional[Sequence[str]] = None) -> Dict[str, dict]:
    """Équipe chaque baie du modèle d'un BSO manœuvré à la main. Rend, par orientation, le bilan de la pose.

    `temperatures_c` : par identifiant de pièce, la température heure par heure d'un calcul précédent. Elle
    ne sert qu'aux comportements déclenchés par la chaleur (le logement).
    """
    lames = EnergyWindowMaterialBlind("lames_bso_manuel", slat_angle=45, solar_reflectance=0.5,
                                      visible_reflectance=0.5)
    deja: Dict[tuple, WindowConstructionShade] = {}
    soleils: Dict[int, List[float]] = {}
    bilan: Dict[str, dict] = {}
    for piece in modele.rooms:
        par_facade: Dict[int, list] = {}
        for face in piece.faces:
            if face.apertures and (orientations is None or _secteur(face.azimuth) in orientations):
                par_facade.setdefault(int(round(face.azimuth)) % 360, []).extend(face.apertures)
        temperature = (temperatures_c or {}).get(piece.identifier.upper())
        for azimut, baies in par_facade.items():
            if azimut not in soleils:
                soleils[azimut] = soleil_direct_sur_facade(epw, float(azimut))
            series = plannings(usage, residentiel, len(baies), soleils[azimut], temperature)
            # On alterne les comportements le long de la façade plutôt que de les ranger par blocs.
            ordre = sorted(range(len(series)), key=lambda i: (i * 0.6180339887) % 1.0)
            for baie, rang in zip(baies, ordre):
                comportement, valeurs = series[rang]
                vitrage = baie.properties.energy.construction
                cle = (vitrage.identifier, valeurs)
                if cle not in deja:
                    numero = len(deja)
                    planning = ScheduleFixedInterval(f"bso_manuel_{numero}", list(valeurs), limites.fractional)
                    # Chaque BSO écrit aussi son vitrage nu dans le fichier EnergyPlus : il lui faut un nom à lui.
                    nu = vitrage.duplicate()
                    nu.identifier = f"{vitrage.identifier}_nu_{numero}"
                    deja[cle] = WindowConstructionShade(
                        f"{vitrage.identifier}_bso_manuel_{numero}", nu, lames, "Exterior", "AlwaysOn",
                        None, planning)
                baie.properties.energy.construction = deja[cle]
                ligne = bilan.setdefault(str(azimut), {"baies": 0, "heures_baissees": 0, "comportements": {}})
                ligne["baies"] += 1
                ligne["heures_baissees"] += sum(valeurs)
                ligne["comportements"][comportement] = ligne["comportements"].get(comportement, 0) + 1
    for ligne in bilan.values():
        ligne["part_du_temps_baisse"] = round(ligne.pop("heures_baissees") / (8760.0 * ligne["baies"]), 3)
    return bilan
