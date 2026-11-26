"""Le lieu d'une étude : une adresse suffit, tout le reste en découle.

D'une adresse, le géocodeur de la Géoplateforme (IGN, gratuit, sans clé, France seulement) donne la latitude
et la longitude. De là viennent la météo (`io.meteo.preparer`) et les bâtiments voisins
(`environnement.entourer`).

L'ORDRE DE CONFIANCE. L'adresse donnée par la personne passe avant des coordonnées saisies, qui passent avant
la position écrite dans la maquette. Cette dernière n'est qu'un repli : mesuré sur des maquettes réelles, elle
est parfois celle du gabarit du logiciel de dessin, pas celle du bâtiment. Quand l'adresse et la maquette
disent 2 endroits éloignés, c'est signalé.

CE QUE LE LIEU SAIT DE PLUS. Le géocodeur rend aussi la commune, son département et sa population ; le
service d'altimétrie de la Géoplateforme rend l'altitude du point. `completer` les ajoute à un lieu connu
par ses seules coordonnées, par le géocodage inverse. De là viennent la zone climatique et la température
de base (`rayflect.climat`).

Ce module envoie au service de l'IGN l'adresse saisie, ou les coordonnées du point. Rien d'autre ne sort.
"""

from __future__ import annotations

import json
import math
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

GEOCODEUR = "https://data.geopf.fr/geocodage/search"
GEOCODEUR_INVERSE = "https://data.geopf.fr/geocodage/reverse"
ALTIMETRIE = "https://data.geopf.fr/altimetrie/1.0/calcul/alti/rest/elevation.json"
RESSOURCE_D_ALTITUDE = "ign_rge_alti_wld"
ALTITUDE_INCONNUE_M = -99999.0  # ce que le service rend hors de sa couverture
SCORE_MINIMAL = 0.5             # [H] en dessous, le géocodeur n'a pas reconnu l'adresse
ECART_A_SIGNALER_M = 500.0      # [H] au-delà, la maquette et l'adresse ne désignent pas le même endroit
RAYON_TERRE_M = 6_371_000.0
# Ce que le géocodeur a reconnu, et ce que cela vaut pour retrouver le bâtiment sur la carte.
PRECISIONS = {"housenumber": "au numéro", "street": "à la rue", "locality": "au lieu-dit",
              "municipality": "à la commune"}


class LieuIntrouvable(ValueError):
    """Le lieu n'a pas pu être établi : il faut le demander."""


@dataclass
class Lieu:
    latitude: float
    longitude: float
    libelle: str
    origine: str                                    # "adresse", "coordonnées" ou "maquette"
    remarques: List[str] = field(default_factory=list)
    commune: Optional[str] = None
    code_commune: Optional[str] = None              # code de l'INSEE
    departement: Optional[str] = None               # son numéro : "33", "2A"
    population: Optional[int] = None                # de la commune
    altitude_m: Optional[float] = None

    def resume(self) -> str:
        return f"{self.libelle} ({self.latitude:.5f}, {self.longitude:.5f}), d'après {self.origine}"

    def fiche(self) -> List[str]:
        """Ce qu'on sait du lieu, en clair : commune, altitude, zone climatique, température de base, terrain."""
        from rayflect import climat

        lignes = []
        if self.commune:
            habitants = f", {self.population} habitants" if self.population else ""
            lignes.append(f"commune : {self.commune} ({self.departement or 'département inconnu'}){habitants}")
        if self.altitude_m is not None:
            lignes.append(f"altitude : {self.altitude_m:.0f} m")
        zone = climat.zone(self.departement)
        if zone:
            lignes.append(f"zone climatique : {zone}")
        base = climat.temperature_de_base(self.departement, self.altitude_m)
        if base:
            lignes.append(f"température extérieure de base : {base[0]:g} °C ({base[1]})")
        terrain = climat.terrain_propose(self.population)
        if terrain:
            lignes.append(f"terrain proposé : {terrain[0]} ({terrain[1]}) [H]")
        return lignes


def distance_m(a: Tuple[float, float], b: Tuple[float, float]) -> float:
    """La distance entre 2 points (latitude, longitude), à vol d'oiseau."""
    lat1, lon1, lat2, lon2 = map(math.radians, (*a, *b))
    h = math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    return 2 * RAYON_TERRE_M * math.asin(math.sqrt(h))


