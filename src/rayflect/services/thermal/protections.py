# -*- coding: utf-8 -*-
"""Les protections solaires d'une façade : ce qui ombre le vitrage.

Ce module calcule, pour un niveau de la façade et heure par heure :

  1. la part du rayonnement DIRECT qui atteint encore les baies, sous une
     saillie (casquette, balcon, brise-soleil) et entre des joues :
     EN ISO 52016-1:2017 annexe F (§ F.3 : ombre d'une avancée et de joues
     sur une baie), EN ISO 13790:2008 § 11.4.4 (F_sh,ob = F_hor · F_ov ·
     F_fin : les facteurs se MULTIPLIENT), ASHRAE Fundamentals (chap. 15,
     « Shading of fenestration » : angle de profil, angle d'ombre horizontal) ;
  2. la part du DIFFUS du ciel et du sol que les baies voient encore, par le
     facteur de vue de la saillie et des joues (cordes croisées de Hottel,
     géométrie 2D) ;
  3. le facteur Fc d'une occultation mobile déployée : EN 13363-1 (méthode
     simplifiée, reprise par l'EN ISO 52022-1) ;
  4. la résistance additionnelle d'un volet FERMÉ la nuit : EN ISO 10077-1
     (annexe : résistance additionnelle des fermetures selon leur
     perméabilité à l'air).

Tout est facultatif : sans protection déclarée, aucun facteur ne s'applique.

La décision de déployer une occultation mobile dépend de la température
intérieure, que seule la boucle horaire de l'appelant connaît. Ce module ne
rend que des facteurs à géométrie et soleil donnés.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from ...config.system_constants import GLASS_PROPERTIES, SYSTEM_DEFAULTS

# ═══════════════════════════════════════════════════════════════════════════
# LE VOCABULAIRE DU CONTRAT
# ═══════════════════════════════════════════════════════════════════════════

#: Les occultations mobiles qu'une baie peut déjà porter. Le moteur ne
#: connaît que ces 4 clés et refuse les autres.
TYPES_OCCULTATION: Tuple[str, ...] = (
    "roller_shutter",            # volet roulant
    "louvered_shutter",          # persiennes (volets à lames)
    "external_venetian_blind",   # BSO : brise-soleil orientable extérieur
    "internal_blind",            # store intérieur, rideau
)

# ═══════════════════════════════════════════════════════════════════════════
# LES OCCULTATIONS DÉPLOYÉES L'ÉTÉ : EN 13363-1, MÉTHODE SIMPLIFIÉE
# ═══════════════════════════════════════════════════════════════════════════
#
# g_tot d'un vitrage muni d'une protection parallèle, à partir de g et U du
# vitrage et de la transmission / réflexion solaires de la protection :
#
#   EXTÉRIEURE  g_tot = τ·g + α·G/G2 + τ·(1 − g)·G/G1
#               G = (1/U + 1/G1 + 1/G2)⁻¹,  G1 = 5,  G2 = 10 W/(m².K)
#   INTÉRIEURE  g_tot = g·(1 − g·ρ − α·G/G2)
#               G = (1/U + 1/G2)⁻¹,  G2 = 30 W/(m².K)
#
# avec α = 1 − τ − ρ. Fc = g_tot / g. LES CONSTANTES SONT CITÉES DE MÉMOIRE,
# sans relecture du texte de la norme ; le résultat est RECOUPÉ par une
# source indépendante, la table 7 de la DIN 4108-2 : volet roulant fermé aux
# 3 quarts ≈ 0,30 à 0,35, store intérieur clair ≈ 0,75. Les valeurs rendues
# ici sont 0,35 et 0,73 sur un double vitrage à faible émissivité.
G1_EXTERIEUR_W_M2K = 5.0
G2_EXTERIEUR_W_M2K = 10.0
G2_INTERIEUR_W_M2K = 30.0

# La méthode simplifiée n'est donnée que pour les doubles vitrages courants.
# Hors de ce domaine (un simple vitrage à 5,8), U est ramené à la borne, et
# c'est écrit ici plutôt que caché dans une formule qui extrapole.
U_METHODE_SIMPLIFIEE_MIN_W_M2K = 1.1
U_METHODE_SIMPLIFIEE_MAX_W_M2K = 3.0

# Propriétés optiques REPRÉSENTATIVES (fiches fabricants, ordre de grandeur,
# teinte moyenne) et part de la baie couverte quand l'occupant la manœuvre
# aux heures chaudes et ensoleillées.
#
# VOLET ROULANT FERMÉ AUX TROIS QUARTS, pas complètement : il faut encore y
# voir. C'est aussi l'hypothèse de la DIN 4108-2 pour le confort d'été. Les
# PERSIENNES laissent passer le jour entre leurs lames : on les ferme, et
# leur τ porte ce jour. Le STORE INTÉRIEUR est clair (ρ 0,50).
PROPRIETES_OCCULTATION: Dict[str, Dict[str, float]] = {
    "roller_shutter": {"exterieure": 1.0, "tau": 0.00, "rho": 0.35, "part_fermee": 0.75},
    "louvered_shutter": {"exterieure": 1.0, "tau": 0.10, "rho": 0.35, "part_fermee": 1.00},
    "internal_blind": {"exterieure": 0.0, "tau": 0.10, "rho": 0.50, "part_fermee": 1.00},
}
# Le BSO n'est pas dans cette table : il a son propre modèle
# (`services/analysis/bso_model.py`, lames pilotées par la hauteur du soleil,
# EN 15232 classe B). Un BSO existant sur la façade passe par ce modèle, pour
# qu'il n'y ait qu'un BSO dans le moteur.

# ═══════════════════════════════════════════════════════════════════════════
# QUAND L'OCCUPANT MANŒUVRE : UNE HYPOTHÈSE DE COMPORTEMENT, DITE COMME TELLE
# ═══════════════════════════════════════════════════════════════════════════
#
# « Heures chaudes et ensoleillées » : la zone est chaude ET la baie est au
# soleil. Aucune de ces deux valeurs n'est une mesure d'occupant.
#
#   CHAUD : T_int (heure précédente) ≥ consigne de froid − 2 K : on ne
#     protège que quand le bâtiment a besoin de refroidir.
#   ENSOLEILLÉ : irradiance totale sur la façade ≥ 300 W/m². Valeur d'usage
#     des outils de simulation pour une manœuvre manuelle (IES VE baisse le
#     store entre 200 et 300 W/m²). Elle ne figure pas dans l'EN ISO 52016-1 :
#     c'est une convention, pas une norme.
ECART_INCONFORT_CHAUD_K = 2.0
SEUIL_SOLEIL_MANUEL_W_M2 = 300.0

# Transmission solaire d'une toile de store banne (acrylique teinte moyenne,
# fiches fabricants : 0,02 foncé à 0,20 clair). La toile absorbe le reste,
# loin de la vitre et ventilée : elle ne rayonne pas vers la pièce.
TAU_TOILE_STORE = 0.10

# ═══════════════════════════════════════════════════════════════════════════
# LA NUIT : RÉSISTANCE ADDITIONNELLE D'UN VOLET FERMÉ
# ═══════════════════════════════════════════════════════════════════════════
#
# EN ISO 10077-1 : ΔR = a·R_volet + b, selon la perméabilité à l'air de la
# fermeture (très élevée 0,08 ; élevée 0,25·R + 0,09 ; moyenne 0,55·R + 0,11).
#
# VOLET ROULANT : `SYSTEM_DEFAULTS.r_shutter_default`, 0,19 m²K/W, volet
# roulant PVC de tablier ≤ 12 mm (Règles Th-U, tableau 2). Une seule valeur
# pour cet objet dans tout le moteur.
# PERSIENNES : perméabilité élevée (lames), R_volet ≈ 0,15 → 0,13.
# BSO et STORE INTÉRIEUR : pas crédités la nuit. Le premier n'est pas
# supposé fermé la nuit, le second n'isole presque rien.
R_NUIT_OCCULTATION: Dict[str, float] = {
    "roller_shutter": SYSTEM_DEFAULTS.r_shutter_default,
    "louvered_shutter": 0.13,
    "external_venetian_blind": 0.0,
    "internal_blind": 0.0,
}

# Les dimensions de baie par défaut, quand le dessin ne dit pas les siennes.
HAUTEUR_BAIE_DEFAUT_M = SYSTEM_DEFAULTS.window_height_standard_m
LARGEUR_BAIE_DEFAUT_M = round(SYSTEM_DEFAULTS.window_area_per_shutter_m2
                              / SYSTEM_DEFAULTS.window_height_standard_m, 4)


# ═══════════════════════════════════════════════════════════════════════════
# LE CONTRAT INTERNE
# ═══════════════════════════════════════════════════════════════════════════

@dataclass(frozen=True)
class ProtectionNiveau:
    """Ce qui protège le vitrage d'UN niveau de la façade dessinée.

    Chaque grandeur est une MOYENNE PONDÉRÉE PAR L'AIRE des baies du niveau
    (portes exclues : elles n'ont pas de vitrage). Les parts (`part_*`) sont
    des parts de LARGEUR vitrée couverte, de 0 à 1.

    `occultations` vaut None quand le dessin ne dit RIEN des occultations :
    l'appelant garde alors sa convention par défaut, parce qu'une donnée
    absente n'est pas une donnée nulle. Un tuple vide veut dire
    « déclaré : aucune ».
    """

    vitrage_m2: float
    hauteur_baie_m: float = HAUTEUR_BAIE_DEFAUT_M
    largeur_baie_m: float = LARGEUR_BAIE_DEFAUT_M
    # Saillie fixe au-dessus des baies : casquette, balcon, brise-soleil.
    saillie_m: float = 0.0
    ecart_saillie_m: float = 0.0          # sous-face → linteau
    part_saillie: float = 0.0
    debord_saillie_m: Optional[float] = None   # None = saillie continue
    # Joues (retours verticaux) de part et d'autre des baies.
    joue_m: float = 0.0
    joues_par_baie: float = 0.0            # 0 à 2, moyenne pondérée
    ecart_joue_m: float = 0.0              # joue → tableau de la baie
    # Store banne : même géométrie qu'une saillie, mais MOBILE.
    store_m: float = 0.0
    ecart_store_m: float = 0.0
    part_store: float = 0.0
    occultations: Optional[Tuple[Tuple[str, float], ...]] = None

    @property
    def a_une_saillie(self) -> bool:
        return self.saillie_m > 0.0 and self.part_saillie > 0.0

    @property
    def a_des_joues(self) -> bool:
        return self.joue_m > 0.0 and self.joues_par_baie > 0.0

    @property
    def a_un_store(self) -> bool:
        return self.store_m > 0.0 and self.part_store > 0.0

    def part_occultation(self, type_occultation: str) -> float:
        if not self.occultations:
            return 0.0
        return sum(p for t, p in self.occultations if t == type_occultation)


@dataclass(frozen=True)
class ProtectionsFacade:
    """Les protections d'une façade dessinée, niveau par niveau (index 0 = RdC).

    `vitrages_m2` : le vitrage DESSINÉ par type (clés de GLASS_PROPERTIES),
    None = celui du bâtiment. La façade porte son propre vitrage parce que
    deux façades d'un même immeuble n'ont pas toujours été rénovées ensemble.
    """

    niveaux: Tuple[Optional[ProtectionNiveau], ...]
    vitrages_m2: Optional[Tuple[Tuple[str, float], ...]] = None
    # Mémoire des facteurs horaires : plusieurs appels par heure et par façade
    # demandent le même soleil. Hors comparaison et hors hachage.
    _memo: Dict = field(default_factory=dict, compare=False, repr=False)

    @property
    def vitrage_total_m2(self) -> float:
        """Le vitrage dessiné : par niveau s'il est donné, sinon par type."""
        total = sum(n.vitrage_m2 for n in self.niveaux if n is not None)
        if total <= 0.0 and self.vitrages_m2:
            total = sum(a for _, a in self.vitrages_m2)
        return total

    def aires_par_niveau(self) -> Tuple[float, ...]:
        """Le vitrage dessiné de chaque niveau. Un appelant qui ne donne que
        son mélange de vitrages le voit réparti également sur les niveaux :
        seul le total compte alors (U et g), aucune protection ne pèse."""
        aires = tuple(n.vitrage_m2 if n is not None else 0.0 for n in self.niveaux)
        if sum(aires) <= 0.0 and self.vitrages_m2 and self.niveaux:
            part = self.vitrage_total_m2 / len(self.niveaux)
            return tuple(part for _ in self.niveaux)
        return aires

    @property
    def occultations_declarees(self) -> bool:
        """Le dessin a-t-il DIT quelque chose des occultations ?"""
        return any(n is not None and n.occultations is not None for n in self.niveaux)

    @property
    def a_un_store(self) -> bool:
        return any(n is not None and n.a_un_store for n in self.niveaux)

    @property
    def a_des_masques_fixes(self) -> bool:
        return any(n is not None and (n.a_une_saillie or n.a_des_joues) for n in self.niveaux)

    def facteurs_fixes(self, facade_azimuth_deg: float, sun_elevation_deg: float,
                       sun_azimuth_deg: float) -> Tuple[Tuple[float, float, float], ...]:
        """(direct, ciel, sol) par niveau, pour les masques FIXES (mémorisé)."""
        cle = (facade_azimuth_deg, sun_elevation_deg, sun_azimuth_deg)
        valeur = self._memo.get(cle)
        if valeur is None:
            if len(self._memo) > 60000:
                self._memo.clear()
            valeur = tuple(
                facteurs_niveau(n, facade_azimuth_deg, sun_elevation_deg, sun_azimuth_deg)
                if n is not None else (1.0, 1.0, 1.0)
                for n in self.niveaux)
            self._memo[cle] = valeur
        return valeur


def construire_protections(shading_by_floor: Optional[Sequence],
                           glazing_by_type_m2: Optional[Dict[str, float]],
                           n_floors: int, nom: str = "shading_by_floor"
                           ) -> Optional[ProtectionsFacade]:
    """Valide le contrat d'entrée et rend la forme interne, ou None.

    UN REFUS SE VOIT, UNE APPROXIMATION NON. Un tableau d'une autre hauteur
    que le bâtiment décalerait tous les niveaux ; une part d'occultation qui
    dépasse 1 compterait 2 fois la même vitre. Les 2 cas lèvent ici, avant le
    calcul, plutôt que de rendre un chiffre plausible.
    """
    if shading_by_floor is None and glazing_by_type_m2 is None:
        return None

    vitrages = None
    if glazing_by_type_m2 is not None:
        if not isinstance(glazing_by_type_m2, dict) or not glazing_by_type_m2:
            raise ValueError("glazing_by_type_m2 : un dictionnaire {type de vitrage: m2} non vide")
        inconnus = sorted(set(glazing_by_type_m2) - set(GLASS_PROPERTIES))
        if inconnus:
            raise ValueError(f"glazing_by_type_m2 : vitrages inconnus du moteur {inconnus}")
        if any(float(v) < 0 for v in glazing_by_type_m2.values()):
            raise ValueError("glazing_by_type_m2 : les surfaces sont positives ou nulles")
        if sum(float(v) for v in glazing_by_type_m2.values()) <= 0:
            raise ValueError("glazing_by_type_m2 : aucune surface vitrée")
        vitrages = tuple(sorted((str(k), float(v)) for k, v in glazing_by_type_m2.items()
                                if float(v) > 0))

    niveaux: List[Optional[ProtectionNiveau]] = []
    if shading_by_floor is not None:
        if len(shading_by_floor) != n_floors:
            raise ValueError(f"{nom} : {len(shading_by_floor)} niveaux pour n_floors={n_floors}")
        for k, brut in enumerate(shading_by_floor):
            if brut is None:
                niveaux.append(None)
                continue
            d = brut if isinstance(brut, dict) else brut.model_dump()
            niveaux.append(_niveau_depuis(d, f"{nom}[{k}]"))
        if not any(n is not None and n.vitrage_m2 > 0 for n in niveaux):
            raise ValueError(f"{nom} : aucun niveau ne porte de vitrage, rien à protéger")
    else:
        niveaux = [None] * n_floors
    return ProtectionsFacade(niveaux=tuple(niveaux), vitrages_m2=vitrages)


def _borne(d: dict, cle: str, defaut, mini: float, maxi: float, ou: str):
    v = d.get(cle, defaut)
    if v is None:
        return defaut
    v = float(v)
    if not (mini <= v <= maxi) or v != v:
        raise ValueError(f"{ou}.{cle} = {v:g} hors de [{mini:g}, {maxi:g}]")
    return v


def _niveau_depuis(d: dict, ou: str) -> ProtectionNiveau:
    occultations = d.get("blinds")
    occ: Optional[Tuple[Tuple[str, float], ...]] = None
    if occultations is not None:
        if not isinstance(occultations, dict):
            raise ValueError(f"{ou}.blinds : un dictionnaire {{type: part}}")
        inconnus = sorted(set(occultations) - set(TYPES_OCCULTATION))
        if inconnus:
            raise ValueError(f"{ou}.blinds : occultations inconnues {inconnus} "
                             f"(attendu : {', '.join(TYPES_OCCULTATION)})")
        parts = {t: float(p) for t, p in occultations.items()}
        if any(not (0.0 <= p <= 1.0) for p in parts.values()):
            raise ValueError(f"{ou}.blinds : chaque part tient entre 0 et 1")
        # Tolérance d'ARRONDI seulement : les parts arrivent arrondies à 10⁻⁴.
        if sum(parts.values()) > 1.0 + 1e-3:
            raise ValueError(f"{ou}.blinds : les parts totalisent {sum(parts.values()):.3f} > 1 : "
                             "une même vitre compterait 2 fois")
        occ = tuple(sorted((t, p) for t, p in parts.items() if p > 0.0))
    debord = d.get("overhang_extension_m")
    return ProtectionNiveau(
        vitrage_m2=_borne(d, "glazing_m2", 0.0, 0.0, 1e6, ou),
        hauteur_baie_m=_borne(d, "window_height_m", HAUTEUR_BAIE_DEFAUT_M, 0.1, 12.0, ou),
        largeur_baie_m=_borne(d, "window_width_m", LARGEUR_BAIE_DEFAUT_M, 0.1, 60.0, ou),
        saillie_m=_borne(d, "overhang_depth_m", 0.0, 0.0, 5.0, ou),
        ecart_saillie_m=_borne(d, "overhang_gap_m", 0.0, 0.0, 12.0, ou),
        part_saillie=_borne(d, "overhang_coverage", 0.0, 0.0, 1.0, ou),
        debord_saillie_m=(None if debord is None
                          else _borne(d, "overhang_extension_m", None, 0.0, 1e3, ou)),
        joue_m=_borne(d, "fin_depth_m", 0.0, 0.0, 5.0, ou),
        joues_par_baie=_borne(d, "fin_count", 0.0, 0.0, 2.0, ou),
        ecart_joue_m=_borne(d, "fin_gap_m", 0.0, 0.0, 5.0, ou),
        store_m=_borne(d, "awning_depth_m", 0.0, 0.0, 5.0, ou),
        ecart_store_m=_borne(d, "awning_gap_m", 0.0, 0.0, 12.0, ou),
        part_store=_borne(d, "awning_coverage", 0.0, 0.0, 1.0, ou),
        occultations=occ,
    )


# ═══════════════════════════════════════════════════════════════════════════
# LA GÉOMÉTRIE SOLAIRE DE LA FAÇADE
# ═══════════════════════════════════════════════════════════════════════════

def angles_facade(facade_azimuth_deg: float, sun_elevation_deg: float,
                  sun_azimuth_deg: float) -> Optional[Tuple[float, float, float]]:
    """(tan Ω, |tan γ|, k), ou None quand le soleil n'éclaire pas la façade.

    γ, angle d'ombre HORIZONTAL : écart d'azimut soleil / normale.
    Ω, angle de PROFIL (d'ombre vertical) : tan Ω = tan α / cos γ. C'est lui
    qui règle la profondeur de l'ombre d'une saillie sur la façade.
    k = |tan γ| / tan Ω = |sin γ| / tan α : le glissement LATÉRAL de l'ombre
    par mètre de profondeur sous la sous-face.
    """
    if sun_elevation_deg <= 0.0:
        return None
    gamma = (sun_azimuth_deg - facade_azimuth_deg + 180.0) % 360.0 - 180.0
    if abs(gamma) >= 90.0:
        return None
    g_rad = math.radians(gamma)
    tan_alpha = math.tan(math.radians(min(sun_elevation_deg, 89.999)))
    cos_g = math.cos(g_rad)
    tan_profil = tan_alpha / cos_g
    k = abs(math.sin(g_rad)) / tan_alpha if tan_alpha > 0 else float("inf")
    return tan_profil, abs(math.tan(g_rad)), k


def fraction_ombre_saillie(tan_profil: float, k_lateral: float, saillie_m: float,
                           ecart_m: float, hauteur_m: float, largeur_m: float,
                           debord_m: Optional[float]) -> float:
    """Part d'une baie (hauteur × largeur) à l'ombre d'une saillie horizontale.

    EN ISO 52016-1 annexe F (§ F.3) et ASHRAE : l'arête avant d'une saillie
    de profondeur P projette son ombre à P·tan Ω sous la sous-face. La baie
    commence à `ecart_m` sous la sous-face : la hauteur ombrée vaut
    P·tan Ω − écart, bornée à la baie.

    LARGEUR FINIE. Une casquette de la largeur de la fenêtre ne l'ombre plus
    en entier quand le soleil vient de côté : son ombre glisse de k·y à la
    profondeur y. On intègre donc la largeur ombrée W − (k·y − débord)⁺ sur
    la hauteur ombrée : forme fermée, exacte pour une saillie rectangulaire
    débordant de `debord_m` de chaque côté. `debord_m` None : saillie
    continue (un balcon filant), aucun effet de bord.
    """
    if saillie_m <= 0.0 or hauteur_m <= 0.0 or largeur_m <= 0.0 or tan_profil <= 0.0:
        return 0.0
    y1 = ecart_m
    y2 = min(ecart_m + hauteur_m, saillie_m * tan_profil)
    if y2 <= y1:
        return 0.0
    if debord_m is None or k_lateral <= 0.0:
        return (y2 - y1) / hauteur_m
    if not math.isfinite(k_lateral):
        return 0.0
    w, e, k = largeur_m, debord_m, k_lateral
    ya = e / k                  # en dessous, l'ombre couvre toute la largeur
    yb = (e + w) / k            # au-delà, elle a quitté la baie
    aire = 0.0
    a, b = y1, min(y2, ya)
    if b > a:
        aire += w * (b - a)
    a, b = max(y1, ya), min(y2, yb)
    if b > a:
        aire += (w + e) * (b - a) - k * (b * b - a * a) / 2.0
    return max(0.0, min(1.0, aire / (w * hauteur_m)))


def fraction_ombre_joues(tan_gamma_abs: float, joue_m: float, ecart_m: float,
                         largeur_m: float, joues_par_baie: float) -> float:
    """Part d'une baie à l'ombre de ses joues (retours verticaux).

    EN ISO 52016-1 annexe F (§ F.3) : la joue du côté du soleil ombre une
    bande de largeur P_joue·|tan γ| − écart. Celle de l'autre côté n'ombre
    rien en direct.

    LE CÔTÉ N'EST PAS TRANSMIS, SEULEMENT LE NOMBRE. Avec deux joues, l'une
    est toujours du côté du soleil. Avec une seule, elle l'est une heure sur
    deux en moyenne : on prend la moitié. L'énergie journalière est juste ;
    ce qui est approché, c'est l'heure (une joue à l'ouest ombre l'après-midi,
    le plus chaud).
    """
    if joue_m <= 0.0 or joues_par_baie <= 0.0 or largeur_m <= 0.0:
        return 0.0
    bande = min(largeur_m, max(0.0, joue_m * tan_gamma_abs - ecart_m))
    return min(1.0, joues_par_baie / 2.0) * bande / largeur_m


def vue_bloquee(profondeur_m: float, ecart_m: float, cote_m: float) -> float:
    """Facteur de vue d'une baie vers une saillie qui la borde (2D, Hottel).

    Cordes croisées : F = [(AC + BD) − (AD + BC)] / (2·AB), avec la baie AB,
    la saillie CD née du mur à `ecart_m` de la baie. Pour une casquette,
    AB est la hauteur ; pour une joue, la largeur (même topologie, tournée
    d'un quart de tour). Limites vérifiées : P → ∞ sans écart donne 0,5 (la
    moitié haute du champ), P = 0 donne 0.
    """
    if profondeur_m <= 0.0 or cote_m <= 0.0:
        return 0.0
    f = (cote_m + math.hypot(profondeur_m, ecart_m)
         - math.hypot(profondeur_m, cote_m + ecart_m)) / (2.0 * cote_m)
    return max(0.0, min(0.5, f))


def facteurs_niveau(n: ProtectionNiveau, facade_azimuth_deg: float,
                    sun_elevation_deg: float, sun_azimuth_deg: float
                    ) -> Tuple[float, float, float]:
    """(direct, ciel, sol) : ce que les baies du niveau reçoivent encore.

    DIRECT = (1 − part·f_saillie)·(1 − f_joues), EN ISO 13790 § 11.4.4 :
    les facteurs d'ombrage d'obstacles se multiplient. C'est exact pour une
    bande horizontale et une bande verticale (l'aire de leur union vaut
    a + b − a·b).
    CIEL : la saillie masque la part 2·F de la demi-sphère haute (une baie
    verticale voit le ciel pour moitié), les joues la part n·F de tout le
    champ.
    SOL (et bande d'horizon de Perez) : seules les joues le masquent, une
    saillie au-dessus ne cache pas le sol.
    """
    direct = 1.0
    angles = angles_facade(facade_azimuth_deg, sun_elevation_deg, sun_azimuth_deg)
    if angles is not None:
        tan_profil, tan_gamma, k = angles
        if n.a_une_saillie:
            direct *= 1.0 - n.part_saillie * fraction_ombre_saillie(
                tan_profil, k, n.saillie_m, n.ecart_saillie_m,
                n.hauteur_baie_m, n.largeur_baie_m, n.debord_saillie_m)
        if n.a_des_joues:
            direct *= 1.0 - fraction_ombre_joues(
                tan_gamma, n.joue_m, n.ecart_joue_m, n.largeur_baie_m, n.joues_par_baie)
    ciel = 1.0
    sol = 1.0
    if n.a_une_saillie:
        ciel *= 1.0 - 2.0 * n.part_saillie * vue_bloquee(
            n.saillie_m, n.ecart_saillie_m, n.hauteur_baie_m)
    if n.a_des_joues:
        joues = 1.0 - min(1.0, n.joues_par_baie * vue_bloquee(
            n.joue_m, n.ecart_joue_m, n.largeur_baie_m))
        ciel *= joues
        sol *= joues
    return (max(0.0, min(1.0, direct)), max(0.0, min(1.0, ciel)), max(0.0, min(1.0, sol)))


def facteurs_store(n: ProtectionNiveau, facade_azimuth_deg: float,
                   sun_elevation_deg: float, sun_azimuth_deg: float
                   ) -> Tuple[float, float]:
    """(direct, ciel) sous un store banne DÉPLOYÉ : une saillie de toile.

    La toile transmet `TAU_TOILE_STORE` du rayonnement qui la traverse.
    Le store est supposé déborder de la baie (pas d'effet de bord).
    """
    if not n.a_un_store:
        return 1.0, 1.0
    direct = 1.0
    angles = angles_facade(facade_azimuth_deg, sun_elevation_deg, sun_azimuth_deg)
    if angles is not None:
        tan_profil, _, k = angles
        direct = 1.0 - n.part_store * (1.0 - TAU_TOILE_STORE) * fraction_ombre_saillie(
            tan_profil, k, n.store_m, n.ecart_store_m, n.hauteur_baie_m,
            n.largeur_baie_m, None)
    ciel = 1.0 - 2.0 * n.part_store * (1.0 - TAU_TOILE_STORE) * vue_bloquee(
        n.store_m, n.ecart_store_m, n.hauteur_baie_m)
    return max(0.0, min(1.0, direct)), max(0.0, min(1.0, ciel))


# ═══════════════════════════════════════════════════════════════════════════
# LE VITRAGE, L'OCCULTATION, LA NUIT
# ═══════════════════════════════════════════════════════════════════════════

def u_g_vitrage(glass_type: str) -> Tuple[float, float]:
    """(U, g) d'un type de vitrage, lus dans la table commune du moteur."""
    p = GLASS_PROPERTIES[glass_type]
    return float(p["u_value"]), float(p["g_factor"])


def fractions_vitrage(protections: Optional[ProtectionsFacade],
                      glass_type_batiment: str) -> Tuple[Tuple[str, float], ...]:
    """Les types de vitrage de la façade dessinée et leur part d'aire."""
    if protections is None or not protections.vitrages_m2:
        return ((glass_type_batiment, 1.0),)
    total = sum(a for _, a in protections.vitrages_m2)
    return tuple((t, a / total) for t, a in protections.vitrages_m2)


def u_g_moyens(fractions: Iterable[Tuple[str, float]]) -> Tuple[float, float]:
    """U et g pondérés par l'aire : exacts pour la transmission (H = Σ U·A) et
    pour le solaire (Σ g·A·I, même irradiance sur la façade)."""
    u = g = 0.0
    for t, part in fractions:
        ut, gt = u_g_vitrage(t)
        u += part * ut
        g += part * gt
    return u, g


def delta_u_nuit(u_vitrage: float, r_volet: float) -> float:
    """ΔU d'une fenêtre dont le volet se ferme : U − 1/(1/U + R)."""
    if r_volet <= 0.0 or u_vitrage <= 0.0:
        return 0.0
    return u_vitrage - 1.0 / (1.0 / u_vitrage + r_volet)


def delta_u_nuit_melange(fractions: Iterable[Tuple[str, float]], r_volet: float) -> float:
    """ΔU moyen d'un mélange de vitrages : calculé type par type, puis pondéré.
    ΔU n'est pas linéaire en U, la moyenne des U tromperait."""
    return sum(part * delta_u_nuit(u_g_vitrage(t)[0], r_volet) for t, part in fractions)


def facteur_fc(type_occultation: str, g_vitrage: float, u_vitrage: float) -> float:
    """Fc d'une occultation manœuvrée (1 = rien n'est arrêté), EN 13363-1.

    Fc = (1 − part fermée) + part fermée · g_tot/g : un volet roulant baissé
    aux 3 quarts laisse le quart haut de la vitre au soleil.
    """
    p = PROPRIETES_OCCULTATION[type_occultation]
    if g_vitrage <= 0.0:
        return 1.0
    tau, rho = p["tau"], p["rho"]
    alpha = max(0.0, 1.0 - tau - rho)
    u = min(max(u_vitrage, U_METHODE_SIMPLIFIEE_MIN_W_M2K), U_METHODE_SIMPLIFIEE_MAX_W_M2K)
    g = g_vitrage
    if p["exterieure"]:
        gg = 1.0 / (1.0 / u + 1.0 / G1_EXTERIEUR_W_M2K + 1.0 / G2_EXTERIEUR_W_M2K)
        g_tot = tau * g + alpha * gg / G2_EXTERIEUR_W_M2K + tau * (1.0 - g) * gg / G1_EXTERIEUR_W_M2K
    else:
        gg = 1.0 / (1.0 / u + 1.0 / G2_INTERIEUR_W_M2K)
        g_tot = g * (1.0 - g * rho - alpha * gg / G2_INTERIEUR_W_M2K)
    fc_ferme = max(0.0, min(1.0, g_tot / g))
    part = p["part_fermee"]
    return (1.0 - part) + part * fc_ferme


def r_nuit_moyenne(niveaux: Iterable[Tuple[ProtectionNiveau, float]]) -> float:
    """R nocturne moyen des occultations déclarées, pondéré par l'aire donnée."""
    num = den = 0.0
    for n, aire in niveaux:
        if aire <= 0.0:
            continue
        den += aire
        if n.occultations:
            num += aire * sum(p * R_NUIT_OCCULTATION.get(t, 0.0) for t, p in n.occultations)
    return num / den if den > 0 else 0.0


__all__ = [
    "TYPES_OCCULTATION", "PROPRIETES_OCCULTATION", "R_NUIT_OCCULTATION",
    "SEUIL_SOLEIL_MANUEL_W_M2", "ECART_INCONFORT_CHAUD_K", "TAU_TOILE_STORE",
    "ProtectionNiveau", "ProtectionsFacade", "construire_protections",
    "angles_facade", "fraction_ombre_saillie", "fraction_ombre_joues",
    "vue_bloquee", "facteurs_niveau", "facteurs_store", "u_g_vitrage",
    "fractions_vitrage", "u_g_moyens", "delta_u_nuit", "delta_u_nuit_melange",
    "facteur_fc", "r_nuit_moyenne",
]
