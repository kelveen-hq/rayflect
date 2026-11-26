"""D'autres climats que l'année type : une année réelle, l'été le plus chaud des dernières années, le climat de 2045.

Une mesure passive se choisit pour 30 ans. L'année type de PVGIS est faite pour le soleil, pas pour les étés chauds
(voir rayflect.io.meteo) : c'est sous un été réel chaud, et sous le climat qui vient, que la ventilation de nuit,
l'inertie et les protections solaires se départagent.

UNE ANNÉE RÉELLE vient des réanalyses du programme européen Copernicus, servies par l'API d'archives d'Open-Meteo
sous le nom ERA5-Seamless : la température et l'humidité d'ERA5-Land (maille de 0,1°, environ 11 km, depuis 1950),
le vent et le soleil d'ERA5 (0,25°, environ 25 km) [S : open-meteo.com/en/docs/historical-weather-api, lu le
23/11/2026]. Heure par heure : température, rosée, humidité, pression, vent, soleil global, direct et diffus,
nébulosité. Le rayonnement du ciel n'y est pas : il est recalculé comme pour un fichier de PVGIS défectueux
(`meteo.reparer_le_ciel`, 4 % près sur 6 fichiers sains). Le 29 février d'une année bissextile est retiré : le
calcul prend 365 jours.

LE CLIMAT DE 2045 se fabrique par la méthode de Belcher, Hacker et Powell [S : « Constructing design weather data
for future climates », Building Services Engineering Research and Technology 26(1), 2005, p. 49-61], celle des
fichiers météo futurs des bureaux d'études, appliquée à 2 années :
  - « futur » : l'année type de PVGIS, une année ordinaire de la décennie 2040 ;
  - « futur_chaud » : l'été réel le plus chaud depuis 2000, sa canicule dans le climat de 2045. Une année réelle garde
    ce que l'année type et la moyenne des modèles lissent : la suite des jours chauds et de leurs nuits, avec le
    soleil et l'humidité qui vont avec.
Pour chaque mois m, les modèles climatiques donnent l'écart entre les années de départ et 2040 à 2049 de la
température moyenne (ΔT), de la maximale (ΔTmax) et de la minimale (ΔTmin). Chaque heure devient :

    T' = T + ΔT + α (T − T_m)        α = (ΔTmax − ΔTmin) / (Tmax_m − Tmin_m)

T_m, Tmax_m et Tmin_m : la moyenne du mois et celles de ses maximales et minimales journalières, dans l'année type.
Les journées gardent leur forme ; elles se décalent et s'étirent comme les modèles le disent. Les écarts sont la
moyenne de 7 modèles CMIP6 HighResMIP, « aussi proches de RCP8.5 que possible dans CMIP6 », ramenés à 10 km et
corrigés de leur biais sur ERA5-Land, ce qui ne change pas leurs écarts [S : open-meteo.com/en/docs/climate-api, lu le
23/11/2026]. L'API s'arrête au 1er janvier 2050 : d'où la décennie 2040, centrée sur 2045.

L'humidité relative est décalée de l'écart du mois, le soleil (global, direct et diffus) et le vent mis à l'échelle
de leur rapport, comme Belcher le fait ; la rosée suit. La pression ne bouge pas [H]. Chaque grandeur est la moyenne
des modèles qui la donnent (6 sur 7 pour le soleil).

À SAVOIR. Les données d'Open-Meteo sont sous licence CC BY 4.0, gratuites pour un usage non commercial ; un usage
commercial demande un abonnement à Open-Meteo. ERA5 relève de la licence Copernicus, les modèles du programme CMIP6.
"""

from __future__ import annotations

import datetime
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

from rayflect.io import meteo

ARCHIVE = "https://archive-api.open-meteo.com/v1/archive"
ESSAIS, ATTENTE_S = 4, 65.0         # [H] la limite de l'API gratuite se compte par minute
MODELE_DU_PASSE = "era5_seamless"  # la température et l'humidité d'ERA5-Land (11 km), le vent et le soleil d'ERA5
CLIMAT = "https://climate-api.open-meteo.com/v1/climate"
MODELES = ("CMCC_CM2_VHR4", "FGOALS_f3_H", "HiRAM_SIT_HR", "MRI_AGCM3_2_S", "EC_Earth3P_HR", "MPI_ESM1_2_XR",
           "NICAM16_8S")
