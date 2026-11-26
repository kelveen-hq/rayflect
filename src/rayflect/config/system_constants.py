"""Les constantes physiques par défaut du moteur.

Chaque valeur porte sa source. Les repères : [P] lu dans la source primaire, [S] repris d'une source qui la cite,
[R] résumé non relu, [D] déduit, [H] hypothèse sans mesure.

Ce fichier ne contient que de la physique du bâtiment et des protections solaires courantes. Les constantes
d'un produit particulier vivent dans le paquet de ce produit.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SystemConstants:
    """Les valeurs par défaut, modifiables par `dataclasses.replace`."""

    # --- Rayonnement diffus sur un plan ---
    diffuse_plane_offset_deg: float = 30.0
    """Angle entre la direction du flux diffus modélisé et le plan de façade (degrés).

    Le diffus horizontal est modélisé comme venant d'une direction unique à 30° du plan de façade,
    soit 60° de sa normale [H].
    """

    # --- Baie type ---
    window_height_standard_m: float = 1.80
    """Hauteur d'une baie type quand elle n'est pas dessinée (m) [H]."""

    window_area_per_shutter_m2: float = 2.55
    """Aire d'une baie type quand elle n'est pas dessinée (m²) : 1,50 m × 1,70 m [H]."""

    # --- Fermetures existantes ---
    r_shutter_default: float = 0.19
    """Résistance thermique additionnelle d'un volet roulant léger fermé (m².K/W).

    Volet roulant PVC, tablier de 12 mm au plus : règles Th-U, tableau 2 [S] ; EN ISO 10077-1.
    """

    # --- Consignes ---
    setpoint_heating_default_c: float = 19.0
    """Consigne de chauffage par défaut (°C) : RT2012, RE2020 [S]."""

    # --- Casquette ---
    casquette_depth_typical_m: float = 0.40
    """Profondeur d'une casquette courante (m) [H]."""

    # --- Brise-soleil orientable (BSO) ---
    bso_g_tot_closed: float = 0.04
    """Facteur solaire total, lames fermées, devant un double vitrage à couche (g du vitrage 0,50).

    Fourchette 0,02 à 0,05, valeur centrale 0,04 : EN 14501, tableau C.2 [S].
    """

    bso_g_tot_tilted_45: float = 0.10
    """Facteur solaire total, lames à 45°, devant un double vitrage à couche : EN 14501 [S]."""

    bso_frame_factor: float = 0.97
    """Transmission résiduelle, lames ouvertes : le cadre et les guides masquent environ 3 % de la baie [H]."""

    bso_irr_deploy_threshold_w_m2: float = 150.0
    """Éclairement de façade au-delà duquel un BSO automatique se baisse (W/m²).

    Gestion technique du bâtiment de classe B, typiquement 150 à 250 W/m² : EN 15232 [S].
    """

    bso_reference_pilotage: str = "manuel"
    """Pilotage du BSO de comparaison : « manuel », « saisonnier » ou « thermique »."""

    bso_existant_pilotage: str = "manuel"
    """Pilotage d'un BSO déjà posé sur le bâtiment : « manuel » ou « saisonnier »."""

    bso_manuel_seuil_soleil_direct_w_m2: float = 50.0
    """Éclairement direct sur la façade qui fait baisser la protection (W/m²).

    Reinhart 2004 (Lightswitch-2002) : direct de plus de 50 W/m² sur le plan de travail [S, Haldi et
    Robinson 2009] ; Inoue et al. 1988 : l'occlusion suit la pénétration du soleil au-delà de 12 à 58 W/m²
    directs sur la façade [S]. Fourchette 12 à 233 W/m² (Newsham 1994, global vertical [S]).
    """

    bso_manuel_ecart_chaud_k: float = 2.0
    """La pièce est « chaude » à la consigne de froid moins cet écart (K) [H]."""

    bso_manuel_heure_lever: int = 7
    """L'« arrivée » d'une occupation continue (santé, hôtel) : le matin, à cette heure [H]."""

    bso_manuel_logement_part_vide_journee: float = 0.5
    """Part des logements vides les jours ouvrés en journée : personne n'y baisse avant le retour [H].

    Ordre de grandeur des ménages dont tous les adultes travaillent hors du domicile ; non mesuré sur les
    protections solaires (aucune campagne française trouvée).
    """

    bso_manuel_logement_heures_absence: tuple = (8, 18)
    """Heures d'absence (de, à) des logements vidés en journée ouvrée [H]."""

    bso_manuel_g_tot_baisse: float = 0.10
    """Facteur solaire d'un BSO baissé à la main : lames laissées à 45° (EN 14501).

    Un occupant ne suit pas le soleil : ses lames restent au préréglage de la commande [H].
    """

    bso_manuel_comportements: tuple = (
        # nom, p baisse à l'arrivée, p baisse par heure de présence,
        # p relève à l'arrivée, p relève par heure de présence, déclencheur
        ("dynamique", 1.0, 1.0, 1.0, 0.0, "soleil"),
        ("probabiliste", 0.30, 0.18, 0.30, 0.05, "soleil"),
        ("chaleur", 0.50, 0.30, 0.50, 0.10, "soleil_et_chaud"),
    )
    """Les comportements des occupants qui manœuvrent (probabilités par occasion).

    « dynamique » : l'usager actif de Lightswitch-2002 (Reinhart 2004 [S]), relève chaque matin en arrivant
    et baisse dès le soleil direct.
    « probabiliste » : les modèles logit de Haldi et Robinson 2009 (LESO, Lausanne, 12 bureaux, 5 ans [P])
    ramenés à l'heure [D] : baisse à l'arrivée 0,14 à 0,47 selon l'éclairement (0,30 retenu), 0,18 par heure
    de présence ; relève à l'arrivée 0,30 ; en présence 0,03 à 0,28 par heure selon l'éclairement, 0,05
    retenu (Rea 1984 [P] : aucun effet de l'heure).
    « chaleur » : le logement, qui baisse contre la chaleur quand le soleil est sur la façade ;
    probabilités [H] (aucune mesure trouvée), calées pour qu'environ 35 % des protections soient fermées à
    30 °C (RENOPTIM, CSTB, été 2023 : plus de 60 % ouvertes [S]).
    """

    bso_manuel_parts_tertiaire: tuple = (
        ("dynamique", 0.15), ("probabiliste", 0.30),
        ("toujours_baisse", 0.25), ("jamais_baisse", 0.30),
    )
    """La population d'une façade tertiaire : part des baies par comportement.

    55 % de baies qui ne bougent presque jamais [D] : Estia 2014 (OFEN, 125 BSO dont 98 manuels, 1 an [P])
    41 % des BSO bougent moins d'une fois par semaine ; Kapsis et al. 2013 [R] 72 % jamais ; Inoue 1988 [S]
    jusqu'à 60 %. Partage entre baissés et relevés [H], calé sur l'occlusion mesurée : sud 65 % (Rea 1984 [P])
    à 74 % (Estia [P]), nord 15 à 25 % (Van Den Wymelenberg 2012 [R]).
    """

    bso_manuel_parts_logement: tuple = (
        ("chaleur", 0.35), ("toujours_baisse", 0.10), ("jamais_baisse", 0.55),
    )
    """La population d'une façade de logement : part des baies par comportement.

    RENOPTIM (CSTB, USH, PROFEEL, été 2023, 76 logements [S]) : à 30 °C dehors, plus de 60 % des protections
    restent ouvertes, le frein étant le besoin de lumière. Bennet et al. 2014 (Ottawa, 102 logements [P]) :
    25 logements sur 102 n'ont rien manœuvré en 6 jours. 10 % toujours baissés (intimité,
    rez-de-chaussée) [H].
    """

    # --- Pompe à chaleur ---
    hvac_cop_heating: float = 3.5
    """COP nominal d'une pompe à chaleur en chauffage [H]."""

    pac_cop_rated_temp_c: float = 7.0
    """Température extérieure de référence du COP nominal (°C) : EN 14825 [S]."""

    pac_cop_min_temp_c: float = -15.0
    """Température extérieure minimale de fonctionnement (°C). En dessous, appoint électrique, COP de 1."""

    pac_cop_at_minus7_factor: float = 0.57
    """COP à −7 °C rapporté au COP à +7 °C, pompe à chaleur sur air : fiches EHPA, EN 14825 condition D [S]."""

    pac_cop_at_minus15_factor: float = 0.37
    """COP à −15 °C rapporté au COP à +7 °C : fiches de 2 constructeurs (EN 14511), date de relevé non tracée [S]."""