def _demander(adresse: str, delai_s: float) -> dict:
    requete = urllib.parse.urlencode({"q": adresse, "limit": "1"})
    with urllib.request.urlopen(f"{GEOCODEUR}?{requete}", timeout=delai_s) as reponse:
        return json.loads(reponse.read().decode("utf-8"))


def _inverser(latitude: float, longitude: float, delai_s: float) -> dict:
    requete = urllib.parse.urlencode({"lon": f"{longitude:.6f}", "lat": f"{latitude:.6f}", "limit": "1"})
    with urllib.request.urlopen(f"{GEOCODEUR_INVERSE}?{requete}", timeout=delai_s) as reponse:
        return json.loads(reponse.read().decode("utf-8"))


def _altitude(latitude: float, longitude: float, delai_s: float) -> dict:
    requete = urllib.parse.urlencode({"lon": f"{longitude:.6f}", "lat": f"{latitude:.6f}",
                                      "resource": RESSOURCE_D_ALTITUDE, "zonly": "true"})
    with urllib.request.urlopen(f"{ALTIMETRIE}?{requete}", timeout=delai_s) as reponse:
        return json.loads(reponse.read().decode("utf-8"))


def _noter_la_commune(lieu: Lieu, proprietes: dict) -> None:
    lieu.commune = proprietes.get("city") or proprietes.get("municipality") or lieu.commune
    lieu.code_commune = proprietes.get("citycode") or lieu.code_commune
    departement = proprietes.get("depcode") or str(proprietes.get("context", "")).split(",")[0].strip()
    if not departement and lieu.code_commune:
        departement = lieu.code_commune[:3] if lieu.code_commune.startswith("97") else lieu.code_commune[:2]
    lieu.departement = departement or lieu.departement
    if isinstance(proprietes.get("population"), (int, float)):
        lieu.population = int(proprietes["population"])


def completer(lieu: Lieu, delai_s: float = 30.0) -> Lieu:
    """Ajoute au lieu sa commune et son altitude, demandées à l'IGN. Ce qui ne répond pas est dit, sans bloquer."""
    if lieu.commune is None:
        try:
            trouves = _inverser(lieu.latitude, lieu.longitude, delai_s).get("features") or []
            if trouves:
                _noter_la_commune(lieu, trouves[0].get("properties", {}))
            else:
                lieu.remarques.append("commune non trouvée : le point est hors de France, ou en mer")
        except (OSError, ValueError) as erreur:
            lieu.remarques.append(f"commune non demandée, le géocodeur ne répond pas ({erreur})")
    if lieu.altitude_m is None:
        try:
            altitudes = _altitude(lieu.latitude, lieu.longitude, delai_s).get("elevations") or []
            if altitudes and float(altitudes[0]) > ALTITUDE_INCONNUE_M + 1:
                lieu.altitude_m = float(altitudes[0])
            else:
                lieu.remarques.append("altitude non trouvée : le point est hors de la couverture de l'IGN")
        except (OSError, ValueError, TypeError) as erreur:
            lieu.remarques.append(f"altitude non demandée, le service ne répond pas ({erreur})")
    return lieu


def _sans_accents(texte: str) -> str:
    import unicodedata

    plat = unicodedata.normalize("NFD", texte.lower())
    return "".join(c if c.isalnum() else " " for c in plat if unicodedata.category(c) != "Mn")


def _autre_commune(adresse: str, proprietes: dict) -> Optional[str]:
    """La commune trouvée, si son nom n'est pas dans l'adresse demandée ; None quand tout concorde.

    LE GÉOCODEUR RÉPOND TOUJOURS QUELQUE CHOSE. Mesuré : « 12 rue de la Paix, Strasbourg » lui fait rendre
    « 12 Rue de Strasbourg, Nantes », avec une ressemblance jugée suffisante. Le nom de la rue a été pris pour
    celui de la ville. Sans ce contrôle, l'étude partait à 700 km de là sans rien dire.
    """
    commune = str(proprietes.get("city") or proprietes.get("municipality") or "")
    if not commune:
        return None
    demande = f" {' '.join(_sans_accents(adresse).split())} "
    voulu = f" {' '.join(_sans_accents(commune).split())} "
    code_postal = str(proprietes.get("postcode") or "")
    if voulu in demande or (code_postal and code_postal in adresse):
        return None
    return commune