HORAIRES = ("temperature_2m", "relative_humidity_2m", "dew_point_2m", "surface_pressure", "wind_speed_10m",
            "wind_direction_10m", "shortwave_radiation", "direct_normal_irradiance", "diffuse_radiation", "cloud_cover")
PREMIERE_ANNEE = 1940               # ERA5
FUTUR = (2040, 2049)                # l'API climatique s'arrête au 1er janvier 2050
FENETRE_AUTOUR = 7                  # [H] le climat d'une année réelle : les 15 ans qui l'entourent
QUOTIDIENS = {"mean": "temperature_2m_mean", "max": "temperature_2m_max", "min": "temperature_2m_min",
              "humidite": "relative_humidity_2m_mean", "soleil": "shortwave_radiation_sum",
              "vent": "wind_speed_10m_mean"}
RAPPORTS = ("soleil", "vent")       # mis à l'échelle ; les autres sont décalés
ETES_DEPUIS = 2000                  # [H] « les dernières années » : depuis 2000
MOIS_D_ETE = (6, 7, 8)
HEURES = 8760
JOURS_AVANT = (0, 31, 59, 90, 120, 151, 181, 212, 243, 273, 304, 334, 365)
# Colonnes d'un fichier EPW, à partir de 0.
C_ANNEE, C_TEMPERATURE, C_ROSEE, C_HUMIDITE, C_PRESSION = 0, 6, 7, 8, 9
C_GLOBAL, C_DIRECT, C_DIFFUS, C_DIRECTION, C_VENT, C_NUAGES, C_NUAGES_OPAQUES = 13, 14, 15, 20, 21, 22, 23


class ClimatIndisponible(RuntimeError):
    """Le climat demandé ne peut pas être préparé : le message dit pourquoi et quoi faire."""


@dataclass
class Climat:
    """Un fichier météo prêt, et ce qu'il faut en dire."""
    chemin: Path
    nom: str
    remarques: List[str] = field(default_factory=list)


def _demander(url: str, parametres: Dict[str, str], fichier: Path, delai_s: float = 180.0) -> dict:
    """La réponse d'une API, gardée dans `fichier` pour ne pas la redemander."""
    if fichier.exists():
        return json.loads(fichier.read_text(encoding="utf-8"))
    adresse = f"{url}?{urllib.parse.urlencode(parametres)}"
    for essai in range(1, ESSAIS + 1):
        try:
            with urllib.request.urlopen(adresse, timeout=delai_s) as reponse:
                donnees = json.loads(reponse.read())
            break
        except urllib.error.HTTPError as erreur:
            # 429 : la limite par minute de l'API gratuite est atteinte ; elle se lève d'elle-même.
            if erreur.code != 429 or essai == ESSAIS:
                raise ClimatIndisponible(f"Open-Meteo refuse ({erreur}) : réessayer plus tard, ou donner un fichier "
                                         f"météo par [lieu] meteo") from erreur
            time.sleep(ATTENTE_S * essai)
        except OSError as erreur:
            raise ClimatIndisponible(f"Open-Meteo n'a pas répondu ({erreur}) : réessayer plus tard, ou donner un "
                                     f"fichier météo par [lieu] meteo") from erreur
    if donnees.get("error"):
        raise ClimatIndisponible(f"Open-Meteo refuse la demande : {donnees.get('reason')}")
    fichier.parent.mkdir(parents=True, exist_ok=True)
    fichier.write_text(json.dumps(donnees), encoding="utf-8")
    return donnees


def _fuseau(lignes: Sequence[str]) -> float:
    """Le fuseau du fichier, en heures (champ 9 de la ligne LOCATION) : ses heures sont en heure normale locale."""
    return float(lignes[0].split(",")[8])


def _ecrire(lignes_d_en_tete: Sequence[str], donnees: List[List[str]], commentaire: str, sortie: Path) -> Path:
    en_tete = list(lignes_d_en_tete)
    en_tete[6] = f"COMMENTS 2,{commentaire}"
    sortie.parent.mkdir(parents=True, exist_ok=True)
    sortie.write_text("\n".join(en_tete + [",".join(d) for d in donnees]) + "\n", encoding="utf-8")
    return sortie


