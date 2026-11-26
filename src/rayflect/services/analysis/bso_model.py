"""Modèle BSO (Brise-Soleil Orientable) horaire pour simulation 5R1C.

Ce module calcule l'état horaire du BSO (position des lames, g_value effectif)
pour le moteur thermique 5R1C (8760 pas de temps).

Architecture :
    services/ (calculs purs, pas d'I/O)

Conventions :
    - Les angles de lames sont en degrés : 0° = ouvertes (horizontales),
      90° = fermées (verticales)
    - Le BSO se déploie automatiquement quand l'irradiance façade dépasse un
      seuil (EN 15232 GTB classe B) ET qu'il y a du froid à éviter : d'avril à
      octobre (pilotage « saisonnier ») ou quand la pièce demande du froid,
      avec hystérésis (pilotage « thermique »,
      `SYSTEM_DEFAULTS.bso_reference_pilotage`)
    - Sinon les lames restent ouvertes pour laisser entrer les gains solaires
    - Le BSO de référence est MANUEL par défaut : une population d'occupants
      le manœuvre (`PiloteBSOManuel`, en fin de module) ; les 2 pilotages
      automatiques ci-dessus restent des options de réglage

Sources :
    - EN 14501 : Classification protections solaires, facteur solaire g_tot
    - EN 13659 : Fermetures et stores extérieurs
    - EN 15232 : Systèmes GTB (pilotage automatique)
    - CSTB : Essais en conditions réelles BSO aluminium

Convention g_tot BSO (EN 14501) :
    - Lames fermées (90°) : g_tot = 0.02-0.05 selon vitrage
    - Lames à 45° : g_tot = 0.08-0.12
    - Lames ouvertes (0°) : g_tot ≈ g_vitrage × 0.97 (perte cadre ~3%)
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Dict, Optional

from ...config.system_constants import SYSTEM_DEFAULTS


# ─── Constantes BSO (aliasées depuis SYSTEM_DEFAULTS) ──────────────────────

BSO_G_TOT_CLOSED = SYSTEM_DEFAULTS.bso_g_tot_closed
"""g_tot BSO lames fermées à 90° (EN 14501, double Low-E)."""

BSO_G_TOT_TILTED_45 = SYSTEM_DEFAULTS.bso_g_tot_tilted_45
"""g_tot BSO lames inclinées à 45° (EN 14501)."""

BSO_FRAME_FACTOR = SYSTEM_DEFAULTS.bso_frame_factor
"""Facteur cadre : transmission résiduelle lames ouvertes (0.97 = 3% obstruction)."""

BSO_IRR_DEPLOY_THRESHOLD = SYSTEM_DEFAULTS.bso_irr_deploy_threshold_w_m2
"""Seuil d'irradiance façade pour déploiement automatique (W/m²)."""

BSO_SUMMER_MONTHS = (4, 5, 6, 7, 8, 9, 10)
"""Mois de la saison de protection solaire (avril → octobre).

Pilotage « saisonnier » seulement. Le pilotage « thermique »
(`bso_reference_pilotage`) ne lit pas le calendrier : il lit le besoin de
froid de la pièce (`bso_besoin_de_froid`).
"""

BSO_PILOTAGES = ("saisonnier", "thermique", "manuel")
"""Les pilotages du BSO de référence (`SYSTEM_DEFAULTS.bso_reference_pilotage`).

« manuel » : manœuvré par des occupants, voir `PiloteBSOManuel`.
"""

BSO_EXISTANT_PILOTAGES = ("saisonnier", "manuel")
"""Les pilotages du BSO DÉJÀ POSÉ d'une façade dessinée (`SYSTEM_DEFAULTS.bso_existant_pilotage`)."""


