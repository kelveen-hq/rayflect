"""Ce que le département et l'altitude d'un lieu disent de son climat : la zone climatique, la température
extérieure de base, et le terrain à proposer.

France métropolitaine seulement. Hors de France, ou quand le département n'est pas connu, chaque fonction
rend None : la valeur est alors à donner dans le fichier d'étude.

LA ZONE CLIMATIQUE (H1a à H3) est celle de la réglementation thermique [S : arrêté du 26 octobre 2010 relatif
aux caractéristiques thermiques des bâtiments nouveaux, annexe I, lu sur Légifrance ; l'annexe y nomme les
départements, la conversion en numéros est faite ici]. Elle ne sert à aucun calcul de ce dépôt : la météo
vient du point exact. Elle situe le bâtiment dans le vocabulaire des bureaux d'études.

LA TEMPÉRATURE EXTÉRIEURE DE BASE sert à dimensionner le chauffage (rayflect.puissance). La norme qui la
fixe, NF P52-612/CN, complément français de la NF EN 12831, est payante et N'A PAS ÉTÉ LUE. Les valeurs
ci-dessous sont des recopies [C] :
  - par département, au niveau de la mer : annexe de la méthode 3CL-DPE v1.3, colonne « Text_base », et la
    table que le site puissance-radiateur.fr dit reprise du guide RAGE de 2013 ; les 2 concordent sur 95
    départements, le 96e (70) ne vient que de la première. Un 3e site s'en écarte sur 3 départements
    (06, 35, 42) ;
  - selon l'altitude : une grille recopiée à l'identique par 2 sites (izi-by-edf-renov.fr, abcclim.net).
Tant que la norme n'est pas lue, la valeur rendue porte la mention « à confirmer ».
"""

from __future__ import annotations

from typing import Dict, Optional, Tuple

ZONES: Dict[str, Tuple[str, ...]] = {
    "H1a": ("02", "14", "27", "28", "59", "60", "61", "62", "75", "76", "77", "78", "80", "91", "92", "93", "94", "95"),
    "H1b": ("08", "10", "45", "51", "52", "54", "55", "57", "58", "67", "68", "70", "88", "89", "90"),
    "H1c": ("01", "03", "05", "15", "19", "21", "23", "25", "38", "39", "42", "43", "63", "69", "71", "73", "74", "87"),
    "H2a": ("22", "29", "35", "50", "56"),
    "H2b": ("16", "17", "18", "36", "37", "41", "44", "49", "53", "72", "79", "85", "86"),
    "H2c": ("09", "12", "24", "31", "32", "33", "40", "46", "47", "64", "65", "81", "82"),
    "H2d": ("04", "07", "26", "48", "84"),
    "H3": ("06", "11", "13", "2A", "2B", "30", "34", "66", "83"),
}
ZONE_PAR_DEPARTEMENT = {departement: zone for zone, departements in ZONES.items() for departement in departements}

# Température extérieure de base au niveau de la mer (0 à 200 m), en °C, par département. [C]
BASE_AU_NIVEAU_DE_LA_MER: Dict[int, Tuple[str, ...]] = {
    -2: ("2A", "2B"),
    -4: ("22", "29", "50", "56"),
    -5: ("06", "09", "11", "13", "16", "17", "24", "30", "31", "32", "33", "34", "35", "40", "44", "47", "64", "65",
         "66", "75", "81", "82", "83", "85"),
    -6: ("07", "26", "46", "84"),
    -7: ("02", "14", "18", "27", "28", "36", "37", "41", "45", "49", "53", "60", "61", "72", "76", "77", "78", "79",
         "86", "91", "92", "93", "94", "95"),
    -8: ("03", "04", "12", "15", "19", "23", "43", "48", "63", "87"),
    -9: ("59", "62", "80"),
    -10: ("01", "05", "08", "10", "21", "38", "39", "42", "51", "58", "69", "71", "73", "74", "89"),
    -12: ("25", "52", "55", "70"),
    -15: ("54", "57", "67", "68", "88", "90"),
}
BASE_PAR_DEPARTEMENT = {d: valeur for valeur, departements in BASE_AU_NIVEAU_DE_LA_MER.items() for d in departements}