def _type(chemin_type: Path) -> Tuple[List[str], List[List[str]]]:
    lignes = Path(chemin_type).read_text(encoding="utf-8", errors="replace").splitlines()
    donnees = [ligne.split(",") for ligne in lignes[meteo.LIGNES_D_EN_TETE:meteo.LIGNES_D_EN_TETE + HEURES]]
    if len(donnees) != HEURES:
        raise ClimatIndisponible(f"l'année type {Path(chemin_type).name} n'a pas 8 760 heures")
    return lignes[:meteo.LIGNES_D_EN_TETE], donnees


def annee_reelle(latitude: float, longitude: float, annee: int, chemin_type: Path, dossier: Path) -> Climat:
    """L'année `annee` heure par heure, au format de l'année type du lieu (son en-tête, ses heures locales)."""
    derniere = datetime.date.today().year - 1
    if not PREMIERE_ANNEE <= annee <= derniere:
        raise ClimatIndisponible(f"année {annee} : ERA5 couvre de {PREMIERE_ANNEE} à {derniere} en années entières")
    en_tete, donnees = _type(chemin_type)
    reponse = _demander(ARCHIVE, {
        "latitude": f"{latitude:.4f}", "longitude": f"{longitude:.4f}", "start_date": f"{annee - 1}-12-31",
        "end_date": f"{annee + 1}-01-01", "hourly": ",".join(HORAIRES), "wind_speed_unit": "ms", "timezone": "GMT",
        "models": MODELE_DU_PASSE}, Path(dossier) / f"era5s_{latitude:.3f}_{longitude:.3f}_{annee}.json")
    horaire = reponse["hourly"]
    rang = {t: k for k, t in enumerate(horaire["time"])}
    # Une ligne EPW porte l'heure qui FINIT à son heure, en heure normale locale. ERA5 donne les températures à
    # l'instant et le soleil en moyenne de l'heure qui finit à l'instant, en temps universel.
    fuseau = datetime.timedelta(hours=_fuseau(en_tete))
    debut = datetime.datetime(annee, 1, 1)
    sortie_lignes: List[List[str]] = []
    heure = 0
    while len(sortie_lignes) < HEURES:
        local = debut + datetime.timedelta(hours=heure + 1)
        heure += 1
        commence = local - datetime.timedelta(hours=1)
        if commence.month == 2 and commence.day == 29:
            continue                # 365 jours : le 29 février est retiré
        cle = (local - fuseau).strftime("%Y-%m-%dT%H:00")
        if cle not in rang:
            raise ClimatIndisponible(f"ERA5 : l'heure {cle} manque dans la réponse")
        k = rang[cle]
        valeurs = {nom: horaire[nom][k] for nom in HORAIRES}
        if any(v is None for v in valeurs.values()):
            raise ClimatIndisponible(f"ERA5 : une valeur manque le {cle} ; prendre une autre année")
        ligne = list(donnees[len(sortie_lignes)])
        ligne[C_ANNEE] = str(annee)
        ligne[C_TEMPERATURE] = f"{valeurs['temperature_2m']:.1f}"
        ligne[C_ROSEE] = f"{valeurs['dew_point_2m']:.1f}"
        ligne[C_HUMIDITE] = f"{valeurs['relative_humidity_2m']:.0f}"
        ligne[C_PRESSION] = f"{valeurs['surface_pressure'] * 100.0:.0f}"
        ligne[C_GLOBAL] = f"{valeurs['shortwave_radiation']:.0f}"
        ligne[C_DIRECT] = f"{valeurs['direct_normal_irradiance']:.0f}"
        ligne[C_DIFFUS] = f"{valeurs['diffuse_radiation']:.0f}"
        ligne[C_DIRECTION] = f"{valeurs['wind_direction_10m']:.0f}"
        ligne[C_VENT] = f"{valeurs['wind_speed_10m']:.1f}"
        nuages = round(valeurs["cloud_cover"] / 10.0)
        ligne[C_NUAGES] = ligne[C_NUAGES_OPAQUES] = str(nuages)
        sortie_lignes.append(ligne)
    brut = _ecrire(en_tete, sortie_lignes, f"Rayflect : annee reelle {annee}, ERA5 par Open-Meteo (CC BY 4.0)",
                   Path(dossier) / f"era5_{latitude:.3f}_{longitude:.3f}_{annee}_brut.epw")
    chemin = meteo.reparer_le_ciel(brut, Path(dossier) / f"era5_{latitude:.3f}_{longitude:.3f}_{annee}.epw")
    ete = _moyenne_d_ete([float(d[C_TEMPERATURE]) for d in sortie_lignes])
    type_ete = _moyenne_d_ete([float(d[C_TEMPERATURE]) for d in donnees])
    return Climat(chemin, f"année {annee}", [
        f"année réelle {annee} : ERA5-Land et ERA5 (Copernicus) par Open-Meteo, température et humidité sur une maille "
        f"d'environ 11 km autour de {reponse['latitude']:.2f}, {reponse['longitude']:.2f}, vent et soleil sur 25 km ; "
        f"rayonnement du ciel recalculé depuis l'humidité et la clarté du jour",
        f"été {annee} (juin à août) : {ete:.1f} °C en moyenne, contre {type_ete:.1f} °C dans l'année type ; "
        f"{chaleur([float(d[C_TEMPERATURE]) for d in sortie_lignes])}, contre "
        f"{chaleur([float(d[C_TEMPERATURE]) for d in donnees])} dans l'année type",
        "données Open-Meteo sous licence CC BY 4.0, gratuites pour un usage non commercial"])


