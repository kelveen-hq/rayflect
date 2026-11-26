"""Des besoins de chaleur et de froid à ce que le bâtiment consomme, émet et paie.

Le calcul thermique rend des BESOINS : la chaleur à fournir aux pièces, la chaleur à en retirer. Ce module les
convertit en énergie achetée (par le rendement du système), en CO2 (par le facteur d'émission de l'énergie)
et en euros (par son prix).

CE QUI EST COMPTÉ : le chauffage et la climatisation. Pas l'éclairage, ni les ventilateurs, ni l'eau chaude,
ni les équipements : ce n'est pas la facture du bâtiment, c'est la part que les protections solaires
déplacent.

D'OÙ VIENNENT LES PRIX. Un prix donné par l'utilisateur passe avant tout. Sinon, pour l'électricité et le gaz,
le prix moyen du pays est pris à Eurostat : une moyenne nationale par tranche de consommation, publiée par
semestre. Ce n'est pas le contrat du bâtiment. Pour les autres énergies, aucun prix n'est supposé : sans prix
donné, le résultat sort en kWh et en CO2, et dit que les euros manquent.

CE QUE CE MODULE NE FAIT PAS : chiffrer ce que coûte une protection, ni un temps de retour.
"""

from __future__ import annotations

import json
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional

from rayflect import cache

# Facteurs d'émission, en kgCO2 par kWh d'énergie finale.
# [S] arrêté du 31 mars 2021 modifiant diverses dispositions relatives au diagnostic de performance
# énergétique (JO du 13 avril 2021, NOR LOGL2107220A), art. 1er, 9° : tableau de la partie 1.1 de l'annexe 4
# de l'arrêté du 15 septembre 2006. Lu dans le texte le 15/11/2026. Valables pour la France métropolitaine.
FACTEURS_KGCO2_KWH = {
    "gaz": 0.227,
    "fioul": 0.324,
    "propane": 0.272,
    "bois": 0.030,                      # bûches et granulés ; plaquettes : 0,024
    "electricite_chauffage": 0.079,
    "electricite_refroidissement": 0.064,
}
SOURCE_DES_FACTEURS = "arrêté du 31 mars 2021 relatif au DPE, annexe 4, tableau 1.1 [S]"
PAYS_DES_FACTEURS = "FR"

# Systèmes de chauffage : énergie achetée, et chaleur rendue par kWh acheté.
# [H] ordres de grandeur sans source, à remplacer par le rendement du système réel (rendement_chauffage).
SYSTEMES_DE_CHAUFFAGE = {
    "gaz": ("gaz", 0.90, "chaudière gaz à condensation"),
    "gaz_ancien": ("gaz", 0.75, "chaudière gaz ancienne"),
    "fioul": ("fioul", 0.80, "chaudière fioul"),
    "propane": ("propane", 0.90, "chaudière propane"),
    "bois": ("bois", 0.75, "chaudière bois"),
    "electrique": ("electricite", 1.00, "convecteurs ou panneaux électriques"),
    "pac": ("electricite", 3.00, "pompe à chaleur, rendement de saison"),
    "reseau_de_chaleur": ("reseau_de_chaleur", 0.95, "sous-station de réseau de chaleur"),
}
RENDEMENT_CLIMATISATION = 3.0           # [H] froid rendu par kWh d'électricité, moyenne de saison
PCS_SUR_PCI_DU_GAZ = 1.11               # [C] le gaz se facture au pouvoir calorifique supérieur
KWH_PAR_GJ = 1000.0 / 3.6