# La même température selon l'altitude. Une colonne par valeur au niveau de la mer ; une ligne par tranche de
# 200 m, repérée par son altitude haute. None : la grille recopiée n'a pas de valeur à cette altitude. [C]
ALTITUDES_HAUTES_M = (200, 400, 600, 800, 1000, 1200, 1400, 1600, 1800, 2000, 2200)
BASE_SELON_L_ALTITUDE: Dict[int, Tuple[Optional[int], ...]] = {
    -2: (-2, -4, -6, -8, -10, -12, -14, -16, -18, -20, None),
    -4: (-4, -5, -6, -7, -8, -9, -10, None, None, None, None),
    -5: (-5, -6, -7, -8, -9, -10, -11, -12, -13, -14, -15),
    -7: (-7, -8, -9, -11, -13, -14, -15, None, None, None, None),
    -8: (-8, -9, -11, -13, -15, -17, -19, -21, -23, -25, -27),
    -9: (-9, -10, -11, -12, -13, None, None, None, None, None, None),
    -10: (-10, -11, -13, -14, -17, -19, -21, -23, -24, -25, -29),
    -12: (-12, -13, -15, -17, -19, -21, -23, -24, None, None, None),
    -15: (-15, -15, -19, -21, -23, -24, -25, None, None, None, None),
}
A_CONFIRMER = "recopie de la norme NF P52-612/CN, non lue : à confirmer"

# LE TERRAIN À PROPOSER, d'après la population de la commune. [H] : aucune source ne relie les 2 ; c'est une
# proposition, jamais un réglage posé d'office.
VILLE_DENSE_HABITANTS = 100_000
BOURG_HABITANTS = 5_000


def zone(departement: Optional[str]) -> Optional[str]:
    """La zone climatique du département, ou None s'il n'est pas en métropole."""
    return ZONE_PAR_DEPARTEMENT.get(str(departement).upper().zfill(2)) if departement else None


def temperature_de_base(departement: Optional[str], altitude_m: Optional[float]) -> Optional[Tuple[float, str]]:
    """(température de base en °C, d'où elle vient), ou None quand rien ne permet de la donner."""
    cle = str(departement).upper().zfill(2) if departement else None
    if cle not in BASE_PAR_DEPARTEMENT:
        return None
    mer = BASE_PAR_DEPARTEMENT[cle]
    if altitude_m is None or altitude_m <= ALTITUDES_HAUTES_M[0]:
        suffixe = "altitude inconnue, prise au niveau de la mer" if altitude_m is None else "moins de 200 m"
        return float(mer), f"département {cle}, {suffixe} ; {A_CONFIRMER}"
    rang = next((k for k, haut in enumerate(ALTITUDES_HAUTES_M) if altitude_m <= haut), None)
    if rang is None:
        return None
    if mer in BASE_SELON_L_ALTITUDE:
        valeur = BASE_SELON_L_ALTITUDE[mer][rang]
        comment = ""
    else:
        # La grille n'a pas de colonne pour -6 °C : la moyenne de ses 2 voisines. [H]
        voisines = (BASE_SELON_L_ALTITUDE[mer + 1][rang], BASE_SELON_L_ALTITUDE[mer - 1][rang])
        valeur = None if None in voisines else sum(voisines) / 2.0
        comment = ", entre les colonnes voisines de la grille [H]"
    if valeur is None:
        return None
    bas = ALTITUDES_HAUTES_M[rang] - 199
    return float(valeur), (f"département {cle} ({mer:g} °C au niveau de la mer), entre {bas} et "
                           f"{ALTITUDES_HAUTES_M[rang]} m{comment} ; {A_CONFIRMER}")


def terrain_propose(population: Optional[int]) -> Optional[Tuple[str, str]]:
    """(terrain, pourquoi), d'après la population de la commune ; None si elle n'est pas connue."""
    if population is None:
        return None
    if population >= VILLE_DENSE_HABITANTS:
        return "City", f"commune de {population} habitants : une grande ville"
    if population >= BOURG_HABITANTS:
        return "Suburbs", f"commune de {population} habitants : une ville moyenne ou une banlieue"
    return "Country", f"commune de {population} habitants : un bourg ou la campagne"
