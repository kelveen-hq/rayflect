"""Un plan fixe simulé heure par heure : casquette, toiture, panneau mural.

Ce module calcule la production photovoltaïque annuelle d'un plan qui ne
bouge pas. Il prend des heures météo (DNI, DHI, GHI, position solaire,
température de l'air), projette l'irradiance sur un plan d'inclinaison et
d'azimut donnés, puis applique la fonction de dérating qu'on lui passe
(température de cellule, pertes système).

Ce qu'il ne fait pas :
  · il ne modélise pas l'ombrage entre rangées de panneaux (une toiture
    dense s'auto-ombre) : l'erreur va dans le sens optimiste pour la toiture ;
  · il ne modélise pas l'apport bifacial (l'albédo au dos du module), qui va
    dans l'autre sens ;
  · l'occlusion par l'environnement est un PARAMÈTRE, pas un calcul : on la
    passe, on ne la devine pas.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Sequence


@dataclass(frozen=True)
class ProductionPlanFixe:
    """Ce qu'un plan fixe produit sur l'année, et de quoi le relire."""

    kwh_an: float
    kwh_par_kwc: float
    kwc: float
    poa_kwh_m2: float
    """Irradiation reçue dans le plan (kWh/m²/an) : le juge de l'orientation."""
    heures_productives: int
    derating_moyen: float
    """Rapport entre la production corrigée et la production STC brute."""


def cos_incidence(sun_altitude_deg: float, sun_azimuth_deg: float,
                  tilt_deg: float, azimuth_deg: float) -> float:
    """Cosinus de l'angle d'incidence sur un plan quelconque.

    Convention d'azimut : 0 = Nord, 90 = Est, 180 = Sud. Un plan
    d'inclinaison 0 est horizontal, 90 vertical.
    """
    alt = math.radians(sun_altitude_deg)
    az = math.radians(sun_azimuth_deg)
    tilt = math.radians(tilt_deg)
    plan_az = math.radians(azimuth_deg)
    return (math.sin(alt) * math.cos(tilt)
            + math.cos(alt) * math.sin(tilt) * math.cos(az - plan_az))


def facteur_ciel(tilt_deg: float) -> float:
    """Part du ciel que voit un plan incliné, modèle isotrope.

    Un plan horizontal voit tout le ciel (1,0), un plan vertical la moitié.
    C'est le modèle de Liu-Jordan.
    """
    return (1.0 + math.cos(math.radians(tilt_deg))) / 2.0


def facteur_sol(tilt_deg: float, albedo: float = 0.2) -> float:
    """Part du rayonnement réfléchi par le sol que reçoit le plan."""
    return albedo * (1.0 - math.cos(math.radians(tilt_deg))) / 2.0


def produire(heures: Sequence[dict], tilt_deg: float, azimuth_deg: float,
             surface_m2: float, kwc_par_m2: float,
             occlusion: float = 1.0,
             derating=None,
             albedo: float = 0.2) -> ProductionPlanFixe:
    """La production annuelle d'un plan fixe, heure par heure.

    `heures` est une suite de dictionnaires portant au minimum ``dni``,
    ``dhi``, ``ghi``, ``temp_air``, ``sun_altitude_deg`` et
    ``sun_azimuth_deg``.

    `derating` est une fonction `(puissance_brute_w, temp_air_c, poa_w_m2)`
    qui rend la puissance nette en watts. On la REÇOIT en argument, pour que
    ce module reste utilisable seul et pour rendre visible, à l'appel, quelle
    physique on emploie. Sans elle, aucune perte n'est appliquée et le
    résultat est une BORNE HAUTE : `derating_moyen` vaut alors 1,0.

    `occlusion` vaut 1,0 quand rien ne masque le plan (une toiture dégagée) et
    descend vers 0 quand l'environnement le masque. C'est un paramètre :
    ce module ne devine pas le masque, il l'applique.
    """
    if surface_m2 <= 0 or kwc_par_m2 <= 0:
        return ProductionPlanFixe(0.0, 0.0, 0.0, 0.0, 0, 1.0)

    kwc = surface_m2 * kwc_par_m2
    # Le rendement implicite du module, pour passer d'une irradiance à des
    # watts : 1 kWc produit 1 kW sous 1 000 W/m² dans son plan.
    w_par_w_m2 = kwc * 1000.0 / 1000.0

    brut_wh = 0.0
    net_wh = 0.0
    poa_wh = 0.0
    productives = 0
    ciel = facteur_ciel(tilt_deg)
    sol = facteur_sol(tilt_deg, albedo)

    def nombre(valeur, defaut=0.0):
        """Rend `defaut` seulement si la valeur est absente (None).

        `x or defaut` se trompe sur un zéro, car 0,0 est faux en Python : un
        azimut de 0 (plein NORD) deviendrait 180 (plein SUD).
        """
        return defaut if valeur is None else float(valeur)

    for h in heures:
        alt = nombre(h.get("sun_altitude_deg"))
        if alt <= 0.0:
            continue
        cos_i = cos_incidence(alt, nombre(h.get("sun_azimuth_deg"), 180.0),
                              tilt_deg, azimuth_deg)
        if cos_i < 0.0:
            cos_i = 0.0
        dni = nombre(h.get("dni"))
        dhi = nombre(h.get("dhi"))
        ghi = nombre(h.get("ghi"))
        # Irradiance dans le plan : direct + diffus du ciel + réfléchi du sol.
        poa = dni * cos_i + dhi * ciel + ghi * sol
        if poa <= 0.0:
            continue
        poa *= occlusion
        poa_wh += poa
        brut = w_par_w_m2 * poa
        brut_wh += brut
        net = brut if derating is None else derating(
            brut, nombre(h.get("temp_air"), 15.0), poa)
        net_wh += net
        productives += 1

    kwh = net_wh / 1000.0
    return ProductionPlanFixe(
        kwh_an=round(kwh, 1),
        kwh_par_kwc=round(kwh / kwc, 1) if kwc else 0.0,
        kwc=round(kwc, 3),
        poa_kwh_m2=round(poa_wh / 1000.0 / surface_m2, 1) if surface_m2 else 0.0,
        heures_productives=productives,
        derating_moyen=round(net_wh / brut_wh, 4) if brut_wh else 1.0,
    )


__all__ = ["ProductionPlanFixe", "cos_incidence", "facteur_ciel",
           "facteur_sol", "produire"]