# Les seuils des indicateurs de Météo-France [S : Météo-France, glossaire : « jour de forte chaleur » au-delà de 30 °C,
# « nuit tropicale » quand la minimale reste au-dessus de 20 °C] ; 35 °C : la vague de chaleur forte [H].
JOUR_CHAUD_C, JOUR_TRES_CHAUD_C, NUIT_CHAUDE_C = 30.0, 35.0, 20.0


def chaleur(temperatures: Sequence[float]) -> str:
    """Les jours à 30 et 35 °C ou plus, et les nuits qui ne descendent pas sous 20 °C, sur l'année."""
    jours = [temperatures[k:k + 24] for k in range(0, len(temperatures) - 23, 24)]
    return (f"{sum(1 for j in jours if max(j) >= JOUR_CHAUD_C)} jours à 30 °C ou plus, "
            f"{sum(1 for j in jours if max(j) >= JOUR_TRES_CHAUD_C)} à 35 °C ou plus, "
            f"{sum(1 for j in jours if min(j) > NUIT_CHAUDE_C)} nuits au-dessus de 20 °C")


def _moyenne_d_ete(temperatures: Sequence[float]) -> float:
    debut, fin = JOURS_AVANT[MOIS_D_ETE[0] - 1] * 24, JOURS_AVANT[MOIS_D_ETE[-1]] * 24
    return sum(temperatures[debut:fin]) / (fin - debut)


def etes(latitude: float, longitude: float, dossier: Path, depuis: int = ETES_DEPUIS,
         jusqu_a: Optional[int] = None) -> Dict[int, float]:
    """La température moyenne de chaque été (juin à août) d'ERA5, de `depuis` à la dernière année entière."""
    jusqu_a = jusqu_a or datetime.date.today().year - 1
    reponse = _demander(ARCHIVE, {
        "latitude": f"{latitude:.4f}", "longitude": f"{longitude:.4f}", "start_date": f"{depuis}-01-01",
        "end_date": f"{jusqu_a}-12-31", "daily": "temperature_2m_mean", "timezone": "GMT", "models": MODELE_DU_PASSE},
        Path(dossier) / f"era5s_etes_{latitude:.3f}_{longitude:.3f}_{depuis}_{jusqu_a}.json")
    par_annee: Dict[int, List[float]] = {}
    for jour, t in zip(reponse["daily"]["time"], reponse["daily"]["temperature_2m_mean"]):
        if t is not None and int(jour[5:7]) in MOIS_D_ETE:
            par_annee.setdefault(int(jour[:4]), []).append(t)
    return {a: sum(v) / len(v) for a, v in sorted(par_annee.items()) if len(v) >= 90}


def ete_le_plus_chaud(latitude: float, longitude: float, chemin_type: Path, dossier: Path) -> Climat:
    """L'année réelle dont l'été a été le plus chaud depuis 2000."""
    moyennes = etes(latitude, longitude, dossier)
    if not moyennes:
        raise ClimatIndisponible("ERA5 n'a rendu aucun été complet")
    classes = sorted(moyennes.items(), key=lambda e: -e[1])
    climat = annee_reelle(latitude, longitude, classes[0][0], chemin_type, dossier)
    climat.nom = f"l'été le plus chaud ({classes[0][0]})"
    climat.remarques.insert(0, f"l'été le plus chaud depuis {min(moyennes)} : " + ", ".join(
        f"{a} ({t:.1f} °C)" for a, t in classes[:3]) + f" ; moyenne des étés {sum(moyennes.values()) / len(moyennes):.1f} °C")
    return climat