SYSTEM_DEFAULTS = SystemConstants()


GLASS_PROPERTIES: dict[str, dict[str, float]] = {
    # tau_normal + reflectance_normal + absorptivity = 1 ; g_factor selon EN 410 ; u_value selon EN 673 (W/m².K).
    "single": {
        "tau_normal": 0.88, "reflectance_normal": 0.08, "absorptivity": 0.04,
        "g_factor": 0.87, "u_value": 5.8, "n_layers": 1,
    },
    "double": {
        "tau_normal": 0.78, "reflectance_normal": 0.12, "absorptivity": 0.10,
        "g_factor": 0.76, "u_value": 2.8, "n_layers": 2,
    },
    "double_high_transmission": {
        "tau_normal": 0.75, "reflectance_normal": 0.12, "absorptivity": 0.13,
        "g_factor": 0.68, "u_value": 1.1, "n_layers": 2,
    },
    "double_low_e": {
        "tau_normal": 0.65, "reflectance_normal": 0.18, "absorptivity": 0.17,
        "g_factor": 0.50, "u_value": 1.5, "n_layers": 2,
    },
    "double_solar_control": {
        "tau_normal": 0.50, "reflectance_normal": 0.30, "absorptivity": 0.20,
        "g_factor": 0.35, "u_value": 1.3, "n_layers": 2,
    },
    "triple": {
        "tau_normal": 0.68, "reflectance_normal": 0.14, "absorptivity": 0.18,
        "g_factor": 0.62, "u_value": 1.1, "n_layers": 3,
    },
    "triple_low_e": {
        "tau_normal": 0.55, "reflectance_normal": 0.22, "absorptivity": 0.23,
        "g_factor": 0.45, "u_value": 0.8, "n_layers": 3,
    },
    "reflective": {
        "tau_normal": 0.40, "reflectance_normal": 0.40, "absorptivity": 0.20,
        "g_factor": 0.25, "u_value": 1.8, "n_layers": 2,
    },
    "double_high_solar_gain": {
        "tau_normal": 0.72, "reflectance_normal": 0.10, "absorptivity": 0.18,
        "g_factor": 0.65, "u_value": 1.3, "n_layers": 2,
    },
    "triple_high_solar_gain": {
        "tau_normal": 0.60, "reflectance_normal": 0.14, "absorptivity": 0.26,
        "g_factor": 0.55, "u_value": 0.7, "n_layers": 3,
    },
    "triple_passivhaus_solar": {
        "tau_normal": 0.58, "reflectance_normal": 0.12, "absorptivity": 0.30,
        "g_factor": 0.52, "u_value": 0.5, "n_layers": 3,
    },
}
