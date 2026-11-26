"""Ce que le bâtiment échange avec le dehors par ses parois : le sol sous le plancher, le vent sur les façades.

2 réglages qu'EnergyPlus prend par défaut sans le dire, et qui pèsent sur le résultat. Ils sont ici nommés,
réglables depuis le fichier d'étude, et rappelés dans les hypothèses du compte rendu.

LE SOL. Le plancher du niveau le plus bas échange avec un sol dont la température se donne mois par mois.
C'est la température SOUS LA DALLE, que le bâtiment réchauffe : pas celle du terrain nu. La documentation
d'EnergyPlus le dit ainsi [S : Input Output Reference 23.2, Site:GroundTemperature:BuildingSurface] : les
températures de sol non perturbé « are too extreme for the soil under a conditioned building », et faute de
mieux « for typical commercial buildings in the USA, a reasonable default value is 2 °C less than the average
indoor space temperature ». Sans rien donner, EnergyPlus prend 18 °C toute l'année [S : son fichier de
définition, valeur par défaut de chaque mois], ce qui revient à cette règle pour un local tenu vers 20 °C.
Le calcul juste est celui d'un préprocesseur de dalle ou de la norme ISO 13370 ; il n'est pas fait ici.
3 façons de régler cette température, dans la table [sol] :
  - `temperatures_c` : 12 valeurs, de janvier à décembre, quand on les connaît ;
  - `loi = "constante"` : une seule valeur toute l'année, `temperature_c` (18 °C si elle n'est pas donnée) ;
  - `loi = "air_amorti"` : la moyenne annuelle de l'air, plus une part de l'écart du mois précédent à cette
    moyenne. Le sol suit l'air avec du retard et moins d'ampleur. C'est plus froid l'hiver que la règle
    d'EnergyPlus : à réserver à un petit bâtiment ou à un plancher mal couplé au local.

LE VENT SUR LES PAROIS. L'échange par convection entre une paroi et l'air du dehors dépend du vent.
`convection_exterieure` choisit la loi :
  - "energyplus" : celle que prend EnergyPlus par défaut ;
  - "iso_6946" : h = 4 + 4 v, en W/m².K, v étant le vent près de la paroi [S : NF EN ISO 6946, annexe sur les
    résistances superficielles]. Le vent du fichier météo, mesuré à 10 m en terrain dégagé, est ramené à la
    mi-hauteur du bâtiment pour les murs et les vitrages, et à sa hauteur pour le toit.

LE TERRAIN pèse autant que la loi. `terrain` dit ce qui freine le vent autour du bâtiment : en ville dense
(« City », le défaut d'EnergyPlus) le vent à 19 m est 2 fois plus faible qu'en terrain dégagé (« Country »),
et h = 4 + 4 v passe de 18 à 11 W/m².K pour un vent de 3 m/s à la station. Les parois ensoleillées sont alors
plus chaudes et le besoin de froid monte : sur un immeuble de bureaux à Bordeaux, plusieurs mégawattheures
par an. Le terrain vaut aussi pour la loi d'EnergyPlus.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Sequence, Tuple

LOIS_DU_SOL = ("constante", "air_amorti")
CONVECTIONS = ("energyplus", "iso_6946")
TERRAIN_PAR_DEFAUT = "City"                 # celui que Honeybee donne à EnergyPlus
TEMPERATURE_DU_SOL_PAR_DEFAUT_C = 18.0      # [S] ce qu'EnergyPlus prend quand rien n'est donné
AMORTISSEMENT_DU_SOL = 0.4                  # [H] part de l'écart de l'air que le sol sous la dalle garde
RETARD_DU_SOL_MOIS = 1                      # [H] le sol suit l'air avec un mois de retard
JOURS_PAR_MOIS = (31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31)

# LE VENT SELON LA HAUTEUR : v(z) = v_météo × (δ_météo / z_météo)^α_météo × (z / δ)^α.
# La station météo est en terrain dégagé, à 10 m. Chaque terrain a son exposant et sa couche limite.
# [S : EnergyPlus, Engineering Reference 23.2, « Local Wind Speed Calculation », tableau repris de l'ASHRAE
# Handbook of Fundamentals 2005 ; les noms sont ceux du champ Terrain de l'objet Building.]
Z_METEO_M, ALPHA_METEO, DELTA_METEO_M = 10.0, 0.14, 270.0
TERRAINS = {"Country": (0.14, 270.0), "Suburbs": (0.22, 370.0), "City": (0.33, 460.0), "Ocean": (0.10, 210.0),
            "Urban": (0.22, 370.0)}
H_SANS_VENT, H_PAR_M_S = 4.0, 4.0           # [S] NF EN ISO 6946 : h = 4 + 4 v
HAUTEUR_MIN_M = 1.0                         # en dessous, le profil du vent n'a plus de sens


@dataclass(frozen=True)
class Sol:
    """La température du sol sous le plancher, mois par mois, et d'où elle vient."""
    temperatures_c: Tuple[float, ...]
    origine: str
    a_demander: Optional[str] = None


def _moyennes_par_mois(valeurs: Sequence[float]) -> List[float]:
    mois, debut = [], 0
    for jours in JOURS_PAR_MOIS:
        tranche = valeurs[debut:debut + 24 * jours]
        mois.append(sum(tranche) / len(tranche))
        debut += 24 * jours
    return mois


