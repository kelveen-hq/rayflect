"""
Module de telechargement et moyennage des donnees PVGIS historiques.

Ce module permet de :
- Telecharger les donnees horaires PVGIS d'une annee (`fetch_pvgis_year`),
  avec un cache sur disque
- Calculer une annee type moyennee sur plusieurs annees (`download_pvgis_tmy`)

API PVGIS utilisee:
https://re.jrc.ec.europa.eu/api/v5_2/seriescalc

Usage:
    from rayflect.io.pvgis_historical import (
        fetch_pvgis_year,
    )
"""

from __future__ import annotations

import math
import os
import re
import tempfile
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import pandas as pd
import requests


# ============================================================================
# CONSTANTES
# ============================================================================

PVGIS_API_URL = "https://re.jrc.ec.europa.eu/api/v5_2/seriescalc"

# Annees disponibles dans PVGIS pour les donnees historiques
# Note: PVGIS va jusqu'a 2020 pour les donnees horaires historiques
# Pour 2021-2024, on utilise les donnees satellites ERA5/SARAH
PVGIS_YEARS_AVAILABLE = [2016, 2017, 2018, 2019, 2020]

# Facteurs d'ajustement climatique pour extrapoler vers 2021-2024
# Bases sur les tendances observees (rechauffement +0.2C/an, GHI +0.5%/an)
# ATTENTION : le GHI +0.5%/an est très surestimé par rapport
# aux observations (~+0.03%/an en Europe, Météo-France/PVGIS). L'impact moyen
# résultant est toutefois faible (+1% sur le GHI, +0.4°C sur la température).
CLIMATE_TREND_FACTORS = {
    2021: {"ghi_factor": 1.005, "temp_offset": 0.2},
    2022: {"ghi_factor": 1.010, "temp_offset": 0.4},
    2023: {"ghi_factor": 1.015, "temp_offset": 0.6},
    2024: {"ghi_factor": 1.020, "temp_offset": 0.8},
}


# ============================================================================
# FONCTIONS DE TELECHARGEMENT
# ============================================================================

# ── LE CACHE PEUT ETRE PARTAGE PAR PLUSIEURS FILS ET PLUSIEURS PROCESSUS ──
#
# Plusieurs calculs du meme site peuvent demander la meme annee en meme temps,
# cache froid. Sans precaution, un lecteur ouvre un fichier qu'un ecrivain est
# en train de remplir (0 octet, puis partiel) et `pd.read_csv` leve
# `EmptyDataError`.
#
# ECRIRE A COTE, PUIS RENOMMER. `os.replace` est atomique sur Windows comme
# sur POSIX : un lecteur voit soit rien, soit un fichier entier.
#
# UN BROUILLON PROPRE A CHAQUE ECRIVAIN (`mkstemp`). Deux fils du meme
# processus ont le meme PID : un brouillon nomme par le PID seul serait ecrit
# par les deux, et `os.replace` leverait (WinError 32, FileNotFoundError,
# WinError 5).
#
# UNE PUBLICATION QUI ATTEND. Sous Windows, `os.replace` sur une cible qu'un
# lecteur d'un autre processus tient ouverte leve WinError 5 (Python n'ouvre
# pas avec FILE_SHARE_DELETE). La publication attend donc que le lecteur lache
# la cible, ou constate qu'un autre ecrivain a deja publie la meme annee,
# lisible.
_ESSAIS_PUBLICATION = 12      # 11 attentes de 50 a 550 ms : 3,3 s au plus
_PAUSE_PUBLICATION_S = 0.05


