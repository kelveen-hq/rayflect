"""
Estimation de la surface vitrée totale d'un bâtiment.

Basé sur les normes françaises (RT2012, RE2020) et les pratiques européennes.

**RT2012** : surface de baie ≥ 1/6 de la surface habitable (résidentiel).
**EN ISO 13790** / **EN 15217** : ratios typiques par usage.
**Passivhaus** : ~25% de la surface plancher traitée.

Hypothèses :
    - La surface vitrée est la surface totale de baies (toutes façades, tous étages).
    - Les ratios sont exprimés en % de la surface plancher totale (= floor_area × n_floors).
    - Les valeurs sont des moyennes statistiques, pas des minimums réglementaires.

Unités :
    - Surfaces en m²
    - Ratios sans dimension (0 à 1)
"""

from __future__ import annotations


# ─────────────────────────────────────────────────────────────────────────────
# Ratios surface vitrée / surface plancher totale par type de bâtiment
# Source : RT2012 (résidentiel), EN 15217, pratiques courantes (tertiaire)
# ─────────────────────────────────────────────────────────────────────────────
WINDOW_TO_FLOOR_RATIOS: dict[str, float] = {
    # Résidentiel : RT2012 impose ≥ 1/6 ≈ 16.7%
    "residential": 0.17,
    # Bureaux : grandes baies vitrées, éclairage naturel, norme EN 15232
    "office": 0.25,
    # Enseignement : salles de classe bien éclairées
    "education": 0.22,
    # Commerce : vitrines, accès lumière naturelle
    "retail": 0.30,
    # Hébergement / Hôtel : similaire résidentiel, plus confort
    "hotel": 0.20,
    # Industriel : éclairage zénithal dominant, peu de façade vitrée
    "industrial": 0.12,
    # Santé : confort patient, éclairage naturel requis
    "healthcare": 0.22,
}

# Ces ratios sont des CONVENTIONS D'USAGE : ils décrivent le bâtiment supposé
# quand aucune surface vitrée n'est donnée. Ils ne sont pas mesurés. Pour le
# tertiaire, une mesure existe plus bas (`mesure_ratio_vitrage`) et elle est
# très loin de ces valeurs : la médiane d'un tertiaire de 2 000 m² d'emprise
# est à 1,0 % de son plancher, pas à 25 %. Les 2 coexistent ; la docstring de
# `mesure_ratio_vitrage` dit pourquoi.

# Valeur par défaut si le type n'est pas connu
_DEFAULT_RATIO = 0.17


def get_window_to_floor_ratio(building_type: str) -> float:
    """Retourne le ratio surface vitrée / surface plancher totale.

    Parameters
    ----------
    building_type : str
        Type de bâtiment (residential, office, education, retail, hotel,
        industrial, healthcare).

    Returns
    -------
    float
        Ratio (0 à 1). Ex: 0.17 pour résidentiel.
    """
    return WINDOW_TO_FLOOR_RATIOS.get(building_type, _DEFAULT_RATIO)


def estimate_window_area(
    floor_area_m2: float,
    n_floors: int,
    building_type: str = "residential",
) -> float:
    """Estime la surface vitrée totale du bâtiment.

    Formule : window_area = floor_area × n_floors × ratio

    Parameters
    ----------
    floor_area_m2 : float
        Surface plancher par étage (m²).
    n_floors : int
        Nombre d'étages.
    building_type : str
        Type de bâtiment.

    Returns
    -------
    float
        Surface vitrée totale estimée (m²), arrondie à 1 décimale.

    Examples
    --------
    >>> estimate_window_area(500, 3, "residential")
    255.0
    >>> estimate_window_area(500, 3, "office")
    375.0
    """
    ratio = get_window_to_floor_ratio(building_type)
    return round(floor_area_m2 * n_floors * ratio, 1)


