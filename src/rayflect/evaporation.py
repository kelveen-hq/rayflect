"""L'eau qu'un mur végétalisé évapore, et ce qu'elle retire de chaleur aux modules, heure par heure.

LA MÉTHODE est celle de Hoffmann, Saad, Kluge et Nehls [S : « Modelling reference evapotranspiration of green walls »,
Hydrology and Earth System Sciences Discussions, 2023, doi 10.5194/hess-2023-221, CC BY 4.0], validée sur un
lysimètre pesé devant un mur de 12 m à Berlin : l'évapotranspiration de référence de la FAO, heure par heure, dans la
forme standardisée de l'ASCE (Allen et al. 2005, leur équation 2), « verticalisée » : le soleil est celui que reçoit
le mur, pas celui d'une station horizontale. Avec le soleil du mur, l'écart au lysimètre tombe à quelques % ; sans,
il dépasse +90 %.

    ET0 = [0,408 Δ (Rn − G) + γ (37 / (T + 273)) u2 (es − ea)] / [Δ + γ (1 + Cd u2)]      mm par heure

    Cd = 0,24 le jour, 0,96 la nuit ; Rn − G ramené à 0 quand il est négatif (§2, comme la source) ; G, le flux dans
    le mur, négligé : 20 W/m² au plus pour 450 W/m² de soleil (§2, d'après Hoffmann 2019).

L'ÉVAPOTRANSPIRATION DU MUR : ET = Kc × ET0, Kc le coefficient du système [C : van de Wouw et al. 2017, cités par la
source : 0,76 pour des bacs, 1,46 pour des panneaux ; 1,21 pour une grimpante, la source elle-même]. L'été, les murs
végétalisés demandent 2,5 à 5 L d'eau par m² et par jour [C : la source, d'après Fernández Cañero 2011, Perini 2017,
Prodanovic 2019] : le compte rendu confronte l'eau calculée à cette fourchette.

LA TEMPÉRATURE DES MODULES, celle que voit le mur derrière eux, sort de leur bilan d'énergie à chaque heure : le soleil
qu'ils absorbent les chauffe, l'eau qui s'évapore les refroidit, l'air les ramène à sa température par leurs 2 faces :

    T_modules = T_air + (a × Soleil_du_mur − λ ET) / (h_r + 2 h_c)        h_c = 4 + 4 u2, h_r = 5 W/m².K

a = 0,77, l'absorption d'un couvert végétal (l'albédo de 0,23 de la FAO, Allen et al. 1998, celui de l'équation) ;
h_c et h_r d'après la norme ISO 6946 [S]. Hors de la saison d'arrosage, ou sans arrosage, les modules n'évaporent rien
et le soleil seul les chauffe [H : la saison, d'avril à octobre ; Weinläder et al. 2024 n'arrosaient pas l'hiver].

CE QUI EST SIMPLIFIÉ [H] : le rayonnement de grande longueur d'onde du couvert (Rnl de la FAO) n'est pas retiré du
rayonnement net, faute du rayonnement hors atmosphère dans les fichiers de PVGIS : l'évaporation de jour est un peu
forte ; le vent est celui de la station ramené à 2 m (FAO, équation 47), pas celui de la rue ; l'eau ne manque jamais en
saison d'arrosage ; la pluie n'est pas comptée.
"""

from __future__ import annotations

import math
from typing import List, Optional, Sequence, Tuple

ALBEDO_DU_COUVERT = 0.23                # [S] FAO 56, Allen et al. 1998 : le couvert de référence
CHALEUR_D_EVAPORATION_J_KG = 2.45e6     # [S] FAO 56
H_RAYONNEMENT = 5.0                     # [S] ISO 6946, h_r0 vers 10 °C
REFLEXION_DU_SOL = 0.2                  # [H] la part du soleil que le sol renvoie vers le mur
KC = {"bacs": 0.76, "panneaux": 1.46}   # [C] van de Wouw et al. 2017, cités par Hoffmann et al. 2023
SAISON_D_ARROSAGE = ((4, 1), (10, 31))  # [H] d'avril à octobre
JOURS_AVANT = (0, 31, 59, 90, 120, 151, 181, 212, 243, 273, 304, 334)
ETE_ARROSE_L_M2_JOUR = (2.5, 5.0)       # [C] Hoffmann et al. 2023, §1


def vent_a_2_m(vent_a_10_m: float) -> float:
    """La vitesse du vent à 2 m, depuis celle à 10 m [S : FAO 56, équation 47]."""
    return vent_a_10_m * 4.87 / math.log(67.8 * 10.0 - 5.42)