def _ecrire_cache_atomique(df: pd.DataFrame, chemin: Path) -> None:
    """Publie le CSV d'un seul coup, ou pas du tout."""
    chemin.parent.mkdir(parents=True, exist_ok=True)
    # Un nom UNIQUE par ecrivain, fil ou processus. Le descripteur se ferme
    # tout de suite : `to_csv` ecrit par le chemin, et Windows refuse de
    # renommer un fichier encore ouvert.
    fd, nom = tempfile.mkstemp(dir=chemin.parent, prefix=f"{chemin.name}.", suffix=".tmp")
    os.close(fd)
    brouillon = Path(nom)
    try:
        df.to_csv(brouillon, index=False)
        _publier(brouillon, chemin)
    finally:
        # Un brouillon survivant serait un dechet qui grossit a chaque echec.
        try:
            if brouillon.exists():
                brouillon.unlink()
        except OSError:
            pass


def _publier(brouillon: Path, chemin: Path) -> None:
    """`os.replace`, en laissant a un lecteur le temps de lacher la cible.

    Si la cible reste tenue mais qu'elle est DEJA une annee lisible, un autre
    ecrivain l'a publiee : c'est la meme annee PVGIS, on s'arrete la. Une cible
    illisible qu'on ne parvient pas a remplacer leve : cette panne-la doit se
    voir.
    """
    for essai in range(_ESSAIS_PUBLICATION):
        try:
            os.replace(brouillon, chemin)
            return
        except PermissionError:
            if lire_cache_pvgis(chemin) is not None:
                return
            if essai == _ESSAIS_PUBLICATION - 1:
                raise
            time.sleep(_PAUSE_PUBLICATION_S * (essai + 1))


# UN SEUL TELECHARGEMENT PAR ANNEE ET PAR PROCESSUS. Le premier fil
# telecharge et publie ; les autres attendent son verrou, puis lisent son
# fichier, exactement comme un calcul lance juste apres.
_VERROUS_ANNEE: Dict[str, threading.Lock] = {}
_VERROU_DES_VERROUS = threading.Lock()


def _verrou_du_fichier(chemin: Path) -> threading.Lock:
    cle = os.path.normcase(os.path.abspath(chemin))
    with _VERROU_DES_VERROUS:
        return _VERROUS_ANNEE.setdefault(cle, threading.Lock())


def lire_cache_pvgis(chemin: Path) -> Optional[pd.DataFrame]:
    """Le contenu du cache, ou None si ce fichier n'est pas utilisable.

    REND None PLUTOT QUE DE LEVER. Un cache est une optimisation : quand il
    est illisible, la reponse juste est de le retelecharger, pas de faire
    echouer le calcul. Un fichier peut etre tronque, par exemple quand le
    disque est plein.
    """
    if not chemin.exists() or chemin.stat().st_size == 0:
        return None
    try:
        df = pd.read_csv(chemin, parse_dates=['timestamp'])
    except (pd.errors.EmptyDataError, pd.errors.ParserError, ValueError, OSError):
        return None
    if df.empty or 'timestamp' not in df.columns:
        return None
    return df


# ── LE MESSAGE D'UNE PANNE PVGIS NE RECOPIE PAS L'URL ─────────────────────
#
# requests met l'URL de la requete dans son message : `…/seriescalc?lat=…
# &lon=…`, donc les coordonnees du site au millionieme de degre. Ce message
# peut finir dans une reponse ou dans un journal.
#
# Le message se CONSTRUIT donc avec ce qui sert a chercher la panne -- le
# type, la cause de bas niveau (refus, DNS, delai), le code HTTP et sa raison
# -- et rien d'autre. Le detail complet reste chaine (`__cause__`).
_RAISON_HTTP = re.compile(r"[A-Za-z][A-Za-z '\-]{0,40}")