def bso_besoin_de_froid(
    t_interieure_c: float,
    seuil_protection_c: float,
    hysteresis_c: float,
    deja_en_protection: bool,
) -> bool:
    """La pièce demande-t-elle qu'on coupe le soleil ? Elle demande du froid, avec hystérésis.

    Le pilotage « saisonnier » baisse le BSO d'avril à octobre dès que la
    façade est éclairée, quel que soit l'état de la pièce : au printemps et à
    l'automne il coupe un soleil qui chauffe utilement, et un bâtiment sans
    climatisation n'a aucun froid à éviter. Le pilotage « thermique » ne
    protège que quand la pièce en a besoin.

    La règle : la pièce demande du froid quand sa température, à la fin de
    l'heure précédente, dépasse le seuil de l'heure (dérivé des consignes).
    Une fois en protection, elle n'en sort que sous le seuil moins
    l'hystérésis.

    Args:
        t_interieure_c: Température intérieure du scénario BSO (°C), fin de l'heure précédente.
        seuil_protection_c: Seuil de température de l'heure (°C) au-dessus duquel la pièce demande du froid.
        hysteresis_c: Hystérésis du pilotage (°C).
        deja_en_protection: Vrai si la pièce demandait déjà du froid l'heure précédente.

    Returns:
        Vrai si le BSO doit protéger (sous réserve du seuil d'irradiance).
    """
    seuil = seuil_protection_c - hysteresis_c if deja_en_protection else seuil_protection_c
    return bool(t_interieure_c > seuil)


@dataclass(frozen=True)
class BSOState:
    """État horaire du BSO pour une façade donnée.

    Attributes:
        deployed: True si les lames sont en position de protection.
        slat_angle_deg: Angle des lames (0°=ouvertes, 90°=fermées).
        g_value_effective: g_value résultant (vitrage × facteur lames).
        shading_factor: Fraction du flux solaire bloqué (0-1).
            Utilisable directement dans compute_solar_gains(shading_override).
    """
    deployed: bool
    slat_angle_deg: float
    g_value_effective: float
    shading_factor: float