def sol(epw, temperatures_c: Optional[Sequence[float]] = None, loi: Optional[str] = None,
        temperature_c: Optional[float] = None) -> Sol:
    """Le sol de l'étude. Lève ValueError en disant ce qui ne va pas dans le réglage."""
    if temperatures_c is not None:
        if loi is not None or temperature_c is not None:
            raise ValueError("donner temperatures_c, ou une loi : pas les 2")
        valeurs = list(temperatures_c)
        if len(valeurs) != 12 or any(isinstance(v, bool) or not isinstance(v, (int, float)) or not -30 <= v <= 40
                                     for v in valeurs):
            raise ValueError("temperatures_c : 12 températures de sol, de janvier à décembre, de -30 à 40 °C")
        return Sol(tuple(round(float(v), 1) for v in valeurs), "données mois par mois")
    loi = loi or "constante"
    if loi not in LOIS_DU_SOL:
        raise ValueError(f"loi : « {loi} » n'est pas dans {', '.join(LOIS_DU_SOL)}")
    if loi == "constante":
        if temperature_c is not None and (isinstance(temperature_c, bool) or not -30 <= temperature_c <= 40):
            raise ValueError(f"temperature_c : {temperature_c!r} n'est pas une température de sol")
        if temperature_c is not None:
            return Sol((round(float(temperature_c), 1),) * 12, "constante, donnée")
        return Sol((TEMPERATURE_DU_SOL_PAR_DEFAUT_C,) * 12,
                   f"{TEMPERATURE_DU_SOL_PAR_DEFAUT_C:g} °C toute l'année, la valeur par défaut d'EnergyPlus : "
                   f"environ 2 °C sous la température d'un local chauffé")
    if temperature_c is not None:
        raise ValueError("temperature_c ne vaut qu'avec loi = \"constante\"")
    air = _moyennes_par_mois(list(epw.dry_bulb_temperature.values))
    annee = sum(a * j for a, j in zip(air, JOURS_PAR_MOIS)) / 365.0
    valeurs = [annee + AMORTISSEMENT_DU_SOL * (air[(m - RETARD_DU_SOL_MOIS) % 12] - annee) for m in range(12)]
    return Sol(tuple(round(v, 1) for v in valeurs),
               f"air amorti : moyenne annuelle de l'air ({annee:.1f} °C) plus {AMORTISSEMENT_DU_SOL:g} fois "
               f"l'écart du mois précédent [H]")


def texte_du_sol(le_sol: Sol) -> str:
    """Le texte à ajouter au fichier d'EnergyPlus."""
    return ("\nSite:GroundTemperature:BuildingSurface,\n  "
            + ", ".join(f"{t:.1f}" for t in le_sol.temperatures_c) + ";\n")


def vent_a_la_hauteur(vent_meteo_m_s: float, hauteur_m: float, terrain: str = "City") -> float:
    """Le vent à une hauteur donnée au-dessus du sol, depuis celui du fichier météo."""
    alpha, delta = TERRAINS[terrain]
    z = max(HAUTEUR_MIN_M, hauteur_m)
    return vent_meteo_m_s * (DELTA_METEO_M / Z_METEO_M) ** ALPHA_METEO * (z / delta) ** alpha


def echange_iso_6946(vent_m_s: float) -> float:
    return H_SANS_VENT + H_PAR_M_S * max(0.0, vent_m_s)


def texte_de_la_convection(modele, epw, dossier, terrain: str = "City") -> str:
    """Le texte d'EnergyPlus qui impose h = 4 + 4 v aux parois extérieures. Écrit le planning dans `dossier`."""
    if terrain not in TERRAINS:
        raise ValueError(f"terrain inconnu : « {terrain} ». Connus : {', '.join(TERRAINS)}")
    bas = min(piece.geometry.min.z for piece in modele.rooms)
    haut = max(piece.geometry.max.z for piece in modele.rooms)
    vents = list(epw.wind_speed.values)
    dossier = Path(dossier)
    dossier.mkdir(parents=True, exist_ok=True)
    planning = dossier / "echange_exterieur.csv"
    with open(planning, "w", newline="", encoding="utf-8") as flux:
        ecrit = csv.writer(flux)
        ecrit.writerow(["murs_et_vitrages_w_m2_k", "toit_w_m2_k"])
        ecrit.writerows([round(echange_iso_6946(vent_a_la_hauteur(v, (haut - bas) / 2.0, terrain)), 3),
                         round(echange_iso_6946(vent_a_la_hauteur(v, haut - bas, terrain)), 3)] for v in vents)
    texte = ["\nScheduleTypeLimits,\n  echange_exterieur_w_m2_k, , , Continuous;\n"]
    for colonne, nom in ((1, "echange_des_murs"), (2, "echange_du_toit")):
        texte.append(f"\nSchedule:File,\n  {nom}, echange_exterieur_w_m2_k, {planning.resolve()}, {colonne}, 1, "
                     f"8760, Comma, No, 60, No;\n")
    for surfaces, nom in (("AllExteriorWalls", "echange_des_murs"), ("AllExteriorWindows", "echange_des_murs"),
                          ("AllExteriorRoofs", "echange_du_toit")):
        texte.append(f"\nSurfaceProperty:ConvectionCoefficients:MultipleSurface,\n  {surfaces}, Outside, Schedule, , "
                     f"{nom};\n")
    return "".join(texte)


def dire_la_convection(convection: str, terrain: str = "City") -> str:
    if convection == "iso_6946":
        return (f"échange des parois avec l'air du dehors : h = 4 + 4 v (NF EN ISO 6946), vent du fichier météo "
                f"ramené à la hauteur de la paroi, terrain « {terrain} »")
    return f"échange des parois avec l'air du dehors : loi par défaut d'EnergyPlus, terrain « {terrain} »"


def position_de_la_meteo(epw) -> Tuple[float, float]:
    return float(epw.location.latitude), float(epw.location.longitude)