def message_erreur_pvgis(year: int, erreur: BaseException) -> str:
    """Le message d'une panne PVGIS, sans l'URL de la requete ni ses coordonnees."""
    morceaux = [type(erreur).__name__]
    reponse = getattr(erreur, "response", None)
    code = getattr(reponse, "status_code", None)
    if isinstance(code, int):
        raison = getattr(reponse, "reason", None)
        morceaux.append(f"HTTP {code}" + (
            f" {raison}" if isinstance(raison, str) and _RAISON_HTTP.fullmatch(raison) else ""))
    else:
        # Sans reponse : la cause d'urllib3 se nomme par son TYPE
        # (NewConnectionError, NameResolutionError, ConnectTimeoutError…),
        # jamais par son texte, qui recopie l'URL lui aussi.
        cause = erreur.args[0] if erreur.args else None
        cause = getattr(cause, "reason", cause)
        if isinstance(cause, BaseException):
            morceaux.append(f"cause {type(cause).__name__}")
    return f"Erreur API PVGIS pour {year}: {', '.join(morceaux)} (coordonnées retirées du message)"


# ── UNE PANNE PASSAGERE DE PVGIS SE DISTINGUE D'UN REFUS ──────────────────
#
# Ce qu'une relance peut faire aboutir -- connexion coupee ou refusee, delai
# depasse, corps tronque, PVGIS en panne (5xx) ou qui limite le debit (429) --
# leve `MeteoIndisponible` : l'appelant peut relancer apres
# `relancer_apres_s` secondes. Le reste garde sa `RuntimeError` : un refus 4xx
# de PVGIS se reproduirait a l'identique. Une annee en cache ne passe jamais
# ici.
#
# `MeteoIndisponible` herite de `RuntimeError` : qui attrape l'une attrape
# l'autre, avec le meme message.
class MeteoIndisponible(RuntimeError):
    """PVGIS n'a pas repondu, pour une raison qui peut passer : relancer."""

    # Delai conseille avant de relancer, en secondes.
    relancer_apres_s = 30


def panne_passagere(erreur: BaseException) -> bool:
    """Vrai si relancer le meme telechargement a une chance d'aboutir."""
    if isinstance(erreur, (requests.ConnectionError, requests.Timeout,
                           requests.exceptions.ChunkedEncodingError)):
        return True
    if isinstance(erreur, requests.HTTPError):
        code = getattr(getattr(erreur, "response", None), "status_code", None)
        return isinstance(code, int) and (code == 429 or 500 <= code <= 599)
    return False


def fetch_pvgis_year(
    latitude: float,
    longitude: float,
    year: int,
    cache_dir: Optional[Path] = None,
) -> pd.DataFrame:
    """Telecharge les donnees horaires PVGIS pour une annee complete.

    Args:
        latitude: Latitude du site (degres)
        longitude: Longitude du site (degres)
        year: Annee a telecharger (2005-2020 disponibles)
        cache_dir: Repertoire de cache (optionnel)

    Returns:
        DataFrame avec colonnes: timestamp, ghi, dni, dhi, temp_air, wind_speed
    """
    if cache_dir is None:
        df, telecharge = _lire_ou_telecharger(latitude, longitude, year, None)
    else:
        # Lire, telecharger et publier se font SOUS LE VERROU de l'annee :
        # voir `_verrou_du_fichier`.
        with _verrou_du_fichier(
                cache_dir / f"pvgis_{latitude:.4f}_{longitude:.4f}_{year}_hourly.csv"):
            df, telecharge = _lire_ou_telecharger(latitude, longitude, year, cache_dir)
    if telecharge:
        # Pause pour respecter les limites de l'API -- verrou deja rendu : les
        # fils qui attendaient cette annee la lisent sans attendre la pause.
        time.sleep(1)
    return df