def compute_bso_hourly_state(
    sun_elevation_deg: float,
    irr_facade_w_m2: float,
    month: int,
    g_value_glazing: float,
    *,
    irr_deploy_threshold: float = BSO_IRR_DEPLOY_THRESHOLD,
    summer_months: tuple = BSO_SUMMER_MONTHS,
    besoin_de_froid: Optional[bool] = None,
) -> BSOState:
    """Calcule l'état BSO pour une heure donnée sur une façade.

    Logique de pilotage (EN 15232 GTB classe B) :
    1. Si nuit (soleil < 0°) → lames ouvertes (pas de protection nécessaire)
    2. Si hors saison été → lames ouvertes (maximiser gains solaires hiver)
    3. Si irradiance façade < seuil → lames ouvertes
    4. Si irradiance façade ≥ seuil en été → lames fermées (protection)

    L'angle de fermeture dépend de l'élévation solaire :
    - Soleil haut (> 45°) : lames horizontales suffisent → angle modéré
    - Soleil bas (< 20°) : fermeture quasi-complète nécessaire

    Args:
        sun_elevation_deg: Élévation solaire (°). Négatif = nuit.
        irr_facade_w_m2: Irradiance totale sur la façade (W/m²).
        month: Mois (1-12).
        g_value_glazing: g_value du vitrage nu (sans protection).
        irr_deploy_threshold: Seuil d'irradiance pour déploiement (W/m²).
        summer_months: Tuple des mois de protection solaire.
        besoin_de_froid: None = pilotage saisonnier (le calendrier décide, cas 2) ;
            un booléen = pilotage thermique (`bso_besoin_de_froid`) : il REMPLACE
            le calendrier, le seuil d'irradiance reste.

    Returns:
        BSOState avec deployed, slat_angle_deg, g_value_effective, shading_factor.

    Source:
        EN 14501, EN 15232, CSTB essais BSO 2020.
    """
    # Cas 1 : Nuit ou soleil sous horizon → lames ouvertes
    if sun_elevation_deg <= 0:
        return BSOState(
            deployed=False,
            slat_angle_deg=0.0,
            g_value_effective=g_value_glazing * BSO_FRAME_FACTOR,
            shading_factor=0.0,
        )

    # Cas 2 : Pas de froid à éviter → lames ouvertes. Saisonnier : hors saison
    # de protection. Thermique : la pièce ne demande pas de froid (elle profite
    # du soleil).
    hors_besoin = (month not in summer_months) if besoin_de_froid is None else (not besoin_de_froid)
    if hors_besoin:
        return BSOState(
            deployed=False,
            slat_angle_deg=0.0,
            g_value_effective=g_value_glazing * BSO_FRAME_FACTOR,
            shading_factor=0.0,
        )

    # Cas 3 : Irradiance insuffisante → lames ouvertes
    if irr_facade_w_m2 < irr_deploy_threshold:
        return BSOState(
            deployed=False,
            slat_angle_deg=0.0,
            g_value_effective=g_value_glazing * BSO_FRAME_FACTOR,
            shading_factor=0.0,
        )

    # Cas 4 : Protection active, calcul de l'angle des lames
    #
    # Quand le soleil est haut (élévation > 50°), les lames horizontales
    # bloquent efficacement sans fermeture complète → angle modéré (45-60°).
    # Quand le soleil est bas (< 20°), les rayons passent entre les lames
    # → fermeture quasi-complète nécessaire (80-90°).
    #
    # Interpolation linéaire : high_sun → 45°, low_sun → 85°
    if sun_elevation_deg >= 50.0:
        slat_angle = 45.0
    elif sun_elevation_deg <= 15.0:
        slat_angle = 85.0
    else:
        # Interpolation linéaire entre 15° et 50° d'élévation
        t = (sun_elevation_deg - 15.0) / (50.0 - 15.0)
        slat_angle = 85.0 - t * (85.0 - 45.0)

    # g_value effectif selon l'angle des lames
    # Interpolation entre g_tot_closed (90°) et g_tot_tilted_45 (45°)
    g_eff = _interpolate_g_value(slat_angle, g_value_glazing)

    # Facteur d'ombrage = 1 - (g_eff / g_glazing)
    # C'est la fraction du flux solaire bloqué par le BSO
    if g_value_glazing > 0:
        shading_factor = max(0.0, min(1.0, 1.0 - g_eff / g_value_glazing))
    else:
        shading_factor = 0.0

    return BSOState(
        deployed=True,
        slat_angle_deg=round(slat_angle, 1),
        g_value_effective=round(g_eff, 4),
        shading_factor=round(shading_factor, 4),
    )


def _interpolate_g_value(
    slat_angle_deg: float,
    g_value_glazing: float,
) -> float:
    """Interpole le g_value effectif BSO selon l'angle des lames.

    Points de référence (EN 14501) :
    - 0° (ouvert)  : g_eff = g_vitrage × 0.97 (cadre seul)
    - 45° (incliné) : g_eff = BSO_G_TOT_TILTED_45 (~ 0.10)
    - 90° (fermé)   : g_eff = BSO_G_TOT_CLOSED (~ 0.04)

    Interpolation linéaire par morceaux entre ces 3 points.

    Args:
        slat_angle_deg: Angle des lames (0-90°).
        g_value_glazing: g_value du vitrage nu.

    Returns:
        g_value effectif (vitrage + BSO).
    """
    g_open = g_value_glazing * BSO_FRAME_FACTOR
    g_tilted = BSO_G_TOT_TILTED_45
    g_closed = BSO_G_TOT_CLOSED

    angle = max(0.0, min(90.0, slat_angle_deg))

    if angle <= 45.0:
        # Interpolation 0° → 45°
        t = angle / 45.0
        return g_open * (1.0 - t) + g_tilted * t
    else:
        # Interpolation 45° → 90°
        t = (angle - 45.0) / 45.0
        return g_tilted * (1.0 - t) + g_closed * t