EUROSTAT = "https://ec.europa.eu/eurostat/api/dissemination/statistics/1.0/data"
# (table, tranches par plafond de consommation annuelle en kWh). Vérifié sur l'API le 15/11/2026.
TABLES = {
    ("electricite", False): ("nrg_pc_205", [(20e3, "MWH_LT20"), (500e3, "MWH20-499"), (2000e3, "MWH500-1999"),
                                            (20000e3, "MWH2000-19999"), (70000e3, "MWH20000-69999"),
                                            (150000e3, "MWH70000-149999"), (float("inf"), "MWH_GE150000")]),
    ("electricite", True): ("nrg_pc_204", [(1000, "KWH_LT1000"), (2500, "KWH1000-2499"), (5000, "KWH2500-4999"),
                                           (15000, "KWH5000-14999"), (float("inf"), "KWH_GE15000")]),
    ("gaz", False): ("nrg_pc_203", [(1000 * KWH_PAR_GJ, "GJ_LT1000"), (10000 * KWH_PAR_GJ, "GJ1000-9999"),
                                    (100000 * KWH_PAR_GJ, "GJ10000-99999"),
                                    (1000000 * KWH_PAR_GJ, "GJ100000-999999"),
                                    (4000000 * KWH_PAR_GJ, "GJ1000000-3999999"), (float("inf"), "GJ_GE4000000")]),
    ("gaz", True): ("nrg_pc_202", [(20 * KWH_PAR_GJ, "GJ_LT20"), (200 * KWH_PAR_GJ, "GJ20-199"),
                                   (float("inf"), "GJ_GE200")]),
}
DUREE_DU_CACHE_S = 30 * 24 * 3600.0     # le prix est semestriel : le redemander chaque mois suffit
NOMS = {"gaz": "de gaz", "fioul": "de fioul", "propane": "de propane", "bois": "de bois",
        "electricite": "d'électricité", "reseau_de_chaleur": "de réseau de chaleur"}


class EnergieInvalide(ValueError):
    """La description de l'énergie ne peut pas être suivie : le message dit quoi corriger."""


@dataclass(frozen=True)
class Energie:
    """Avec quoi le bâtiment est chauffé et refroidi, et à quel prix si on le sait."""
    chauffage: str = "gaz"                                  # clé de SYSTEMES_DE_CHAUFFAGE
    rendement_chauffage: Optional[float] = None
    rendement_climatisation: Optional[float] = None
    prix_chauffage_eur_kwh: Optional[float] = None          # prix de l'énergie de chauffage, tel que facturé
    prix_electricite_eur_kwh: Optional[float] = None
    facteur_chauffage_kgco2_kwh: Optional[float] = None     # à donner pour un réseau de chaleur, ou hors de France
    facteur_electricite_kgco2_kwh: Optional[float] = None
    pays: str = "FR"                                        # code du pays pour les prix d'Eurostat

    def __post_init__(self):
        if self.chauffage not in SYSTEMES_DE_CHAUFFAGE:
            raise EnergieInvalide(
                f"chauffage inconnu : « {self.chauffage} ». Connus : {', '.join(SYSTEMES_DE_CHAUFFAGE)}")
        for nom in ("rendement_chauffage", "rendement_climatisation", "prix_chauffage_eur_kwh",
                    "prix_electricite_eur_kwh"):
            valeur = getattr(self, nom)
            if valeur is not None and (isinstance(valeur, bool) or valeur <= 0):
                raise EnergieInvalide(f"{nom} : {valeur} n'est pas une valeur possible")
        for nom in ("facteur_chauffage_kgco2_kwh", "facteur_electricite_kgco2_kwh"):
            valeur = getattr(self, nom)
            if valeur is not None and (isinstance(valeur, bool) or valeur < 0):
                raise EnergieInvalide(f"{nom} : {valeur} n'est pas une valeur possible")

    @property
    def energie_de_chauffage(self) -> str:
        return SYSTEMES_DE_CHAUFFAGE[self.chauffage][0]

    @property
    def rendement_de_chauffage(self) -> float:
        return self.rendement_chauffage or SYSTEMES_DE_CHAUFFAGE[self.chauffage][1]

    @property
    def rendement_de_climatisation(self) -> float:
        return self.rendement_climatisation or RENDEMENT_CLIMATISATION


@dataclass(frozen=True)
class Prix:
    eur_kwh: float
    origine: str


def _demander(adresse: str, delai_s: float) -> dict:
    with urllib.request.urlopen(adresse, timeout=delai_s) as reponse:
        return json.loads(reponse.read().decode("utf-8"))


def _dernier(reponse: dict) -> Optional[tuple]:
    """(prix, semestre) le plus récent d'une réponse d'Eurostat qui ne porte qu'une série."""
    valeurs = reponse.get("value") or {}
    semestres = reponse["dimension"]["time"]["category"]["index"]
    connus = [(rang, nom) for nom, rang in semestres.items() if valeurs.get(str(rang)) is not None]
    if not connus:
        return None
    rang, nom = max(connus)
    return float(valeurs[str(rang)]), nom