def _lire_ou_telecharger(
    latitude: float,
    longitude: float,
    year: int,
    cache_dir: Optional[Path],
) -> Tuple[pd.DataFrame, bool]:
    """(tableau, telecharge ?) : le corps de `fetch_pvgis_year`, sans la pause."""
    # Verifier le cache
    if cache_dir is not None:
        cache_file = cache_dir / f"pvgis_{latitude:.4f}_{longitude:.4f}_{year}_hourly.csv"
        _cache = lire_cache_pvgis(cache_file)
        if _cache is not None:
            print(f"  [Cache] Chargement {year} depuis {cache_file.name}")
            return _cache, False
        if cache_file.exists():
            print(f"  [Cache] {cache_file.name} inutilisable : retelechargement")

    # Telecharger depuis PVGIS
    print(f"  [API] Telechargement PVGIS {year}...")

    params = {
        "lat": latitude,
        "lon": longitude,
        "startyear": year,
        "endyear": year,
        "outputformat": "json",
        "components": 1,  # Composantes separees (GHI, DNI, DHI)
    }

    try:
        response = requests.get(PVGIS_API_URL, params=params, timeout=60)
        response.raise_for_status()
        data = response.json()
    except requests.RequestException as e:
        # Le message peut etre journalise ou rendu a l'appelant : jamais
        # l'URL. Voir message_erreur_pvgis. Passagere ou non : voir
        # MeteoIndisponible.
        classe = MeteoIndisponible if panne_passagere(e) else RuntimeError
        raise classe(message_erreur_pvgis(year, e)) from e

    # Parser les donnees
    hourly_data = data.get("outputs", {}).get("hourly", [])
    if not hourly_data:
        raise ValueError(f"Pas de donnees horaires PVGIS pour {year}")

    records = []
    for entry in hourly_data:
        # Format PVGIS: "20200101:0000"
        time_str = entry.get("time", "")
        try:
            ts = datetime.strptime(time_str, "%Y%m%d:%H%M")
        except ValueError:
            continue

        # Composantes séparées (components=1): Gb(i), Gd(i), Gr(i)
        # IMPORTANT : avec slope=0 (défaut), Gb(i) = beam sur plan horizontal (BHI),
        # PAS le DNI (beam normal). Conversion : DNI = BHI / sin(H_sun)
        # H_sun = hauteur solaire en degrés, fournie par l'API.
        bhi = float(entry.get("Gb(i)", 0))   # Beam Horizontal Irradiance (W/m²)
        dhi = float(entry.get("Gd(i)", 0))   # Diffuse Horizontal Irradiance (W/m²)
        gri = float(entry.get("Gr(i)", 0))   # Ground-Reflected Irradiance (W/m²)
        h_sun = float(entry.get("H_sun", 0)) # Hauteur solaire (degrés)

        # Convertir BHI → DNI via la hauteur solaire
        # Guard : sin(5°) ≈ 0.087 : sous 5° la mesure satellite n'est pas fiable
        MIN_SOLAR_ELEVATION_DEG = 5.0
        if h_sun > MIN_SOLAR_ELEVATION_DEG and bhi > 0:
            sin_h = math.sin(math.radians(h_sun))
            dni = bhi / sin_h
        else:
            dni = 0.0

        # GHI = somme des composantes (ou G(i) si disponible)
        ghi = float(entry.get("G(i)", bhi + dhi + gri))

        records.append({
            "timestamp": ts,
            "ghi": ghi,
            "dni": dni,
            "dhi": dhi,
            "temp_air": float(entry.get("T2m", 12)),  # Temperature 2m
            "wind_speed": float(entry.get("WS10m", 3)),  # Wind speed 10m
        })

    df = pd.DataFrame(records)

    # Sauvegarder en cache
    if cache_dir is not None:
        _ecrire_cache_atomique(df, cache_file)
        print(f"  [Cache] Sauvegarde {cache_file.name}")

    return df, True




# ============================================================================
# FONCTIONS DE MOYENNAGE
# ============================================================================



# ============================================================================
# TÉLÉCHARGEMENT TMY SIMPLIFIÉ
# ============================================================================