def compute_bso_shading_for_facades(
    sun_elevation_deg: float,
    sun_azimuth_deg: float,
    ghi_w_m2: float,
    dni_w_m2: float,
    dhi_w_m2: float,
    month: int,
    g_value_glazing: float,
    facade_azimuth_deg: float = 180.0,
    *,
    irr_deploy_threshold: float = BSO_IRR_DEPLOY_THRESHOLD,
    besoin_de_froid: Optional[bool] = None,
) -> Dict[str, float]:
    """Calcule les facteurs d'ombrage BSO pour les 4 façades.

    Le BSO est installé sur la façade principale (facade_azimuth_deg)
    et éventuellement sur les façades latérales. Ici on équipe la façade
    correspondant à facade_azimuth_deg.

    Le résultat est un dict {facade_name: shading_factor} directement
    utilisable dans compute_solar_gains(shading_override=...).

    Args:
        sun_elevation_deg: Élévation solaire (°).
        sun_azimuth_deg: Azimut solaire (°).
        ghi_w_m2: Irradiance globale horizontale (W/m²).
        dni_w_m2: Irradiance directe normale (W/m²).
        dhi_w_m2: Irradiance diffuse horizontale (W/m²).
        month: Mois (1-12).
        g_value_glazing: g_value du vitrage nu.
        facade_azimuth_deg: Azimut de la façade équipée (°).
        irr_deploy_threshold: Seuil d'irradiance (W/m²).
        besoin_de_froid: voir `compute_bso_hourly_state` (None = saisonnier).

    Returns:
        Dict {facade_name: shading_factor} pour la façade équipée.
        Les façades sans BSO ne sont pas incluses dans le dict
        (→ compute_solar_gains utilisera leur shading_factor par défaut).
    """
    if sun_elevation_deg <= 0:
        return {}

    # Estimer l'irradiance sur la façade équipée
    irr_facade = _estimate_facade_irradiance(
        dni_w_m2, dhi_w_m2, sun_elevation_deg, sun_azimuth_deg,
        facade_azimuth_deg, tilt_deg=90.0,
    )

    # Calculer l'état BSO pour cette façade
    state = compute_bso_hourly_state(
        sun_elevation_deg=sun_elevation_deg,
        irr_facade_w_m2=irr_facade,
        month=month,
        g_value_glazing=g_value_glazing,
        irr_deploy_threshold=irr_deploy_threshold,
        besoin_de_froid=besoin_de_froid,
    )

    if not state.deployed:
        return {}

    # Identifier le nom de la façade dans le modèle 5R1C
    facade_name = _azimuth_to_facade_name(facade_azimuth_deg)

    return {facade_name: state.shading_factor}


def _estimate_facade_irradiance(
    dni_w_m2: float,
    dhi_w_m2: float,
    solar_alt_deg: float,
    solar_azi_deg: float,
    facade_azimuth_deg: float,
    tilt_deg: float = 90.0,
) -> float:
    """Estime l'irradiance totale sur une façade verticale.

    Modèle simplifié (isotrope pour le DHI) cohérent avec le calcul
    du modèle 5R1C (compute_solar_gains).

    Args:
        dni_w_m2: Irradiance directe normale (W/m²).
        dhi_w_m2: Irradiance diffuse horizontale (W/m²).
        solar_alt_deg: Élévation solaire (°).
        solar_azi_deg: Azimut solaire (°).
        facade_azimuth_deg: Azimut de la façade (°).
        tilt_deg: Inclinaison de la façade (° depuis horizontal).

    Returns:
        Irradiance totale estimée sur la façade (W/m²).
    """
    alt_rad = math.radians(solar_alt_deg)
    azi_sun_rad = math.radians(solar_azi_deg)
    tilt_rad = math.radians(tilt_deg)
    azi_facade_rad = math.radians(facade_azimuth_deg)

    # Composante directe (cos de l'angle d'incidence)
    cos_inc = max(0.0, (
        math.sin(alt_rad) * math.cos(tilt_rad)
        + math.cos(alt_rad) * math.sin(tilt_rad)
        * math.cos(azi_sun_rad - azi_facade_rad)
    ))
    irr_direct = dni_w_m2 * cos_inc

    # Composante diffuse isotrope (sky view factor pour plan vertical)
    sky_view = (1.0 + math.cos(tilt_rad)) / 2.0
    irr_diffuse = dhi_w_m2 * sky_view

    return irr_direct + irr_diffuse