def prix_eurostat(energie: str, pays: str, consommation_kwh: float, menage: bool, dossier=None,
                  delai_s: float = 40.0) -> Optional[Prix]:
    """Le prix moyen du pays pour cette énergie et cette consommation annuelle, ou None s'il n'est pas connu.

    Ménages : toutes taxes comprises. Autres consommateurs : hors TVA et taxes récupérables.
    """
    if (energie, menage) not in TABLES:
        return None
    table, tranches = TABLES[(energie, menage)]
    tranche = next(code for plafond, code in tranches if consommation_kwh < plafond)
    taxes = "I_TAX" if menage else "X_VAT"
    fichier = Path(dossier or cache.dossier("prix")) / f"{table}_{pays}_{taxes}_{tranche}.json"
    garde = json.loads(fichier.read_text(encoding="utf-8")) if fichier.exists() else None
    trop_vieux = ""
    if garde is None or time.time() - garde["lu_le"] > DUREE_DU_CACHE_S:
        requete = urllib.parse.urlencode({"format": "JSON", "geo": pays, "unit": "KWH", "currency": "EUR",
                                          "tax": taxes, "nrg_cons": tranche, "lastTimePeriod": "6"})
        try:
            dernier = _dernier(_demander(f"{EUROSTAT}/{table}?{requete}", delai_s))
        except (OSError, ValueError, KeyError):
            dernier = None
            trop_vieux = " ; Eurostat ne répond pas, valeur gardée d'une lecture précédente" if garde else ""
        if dernier is not None:
            garde = {"eur_kwh": dernier[0], "semestre": dernier[1], "lu_le": time.time()}
            fichier.parent.mkdir(parents=True, exist_ok=True)
            fichier.write_text(json.dumps(garde), encoding="utf-8")
    if garde is None:
        return None
    qui = "ménages, toutes taxes comprises" if menage else "entreprises, hors TVA"
    return Prix(garde["eur_kwh"], f"Eurostat {table}, {pays}, {garde['semestre']}, tranche {tranche}, {qui} : "
                                  f"moyenne nationale, pas le contrat du bâtiment ; tranche choisie sur le chauffage "
                                  f"et la climatisation seuls, un bâtiment qui consomme davantage paie moins "
                                  f"cher{trop_vieux}")


def consommations(besoin_chauffage_kwh: float, besoin_froid_kwh: float, config: Energie) -> Dict[str, float]:
    """L'énergie achetée par an, par énergie, en kWh tels que comptés par le facteur d'émission."""
    achete = {config.energie_de_chauffage: besoin_chauffage_kwh / config.rendement_de_chauffage}
    froid = besoin_froid_kwh / config.rendement_de_climatisation
    if froid > 0:
        achete["electricite"] = achete.get("electricite", 0.0) + froid
    return achete


def prix_de_l_etude(config: Energie, consommation_de_reference: Dict[str, float], menage: bool,
                    dossier=None) -> Dict[str, Optional[Prix]]:
    """Le prix de chaque énergie de l'étude : celui donné, sinon celui d'Eurostat, sinon None.

    Un seul prix par énergie pour tous les scénarios, pris à la consommation du scénario de référence :
    sinon un changement de tranche se lirait comme un effet de la protection.
    """
    prix: Dict[str, Optional[Prix]] = {}
    for energie, kwh in consommation_de_reference.items():
        donne = config.prix_electricite_eur_kwh if energie == "electricite" else None
        if energie == config.energie_de_chauffage and config.prix_chauffage_eur_kwh is not None:
            donne = config.prix_chauffage_eur_kwh
        if donne is not None:
            prix[energie] = Prix(float(donne), "donné")
        else:
            prix[energie] = prix_eurostat(energie, config.pays, kwh, menage, dossier)
    return prix