def _par_mois(jours: Sequence[str], valeurs: Sequence[Optional[float]], annees: Tuple[int, int]) -> List[Optional[float]]:
    """La moyenne de chaque mois sur les années données, ou None si le modèle n'a rien rendu."""
    sommes, comptes = [0.0] * 12, [0] * 12
    for jour, v in zip(jours, valeurs):
        if v is not None and annees[0] <= int(jour[:4]) <= annees[1]:
            sommes[int(jour[5:7]) - 1] += v
            comptes[int(jour[5:7]) - 1] += 1
    return [s / c if c else None for s, c in zip(sommes, comptes)]


def _quotidien(latitude: float, longitude: float, annees: Tuple[int, int], dossier: Path) -> dict:
    """Les grandeurs quotidiennes des 7 modèles sur ces années, gardées dans le cache."""
    return _demander(CLIMAT, {
        "latitude": f"{latitude:.4f}", "longitude": f"{longitude:.4f}", "start_date": f"{annees[0]}-01-01",
        "end_date": f"{annees[1]}-12-31", "models": ",".join(MODELES), "wind_speed_unit": "ms",
        "daily": ",".join(QUOTIDIENS.values())},
        Path(dossier) / f"cmip6_{latitude:.3f}_{longitude:.3f}_{annees[0]}_{annees[1]}.json")["daily"]


def ecarts_des_modeles(latitude: float, longitude: float, base: Tuple[int, int], dossier: Path,
                       futur: Tuple[int, int] = FUTUR) -> Dict[str, Dict[str, List[float]]]:
    """Par modèle, mois par mois, de `base` à `futur` : les écarts de la température moyenne, maximale et minimale
    (« mean », « max », « min », en K), de l'humidité relative (« humidite », en points), et les rapports du soleil
    (« soleil ») et du vent (« vent »). Un modèle sans une grandeur ne la donne pas ; sans les températures, il est écarté.
    """
    # 2 demandes, l'une pour les années de départ, l'autre pour l'horizon : l'API compte une demande au poids de ses
    # jours et de ses grandeurs, et la décennie de l'horizon se garde pour tous les climats futurs du lieu.
    passe, vient = _quotidien(latitude, longitude, base, dossier), _quotidien(latitude, longitude, futur, dossier)
    rendu = {}
    for modele in MODELES:
        ecarts: Dict[str, List[float]] = {}
        for grandeur, variable in QUOTIDIENS.items():
            serie_avant, serie_apres = passe.get(f"{variable}_{modele}"), vient.get(f"{variable}_{modele}")
            if serie_avant is None or serie_apres is None:
                continue
            avant = _par_mois(passe["time"], serie_avant, base)
            apres = _par_mois(vient["time"], serie_apres, futur)
            if any(v is None for v in avant + apres):
                continue
            if grandeur in RAPPORTS:
                ecarts[grandeur] = [b / a if a > 0 else 1.0 for a, b in zip(avant, apres)]
            else:
                ecarts[grandeur] = [b - a for a, b in zip(avant, apres)]
        if all(g in ecarts for g in ("mean", "max", "min")):
            rendu[modele] = ecarts
    if not rendu:
        raise ClimatIndisponible("aucun modèle climatique n'a rendu ses températures pour ce lieu")
    return rendu


def ensemble(modeles: Dict[str, Dict[str, List[float]]]) -> Dict[str, List[float]]:
    """La moyenne des modèles, grandeur par grandeur, sur ceux qui la donnent. Sans aucun : pas de changement."""
    rendu = {}
    for grandeur in QUOTIDIENS:
        donnent = [m[grandeur] for m in modeles.values() if grandeur in m]
        neutre = 1.0 if grandeur in RAPPORTS else 0.0
        rendu[grandeur] = [sum(d[k] for d in donnent) / len(donnent) for k in range(12)] if donnent else [neutre] * 12
        rendu[f"{grandeur}_modeles"] = [float(len(donnent))] * 12
    return rendu