def download_pvgis_tmy(
    latitude: float,
    longitude: float,
    cache_dir: Path,
    force_download: bool = False,
    years: Optional[List[int]] = None,
    verbose: bool = True,
) -> Path:
    """Télécharge les données TMY PVGIS et retourne le chemin du fichier.

    Télécharge plusieurs années et calcule une moyenne pour créer
    un fichier TMY (Typical Meteorological Year) annuel.

    Parameters
    ----------
    latitude:
        Latitude du site
    longitude:
        Longitude du site
    cache_dir:
        Répertoire de cache
    force_download:
        Si True, retélécharge même si le cache existe
    years:
        Liste des années à télécharger (défaut: 2016-2020)
    verbose:
        Affiche la progression

    Returns
    -------
    Path
        Chemin vers le fichier TMY CSV

    Example
    -------
    >>> tmy_file = download_pvgis_tmy(44.8378, -0.5792, Path("./cache"))
    >>> print(tmy_file)
    cache/pvgis_44.8378_-0.5792_tmy_annual.csv
    """
    cache_dir = Path(cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)

    # Nom du fichier TMY final
    tmy_file = cache_dir / f"pvgis_{latitude:.4f}_{longitude:.4f}_tmy_annual.csv"

    if tmy_file.exists() and not force_download:
        if verbose:
            print(f"   [Cache] TMY existant: {tmy_file.name}")
        return tmy_file

    if verbose:
        print("   [PVGIS] Téléchargement données météo...")
        print(f"   Coordonnées: {latitude:.4f}°N, {longitude:.4f}°E")

    # Années à télécharger
    if years is None:
        years = PVGIS_YEARS_AVAILABLE

    all_data = {}

    for i, year in enumerate(years):
        if verbose:
            pct = (i + 1) / len(years) * 100
            print(f"\r   Téléchargement: {pct:.0f}% - Année {year}", end="", flush=True)
        try:
            df = fetch_pvgis_year(latitude, longitude, year, cache_dir)
            all_data[year] = df
        except Exception as e:
            if verbose:
                print(f"\n   [Warning] Erreur pour {year}: {e}")
            continue

    if verbose:
        print()  # Nouvelle ligne

    if not all_data:
        raise RuntimeError("Impossible de télécharger les données PVGIS")

    # Calculer la moyenne sur toutes les années
    if verbose:
        print("   [Calcul] Création de l'année type TMY...")

    # Combiner toutes les données
    combined = pd.concat(all_data.values(), ignore_index=True)

    # Créer une clé mois-jour-heure pour grouper
    combined['month'] = combined['timestamp'].dt.month
    combined['day'] = combined['timestamp'].dt.day
    combined['hour'] = combined['timestamp'].dt.hour

    # Moyenne par mois-jour-heure
    tmy_data = combined.groupby(['month', 'day', 'hour']).agg({
        'ghi': 'mean',
        'dni': 'mean',
        'dhi': 'mean',
        'temp_air': 'mean',
        'wind_speed': 'mean',
    }).reset_index()

    # Recréer les timestamps pour une année de référence (2024)
    ref_year = 2024

    def make_timestamp(row):
        try:
            return datetime(ref_year, int(row['month']), int(row['day']), int(row['hour']))
        except ValueError:
            # Gérer le 29 février
            if int(row['month']) == 2 and int(row['day']) == 29:
                return datetime(ref_year, 2, 28, int(row['hour']))
            raise

    tmy_data['timestamp'] = tmy_data.apply(make_timestamp, axis=1)

    # Format pour export
    tmy_data['time'] = tmy_data['timestamp'].dt.strftime('%Y%m%d:%H%M')

    # Colonnes finales
    export_df = tmy_data[['time', 'ghi', 'dni', 'dhi', 'temp_air', 'wind_speed']].copy()
    export_df = export_df.sort_values('time')

    # Sauvegarder
    export_df.to_csv(tmy_file, index=False)

    if verbose:
        print(f"   [OK] TMY sauvegardé: {tmy_file.name} ({len(export_df)} heures)")

    return tmy_file


# ============================================================================
# EXPORTS
# ============================================================================

__all__ = [
    "PVGIS_API_URL",
    "PVGIS_YEARS_AVAILABLE",
    "CLIMATE_TREND_FACTORS",
    "fetch_pvgis_year",
    "download_pvgis_tmy",
]