def et0_horaire(t_c: float, rosee_c: float, pression_kpa: float, u2: float, rn_mj_h: float, de_jour: bool,
                cd: Optional[float] = None) -> float:
    """L'évapotranspiration de référence d'une heure, en mm, par la forme ASCE de Penman-Monteith (Allen et al. 2005).

    `cd` : 0,24 le jour et 0,96 la nuit par défaut (ASCE) ; la FAO 56 prend 0,34 à toute heure."""
    es = 0.6108 * math.exp(17.27 * t_c / (t_c + 237.3))
    ea = 0.6108 * math.exp(17.27 * rosee_c / (rosee_c + 237.3))
    delta = 4098.0 * es / (t_c + 237.3) ** 2
    gamma = 0.000665 * pression_kpa
    if cd is None:
        cd = 0.24 if de_jour else 0.96
    rn = max(0.0, rn_mj_h)
    et0 = (0.408 * delta * rn + gamma * 37.0 / (t_c + 273.0) * u2 * max(0.0, es - ea)) / (delta + gamma * (1.0 + cd * u2))
    return max(0.0, et0)


def soleil_sur_le_mur(epw, azimut_deg: float) -> List[float]:
    """Le soleil reçu par un mur vertical d'azimut donné, heure par heure, en W/m² : direct, ciel (isotrope), sol."""
    from ladybug.sunpath import Sunpath

    course = Sunpath.from_location(epw.location)
    direct = epw.direct_normal_radiation.values
    diffus = epw.diffuse_horizontal_radiation.values
    globale = epw.global_horizontal_radiation.values
    rendu = []
    for h in range(len(direct)):
        soleil = course.calculate_sun_from_hoy(h + 0.5)
        incidence = 0.0
        if soleil.altitude > 0:
            incidence = max(0.0, math.cos(math.radians(soleil.altitude))
                            * math.cos(math.radians(soleil.azimuth - azimut_deg)))
        rendu.append(direct[h] * incidence + diffus[h] * 0.5 + globale[h] * REFLEXION_DU_SOL * 0.5)
    return rendu


def _en_saison(h: int, saison: Tuple[Tuple[int, int], Tuple[int, int]]) -> bool:
    jour = h // 24
    debut = JOURS_AVANT[saison[0][0] - 1] + saison[0][1] - 1
    fin = JOURS_AVANT[saison[1][0] - 1] + saison[1][1] - 1
    return debut <= jour <= fin


def modules(epw, azimut_deg: float, kc: float, arrose: bool = True,
            saison: Tuple[Tuple[int, int], Tuple[int, int]] = SAISON_D_ARROSAGE) -> Tuple[List[float], List[float]]:
    """(température des modules en °C, eau évaporée en mm, c'est-à-dire en L par m² de mur), heure par heure."""
    air = epw.dry_bulb_temperature.values
    rosee = epw.dew_point_temperature.values
    pression = epw.atmospheric_station_pressure.values
    vent = epw.wind_speed.values
    soleil = soleil_sur_le_mur(epw, azimut_deg)
    temperatures, eau = [], []
    for h in range(len(air)):
        u2 = vent_a_2_m(vent[h])
        absorbe = (1.0 - ALBEDO_DU_COUVERT) * soleil[h]                       # W/m²
        et = 0.0
        if arrose and _en_saison(h, saison):
            et = kc * et0_horaire(air[h], min(rosee[h], air[h]), pression[h] / 1000.0, u2,
                                  absorbe * 3600.0 / 1e6, soleil[h] > 0)
        latent = et * CHALEUR_D_EVAPORATION_J_KG / 3600.0                     # W/m²
        temperatures.append(air[h] + (absorbe - latent) / (H_RAYONNEMENT + 2.0 * (4.0 + 4.0 * u2)))
        eau.append(et)
    return temperatures, eau


def dire_l_eau(eau: Sequence[float]) -> str:
    """L'eau évaporée sur l'année et en été, confrontée à ce que les murs mesurés demandent."""
    ete = sum(eau[JOURS_AVANT[5] * 24:JOURS_AVANT[8] * 24]) / 92.0
    bas, haut = ETE_ARROSE_L_M2_JOUR
    jugement = "dans" if bas <= ete <= haut else "sous" if ete < bas else "au-dessus de"
    return (f"eau évaporée : {sum(eau):.0f} L par m² de mur et par an, {ete:.1f} L par m² et par jour l'été, {jugement} "
            f"la fourchette mesurée de {bas:g} à {haut:g} L [C : Hoffmann et al. 2023]")