def _azimuth_to_facade_name(azimuth_deg: float) -> str:
    """Convertit un azimut en nom de façade 5R1C.

    Le modèle 5R1C utilise 4 façades fixes :
    0° → "Nord", 90° → "Est", 180° → "Sud", 270° → "Ouest".

    On mappe l'azimut à la façade la plus proche.

    Args:
        azimuth_deg: Azimut de la façade (°).

    Returns:
        Nom de la façade ("Sud", "Nord", "Est", "Ouest").
    """
    az = azimuth_deg % 360
    if 45 <= az < 135:
        return "Est"
    elif 135 <= az < 225:
        return "Sud"
    elif 225 <= az < 315:
        return "Ouest"
    else:
        return "Nord"


# ═══════════════════════════════════════════════════════════════════════════
# LE BSO MANUEL : MANŒUVRÉ PAR DES OCCUPANTS, PAS PAR UN ALGORITHME
# ═══════════════════════════════════════════════════════════════════════════
#
# Le BSO de référence est celui qu'on trouve vraiment sur les bâtiments :
# commandé à la main (manivelle, interrupteur ou télécommande), il s'ouvre et
# se ferme selon ses occupants. La littérature dit 5 choses que ce modèle
# reprend, et rien d'autre :
#   1. on BAISSE pour le soleil direct (éblouissement, tache solaire : Reinhart
#      2004, 50 W/m² direct ; Inoue 1988, 12 à 58 W/m² sur la façade), surtout
#      en ARRIVANT (Haldi et Robinson 2009) ; en logement, contre la chaleur ;
#   2. on RELÈVE rarement, surtout en arrivant (souvent le lendemain), presque
#      jamais pendant la journée (Rea 1984 : aucun effet de l'heure) ;
#   3. une grande part des stores ne bouge presque jamais (Estia 2014 : 41 %
#      des BSO manuels bougent moins d'une fois par semaine ; Kapsis 2013 :
#      72 % jamais) : laissés baissés, ou jamais baissés ;
#   4. personne ne manœuvre un local VIDE (Haldi et Robinson : aucune descente
#      anticipée au départ) : la nuit, le week-end d'un bureau, la journée d'un
#      logement dont les occupants travaillent dehors. Le store reste où il est ;
#   5. sur UNE façade, les occupants ne se ressemblent pas (Reinhart : usagers
#      « dynamiques » et « statiques » ; Estia : de 0,1 % à 94,4 % de vitrage
#      couvert selon l'occupant). Le modèle porte donc une POPULATION de
#      comportements, chacun sur sa part de baies, et la façade voit leur
#      moyenne pondérée, pas un occupant moyen.
#
# EN ESPÉRANCE, PAS PAR TIRAGE. Chaque comportement porte la part baissée
# ATTENDUE de ses baies : f ← f + (1 − f)·p_baisse − f·p_relève, la chaîne de
# Markov de chaque occupant prise en espérance. Un tirage à graine fixe
# ajouterait un bruit d'échantillonnage (environ 7 points de part baissée pour
# 50 BSO) qui dépendrait de la graine et du nombre de BSO, ferait bouger le
# résultat d'une graine à l'autre, et ne représenterait aucun occupant de plus.
# Limite : la chaleur de la pièce est celle de la zone unique du moteur
# (bilan d'air monozone), pas celle du bureau de chaque occupant.

COMPORTEMENTS_FIXES = ("toujours_baisse", "jamais_baisse")
"""Les comportements qui ne manœuvrent jamais : baies baissées en permanence, ou jamais baissées."""

DECLENCHEURS = ("soleil", "soleil_et_chaud")
"""Ce qui fait baisser : le soleil direct seul (tertiaire, éblouissement), ou le soleil ET la chaleur (logement)."""