# =============================================================================
# CE QUE LE PARC MESURE : 841 DPE TERTIAIRES DE GIRONDE
# =============================================================================
# Le vitrage d'un bâtiment est sur son PÉRIMÈTRE ; le plancher est une SURFACE.
# Un coefficient vitrage ÷ (emprise × niveaux) ne peut donc pas être constant, et
# il ne l'est pas. Mesuré sur les diagnostics tertiaires de la BDNB (millésime
# 2026-02-a), même dénominateur qu'`estimate_window_area` :
#
#   emprise au sol      coefficient médian   bandeau équivalent   × / médiane
#   < 200 m²                 0,0936               0,22 m             2,07
#   200 – 600 m²              0,0431               0,14 m             0,95
#   600 – 2 000 m²            0,0175               0,08 m             0,39
#   ≥ 2 000 m²                0,0100               0,06 m             0,22
#
# UN FACTEUR 9,4 D'UN BOUT À L'AUTRE : 4 fois l'écart que les conventions
# ci-dessus mettent entre l'industriel (0,12) et le commerce (0,30). L'emprise
# explique le vitrage bien mieux que l'étiquette d'usage. Appliquer la médiane
# de TOUT le tertiaire (0,0452, dominée par les petits bâtiments) à un parc
# composé de gros surestime leur vitrage d'un facteur 2,7.
#
# Sur les seuls assujettis au décret tertiaire (≥ 1 000 m² de plancher), le
# coefficient mesuré est 0,0169 : 204 diagnostics, q1 0,0092, q3 0,0382.
#
# AUCUNE LOI GÉOMÉTRIQUE NE RATTRAPE LE TERTIAIRE. 3 lois testées en
# validation croisée sur les 841 diagnostics : k·emprise·niveaux (57 % d'erreur
# médiane), k·périmètre·niveaux (52 %), k·emprise^0,35·niveaux (44 %, la
# meilleure). Même la meilleure se trompe d'un facteur 1,5 une fois sur deux :
# un seul chiffre pour « le tertiaire » mélange un showroom tout vitré et un
# hangar aveugle, et la géométrie seule ne les distingue pas.
#
# LE LOGEMENT COLLECTIF : le ratio constant y reste la meilleure loi (48 %
# d'erreur médiane), et le 1/6 de la RT2012 la porte.
#
# Bornes en m² d'emprise au sol (surface d'UN niveau) ; le coefficient est
# rapporté au plancher TOTAL (emprise × niveaux).
MESURE_TERTIAIRE_PAR_EMPRISE: tuple = (
    (200.0, 0.0936),
    (600.0, 0.0431),
    (2000.0, 0.0175),
    (float("inf"), 0.0100),
)

MESURE_TERTIAIRE_ASSUJETTIS = 0.0169
"""Médiane sur les assujettis au décret tertiaire (≥ 1 000 m² de plancher)."""

MESURE_TERTIAIRE_TOUTES_EMPRISES = 0.0452
"""Médiane de tout le tertiaire : à ne PAS appliquer aux grands bâtiments."""

_TYPES_TERTIAIRES = frozenset(
    {"office", "education", "healthcare", "retail", "hotel", "industrial",
     "bureau", "enseignement", "sante", "commerce", "hebergement", "industriel"})


def mesure_ratio_vitrage(
    building_type: str,
    footprint_m2: float | None,
    n_floors: int = 1,
) -> tuple | None:
    """Le ratio vitrage/plancher MESURÉ pour ce bâtiment, ou None.

    Rend ``(ratio, source)`` quand une mesure existe pour ce cas, et ``None``
    sinon : jamais un chiffre plausible à la place d'une mesure absente.

    Cette mesure n'est pas branchée sur `get_window_to_floor_ratio`. Ce
    ratio-là sert à supposer un bâtiment quand l'appelant n'en donne aucun :
    le plancher se déduit du vitrage, plancher = vitrage / ratio. Passer le
    bureau de 0,25 à 0,017 multiplierait par 15 le bâtiment supposé autour du
    même vitrage, et avec lui ses apports internes et sa surventilation
    nocturne, qui portent sur le bâtiment entier. La mesure sert donc à
    informer, pas à déduire une géométrie.

    Args:
        building_type: type de bâtiment (libellé français ou anglais).
        footprint_m2: emprise au sol, c'est-à-dire la surface d'UN niveau.
        n_floors: nombre de niveaux (sert à repérer l'assujettissement).

    Returns:
        ``(ratio, source)`` ou ``None`` si rien n'est mesuré pour ce cas.
    """
    if building_type not in _TYPES_TERTIAIRES:
        return None            # le logement garde le 1/6
    if not footprint_m2 or footprint_m2 <= 0:
        return None            # sans emprise, la mesure ne dit rien d'utile
    for borne, ratio in MESURE_TERTIAIRE_PAR_EMPRISE:
        if footprint_m2 < borne:
            plancher = footprint_m2 * max(1, n_floors)
            quoi = ("assujetti au décret tertiaire"
                    if plancher >= 1000.0 else "tertiaire")
            borne_txt = "∞" if borne == float("inf") else f"{borne:.0f}"
            return ratio, (
                f"mesuré : {quoi}, emprise {footprint_m2:.0f} m² "
                f"(tranche < {borne_txt} m²), 841 DPE tertiaires de Gironde")
    return None
