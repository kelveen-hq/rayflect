"""
Calcul de position solaire avec gestion de l'azimut.

Ce module fournit des fonctions pour calculer la position du soleil
(elevation et azimut) et son effet sur une surface orientee.

Supporte deux methodes de calcul:
- Methode simplifiee (builtin) pour tests rapides
- Methode precise via pvlib (recommandee)

Conventions :
- Azimut : 0 deg = Nord, 90 deg = Est, 180 deg = Sud, 270 deg = Ouest
- Elevation : 0 deg = horizon, 90 deg = zenith
- Facade : azimut de la normale sortante (180 deg = facade Sud regardant vers le Sud)

Axes 2D (coupe verticale perpendiculaire a la facade) :
- X : distance depuis la facade (positif vers l'exterieur)
- Z : hauteur (positif vers le haut)
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime
from typing import Optional
from enum import Enum

# Import conditionnel de pvlib
try:
    import pvlib
    import pandas as pd
    HAS_PVLIB = True
except ImportError:
    HAS_PVLIB = False
    pvlib = None
    pd = None


# ============================================================================
# CONSTANTES
# ============================================================================

# Seuil d'élévation minimale pour considérer le soleil levé
MIN_ELEVATION_DEG = 0.5

# Angles typiques par rapport à la façade
FACADE_PERPENDICULAR_TOLERANCE_DEG = 5.0  # Soleil quasi-perpendiculaire à la façade

# Plage horaire de scan pour les calculs d'exposition
# Ces valeurs couvrent les heures de soleil possibles en Europe (latitudes 35-60°N)
SCAN_START_HOUR = 5   # Début du scan journalier
SCAN_END_HOUR = 22    # Fin du scan journalier

# Pas de temps par défaut pour les scans (minutes)
DEFAULT_SCAN_TIME_STEP_MINUTES = 10


class FacadeExposure(str, Enum):
    """Exposition de la façade par rapport au soleil.

    Basé sur l'angle d'incidence (0° = perpendiculaire à la façade, 90° = rasant).
    """
    NIGHT = "night"                 # Soleil couché
    BACK = "back"                   # Soleil derrière la façade (pas d'exposition)
    GRAZING = "grazing"             # Soleil rasant (incidence > 85°)
    PARTIAL = "partial"             # Exposition partielle (incidence 60-85°)
    DIRECT = "direct"               # Exposition directe (incidence 15-60°)
    PERPENDICULAR = "perpendicular" # Quasi-perpendiculaire (incidence < 15°)


# ============================================================================
# STRUCTURES DE DONNÉES
# ============================================================================

@dataclass(frozen=True)
class SolarPosition:
    """Position du soleil dans le ciel.

    Attributes:
        elevation_deg: Élévation au-dessus de l'horizon (°), 0-90
        azimuth_deg: Azimut (°), 0=N, 90=E, 180=S, 270=O
        is_daylight: True si le soleil est au-dessus de l'horizon
    """
    elevation_deg: float
    azimuth_deg: float
    is_daylight: bool = True

    def __post_init__(self) -> None:
        # Normaliser l'azimut dans [0, 360[
        object.__setattr__(self, 'azimuth_deg', self.azimuth_deg % 360)
        object.__setattr__(self, 'is_daylight', self.elevation_deg > MIN_ELEVATION_DEG)

    @property
    def zenith_deg(self) -> float:
        """Angle zénithal (90° - élévation)."""
        return 90.0 - self.elevation_deg

    @property
    def elevation_rad(self) -> float:
        """Élévation en radians."""
        return math.radians(self.elevation_deg)

    @property
    def azimuth_rad(self) -> float:
        """Azimut en radians."""
        return math.radians(self.azimuth_deg)

    def direction_3d(self) -> tuple[float, float, float]:
        """Vecteur unitaire pointant VERS le soleil (x=E, y=N, z=up).

        Returns:
            Tuple (x, y, z) avec x vers l'Est, y vers le Nord, z vers le haut
        """
        elev_rad = self.elevation_rad
        azi_rad = self.azimuth_rad

        # Azimut mesuré depuis le Nord, sens horaire
        # x = sin(azi) = composante Est
        # y = cos(azi) = composante Nord
        # z = sin(elev) = composante verticale
        cos_elev = math.cos(elev_rad)

        return (
            math.sin(azi_rad) * cos_elev,  # x: Est
            math.cos(azi_rad) * cos_elev,  # y: Nord
            math.sin(elev_rad),            # z: haut
        )


@dataclass(frozen=True)
class FacadeIncidence:
    """Incidence du soleil sur une façade orientée.

    Attributes:
        facade_azimuth_deg: Orientation de la façade (0=N, 180=S)
        solar_position: Position du soleil
        incidence_angle_deg: Angle d'incidence sur la façade (0=perpendiculaire)
        horizontal_angle_deg: Angle horizontal du soleil par rapport à la normale
        cosine_factor: cos(incidence), facteur d'irradiance directe
        exposure: Type d'exposition de la façade
        sun_2d_direction: Direction du soleil en 2D (x, z) dans le plan façade
    """
    facade_azimuth_deg: float
    solar_position: SolarPosition
    incidence_angle_deg: float
    horizontal_angle_deg: float
    cosine_factor: float
    exposure: FacadeExposure
    sun_2d_direction: tuple[float, float]  # (x, z) direction vers le soleil en 2D

    @property
    def is_exposed(self) -> bool:
        """La façade reçoit-elle du flux solaire direct ?"""
        return self.exposure not in (FacadeExposure.NIGHT, FacadeExposure.BACK)

    @property
    def effective_elevation_deg(self) -> float:
        """Élévation effective vue depuis la façade.

        Correspond à l'angle dans le plan vertical perpendiculaire à la façade.
        """
        if not self.is_exposed:
            return 0.0

        # L'élévation effective est l'arctangente de z/x dans le repère 2D
        x, z = self.sun_2d_direction
        if x <= 0:
            return 0.0
        return math.degrees(math.atan2(z, x))


# ============================================================================
# FONCTIONS DE CALCUL
# ============================================================================

def compute_solar_position(
    elevation_deg: float,
    azimuth_deg: float,
) -> SolarPosition:
    """Crée une position solaire à partir des angles.

    Args:
        elevation_deg: Élévation solaire (°)
        azimuth_deg: Azimut solaire (°), 0=N, 90=E, 180=S, 270=O

    Returns:
        SolarPosition validée
    """
    return SolarPosition(
        elevation_deg=max(0.0, elevation_deg),
        azimuth_deg=azimuth_deg % 360,
    )


def compute_facade_incidence(
    solar_position: SolarPosition,
    facade_azimuth_deg: float,
) -> FacadeIncidence:
    """Calcule l'incidence du soleil sur une façade orientée.

    Args:
        solar_position: Position du soleil
        facade_azimuth_deg: Orientation de la façade (0=N, 180=S)

    Returns:
        FacadeIncidence avec tous les paramètres calculés

    Example:
        >>> sun = SolarPosition(elevation_deg=45.0, azimuth_deg=180.0)  # Soleil plein Sud
        >>> incidence = compute_facade_incidence(sun, facade_azimuth_deg=180.0)  # Façade Sud
        >>> print(f"Angle: {incidence.incidence_angle_deg:.1f}°")
        Angle: 45.0°
    """
    facade_azimuth_deg = facade_azimuth_deg % 360

    # Nuit
    if not solar_position.is_daylight:
        return FacadeIncidence(
            facade_azimuth_deg=facade_azimuth_deg,
            solar_position=solar_position,
            incidence_angle_deg=90.0,
            horizontal_angle_deg=0.0,
            cosine_factor=0.0,
            exposure=FacadeExposure.NIGHT,
            sun_2d_direction=(0.0, 0.0),
        )

    # Angle horizontal entre le soleil et la normale de la façade
    # La normale de la façade pointe vers facade_azimuth_deg
    delta_azimuth = solar_position.azimuth_deg - facade_azimuth_deg

    # Normaliser dans [-180, 180]
    while delta_azimuth > 180:
        delta_azimuth -= 360
    while delta_azimuth < -180:
        delta_azimuth += 360

    horizontal_angle_deg = delta_azimuth

    # Si |delta_azimuth| > 90°, le soleil est derrière la façade
    if abs(horizontal_angle_deg) > 90:
        return FacadeIncidence(
            facade_azimuth_deg=facade_azimuth_deg,
            solar_position=solar_position,
            incidence_angle_deg=90.0,
            horizontal_angle_deg=horizontal_angle_deg,
            cosine_factor=0.0,
            exposure=FacadeExposure.BACK,
            sun_2d_direction=(0.0, 0.0),
        )

    # Calcul de l'angle d'incidence 3D
    # cos(incidence) = cos(élévation) × cos(delta_azimuth)
    elev_rad = solar_position.elevation_rad
    horiz_rad = math.radians(horizontal_angle_deg)

    cos_incidence = math.cos(elev_rad) * math.cos(horiz_rad)
    cos_incidence = max(0.0, min(1.0, cos_incidence))

    incidence_angle_deg = math.degrees(math.acos(cos_incidence))

    # Direction 2D du soleil dans le plan vertical de la façade
    # x = composante horizontale perpendiculaire à la façade (vers l'extérieur)
    # z = composante verticale
    cos_elev = math.cos(elev_rad)
    sin_elev = math.sin(elev_rad)
    cos_horiz = math.cos(horiz_rad)

    # Projection sur le plan perpendiculaire à la façade
    x_component = cos_elev * cos_horiz  # Distance depuis la façade
    z_component = sin_elev              # Hauteur

    # Normaliser le vecteur 2D
    norm = math.sqrt(x_component**2 + z_component**2)
    if norm > 0:
        sun_2d = (x_component / norm, z_component / norm)
    else:
        sun_2d = (0.0, 0.0)

    # Déterminer le type d'exposition
    # incidence_angle_deg: 0° = soleil perpendiculaire à la façade, 90° = rasant
    if incidence_angle_deg > 85:
        exposure = FacadeExposure.GRAZING       # Soleil quasi-parallèle à la façade
    elif incidence_angle_deg > 60:
        exposure = FacadeExposure.PARTIAL       # Exposition partielle
    elif incidence_angle_deg > 15:
        exposure = FacadeExposure.DIRECT        # Exposition directe
    else:
        exposure = FacadeExposure.PERPENDICULAR # Quasi-perpendiculaire à la façade

    return FacadeIncidence(
        facade_azimuth_deg=facade_azimuth_deg,
        solar_position=solar_position,
        incidence_angle_deg=incidence_angle_deg,
        horizontal_angle_deg=horizontal_angle_deg,
        cosine_factor=cos_incidence,
        exposure=exposure,
        sun_2d_direction=sun_2d,
    )


def compute_effective_sun_elevation(
    solar_position: SolarPosition,
    facade_azimuth_deg: float,
) -> float:
    """Calcule l'élévation solaire effective vue depuis une façade.

    L'élévation effective est l'angle dans le plan vertical perpendiculaire
    à la façade. C'est l'angle utilisé pour les calculs en coupe 2D.

    Args:
        solar_position: Position du soleil
        facade_azimuth_deg: Orientation de la façade (°)

    Returns:
        Élévation effective (°), 0 si façade non exposée

    Example:
        >>> sun = SolarPosition(elevation_deg=45.0, azimuth_deg=135.0)  # Soleil Sud-Est
        >>> elev = compute_effective_sun_elevation(sun, facade_azimuth_deg=180.0)  # Façade Sud
        >>> print(f"Élévation effective: {elev:.1f}°")  # Plus haute car soleil de côté
    """
    incidence = compute_facade_incidence(solar_position, facade_azimuth_deg)
    return incidence.effective_elevation_deg


def compute_sun_direction_2d(
    solar_position: SolarPosition,
    facade_azimuth_deg: float,
) -> tuple[float, float]:
    """Calcule la direction 2D du soleil dans le plan vertical de la façade.

    Args:
        solar_position: Position du soleil
        facade_azimuth_deg: Orientation de la façade (°)

    Returns:
        Tuple (x, z) : vecteur unitaire direction vers le soleil
        - x : composante perpendiculaire à la façade (positif vers l'extérieur)
        - z : composante verticale (positif vers le haut)
        - (0, 0) si façade non exposée

    Note:
        Pour obtenir la direction d'incidence (rayons VERS la façade),
        inverser le signe : incident = (-x, -z)
    """
    incidence = compute_facade_incidence(solar_position, facade_azimuth_deg)
    return incidence.sun_2d_direction


def is_facade_exposed(
    solar_position: SolarPosition,
    facade_azimuth_deg: float,
) -> bool:
    """Vérifie si une façade est exposée au soleil direct.

    Args:
        solar_position: Position du soleil
        facade_azimuth_deg: Orientation de la façade (°)

    Returns:
        True si la façade reçoit du flux solaire direct
    """
    incidence = compute_facade_incidence(solar_position, facade_azimuth_deg)
    return incidence.is_exposed


def compute_dni_on_facade(
    dni_w_m2: float,
    solar_position: SolarPosition,
    facade_azimuth_deg: float,
) -> float:
    """Calcule le DNI reçu par une façade verticale.

    Args:
        dni_w_m2: Irradiance directe normale (W/m²)
        solar_position: Position du soleil
        facade_azimuth_deg: Orientation de la façade (°)

    Returns:
        DNI sur la façade (W/m²)
    """
    incidence = compute_facade_incidence(solar_position, facade_azimuth_deg)
    return dni_w_m2 * incidence.cosine_factor


def estimate_sun_position_simple(
    hour: float,
    day_of_year: int,
    latitude_deg: float,
) -> SolarPosition:
    """Estime la position solaire (méthode simplifiée).

    Approximation pour tests et estimations rapides.
    Pour des calculs précis, utiliser pvlib.

    Args:
        hour: Heure solaire (0-24)
        day_of_year: Jour de l'année (1-365)
        latitude_deg: Latitude (°)

    Returns:
        Position solaire approximative
    """
    # Déclinaison solaire (approximation)
    declination_rad = math.radians(23.45 * math.sin(math.radians(360 * (284 + day_of_year) / 365)))

    # Angle horaire (15° par heure, 0 à midi solaire)
    hour_angle_rad = math.radians(15 * (hour - 12))

    lat_rad = math.radians(latitude_deg)

    # Élévation
    sin_elevation = (
        math.sin(lat_rad) * math.sin(declination_rad) +
        math.cos(lat_rad) * math.cos(declination_rad) * math.cos(hour_angle_rad)
    )
    elevation_deg = math.degrees(math.asin(max(-1, min(1, sin_elevation))))

    # Azimut (approximation)
    if elevation_deg > 0:
        cos_azimuth = (
            math.sin(declination_rad) - math.sin(lat_rad) * sin_elevation
        ) / (math.cos(lat_rad) * math.cos(math.radians(elevation_deg)))
        cos_azimuth = max(-1, min(1, cos_azimuth))
        azimuth_deg = math.degrees(math.acos(cos_azimuth))

        if hour > 12:
            azimuth_deg = 360 - azimuth_deg
    else:
        azimuth_deg = 0.0

    return SolarPosition(
        elevation_deg=max(0, elevation_deg),
        azimuth_deg=azimuth_deg,
    )


# ============================================================================
# CALCUL PRECIS AVEC PVLIB
# ============================================================================

def is_pvlib_available() -> bool:
    """Verifie si pvlib est disponible pour calculs precis."""
    return HAS_PVLIB


def compute_sun_position_pvlib(
    timestamp: datetime,
    latitude_deg: float,
    longitude_deg: float,
    altitude_m: float = 0.0,
) -> SolarPosition:
    """Calcule la position solaire precise via pvlib.

    Args:
        timestamp: Horodatage (avec ou sans timezone)
        latitude_deg: Latitude (deg)
        longitude_deg: Longitude (deg)
        altitude_m: Altitude (m)

    Returns:
        SolarPosition avec elevation et azimut precis

    Raises:
        ImportError: Si pvlib n'est pas installe
    """
    if not HAS_PVLIB:
        raise ImportError("pvlib requis pour compute_sun_position_pvlib. "
                         "Installez avec: pip install pvlib")

    # Convertir en pandas Timestamp
    if timestamp.tzinfo is None:
        ts = pd.Timestamp(timestamp, tz='UTC')
    else:
        ts = pd.Timestamp(timestamp)

    # Calcul position solaire (methode NREL precise)
    solpos = pvlib.solarposition.get_solarposition(
        time=ts,
        latitude=latitude_deg,
        longitude=longitude_deg,
        altitude=altitude_m,
        method='nrel_numpy',
    )

    elevation = float(solpos['apparent_elevation'].iloc[0])
    azimuth = float(solpos['azimuth'].iloc[0])

    return SolarPosition(
        elevation_deg=max(0, elevation),
        azimuth_deg=azimuth % 360,
    )


def compute_sun_positions_batch(
    timestamps: list[datetime],
    latitude_deg: float,
    longitude_deg: float,
    altitude_m: float = 0.0,
) -> dict[datetime, SolarPosition]:
    """Calcule les positions solaires pour une liste de timestamps (vectorise).

    Beaucoup plus rapide que des appels individuels.

    Args:
        timestamps: Liste d'horodatages
        latitude_deg: Latitude (deg)
        longitude_deg: Longitude (deg)
        altitude_m: Altitude (m)

    Returns:
        Dictionnaire {timestamp: SolarPosition}
    """
    if not timestamps:
        return {}

    if not HAS_PVLIB:
        # Fallback sur methode simple
        result = {}
        for ts in timestamps:
            day_of_year = ts.timetuple().tm_yday
            hour = ts.hour + ts.minute / 60.0
            result[ts] = estimate_sun_position_simple(hour, day_of_year, latitude_deg)
        return result

    # Convertir en DatetimeIndex pour pvlib
    ts_list = []
    for ts in timestamps:
        if ts.tzinfo is None:
            ts_list.append(pd.Timestamp(ts, tz='UTC'))
        else:
            ts_list.append(pd.Timestamp(ts))

    times = pd.DatetimeIndex(ts_list)

    # Calcul vectorise (tres rapide)
    solpos = pvlib.solarposition.get_solarposition(
        time=times,
        latitude=latitude_deg,
        longitude=longitude_deg,
        altitude=altitude_m,
        method='nrel_numpy',
    )

    # Construire le dictionnaire
    result = {}
    for i, ts in enumerate(timestamps):
        elev = max(0, float(solpos['apparent_elevation'].iloc[i]))
        az = float(solpos['azimuth'].iloc[i]) % 360
        result[ts] = SolarPosition(elevation_deg=elev, azimuth_deg=az)

    return result


def compute_sun_position_auto(
    timestamp: datetime,
    latitude_deg: float,
    longitude_deg: float,
    altitude_m: float = 0.0,
    prefer_pvlib: bool = True,
) -> SolarPosition:
    """Calcule la position solaire avec la meilleure methode disponible.

    Args:
        timestamp: Horodatage
        latitude_deg: Latitude (deg)
        longitude_deg: Longitude (deg)
        altitude_m: Altitude (m)
        prefer_pvlib: Utiliser pvlib si disponible

    Returns:
        SolarPosition
    """
    if prefer_pvlib and HAS_PVLIB:
        return compute_sun_position_pvlib(timestamp, latitude_deg, longitude_deg, altitude_m)

    day_of_year = timestamp.timetuple().tm_yday
    hour = timestamp.hour + timestamp.minute / 60.0
    return estimate_sun_position_simple(hour, day_of_year, latitude_deg)


# ============================================================================
# CALCUL DES HEURES D'EXPOSITION FACADE
# ============================================================================

@dataclass(frozen=True)
class FacadeSunHours:
    """Heures de lever/coucher du soleil spécifiques à une façade.

    Une façade n'est exposée que lorsque :
    1. Le soleil est au-dessus de l'horizon (jour astronomique)
    2. Le soleil est devant la façade (pas derrière)

    Attributes:
        date: Date concernée
        facade_azimuth_deg: Orientation de la façade (0=N, 180=S)
        astronomical_sunrise: Lever astronomique (heure décimale)
        astronomical_sunset: Coucher astronomique (heure décimale)
        facade_sunrise: Heure où la façade commence à être exposée
        facade_sunset: Heure où la façade cesse d'être exposée
        total_sun_hours: Durée totale d'exposition (heures)
        is_ever_exposed: La façade est-elle exposée ce jour-là ?
    """
    date: datetime
    facade_azimuth_deg: float
    astronomical_sunrise: float
    astronomical_sunset: float
    facade_sunrise: Optional[float]
    facade_sunset: Optional[float]
    total_sun_hours: float
    is_ever_exposed: bool

    @property
    def facade_sun_duration_hours(self) -> float:
        """Durée d'exposition de la façade (heures)."""
        if not self.is_ever_exposed or self.facade_sunrise is None or self.facade_sunset is None:
            return 0.0
        return max(0.0, self.facade_sunset - self.facade_sunrise)

    def is_facade_exposed_at(self, hour: float) -> bool:
        """Vérifie si la façade est exposée à une heure donnée.

        Args:
            hour: Heure décimale (ex: 14.5 = 14h30)
        """
        if not self.is_ever_exposed:
            return False
        if self.facade_sunrise is None or self.facade_sunset is None:
            return False
        return self.facade_sunrise <= hour <= self.facade_sunset


def compute_facade_sun_hours(
    date: datetime,
    latitude_deg: float,
    longitude_deg: float,
    facade_azimuth_deg: float,
    time_step_minutes: int = 10,
    altitude_m: float = 0.0,
) -> FacadeSunHours:
    """Calcule les heures d'exposition solaire d'une façade.

    Différent du lever/coucher astronomique : une façade Est ne reçoit
    du soleil que le matin, une façade Ouest que l'après-midi.

    Args:
        date: Date à analyser
        latitude_deg: Latitude du site (°)
        longitude_deg: Longitude du site (°)
        facade_azimuth_deg: Orientation de la façade (0=N, 90=E, 180=S, 270=O)
        time_step_minutes: Pas de temps pour le scan (minutes)
        altitude_m: Altitude du site (m)

    Returns:
        FacadeSunHours avec toutes les informations d'exposition

    Example:
        >>> from datetime import datetime
        >>> # Façade Est à Paris, solstice d'été
        >>> result = compute_facade_sun_hours(
        ...     date=datetime(2024, 6, 21),
        ...     latitude_deg=48.85,
        ...     longitude_deg=2.35,
        ...     facade_azimuth_deg=90.0,  # Est
        ... )
        >>> print(f"Façade Est exposée de {result.facade_sunrise:.1f}h à {result.facade_sunset:.1f}h")
        Façade Est exposée de 5.8h à 12.0h

        >>> # Façade Ouest
        >>> result_west = compute_facade_sun_hours(
        ...     date=datetime(2024, 6, 21),
        ...     latitude_deg=48.85,
        ...     longitude_deg=2.35,
        ...     facade_azimuth_deg=270.0,  # Ouest
        ... )
        >>> print(f"Façade Ouest exposée de {result_west.facade_sunrise:.1f}h à {result_west.facade_sunset:.1f}h")
        Façade Ouest exposée de 12.0h à 21.7h

    Note:
        - Façade Sud (180°) : exposée quand le soleil est au Sud (matin → soir)
        - Façade Est (90°) : exposée le matin uniquement (lever → midi solaire)
        - Façade Ouest (270°) : exposée l'après-midi (midi solaire → coucher)
        - Façade Nord (0°) : exposée uniquement en été quand le soleil passe au Nord
    """
    facade_azimuth_deg = facade_azimuth_deg % 360

    # Générer les timestamps pour la journée
    # Plage SCAN_START_HOUR → SCAN_END_HOUR couvre les heures de soleil possibles
    base_date = datetime(date.year, date.month, date.day)
    timestamps = []
    for h in range(SCAN_START_HOUR, SCAN_END_HOUR):
        for m in range(0, 60, time_step_minutes):
            timestamps.append(datetime(date.year, date.month, date.day, h, m))

    # Calculer les positions solaires
    sun_positions = compute_sun_positions_batch(
        timestamps, latitude_deg, longitude_deg, altitude_m
    )

    # Trouver lever/coucher astronomique et exposition façade
    astronomical_sunrise = None
    astronomical_sunset = None
    facade_sunrise = None
    facade_sunset = None

    prev_is_day = False
    prev_is_exposed = False

    for ts in timestamps:
        sun_pos = sun_positions[ts]
        hour = ts.hour + ts.minute / 60.0

        is_day = sun_pos.is_daylight

        # Lever/coucher astronomique
        if is_day and not prev_is_day:
            astronomical_sunrise = hour
        if not is_day and prev_is_day:
            astronomical_sunset = hour

        # Exposition de la façade
        if is_day:
            incidence = compute_facade_incidence(sun_pos, facade_azimuth_deg)
            is_exposed = incidence.is_exposed

            if is_exposed and not prev_is_exposed:
                facade_sunrise = hour
            if not is_exposed and prev_is_exposed:
                facade_sunset = hour

            prev_is_exposed = is_exposed
        else:
            if prev_is_exposed:
                facade_sunset = hour
            prev_is_exposed = False

        prev_is_day = is_day

    # Cas où le coucher n'a pas été détecté (fin de journée encore exposée)
    # Utilise la fin de la plage de scan comme valeur par défaut
    if prev_is_day and astronomical_sunset is None:
        astronomical_sunset = float(SCAN_END_HOUR)
    if prev_is_exposed and facade_sunset is None:
        facade_sunset = astronomical_sunset or float(SCAN_END_HOUR)

    # Calculer durée totale
    is_ever_exposed = facade_sunrise is not None and facade_sunset is not None
    if is_ever_exposed:
        total_sun_hours = facade_sunset - facade_sunrise
    else:
        total_sun_hours = 0.0

    # Valeurs par défaut pour lever/coucher si non détectés dans la plage
    # Utilise des valeurs typiques (6h lever, 18h coucher)
    default_sunrise = float(SCAN_START_HOUR + 1)  # 6h
    default_sunset = float(SCAN_END_HOUR - 4)     # 18h

    return FacadeSunHours(
        date=base_date,
        facade_azimuth_deg=facade_azimuth_deg,
        astronomical_sunrise=astronomical_sunrise or default_sunrise,
        astronomical_sunset=astronomical_sunset or default_sunset,
        facade_sunrise=facade_sunrise,
        facade_sunset=facade_sunset,
        total_sun_hours=total_sun_hours,
        is_ever_exposed=is_ever_exposed,
    )


# ============================================================================
# PROJECTION 3D → 2D DANS LE PLAN DE LA FAÇADE
# ============================================================================

@dataclass(frozen=True)
class FacadeProjection:
    """Projection du soleil dans le plan vertical de la façade.

    Le plan de la façade est défini comme :
    - Origine : point de référence sur la façade
    - Axe X (horizontal) : parallèle à la façade, positif vers la droite (vu de l'intérieur)
    - Axe Z (vertical) : vers le haut
    - Le plan est perpendiculaire à la normale de la façade

    Cette projection est DIFFÉRENTE de sun_2d_direction dans FacadeIncidence :
    - sun_2d_direction : projection dans le plan PERPENDICULAIRE à la façade (X vers extérieur)
    - FacadeProjection : projection dans le plan DE la façade (X parallèle à la façade)

    Attributes:
        solar_position: Position 3D du soleil
        facade_azimuth_deg: Orientation de la façade
        x_component: Composante horizontale le long de la façade [-1, 1]
                     Négatif = soleil vient de la gauche, Positif = de la droite
        z_component: Composante verticale [0, 1]
        depth_component: Composante perpendiculaire (profondeur) vers l'extérieur
        projected_elevation_deg: Élévation du soleil vue dans le plan de la façade
        projected_azimuth_deg: Direction horizontale du soleil dans le plan façade
                              0° = face, 90° = vient de droite, -90° = vient de gauche
        is_in_front: Le soleil est-il devant la façade ?
    """
    solar_position: SolarPosition
    facade_azimuth_deg: float
    x_component: float       # Composante horizontale le long de la façade
    z_component: float       # Composante verticale
    depth_component: float   # Composante perpendiculaire (profondeur)
    projected_elevation_deg: float
    projected_azimuth_deg: float
    is_in_front: bool

    @property
    def horizontal_offset_deg(self) -> float:
        """Décalage horizontal du soleil par rapport à la perpendiculaire.

        Utile pour savoir si le soleil vient de gauche ou de droite.
        Positif = droite, Négatif = gauche (vu de l'intérieur).
        """
        return self.projected_azimuth_deg

    def to_2d_incidence(self) -> tuple[float, float]:
        """Retourne le vecteur d'incidence 2D dans le plan perpendiculaire à la façade.

        Returns: (x, z) avec x vers l'extérieur, z vers le haut
        """
        # Normaliser depth et z pour obtenir un vecteur unitaire
        norm = math.sqrt(self.depth_component**2 + self.z_component**2)
        if norm < 1e-6:
            return (0.0, 0.0)
        return (self.depth_component / norm, self.z_component / norm)


def project_sun_to_facade_plane(
    solar_position: SolarPosition,
    facade_azimuth_deg: float,
) -> FacadeProjection:
    """Projette la position du soleil dans le repère de la façade.

    Cette fonction calcule comment le soleil apparaît depuis la façade :
    - D'où vient-il horizontalement (gauche/droite) ?
    - À quelle élévation est-il vu depuis la façade ?
    - Est-il devant ou derrière ?

    Args:
        solar_position: Position 3D du soleil (élévation, azimut)
        facade_azimuth_deg: Orientation de la façade (0=N, 90=E, 180=S, 270=O)

    Returns:
        FacadeProjection avec toutes les composantes

    Example:
        >>> sun = SolarPosition(elevation_deg=45.0, azimuth_deg=135.0)  # Soleil Sud-Est
        >>> proj = project_sun_to_facade_plane(sun, facade_azimuth_deg=180.0)  # Façade Sud
        >>> print(f"Le soleil vient de la {'gauche' if proj.x_component < 0 else 'droite'}")
        Le soleil vient de la gauche
        >>> print(f"Décalage horizontal: {proj.horizontal_offset_deg:.1f}°")
        Décalage horizontal: -45.0°

    Ce que la projection donne :
        1. Si la façade est exposée (is_in_front)
        2. L'élévation effective (projected_elevation_deg)
        3. Le décalage horizontal du soleil (horizontal_offset_deg)
    """
    facade_azimuth_deg = facade_azimuth_deg % 360

    # Nuit
    if not solar_position.is_daylight:
        return FacadeProjection(
            solar_position=solar_position,
            facade_azimuth_deg=facade_azimuth_deg,
            x_component=0.0,
            z_component=0.0,
            depth_component=0.0,
            projected_elevation_deg=0.0,
            projected_azimuth_deg=0.0,
            is_in_front=False,
        )

    # Direction 3D du soleil (x=Est, y=Nord, z=haut)
    sun_x, sun_y, sun_z = solar_position.direction_3d()

    # Construire le repère de la façade
    # La normale de la façade pointe vers facade_azimuth_deg
    # Axe "depth" = normale de la façade (vers l'extérieur)
    # Axe "x_facade" = parallèle à la façade, vers la droite (vu de l'intérieur)
    # Axe "z_facade" = vertical vers le haut

    facade_rad = math.radians(facade_azimuth_deg)

    # Normale de la façade (direction vers l'extérieur)
    normal_x = math.sin(facade_rad)  # Composante Est de la normale
    normal_y = math.cos(facade_rad)  # Composante Nord de la normale

    # Vecteur horizontal perpendiculaire à la normale (vers la droite vu de l'intérieur)
    # C'est la normale tournée de 90° dans le sens horaire
    right_x = normal_y   # = cos(facade_azimuth)
    right_y = -normal_x  # = -sin(facade_azimuth)

    # Projection du vecteur soleil dans le repère façade
    # depth = projection sur la normale (positif = devant la façade)
    depth_component = sun_x * normal_x + sun_y * normal_y

    # x_facade = projection sur l'axe horizontal de la façade
    x_component = sun_x * right_x + sun_y * right_y

    # z_facade = composante verticale (inchangée)
    z_component = sun_z

    # Le soleil est-il devant la façade ?
    is_in_front = depth_component > 0

    # Élévation projetée dans le plan perpendiculaire à la façade
    if is_in_front:
        projected_elevation_deg = math.degrees(math.atan2(z_component, depth_component))
    else:
        projected_elevation_deg = 0.0

    # Azimut projeté (décalage horizontal)
    # 0° = pile en face, positif = vient de la droite, négatif = vient de la gauche
    if is_in_front and depth_component > 0:
        projected_azimuth_deg = math.degrees(math.atan2(x_component, depth_component))
    else:
        projected_azimuth_deg = 0.0

    return FacadeProjection(
        solar_position=solar_position,
        facade_azimuth_deg=facade_azimuth_deg,
        x_component=x_component,
        z_component=z_component,
        depth_component=depth_component,
        projected_elevation_deg=projected_elevation_deg,
        projected_azimuth_deg=projected_azimuth_deg,
        is_in_front=is_in_front,
    )


def compute_facade_exposure_profile(
    date: datetime,
    latitude_deg: float,
    longitude_deg: float,
    facade_azimuth_deg: float,
    time_step_minutes: int = 30,
    altitude_m: float = 0.0,
) -> list[dict]:
    """Calcule le profil d'exposition d'une façade sur une journée.

    Retourne pour chaque pas de temps :
    - Position du soleil
    - Projection sur la façade
    - Si la façade est exposée

    Args:
        date: Date à analyser
        latitude_deg: Latitude du site (°)
        longitude_deg: Longitude du site (°)
        facade_azimuth_deg: Orientation de la façade (°)
        time_step_minutes: Pas de temps (minutes)
        altitude_m: Altitude du site (m)

    Returns:
        Liste de dictionnaires avec toutes les informations horaires

    Example:
        >>> profile = compute_facade_exposure_profile(
        ...     date=datetime(2024, 6, 21),
        ...     latitude_deg=45.0,
        ...     longitude_deg=0.0,
        ...     facade_azimuth_deg=180.0,
        ... )
        >>> for p in profile:
        ...     if p['is_exposed']:
        ...         print(f"{p['hour']:.1f}h: élév={p['elevation_deg']:.1f}°, "
        ...               f"depuis {'gauche' if p['horizontal_offset_deg'] < 0 else 'droite'}")
    """
    facade_azimuth_deg = facade_azimuth_deg % 360

    # Générer les timestamps
    # Plage SCAN_START_HOUR → SCAN_END_HOUR couvre les heures de soleil possibles
    timestamps = []
    for h in range(SCAN_START_HOUR, SCAN_END_HOUR):
        for m in range(0, 60, time_step_minutes):
            timestamps.append(datetime(date.year, date.month, date.day, h, m))

    # Calculer les positions solaires
    sun_positions = compute_sun_positions_batch(
        timestamps, latitude_deg, longitude_deg, altitude_m
    )

    # Construire le profil
    profile = []
    for ts in timestamps:
        sun_pos = sun_positions[ts]
        hour = ts.hour + ts.minute / 60.0

        projection = project_sun_to_facade_plane(sun_pos, facade_azimuth_deg)
        incidence = compute_facade_incidence(sun_pos, facade_azimuth_deg)

        profile.append({
            'timestamp': ts,
            'hour': hour,
            'elevation_deg': sun_pos.elevation_deg,
            'azimuth_deg': sun_pos.azimuth_deg,
            'is_daylight': sun_pos.is_daylight,
            'is_exposed': incidence.is_exposed,
            'exposure_type': incidence.exposure.value,
            'incidence_angle_deg': incidence.incidence_angle_deg,
            'cosine_factor': incidence.cosine_factor,
            'projected_elevation_deg': projection.projected_elevation_deg,
            'horizontal_offset_deg': projection.horizontal_offset_deg,
            'sun_2d_x': projection.depth_component,
            'sun_2d_z': projection.z_component,
        })

    return profile