def deformer(temperatures: Sequence[float], ecart: Sequence[float], ecart_max: Sequence[float],
             ecart_min: Sequence[float]) -> List[float]:
    """La méthode de Belcher : chaque heure décalée de l'écart du mois et étirée de l'écart entre max et min."""
    rendu = list(temperatures)
    for m in range(12):
        debut, fin = JOURS_AVANT[m] * 24, JOURS_AVANT[m + 1] * 24
        mois = temperatures[debut:fin]
        jours = [mois[k:k + 24] for k in range(0, len(mois), 24)]
        moyenne = sum(mois) / len(mois)
        amplitude = sum(max(j) for j in jours) / len(jours) - sum(min(j) for j in jours) / len(jours)
        alpha = (ecart_max[m] - ecart_min[m]) / amplitude if amplitude > 0 else 0.0
        for h in range(debut, fin):
            rendu[h] = temperatures[h] + ecart[m] + alpha * (temperatures[h] - moyenne)
    return rendu


def morpher(donnees: List[List[str]], e: Dict[str, List[float]]) -> List[List[str]]:
    """Toutes les grandeurs d'une année, déformées vers le futur [S : Belcher et al. 2005, §3] :
    la température décalée et étirée, l'humidité relative décalée, le soleil et le vent mis à l'échelle. La rosée suit
    la température et l'humidité nouvelles ; la pression ne bouge pas."""
    avant = [float(d[C_TEMPERATURE]) for d in donnees]
    apres = deformer(avant, e["mean"], e["max"], e["min"])
    rendu = []
    for h, (d, t) in enumerate(zip(donnees, apres)):
        m = next(k for k in range(12) if JOURS_AVANT[k] * 24 <= h < JOURS_AVANT[k + 1] * 24)
        ligne = list(d)
        humidite = min(100.0, max(1.0, float(d[C_HUMIDITE]) + e["humidite"][m]))
        ligne[C_TEMPERATURE] = f"{t:.1f}"
        ligne[C_HUMIDITE] = f"{humidite:.0f}"
        ligne[C_ROSEE] = f"{meteo._rosee(t, humidite):.1f}"
        for colonne in (C_GLOBAL, C_DIRECT, C_DIFFUS):
            ligne[colonne] = f"{float(d[colonne]) * e['soleil'][m]:.0f}"
        ligne[C_VENT] = f"{float(d[C_VENT]) * e['vent'][m]:.1f}"
        rendu.append(ligne)
    return rendu


def _dire_les_ecarts(modeles: Dict[str, Dict[str, List[float]]], e: Dict[str, List[float]], base, horizon,
                     avant: Sequence[float], apres: Sequence[float]) -> List[str]:
    def ete(serie: Sequence[float]) -> float:
        return sum(serie[m - 1] for m in MOIS_D_ETE) / len(MOIS_D_ETE)

    par_modele = sorted(ete(m["mean"]) for m in modeles.values())
    return [
        f"écarts de {len(modeles)} modèles CMIP6 HighResMIP (au plus près de RCP8.5) entre {base[0]}-{base[1]} et "
        f"{horizon[0]}-{horizon[1]}, méthode de Belcher (2005)",
        f"été (juin à août) : +{ete(e['mean']):.1f} °C en moyenne des modèles, de +{par_modele[0]:.1f} à "
        f"+{par_modele[-1]:.1f} °C selon le modèle ; humidité relative {ete(e['humidite']):+.1f} points, soleil "
        f"{(ete(e['soleil']) - 1) * 100:+.0f} %, vent {(ete(e['vent']) - 1) * 100:+.0f} % "
        f"({e['soleil_modeles'][0]:.0f} modèles donnent le soleil)",
        f"été du fichier déformé : {_moyenne_d_ete(apres):.1f} °C en moyenne, contre {_moyenne_d_ete(avant):.1f} °C ; "
        f"maximum {max(apres):.1f} °C, contre {max(avant):.1f} °C ; {chaleur(apres)}, contre {chaleur(avant)}",
        "données Open-Meteo et CMIP6 sous licence CC BY 4.0, gratuites pour un usage non commercial"]


def _vers(en_tete, donnees, latitude, longitude, base, dossier, horizon, nom_du_fichier, commentaire):
    modeles = ecarts_des_modeles(latitude, longitude, base, dossier, horizon)
    e = ensemble(modeles)
    deformees = morpher(donnees, e)
    brut = _ecrire(en_tete, deformees, commentaire, Path(dossier) / f"{nom_du_fichier}_brut.epw")
    chemin = meteo.reparer_le_ciel(brut, Path(dossier) / f"{nom_du_fichier}.epw")
    avant = [float(d[C_TEMPERATURE]) for d in donnees]
    apres = [float(d[C_TEMPERATURE]) for d in deformees]
    return chemin, _dire_les_ecarts(modeles, e, base, horizon, avant, apres)