@dataclass(frozen=True)
class Comportement:
    """Un comportement d'occupant face à son BSO, en probabilités par occasion.

    `p_baisse_*` s'appliquent quand le déclencheur est là, `p_releve_*` quand il
    n'y est plus. « arrivée » : la première heure de présence après une absence
    (ou le lever, `bso_manuel_heure_lever`, en occupation continue) ; « présence » :
    chaque heure suivante.
    """
    nom: str
    p_baisse_arrivee: float
    p_baisse_presence: float
    p_releve_arrivee: float
    p_releve_presence: float
    declencheur: str = "soleil"

    def __post_init__(self) -> None:
        for cle in ("p_baisse_arrivee", "p_baisse_presence", "p_releve_arrivee", "p_releve_presence"):
            v = getattr(self, cle)
            if not (0.0 <= v <= 1.0):
                raise ValueError(f"BSO manuel, {self.nom} : {cle} = {v} hors de [0, 1]")
        if self.declencheur not in DECLENCHEURS:
            raise ValueError(f"BSO manuel, {self.nom} : déclencheur {self.declencheur!r} inconnu")


def comportements_bso_manuel() -> Dict[str, Comportement]:
    """Les comportements de `SYSTEM_DEFAULTS.bso_manuel_comportements`, par nom."""
    return {c[0]: Comportement(*c) for c in SYSTEM_DEFAULTS.bso_manuel_comportements}


def population_bso_manuel(residentiel: bool) -> tuple:
    """La population de la façade : ((nom du comportement, part des baies), ...), parts sommant à 1."""
    parts = (SYSTEM_DEFAULTS.bso_manuel_parts_logement if residentiel
             else SYSTEM_DEFAULTS.bso_manuel_parts_tertiaire)
    return verifier_population(parts)


def verifier_population(parts) -> tuple:
    """Refuse un comportement inconnu, une part négative, ou des parts qui ne somment pas à 1."""
    connus = set(comportements_bso_manuel()) | set(COMPORTEMENTS_FIXES)
    for nom, w in parts:
        if nom not in connus:
            raise ValueError(f"BSO manuel : comportement {nom!r} inconnu (attendu : {sorted(connus)})")
        if w < 0.0:
            raise ValueError(f"BSO manuel : part négative pour {nom!r}")
    total = sum(w for _, w in parts)
    if abs(total - 1.0) > 1e-6:
        raise ValueError(f"BSO manuel : les parts de la population somment à {total:.4f}, pas à 1")
    return tuple((str(n), float(w)) for n, w in parts)


