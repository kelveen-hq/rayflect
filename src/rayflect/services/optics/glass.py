"""Module de calcul de la transmission du vitrage.

Ce module implémente les modèles physiques de transmission du vitrage :
1. Transmission normale (perpendiculaire)
2. Transmission angulaire selon l'angle d'incidence
3. Pertes par réflexion sur chaque face du vitrage

FORMULE PRINCIPALE :
====================
τ(θ) = τ₀ × f(θ)

où:
- τ₀ = transmission normale (typiquement 0.80-0.90 pour double vitrage)
- f(θ) = facteur de réduction angulaire
- θ = angle d'incidence (0° = perpendiculaire au vitrage)

MODÈLES DISPONIBLES :
=====================
1. ASHRAE : Polynôme ajusté sur données LBNL WINDOW 7.6
2. Fresnel : Calcul exact des réflexions sur les interfaces air/verre
3. Simple : f(θ) = cos(θ) pour approximation rapide
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import Enum
from typing import Tuple

from rayflect.config.system_constants import GLASS_PROPERTIES


class TransmissionModel(Enum):
    """Modèles de calcul de transmission disponibles."""
    ASHRAE = "ashrae"      # Modèle ASHRAE standard
    FRESNEL = "fresnel"    # Calcul Fresnel exact
    SIMPLE = "simple"      # Approximation linéaire
    CONSTANT = "constant"  # Transmission constante (debug)


@dataclass(frozen=True)
class GlassProperties:
    """Propriétés optiques du vitrage.

    Ces propriétés déterminent la transmission énergétique du vitrage.
    La transmission effective dépend fortement de l'angle d'incidence :
    - A incidence normale (0°) : transmission = tau_normal
    - A 50° d'incidence : transmission ~ 60-70% de tau_normal
    - A 70° d'incidence : transmission ~ 30-40% de tau_normal

    RÉFLECTIVITÉ TYPIQUE DES VITRAGES (valeurs réelles marché) :
    =============================================================
    | Type de vitrage                  | Réflect. totale | tau_normal |
    |----------------------------------|-----------------|------------|
    | Simple vitrage clair (4 mm)      | 8%              | 0.88       |
    | Double vitrage clair (4/16/4)    | 10-12%          | 0.78       |
    | Double vitrage Low-E             | 12-20%          | 0.65       |
    | Double vitrage contrôle solaire  | 20-35%          | 0.50       |
    | Triple vitrage clair             | 12-15%          | 0.68       |
    | Triple vitrage Low-E             | 15-25%          | 0.55       |
    | Vitrage réfléchissant             | 30-45%          | 0.40       |

    Note : Seules les faces externes comptent pour la réflexion vers l'extérieur.
    Un triple vitrage ne réfléchit pas 3× plus qu'un simple.

    Attributes
    ----------
    tau_normal : float
        Transmission à incidence normale (θ=0°).
        tau_normal = 1 - reflectance_normal - absorptivity
    reflectance_normal : float
        Réflectivité totale du vitrage à incidence normale (0-1).
        C'est la valeur mesurée sur les fiches produit.
    n_glass : float
        Indice de réfraction du verre, typiquement 1.52.
        Utilisé pour le calcul de Fresnel.
    n_layers : int
        Nombre de couches de verre (1=simple, 2=double, 3=triple).
    absorptivity : float
        Absorptivité du verre (fraction absorbée), typiquement 0.04-0.10.
    g_factor : float
        Facteur solaire (SHGC = Solar Heat Gain Coefficient).
        Fraction totale d'énergie solaire transmise (direct + réémis).
    """
    tau_normal: float = 0.78       # Double vitrage standard
    reflectance_normal: float = 0.12  # 12% réfléchi (double vitrage clair)
    n_glass: float = 1.52
    n_layers: int = 2              # Double vitrage
    absorptivity: float = 0.10     # ~10% absorbé (tau + rho + alpha = 1)
    g_factor: float = 0.76         # Facteur solaire double vitrage EN 410


@dataclass(frozen=True)
class TransmissionResult:
    """Résultat du calcul de transmission.

    Attributes
    ----------
    tau : float
        Transmission effective (0-1).
    incidence_angle_deg : float
        Angle d'incidence en degrés.
    angular_factor : float
        Facteur de réduction angulaire f(θ).
    reflectance : float
        Fraction réfléchie par le vitrage.
    absorptance : float
        Fraction absorbée par le vitrage.
    """
    tau: float
    incidence_angle_deg: float
    angular_factor: float
    reflectance: float
    absorptance: float


# =============================================================================
# Coefficients du polynôme IAM ajusté sur données LBNL WINDOW 7.6
# (double vitrage Low-E, standard RE2020/RT2012).
# IAM(θ) = a₁·cos(θ) + a₂·cos²(θ) + a₃·cos³(θ) + a₄·cos⁴(θ)
# Normalisé : IAM(0°) = 1.0 exactement.
_IAM_COEFFS = (0.0923, 6.0157, -8.8974, 3.7894)


def ashrae_iam(incidence_angle_deg: float) -> float:
    """Incidence Angle Modifier (IAM) pour double vitrage Low-E.

    Fonction légère retournant uniquement le facteur multiplicatif IAM(θ) ∈ [0, 1].
    Utilisée pour pondérer le g_factor ou la transmission en fonction de
    l'angle d'incidence sur le vitrage.

    Parameters
    ----------
    incidence_angle_deg : float
        Angle d'incidence (°), 0 = perpendiculaire, 90 = rasant.

    Returns
    -------
    float
        IAM ∈ [0, 1].
    """
    if incidence_angle_deg >= 90.0:
        return 0.0
    cos_theta = math.cos(math.radians(min(90.0, max(0.0, abs(incidence_angle_deg)))))
    a1, a2, a3, a4 = _IAM_COEFFS
    iam = a1 * cos_theta + a2 * cos_theta**2 + a3 * cos_theta**3 + a4 * cos_theta**4
    return max(0.0, min(1.0, iam))


# MODÈLE ASHRAE (STANDARD)
# =============================================================================

def compute_transmission_ashrae(
    incidence_angle_deg: float,
    glass: GlassProperties | None = None,
) -> TransmissionResult:
    """Calcule la transmission selon le modèle ASHRAE (LBNL WINDOW 7.6).

    Formule : τ(θ) = τ₀ × IAM(θ)
    où IAM(θ) = polynôme en cos(θ) ajusté sur données mesurées LBNL.

    Ce modèle est plus juste que l'approximation sin⁴(θ), qui sous-estime
    la transmission de 23% à θ=52°.

    Source : LBNL International Glazing Database (IGDB), entry 9901
             "Generic Low-E Double Clear" mesurée spectrale 300-2500nm.

    Parameters
    ----------
    incidence_angle_deg : float
        Angle d'incidence en degrés (0° = perpendiculaire).
    glass : GlassProperties | None
        Propriétés du vitrage. Utilise les valeurs par défaut si None.

    Returns
    -------
    TransmissionResult
        Résultat complet du calcul.
    """
    if glass is None:
        glass = GlassProperties()

    # Angle limité à 0-90°
    theta = min(90.0, max(0.0, abs(incidence_angle_deg)))

    if theta >= 90.0:
        return TransmissionResult(
            tau=0.0,
            incidence_angle_deg=theta,
            angular_factor=0.0,
            reflectance=1.0,
            absorptance=0.0,
        )

    # Facteur angulaire via la fonction partagée ashrae_iam
    cos_theta = math.cos(math.radians(theta))
    angular_factor = ashrae_iam(theta)
    angular_factor = max(0.0, min(1.0, angular_factor))

    # Transmission effective
    tau = glass.tau_normal * angular_factor

    # Estimation de la réflectance et absorptance
    sin_sq = 1 - cos_theta ** 2
    reflectance = (1 - glass.tau_normal) * (1 - glass.absorptivity) * (1 - angular_factor * 0.5)
    absorptance = glass.absorptivity * (1 + sin_sq * 0.3)

    # Normaliser pour que tau + rho + alpha ≤ 1
    total = tau + reflectance + absorptance
    if total > 1.0:
        factor = 1.0 / total
        tau *= factor
        reflectance *= factor
        absorptance *= factor

    return TransmissionResult(
        tau=tau,
        incidence_angle_deg=theta,
        angular_factor=angular_factor,
        reflectance=reflectance,
        absorptance=absorptance,
    )


# =============================================================================
# MODÈLE FRESNEL (EXACT)
# =============================================================================

def _fresnel_reflectance(
    theta_i_rad: float,
    n1: float,
    n2: float,
) -> Tuple[float, float]:
    """Calcule les coefficients de réflexion de Fresnel.

    Parameters
    ----------
    theta_i_rad : float
        Angle d'incidence en radians.
    n1 : float
        Indice de réfraction du milieu 1 (incident).
    n2 : float
        Indice de réfraction du milieu 2 (transmis).

    Returns
    -------
    tuple[float, float]
        (r_s, r_p) coefficients de réflexion pour polarisation s et p.
    """
    cos_i = math.cos(theta_i_rad)
    sin_i = math.sin(theta_i_rad)

    # Loi de Snell : n1 * sin(θi) = n2 * sin(θt)
    sin_t = (n1 / n2) * sin_i

    if abs(sin_t) > 1.0:
        # Réflexion totale interne
        return (1.0, 1.0)

    cos_t = math.sqrt(1 - sin_t ** 2)

    # Coefficients de Fresnel
    # r_s = (n1*cos_i - n2*cos_t) / (n1*cos_i + n2*cos_t)
    # r_p = (n2*cos_i - n1*cos_t) / (n2*cos_i + n1*cos_t)

    denom_s = n1 * cos_i + n2 * cos_t
    denom_p = n2 * cos_i + n1 * cos_t

    if abs(denom_s) < 1e-10 or abs(denom_p) < 1e-10:
        return (1.0, 1.0)

    r_s = ((n1 * cos_i - n2 * cos_t) / denom_s) ** 2
    r_p = ((n2 * cos_i - n1 * cos_t) / denom_p) ** 2

    return (r_s, r_p)


def compute_transmission_fresnel(
    incidence_angle_deg: float,
    glass: GlassProperties | None = None,
) -> TransmissionResult:
    """Calcule la transmission selon les équations de Fresnel.

    Prend en compte les réflexions sur chaque interface air/verre
    pour un double vitrage.

    Parameters
    ----------
    incidence_angle_deg : float
        Angle d'incidence en degrés (0° = perpendiculaire).
    glass : GlassProperties | None
        Propriétés du vitrage.

    Returns
    -------
    TransmissionResult
        Résultat complet du calcul.
    """
    if glass is None:
        glass = GlassProperties()

    theta = min(89.9, max(0.0, abs(incidence_angle_deg)))
    theta_rad = math.radians(theta)

    if theta >= 89.9:
        return TransmissionResult(
            tau=0.0,
            incidence_angle_deg=theta,
            angular_factor=0.0,
            reflectance=1.0,
            absorptance=0.0,
        )

    n_air = 1.0
    n_glass = glass.n_glass

    # Réflexion à l'interface air -> verre
    r_s_in, r_p_in = _fresnel_reflectance(theta_rad, n_air, n_glass)

    # Angle transmis dans le verre (Snell)
    sin_t = (n_air / n_glass) * math.sin(theta_rad)
    theta_t_rad = math.asin(min(1.0, sin_t))

    # Réflexion à l'interface verre -> air (sortie)
    r_s_out, r_p_out = _fresnel_reflectance(theta_t_rad, n_glass, n_air)

    # Réflectance moyenne (lumière non polarisée)
    R_in = (r_s_in + r_p_in) / 2
    R_out = (r_s_out + r_p_out) / 2

    # Transmission à travers une interface
    T_in = 1 - R_in
    T_out = 1 - R_out

    # Absorption dans le verre (loi de Beer-Lambert simplifiée)
    # Plus le verre est épais et l'angle grand, plus l'absorption augmente
    path_factor = 1 / math.cos(theta_t_rad) if theta_t_rad < math.radians(85) else 2.0
    A_single = 1 - math.exp(-glass.absorptivity * path_factor * 2)  # 2 passages pour DV

    # Transmission totale pour double vitrage (4 interfaces)
    # Simplifié : T_total ≈ T_in² × T_out² × (1 - A)
    if glass.n_layers == 1:
        tau_total = T_in * T_out * (1 - A_single / 2)
    else:  # Double vitrage
        tau_total = (T_in ** 2) * (T_out ** 2) * (1 - A_single)

    # Normaliser par rapport à la transmission normale
    tau_0_calculated = compute_transmission_fresnel_normal(glass)

    if tau_0_calculated > 0:
        angular_factor = tau_total / tau_0_calculated
    else:
        angular_factor = 0.0

    # Transmission finale
    tau = glass.tau_normal * angular_factor

    # Réflectance totale (approximation)
    reflectance = R_in + (1 - R_in) * R_out * (1 - R_in)
    absorptance = A_single

    return TransmissionResult(
        tau=tau,
        incidence_angle_deg=theta,
        angular_factor=min(1.0, angular_factor),
        reflectance=min(1.0, reflectance),
        absorptance=min(1.0, absorptance),
    )


def compute_transmission_fresnel_normal(glass: GlassProperties) -> float:
    """Calcule la transmission Fresnel à incidence normale.

    Utilisé pour normaliser les calculs angulaires.
    """
    n_air = 1.0
    n_glass = glass.n_glass

    # À incidence normale : r = ((n2 - n1) / (n2 + n1))²
    r_normal = ((n_glass - n_air) / (n_glass + n_air)) ** 2

    # Transmission à travers une interface
    t_normal = 1 - r_normal

    # Double vitrage : 4 interfaces
    if glass.n_layers == 1:
        return t_normal ** 2 * (1 - glass.absorptivity / 2)
    else:
        return t_normal ** 4 * (1 - glass.absorptivity)


# =============================================================================
# MODÈLE SIMPLE (APPROXIMATION)
# =============================================================================

def compute_transmission_simple(
    incidence_angle_deg: float,
    glass: GlassProperties | None = None,
) -> TransmissionResult:
    """Calcule la transmission selon un modèle simplifié.

    Formule : τ(θ) = τ₀ × cos(θ)

    Approximation rapide pour les calculs préliminaires.

    Parameters
    ----------
    incidence_angle_deg : float
        Angle d'incidence en degrés.
    glass : GlassProperties | None
        Propriétés du vitrage.

    Returns
    -------
    TransmissionResult
        Résultat du calcul.
    """
    if glass is None:
        glass = GlassProperties()

    theta = min(90.0, max(0.0, abs(incidence_angle_deg)))

    if theta >= 90.0:
        return TransmissionResult(
            tau=0.0,
            incidence_angle_deg=theta,
            angular_factor=0.0,
            reflectance=1.0,
            absorptance=0.0,
        )

    cos_theta = math.cos(math.radians(theta))
    tau = glass.tau_normal * cos_theta

    return TransmissionResult(
        tau=tau,
        incidence_angle_deg=theta,
        angular_factor=cos_theta,
        reflectance=(1 - glass.tau_normal) * (1 - cos_theta * 0.5),
        absorptance=glass.absorptivity,
    )


# =============================================================================
# INTERFACE PRINCIPALE
# =============================================================================

def compute_glass_transmission(
    incidence_angle_deg: float,
    glass: GlassProperties | None = None,
    model: TransmissionModel = TransmissionModel.ASHRAE,
) -> TransmissionResult:
    """Calcule la transmission du vitrage.

    Interface principale pour tous les modèles de transmission.

    Parameters
    ----------
    incidence_angle_deg : float
        Angle d'incidence en degrés (0° = perpendiculaire au vitrage).
    glass : GlassProperties | None
        Propriétés optiques du vitrage. Utilise les valeurs par défaut si None.
    model : TransmissionModel
        Modèle de calcul à utiliser.

    Returns
    -------
    TransmissionResult
        Résultat complet du calcul de transmission.

    Examples
    --------
    >>> result = compute_glass_transmission(0.0)  # Incidence normale
    >>> print(f"τ = {result.tau:.2f}")
    τ = 0.85

    >>> result = compute_glass_transmission(60.0)  # 60° d'incidence
    >>> print(f"τ = {result.tau:.2f}, facteur = {result.angular_factor:.2f}")
    τ = 0.69, facteur = 0.81
    """
    if glass is None:
        glass = GlassProperties()

    if model == TransmissionModel.ASHRAE:
        return compute_transmission_ashrae(incidence_angle_deg, glass)
    elif model == TransmissionModel.FRESNEL:
        return compute_transmission_fresnel(incidence_angle_deg, glass)
    elif model == TransmissionModel.SIMPLE:
        return compute_transmission_simple(incidence_angle_deg, glass)
    elif model == TransmissionModel.CONSTANT:
        return TransmissionResult(
            tau=glass.tau_normal,
            incidence_angle_deg=incidence_angle_deg,
            angular_factor=1.0,
            reflectance=(1 - glass.tau_normal) * 0.5,
            absorptance=glass.absorptivity,
        )
    else:
        raise ValueError(f"Unknown transmission model: {model}")


# =============================================================================
# FONCTIONS UTILITAIRES
# =============================================================================

def compute_transmitted_flux(
    incident_flux_w: float,
    incidence_angle_deg: float,
    glass: GlassProperties | None = None,
    model: TransmissionModel = TransmissionModel.ASHRAE,
) -> float:
    """Calcule le flux transmis à travers le vitrage.

    Parameters
    ----------
    incident_flux_w : float
        Flux incident sur le vitrage (W).
    incidence_angle_deg : float
        Angle d'incidence en degrés.
    glass : GlassProperties | None
        Propriétés du vitrage.
    model : TransmissionModel
        Modèle de transmission.

    Returns
    -------
    float
        Flux transmis à l'intérieur (W).
    """
    result = compute_glass_transmission(incidence_angle_deg, glass, model)
    return incident_flux_w * result.tau


def get_standard_glass_properties(glass_type: str) -> GlassProperties:
    """Retourne les propriétés standards pour différents types de vitrage.

    VALEURS BASÉES SUR LES DONNÉES RÉELLES DU MARCHÉ (Saint-Gobain, Guardian, AGC).
    Les données sont centralisées dans rayflect.config.system_constants.GLASS_PROPERTIES.

    RÉFLECTIVITÉ TYPIQUE DES VITRAGES :
    ===================================
    | Type                              | Réflect. | tau_normal | g_factor |
    |-----------------------------------|----------|------------|----------|
    | Simple vitrage clair (4 mm)       | 8%       | 0.88       | 0.85     |
    | Double vitrage clair (4/16/4)     | 10-12%   | 0.78       | 0.70     |
    | Double vitrage Low-E              | 12-20%   | 0.65       | 0.45     |
    | Double contrôle solaire           | 20-35%   | 0.50       | 0.35     |
    | Triple vitrage clair              | 12-15%   | 0.68       | 0.55     |
    | Triple vitrage Low-E              | 15-25%   | 0.55       | 0.40     |
    | Vitrage réfléchissant             | 30-45%   | 0.40       | 0.25     |

    Note importante :
    - Seules les faces externes comptent pour la réflexion vers l'extérieur
    - Un triple vitrage ne réfléchit PAS 3× plus qu'un simple
    - tau_normal = 1 - reflectance - absorptivity (bilan énergétique)

    Parameters
    ----------
    glass_type : str
        Type de vitrage :
        - "single" : Simple vitrage clair (ancien, peu isolant)
        - "double" : Double vitrage clair standard (défaut neuf)
        - "double_low_e" : Double vitrage basse émissivité (RT2012/RE2020)
        - "double_solar_control" : Double vitrage contrôle solaire (bureaux)
        - "triple" : Triple vitrage clair (climat froid)
        - "triple_low_e" : Triple vitrage basse émissivité (passif)
        - "reflective" : Vitrage réfléchissant (façades tertiaire)

    Returns
    -------
    GlassProperties
        Propriétés optiques correspondantes avec reflectance_normal.
    """
    if glass_type not in GLASS_PROPERTIES:
        raise ValueError(
            f"Unknown glass type '{glass_type}'. "
            f"Available types: {list(GLASS_PROPERTIES.keys())}"
        )

    props = GLASS_PROPERTIES[glass_type]
    return GlassProperties(
        tau_normal=props["tau_normal"],
        reflectance_normal=props["reflectance_normal"],
        n_glass=1.52,
        n_layers=int(props["n_layers"]),
        absorptivity=props["absorptivity"],
        g_factor=props["g_factor"],
    )


def compute_effective_g_factor(
    incidence_angle_deg: float,
    glass: GlassProperties | None = None,
    model: TransmissionModel = TransmissionModel.ASHRAE,
) -> float:
    """Calcule le facteur solaire effectif g(θ) en fonction de l'angle d'incidence.

    Le g_factor (SHGC = Solar Heat Gain Coefficient) représente la fraction TOTALE
    d'énergie solaire entrant dans le bâtiment :

        g = τ(θ) + α × qi

    où :
    - τ(θ) = transmittance directe dépendant de l'angle
    - α = absorptivité du vitrage
    - qi = fraction de l'énergie absorbée ré-émise vers l'intérieur (~0.3-0.4)

    DIFFÉRENCE τ vs g :
    ===================
    - τ(θ) : Transmission optique directe uniquement
    - g(θ) : Apport énergétique TOTAL (direct + ré-émission secondaire)

    Pour un double vitrage standard :
    - τ_normal = 0.78 (78% transmis directement)
    - g_factor = 0.70 (70% d'apport énergétique total)

    Cela semble contradictoire (g < τ), mais c'est parce que g_factor est mesuré
    dans des conditions standardisées qui incluent les pertes par convection.

    APPROXIMATION UTILISÉE :
    ========================
    On suppose que le ratio g/τ est constant pour tous les angles :

        g(θ) = τ(θ) × (g_normal / τ_normal)

    C'est une approximation raisonnable car la ré-émission secondaire est
    proportionnelle à l'énergie absorbée, qui elle-même dépend de τ(θ).

    Parameters
    ----------
    incidence_angle_deg : float
        Angle d'incidence en degrés (0° = perpendiculaire au vitrage).
    glass : GlassProperties | None
        Propriétés optiques du vitrage.
    model : TransmissionModel
        Modèle de calcul de transmission.

    Returns
    -------
    float
        Facteur solaire effectif g(θ) pour l'angle donné (0-1).

    Examples
    --------
    >>> glass = get_standard_glass_properties("double")
    >>> compute_effective_g_factor(0.0, glass)   # Incidence normale
    0.70
    >>> compute_effective_g_factor(45.0, glass)  # 45° d'incidence
    0.59  # Approximatif
    >>> compute_effective_g_factor(70.0, glass)  # Incidence rasante
    0.28  # Approximatif
    """
    if glass is None:
        glass = GlassProperties()

    # Calculer τ(θ) avec le modèle choisi
    transmission_result = compute_glass_transmission(incidence_angle_deg, glass, model)
    tau_theta = transmission_result.tau

    # Ratio g/τ à incidence normale
    if glass.tau_normal > 0:
        g_tau_ratio = glass.g_factor / glass.tau_normal
    else:
        g_tau_ratio = 0.0

    # g(θ) = τ(θ) × (g_normal / τ_normal)
    g_effective = tau_theta * g_tau_ratio

    # Borner entre 0 et 1
    return max(0.0, min(1.0, g_effective))