def futur(latitude: float, longitude: float, chemin_type: Path, dossier: Path, horizon: Tuple[int, int] = FUTUR) -> Climat:
    """L'année type du lieu, déformée vers le climat de `horizon` : une année ordinaire de la décennie 2040."""
    en_tete, donnees = _type(chemin_type)
    annees = sorted({int(d[C_ANNEE]) for d in donnees})
    base = (annees[0], annees[-1])
    chemin, dits = _vers(en_tete, donnees, latitude, longitude, base, dossier, horizon,
                         f"futur_{latitude:.3f}_{longitude:.3f}_{horizon[0]}_{horizon[1]}",
                         f"Rayflect : annee type deformee vers {horizon[0]}-{horizon[1]} (Belcher 2005), CMIP6 par Open-Meteo")
    return Climat(chemin, f"climat {horizon[0]}-{horizon[1]}",
                  [f"climat {horizon[0]}-{horizon[1]} : l'année type déformée, une année ordinaire de la décennie"] + dits)


def futur_chaud(latitude: float, longitude: float, chemin_type: Path, dossier: Path,
                horizon: Tuple[int, int] = FUTUR) -> Climat:
    """L'été réel le plus chaud depuis 2000, déformé vers le climat de `horizon` : sa canicule dans le climat qui vient.

    Une année réelle garde ce qu'une année type et une moyenne de modèles lissent : la suite des jours de canicule,
    leurs nuits chaudes, un soleil et une humidité qui vont avec. Elle est décalée de ce que le climat a gagné entre
    les années qui l'entourent (7 ans avant et après) et la décennie `horizon`.
    """
    chaud = ete_le_plus_chaud(latitude, longitude, chemin_type, dossier)
    annee = int(chaud.nom.rsplit("(", 1)[1].rstrip(")"))
    en_tete, donnees = _type(chaud.chemin)
    base = (max(1950, annee - FENETRE_AUTOUR), min(horizon[0] - 1, annee + FENETRE_AUTOUR))
    chemin, dits = _vers(en_tete, donnees, latitude, longitude, base, dossier, horizon,
                         f"futur_chaud_{latitude:.3f}_{longitude:.3f}_{annee}_{horizon[0]}_{horizon[1]}",
                         f"Rayflect : ete {annee} deforme vers {horizon[0]}-{horizon[1]} (Belcher 2005), ERA5 et CMIP6 "
                         f"par Open-Meteo")
    return Climat(chemin, f"l'été {annee} en {horizon[0]}-{horizon[1]}", [
        f"l'été {annee}, le plus chaud depuis 2000, dans le climat {horizon[0]}-{horizon[1]} : sa canicule, décalée de "
        f"ce que le climat gagne d'ici là"] + chaud.remarques[:1] + dits)


CLIMATS = ("type", "ete_le_plus_chaud", "futur", "futur_chaud")


def nom_valide(climat) -> bool:
    """`climat` : "type", "ete_le_plus_chaud", "futur", "futur_chaud", ou une année entière."""
    if isinstance(climat, bool):
        return False
    if isinstance(climat, int):
        return True
    return isinstance(climat, str) and (climat in CLIMATS or (climat.isdigit() and len(climat) == 4))


def preparer(climat, latitude: float, longitude: float, chemin_type: Path, dossier: Path) -> Climat:
    """Le climat demandé, à partir de l'année type du lieu. "type" la rend telle quelle."""
    if climat == "type":
        return Climat(Path(chemin_type), "année type")
    if climat == "ete_le_plus_chaud":
        return ete_le_plus_chaud(latitude, longitude, chemin_type, dossier)
    if climat == "futur":
        return futur(latitude, longitude, chemin_type, dossier)
    if climat == "futur_chaud":
        return futur_chaud(latitude, longitude, chemin_type, dossier)
    if isinstance(climat, int) or (isinstance(climat, str) and climat.isdigit()):
        return annee_reelle(latitude, longitude, int(climat), chemin_type, dossier)
    raise ClimatIndisponible(f"climat « {climat} » : type, ete_le_plus_chaud, futur, futur_chaud, ou une année (2022)")