class PiloteBSOManuel:
    """La part baissée d'une façade de BSO manœuvrés à la main, heure par heure (en espérance).

    Pur et déterministe : aucune I/O, aucun hasard. On l'appelle une fois par
    heure, dans l'ordre ; il rend la part des baies dont le BSO est baissé
    pendant cette heure, toute la population confondue.

    LA POPULATION. Chaque comportement (`population_bso_manuel`) porte sa part
    des baies. En logement, chaque comportement actif est encore partagé entre
    ceux qui restent chez eux et ceux qui partent travailler les jours ouvrés
    (`bso_manuel_logement_part_vide_journee`, absents pendant
    `bso_manuel_logement_heures_absence`) : ces derniers ne peuvent rien
    baisser avant leur retour.
    """

    def __init__(self, residentiel: bool, heures_occupees, *, population: Optional[tuple] = None) -> None:
        self.residentiel = bool(residentiel)
        self.heures_occupees = frozenset(heures_occupees)
        self.continu = len(self.heures_occupees) >= 24
        self.heure_lever = int(SYSTEM_DEFAULTS.bso_manuel_heure_lever)
        self.depart, self.retour = SYSTEM_DEFAULTS.bso_manuel_logement_heures_absence
        comportements = comportements_bso_manuel()
        pop = (verifier_population(population) if population is not None
               else population_bso_manuel(self.residentiel))
        v = float(SYSTEM_DEFAULTS.bso_manuel_logement_part_vide_journee) if self.residentiel else 0.0
        # Les groupes : (comportement, ou None s'il est fixe ; part baissée initiale ; poids ;
        # logement vidé les jours ouvrés)
        self.groupes = []
        for nom, w in pop:
            if w <= 0.0:
                continue
            if nom in COMPORTEMENTS_FIXES:
                self.groupes.append((None, 1.0 if nom == "toujours_baisse" else 0.0, w, False))
                continue
            c = comportements[nom]
            if v > 0.0:
                self.groupes.append((c, 0.0, w * (1.0 - v), False))
                self.groupes.append((c, 0.0, w * v, True))
            else:
                self.groupes.append((c, 0.0, w, False))
        self.f = [g[1] for g in self.groupes]
        self.present_avant = [False for _ in self.groupes]

    def present(self, k: int, heure: int, jour_ouvre: bool) -> bool:
        """Le groupe k est-il là, éveillé, à cette heure ?"""
        if heure not in self.heures_occupees:
            return False
        if not jour_ouvre and not self.residentiel:
            return False
        if self.groupes[k][3] and jour_ouvre and self.depart <= heure < self.retour:
            return False
        return True

    def pas(self, heure: int, jour_ouvre: bool, soleil_direct_w_m2: float, chaud: bool) -> tuple:
        """Avance d'une heure. Rend (part baissée de la façade, part baissée devant un occupant présent).

        Args:
            heure: Heure de la journée (0 à 23), convention de l'occupation du moteur.
            jour_ouvre: Jour ouvré (lundi à vendredi, convention du moteur).
            soleil_direct_w_m2: Éclairement DIRECT sur la façade (W/m²).
            chaud: La pièce est chaude (consigne de froid moins `bso_manuel_ecart_chaud_k`
                atteinte, température de l'heure précédente).
        """
        soleil = soleil_direct_w_m2 >= SYSTEM_DEFAULTS.bso_manuel_seuil_soleil_direct_w_m2
        devant = 0.0
        for k, (c, _, w, _) in enumerate(self.groupes):
            ici = self.present(k, heure, jour_ouvre)
            if c is not None and ici:
                arrivee = (not self.present_avant[k]) or (self.continu and heure == self.heure_lever)
                baisser = soleil and (chaud or c.declencheur == "soleil")
                f = self.f[k]
                if baisser:
                    f += (1.0 - f) * (c.p_baisse_arrivee if arrivee else c.p_baisse_presence)
                else:
                    f -= f * (c.p_releve_arrivee if arrivee else c.p_releve_presence)
                self.f[k] = f
            self.present_avant[k] = ici
            if ici:
                devant += w * self.f[k]
        return self.part_baissee(), devant

    def part_baissee(self) -> float:
        """La part des baies de la façade dont le BSO est baissé."""
        return sum(g[2] * f for g, f in zip(self.groupes, self.f))


def facteur_ombrage_bso_baisse(sun_elevation_deg: float, g_value_glazing: float) -> float:
    """La part du flux solaire qu'arrête un BSO baissé à la main.

    Un occupant ne suit pas le soleil : ses lames restent à l'angle du
    préréglage de la commande, `bso_manuel_g_tot_baisse` (EN 14501, lames à
    45°, le `bso_g_tot_tilted_45` du modèle automatique). Nuit : 0.
    """
    if sun_elevation_deg <= 0 or g_value_glazing <= 0:
        return 0.0
    g_eff = min(SYSTEM_DEFAULTS.bso_manuel_g_tot_baisse, g_value_glazing * BSO_FRAME_FACTOR)
    return max(0.0, min(1.0, 1.0 - g_eff / g_value_glazing))


def irradiance_directe_facade(dni_w_m2: float, sun_elevation_deg: float, sun_azimuth_deg: float,
                              facade_azimuth_deg: float) -> float:
    """L'éclairement DIRECT sur une façade verticale (W/m²) : le soleil qui entre dans la pièce."""
    if sun_elevation_deg <= 0:
        return 0.0
    cos_inc = (math.cos(math.radians(sun_elevation_deg))
               * math.cos(math.radians(sun_azimuth_deg - facade_azimuth_deg)))
    return max(0.0, dni_w_m2 * cos_inc)