def bilan(besoin_chauffage_kwh: float, besoin_froid_kwh: float, config: Energie,
          prix: Dict[str, Optional[Prix]]) -> dict:
    """Énergie achetée, CO2 et euros d'un scénario. Une grandeur qui ne peut pas être établie vaut None."""
    chaleur = besoin_chauffage_kwh / config.rendement_de_chauffage
    froid = besoin_froid_kwh / config.rendement_de_climatisation
    energie = config.energie_de_chauffage
    en_france = config.pays == PAYS_DES_FACTEURS

    facteur_chaleur = config.facteur_chauffage_kgco2_kwh
    if facteur_chaleur is None and energie == "electricite":
        facteur_chaleur = config.facteur_electricite_kgco2_kwh
    if facteur_chaleur is None and en_france:
        facteur_chaleur = FACTEURS_KGCO2_KWH.get("electricite_chauffage" if energie == "electricite" else energie)
    facteur_froid = config.facteur_electricite_kgco2_kwh
    if facteur_froid is None and en_france:
        facteur_froid = FACTEURS_KGCO2_KWH["electricite_refroidissement"]
    co2 = None
    if facteur_chaleur is not None and (froid == 0 or facteur_froid is not None):
        co2 = round(chaleur * facteur_chaleur + froid * (facteur_froid or 0.0))

    facture = chaleur * (PCS_SUR_PCI_DU_GAZ if energie == "gaz" else 1.0)
    prix_chaleur, prix_froid = prix.get(energie), prix.get("electricite")
    euros = None
    if prix_chaleur is not None and (froid == 0 or prix_froid is not None):
        euros = round(facture * prix_chaleur.eur_kwh + froid * (prix_froid.eur_kwh if prix_froid else 0.0))
    return {"chauffage_kwh": round(chaleur), "energie_de_chauffage": energie, "climatisation_kwh": round(froid),
            "kgco2": co2, "euros": euros}


def justification(config: Energie, prix: Dict[str, Optional[Prix]], climatise: bool) -> List[str]:
    """Ce qui a servi à convertir les besoins, valeur par valeur, avec son origine."""
    energie = config.energie_de_chauffage
    nom = SYSTEMES_DE_CHAUFFAGE[config.chauffage][2]
    lignes = [f"chauffage : {nom}, {config.rendement_de_chauffage:g} kWh de chaleur par kWh acheté "
              f"({'donné' if config.rendement_chauffage else '[H]'})"]
    if climatise:
        lignes.append(f"climatisation électrique : {config.rendement_de_climatisation:g} kWh de froid par kWh acheté "
                      f"({'donné' if config.rendement_climatisation else '[H]'})")
    if config.facteur_chauffage_kgco2_kwh is not None or config.facteur_electricite_kgco2_kwh is not None:
        lignes.append("facteurs d'émission donnés pour : "
                      + ", ".join(n for n, v in (("le chauffage", config.facteur_chauffage_kgco2_kwh),
                                                 ("l'électricité", config.facteur_electricite_kgco2_kwh))
                                  if v is not None))
    if config.pays == PAYS_DES_FACTEURS:
        lignes.append(f"facteurs d'émission : {SOURCE_DES_FACTEURS}")
        if energie == "reseau_de_chaleur" and config.facteur_chauffage_kgco2_kwh is None:
            lignes.append("À DEMANDER : le facteur d'émission du réseau de chaleur, propre à chaque réseau "
                          "(facteur_chauffage_kgco2_kwh) ; sans lui, pas de CO2")
    elif config.facteur_chauffage_kgco2_kwh is None:
        lignes.append(f"À DEMANDER : les facteurs d'émission du pays {config.pays} ; ceux du code ne valent que "
                      f"pour la France")
    concernees = [energie] + (["electricite"] if climatise and energie != "electricite" else [])
    for e in concernees:
        connu = prix.get(e)
        if connu is None:
            lignes.append(f"À DEMANDER : le prix du kWh {NOMS[e]} ; sans lui, pas d'euros")
        else:
            facture = " (par kWh facturé, au pouvoir calorifique supérieur)" if e == "gaz" else ""
            lignes.append(f"prix du kWh {NOMS[e]} : {connu.eur_kwh:.4f} €{facture}, {connu.origine}")
    lignes.append("comptés : le chauffage et la climatisation seulement, pas l'éclairage ni les autres usages")
    return lignes