def geocoder(adresse: str, delai_s: float = 30.0) -> Lieu:
    """Le lieu d'une adresse française. Lève `LieuIntrouvable` si elle n'est pas reconnue."""
    adresse = " ".join(adresse.split())
    if len(adresse) < 3:
        raise LieuIntrouvable("adresse vide : à demander")
    try:
        reponse = _demander(adresse, delai_s)
    except OSError as erreur:
        raise LieuIntrouvable(f"le géocodeur ne répond pas ({erreur}) : donner latitude et longitude") from erreur
    trouves = reponse.get("features") or []
    if not trouves:
        raise LieuIntrouvable(f"adresse non reconnue : « {adresse} » (le géocodeur ne couvre que la France)")
    proprietes = trouves[0].get("properties", {})
    score = float(proprietes.get("score", 0.0))
    if score < SCORE_MINIMAL:
        raise LieuIntrouvable(
            f"adresse non reconnue : « {adresse} » (au mieux « {proprietes.get('label', '?')} », "
            f"ressemblance {score * 100:.0f} %)")
    longitude, latitude = trouves[0]["geometry"]["coordinates"][:2]
    lieu = Lieu(float(latitude), float(longitude), str(proprietes.get("label", adresse)), "adresse")
    _noter_la_commune(lieu, proprietes)
    ailleurs = _autre_commune(adresse, proprietes)
    if ailleurs is not None:
        lieu.remarques.append(
            f"LIEU À VÉRIFIER : l'adresse trouvée est à {ailleurs}, dont le nom n'est pas dans « {adresse} ». "
            f"Si ce n'est pas la bonne ville, donner le code postal ou la latitude et la longitude")
    precision = PRECISIONS.get(str(proprietes.get("type", "")), "de façon inconnue")
    if proprietes.get("type") != "housenumber":
        lieu.remarques.append(
            f"adresse reconnue {precision} seulement : assez pour la météo, pas pour retrouver le bâtiment "
            f"parmi ses voisins")
    return lieu


def _position_de_la_maquette(releve) -> Optional[Tuple[float, float]]:
    if releve is None or releve.latitude is None or releve.longitude is None:
        return None
    if abs(releve.latitude) < 1e-6 and abs(releve.longitude) < 1e-6:
        return None                                 # (0, 0) : une position jamais renseignée
    return float(releve.latitude), float(releve.longitude)


def choisir(adresse: Optional[str] = None, coordonnees: Optional[Tuple[float, float]] = None,
            releve=None) -> Lieu:
    """Le lieu de l'étude, par ordre de confiance : adresse, coordonnées données, position de la maquette."""
    maquette = _position_de_la_maquette(releve)
    if adresse:
        lieu = geocoder(adresse)
    elif coordonnees is not None:
        latitude, longitude = float(coordonnees[0]), float(coordonnees[1])
        if not (-90.0 <= latitude <= 90.0 and -180.0 <= longitude <= 180.0):
            raise LieuIntrouvable(f"coordonnées hors du globe : {latitude}, {longitude}")
        lieu = Lieu(latitude, longitude, "point donné", "coordonnées")
    elif maquette is not None:
        return Lieu(maquette[0], maquette[1], "position écrite dans la maquette", "maquette", [
            "lieu non confirmé : la position vient de la maquette, où elle est parfois celle du gabarit du "
            "logiciel de dessin. Donner l'adresse pour en être sûr"])
    else:
        raise LieuIntrouvable("aucun lieu : ni adresse, ni coordonnées, ni position dans la maquette. À demander")
    if maquette is not None:
        ecart = distance_m((lieu.latitude, lieu.longitude), maquette)
        if ecart > ECART_A_SIGNALER_M:
            lieu.remarques.append(
                f"la maquette se dit à {ecart / 1000.0:.1f} km de là ({maquette[0]:.4f}, {maquette[1]:.4f}) : "
                f"sa position est ignorée, le lieu donné fait foi")
    return lieu
