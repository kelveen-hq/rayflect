"""Une étude : une maquette, un lieu, un usage, et des scénarios de protection à comparer.

Une étude s'écrit dans un fichier TOML, pour être rejouée et partagée telle quelle :

    maquette = "ecole.ifc"              # chemin relatif au fichier d'étude ; ou un plan .dxf, ou un bâtiment
                                        # commun .json (voir rayflect.io.lecture_batiment_commun)
    usage = "enseignement"              # bureau, enseignement ou logement
    periode = "1975_1988"               # période de construction, voir rayflect.hypotheses
    fenetres = "ouvrables"              # fermees, ouvrables ou nuit
    zones = false                       # découper les grands plateaux en zones de façade et noyau
    voisins = true                      # entourer le bâtiment de ceux de la BD TOPO (France)

    [lieu]
    adresse = "12 rue des Écoles, Bordeaux"     # ou latitude = 44.84 et longitude = -0.57

    [ventilation]
    double_flux = false
    surventilation = false

    [[scenario]]
    nom = "sans"

    [[scenario]]
    nom = "casquettes de 1,2 m et toit clair"
    [[scenario.element]]
    type = "casquette"
    profondeur_m = 1.2
    [[scenario.element]]
    type = "toit"
    absorption_solaire = 0.35

Sans maquette ni plan, le bâtiment se décrit par ses chiffres, à la place de `maquette` :

    [batiment]
    longueur_m = 30.0
    largeur_m = 12.0
    niveaux = 3
    hauteur_d_etage_m = 3.2
    azimut_avant_deg = 180                  # vers où regarde la façade avant, un des 2 grands côtés
    vitrage_m2 = { S = 60.0, N = 30.0 }     # pour tout le bâtiment, par orientation
    # et au besoin : allege_m, hauteur_de_baie_m, largeur_de_baie_m
    niveaux_non_chauffes = [0]              # un atelier non chauffé sous les bureaux
    mitoyennes = ["E"]                      # la façade est touche un voisin

Le sol, le vent sur les parois et la météo se règlent aussi :

    convection_exterieure = "iso_6946"      # energyplus (le défaut) ou iso_6946 : h = 4 + 4 v
    terrain = "Suburbs"                     # ce qui freine le vent autour du bâtiment : Country (dégagé), Suburbs,
                                            # City (le défaut), Ocean ou Urban

    [sol]
    temperatures_c = [10, 10, 11, 13, 15, 17, 18, 18, 17, 15, 12, 11]    # de janvier à décembre
    # ou : loi = "constante" avec temperature_c = 18.0, ou loi = "air_amorti"

    [lieu]
    meteo = "bordeaux_2019.epw"             # un fichier météo donné, à la place de l'année type de PVGIS
    climat = "futur"                        # type (le défaut), une année réelle (2022), ete_le_plus_chaud
                                            # (depuis 2000), futur (une année ordinaire de 2040-2049) ou
                                            # futur_chaud (l'été le plus chaud, décalé vers 2040-2049) ;
                                            # une liste les compare : ["type", "futur", "futur_chaud"]

Le carbone des matériaux ajoutés se règle (rayflect.carbone) :

    [carbone]
    facteurs = { aluminium = 2.3 }          # kg CO2e par kg, pour un matériau fait autrement
    masses_kg_m2 = { bois = 18.0 }          # kg par m² de protection
    materiaux = { casquette = "bois" }      # et dans un scénario : [scenario.carbone], ou carbone_kg = 950

L'usage se règle, quand on en sait plus que ses valeurs par défaut :

    [usage_regle]
    apports_w_m2 = 12.0                     # en occupation
    air_neuf_m3_h_m2 = 1.5
    heures = [8, 19]
    chauffage_c = 20.0
    chauffage_reduit_c = 16.0               # hors occupation
    air_neuf_reduit_m3_h_m2 = 0.5           # hors occupation ; sans cela l'air neuf est coupé
    air_neuf_avance_h = 2                   # mis en marche 2 heures avant l'occupation
    air_neuf_maintien_h = 1                 # maintenu 1 heure après
    # et : froid_c, part_hors_occupation, jours_ouvres_seuls, ferme_l_ete

La maquette peut aussi être un plan DXF. Ce qu'un plan en 2D ne dit pas se donne alors dans [plan] :

    maquette = "rdc.dxf"
    [plan]
    etages = ["etage.dxf", "etage.dxf"]     # les niveaux au-dessus, du bas vers le haut
    hauteur_d_etage_m = 3.2
    allege_m = 1.0
    hauteur_de_baie_m = 1.4
    nord_deg = 15                           # angle du nord par rapport au haut du dessin, sens horaire
    # et au besoin : unite = "mm", calques_murs = ["GO"], calques_baies = ["MEN_EXT"], calque_emprise = "EMPRISE"

Le bâtiment se décrit plus finement, et ses besoins se convertissent en énergie, en CO2 et en euros :

    climatisation = true                    # refroidi à 26 °C : le résultat devient un besoin de froid en kWh
    consigne = "ressentie"                  # air (le défaut) ou ressentie : ce que le thermostat tient

    [parois]                                # tout ce qui n'est pas donné vient de la période de construction
    isolation_des_murs = "interieure"       # aucune, interieure ou exterieure
    isolant_des_murs_cm = 10
    isolant_du_toit_cm = 20
    vitrage = "double_peu_emissif"          # simple, double, double_peu_emissif, triple, controle_solaire
    inertie = "lourde"                      # lourde ou legere
    # ou directement : u_mur, u_toit, u_plancher, u_vitrage, g_vitrage, n50

    [energie]                               # sans cette table, le résultat reste en besoins
    chauffage = "gaz"                       # gaz, gaz_ancien, fioul, propane, bois, electrique, pac,
                                            # reseau_de_chaleur
    # rendement_chauffage = 0.92, rendement_climatisation = 3.2
    # prix_chauffage_eur_kwh = 0.11, prix_electricite_eur_kwh = 0.19    (sinon : Eurostat, électricité et gaz)
    # facteur_chauffage_kgco2_kwh = 0.12    (réseau de chaleur, ou hors de France)
    # pays = "FR"

Un scénario peut aussi changer le bâtiment lui-même, pour mesurer un choix de conception :

    [[scenario]]
    nom = "façade sud en bandeau vitré, triple vitrage"
    [scenario.parois]                       # les mêmes clés que [parois] ; ce qui n'est pas donné vient de l'étude
    vitrage = "triple"
    [[scenario.element]]
    type = "facade"
    orientations = ["S"]
    part_vitree = 0.6                       # ou baies_fois = 1.5 : l'aire de chaque baie multipliée

Un scénario change aussi l'air : les fenêtres qu'on ouvre (rayflect.aeration) et la ventilation mécanique.
Chacun de ces 2 éléments vaut pour tout le bâtiment et remplace, dans son scénario, le réglage de l'étude.

    [[scenario]]
    nom = "fenêtres ouvertes la nuit, en traversant"
    [[scenario.element]]
    type = "ouvrants"
    heures = [22, 6]                        # sans cette clé : aux heures d'occupation ; [0, 24] : jour et nuit
    traversant = true                       # des ouvrants sur 2 façades, et rien entre elles
    # et : orientations, part_ouvrable, part_de_hauteur, seuil_interieur_c, exterieur_minimal_c, ecart_minimal_k

    [[scenario]]
    nom = "double flux et surventilation de nuit"
    [[scenario.element]]
    type = "ventilation"
    double_flux = true
    surventilation_vol_h = 4.0

Un mur Trombe (rayflect.trombe) et un champ de sondes géothermiques (rayflect.sondes) se posent de même :

    [[scenario.element]]
    type = "mur_trombe"                     # l'allège des façades sud devient un mur sombre derrière une vitre
    tablette_m = 0.4                        # et : orientations, hauteur_m, epaisseur_m, vitrage, ouverture_d_ete_c

    [[scenario.element]]
    type = "sondes"
    rangees = [2, 3]                        # 6 sondes en grille
    profondeur_m = 100                      # et : entraxe_m, conductivite_du_sol_w_m_k, cop_chauffage, froid, annees

Et suivre une plantation au fil des ans : un scénario par âge, à partir du même dessin.

    [[scenario]]
    nom = "tilleuls"
    annees = [1, 5, 15, 30]                 # donne « tilleuls, à 1 an », « tilleuls, à 5 ans »...
    [[scenario.element]]
    type = "arbre"
    est_m = 6.0
    nord_m = -8.0
    essence = "tilleul"                     # voir vegetation.ESSENCES ; la taille suit alors l'âge

La puissance à installer est rendue avec chaque scénario. Le chauffage se dimensionne au jour de base :

    [dimensionnement]
    temperature_de_base_c = -5.0            # celle du lieu ; sinon elle est tirée de la météo, et demandée

Chaque élément a un `type` (voir TYPES) ; ses autres clés sont les paramètres de ce type, tous facultatifs.
Sans aucun scénario, les 6 scénarios de SCENARIOS_PAR_DEFAUT sont comparés.
"""

from __future__ import annotations

import dataclasses
import json
import threading
import time
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from rayflect import aeration
from rayflect import apports  # noqa: F401    importé pour déclarer le type « apport_horaire »
from rayflect import cache, climat, energie as energies, exterieur, extensions, hypotheses as hyp
from rayflect import lieu as lieux
from rayflect import bilan as bilan_de_chaleur
from rayflect import carbone as carbone_construit
from rayflect import confort
from rayflect import lumiere
from rayflect import moteur
from rayflect import resultats as format_des_resultats
from rayflect import trajectoire
from rayflect.io import climats
from rayflect import sondes
from rayflect import trombe
from rayflect import protections_solaires as ps, puissance, variantes, vegetation, ventilation

T_RESSENTIE = "Zone Operative Temperature"
CHAUFFAGE = "Zone Ideal Loads Supply Air Total Heating Energy"
FROID = "Zone Ideal Loads Supply Air Total Cooling Energy"             # avec la vapeur d'eau condensée
FROID_SENSIBLE = "Zone Ideal Loads Supply Air Sensible Cooling Energy"  # ce qui baisse la température
SEUIL_DE_CHALEUR_C = 26.0           # [S] code de l'énergie, art. R241-30
FENETRES = ("fermees", "ouvrables", "nuit")

TYPES = {
    "casquette": ps.Casquette, "joues": ps.Joues, "lames_horizontales": ps.LamesHorizontales,
    "lames_verticales": ps.LamesVerticales, "lames_saisonnieres": ps.LamesSaisonnieres,
    "lames_pilotees": ps.LamesPilotees, "bso": ps.BSO, "balcon": ps.Balcon, "toit": ps.Toit,
    "photovoltaique": ps.PhotovoltaiqueEnToiture, "arbre": vegetation.Arbre, "pergola": vegetation.Pergola,
    "grimpante": vegetation.Grimpante, "mur_vegetal": vegetation.MurVegetal, "facade": variantes.Facade,
    "ouvrants": aeration.Ouvrants, "ventilation": ventilation.Mecanique,
}
_VEGETAL = (vegetation.Arbre, vegetation.Pergola, vegetation.Grimpante)


CALCULS_AU_PLUS = 64                        # [H] garde-fou de saisie, pas une limite du moteur


class EtudeInvalide(ValueError):
    """Le fichier d'étude ne peut pas être joué tel quel : le message dit quoi corriger."""


@dataclass
class Scenario:
    nom: str
    elements: List[Any] = field(default_factory=list)       # protections et plantes, posées dans l'ordre
    parois: Dict[str, Any] = field(default_factory=dict)    # ce que ce scénario change aux parois de l'étude
    carbone_kg: Optional[float] = None                      # le carbone construit, donné ; sinon estimé (rayflect.carbone)
    carbone: Dict[str, Any] = field(default_factory=dict)   # [scenario.carbone] : s'ajoute à la table [carbone]
    famille: Optional[str] = None                           # la plantation dont ce scénario est un âge (annees)
    age: Optional[float] = None                             # son âge depuis la plantation, en années

    @property
    def est_la_reference(self) -> bool:
        """Vrai pour le bâtiment tel qu'il est : ni protection, ni plante, ni variante."""
        return not self.elements and not self.parois


@dataclass
class Etude:
    maquette: Optional[Path] = None                         # ou `batiment` : l'un des 2
    usage: str = "bureau"
    periode: str = "1975_1988"
    fenetres: str = "ouvrables"
    zones: bool = False
    voisins: bool = False
    adresse: Optional[str] = None
    coordonnees: Optional[Tuple[float, float]] = None
    double_flux: bool = False
    surventilation: bool = False
    scenarios: List[Scenario] = field(default_factory=list)
    plan: Dict[str, Any] = field(default_factory=dict)      # paramètres de lecture d'un plan DXF
    climatisation: bool = False
    parois: hyp.Parois = field(default_factory=hyp.Parois)
    energie: Optional[energies.Energie] = None              # None : le résultat reste en besoins
    temperature_de_base_c: Optional[float] = None           # None : tirée de la météo, et demandée
    consigne: str = "air"                                   # air ou ressentie, voir rayflect.puissance
    batiment: Dict[str, Any] = field(default_factory=dict)  # le bâtiment par ses chiffres, sans maquette
    sol: Dict[str, Any] = field(default_factory=dict)       # voir rayflect.exterieur
    convection_exterieure: str = "energyplus"
    terrain: Optional[str] = None                           # None : « City », celui d'EnergyPlus ; un autre est
                                                            # proposé d'après la commune, jamais posé d'office

    @property
    def le_terrain(self) -> str:
        return self.terrain or exterieur.TERRAIN_PAR_DEFAUT
    meteo: Optional[Path] = None                            # un fichier météo donné ; sinon l'année type de PVGIS
    carbone: Any = field(default_factory=lambda: carbone_construit.Reglages())   # la table [carbone]
    parois_donnees: Tuple[str, ...] = ()                    # les clés de [parois] écrites dans le fichier
    objectifs: Dict[str, Any] = field(default_factory=dict)     # [objectifs], voir rayflect.propositions
    propositions: Dict[str, Any] = field(default_factory=dict)  # [propositions]
    climat: Any = "type"                                    # voir rayflect.io.climats ; une liste : calculer_par_climat
    reglages_d_usage: Dict[str, Any] = field(default_factory=dict)
    # Les ombres se recalculent chaque jour. Entouré de nombreux masques, le calcul s'allonge beaucoup : on peut
    # alors l'espacer, au prix d'une ombre moins juste (voir rayflect.moteur).
    ombres_tous_les_n_jours: int = moteur.OMBRES_TOUS_LES_N_JOURS
    calculs_en_meme_temps: Optional[int] = None             # None : la moitié des processeurs du poste

    @property
    def nom(self) -> str:
        return self.maquette.name if self.maquette is not None else "bâtiment décrit par ses chiffres"

    def __post_init__(self):
        if (self.maquette is None) == (not self.batiment):
            raise EtudeInvalide("il faut une maquette ou une table [batiment], l'une des 2")
        if self.maquette is not None:
            self.maquette = Path(self.maquette)
        if self.usage not in hyp.USAGES:
            raise EtudeInvalide(f"usage inconnu : « {self.usage} ». Connus : {', '.join(hyp.USAGES)}")
        try:
            hyp.usage_regle(self.usage, self.reglages_d_usage)
        except ValueError as erreur:
            raise EtudeInvalide(f"[usage_regle] : {erreur}") from erreur
        if self.periode not in hyp.PAROIS_PAR_PERIODE:
            raise EtudeInvalide(
                f"période inconnue : « {self.periode} ». Connues : {', '.join(hyp.PAROIS_PAR_PERIODE)}")
        if self.convection_exterieure not in exterieur.CONVECTIONS:
            raise EtudeInvalide(f"convection_exterieure : « {self.convection_exterieure} » n'est pas dans "
                                f"{', '.join(exterieur.CONVECTIONS)}")
        if self.terrain is not None and self.terrain not in exterieur.TERRAINS:
            raise EtudeInvalide(f"terrain : « {self.terrain} » n'est pas dans {', '.join(exterieur.TERRAINS)}")
        inconnues = sorted(set(self.sol) - {"temperatures_c", "loi", "temperature_c"})
        if inconnues:
            raise EtudeInvalide(f"[sol] : clés inconnues : {', '.join(inconnues)}. Connues : temperatures_c, loi, "
                                f"temperature_c")
        n = self.ombres_tous_les_n_jours
        if isinstance(n, bool) or not isinstance(n, int) or not 1 <= n <= moteur.OMBRES_AU_PLUS_TOUS_LES_N_JOURS:
            raise EtudeInvalide(f"ombres_tous_les_n_jours = {n} : un nombre entier de jours, de 1 à "
                                f"{moteur.OMBRES_AU_PLUS_TOUS_LES_N_JOURS}")
        n = self.calculs_en_meme_temps
        if n is not None and (isinstance(n, bool) or not isinstance(n, int) or not 1 <= n <= CALCULS_AU_PLUS):
            raise EtudeInvalide(f"calculs_en_meme_temps = {n} : un nombre entier de calculs, de 1 à {CALCULS_AU_PLUS}")
        if self.consigne not in puissance.CONSIGNES:
            raise EtudeInvalide(f"consigne : « {self.consigne} » n'est pas dans {', '.join(puissance.CONSIGNES)}")
        if self.fenetres not in FENETRES:
            raise EtudeInvalide(f"fenêtres : « {self.fenetres} » n'est pas dans {', '.join(FENETRES)}")
        if not self.scenarios:
            self.scenarios = scenarios_par_defaut()
        noms = [s.nom for s in self.scenarios]
        if len(set(noms)) != len(noms):
            raise EtudeInvalide("2 scénarios portent le même nom")
        self.scenarios.sort(key=lambda s: not s.est_la_reference)      # les références d'abord, l'ordre gardé sinon


def scenarios_par_defaut() -> List[Scenario]:
    return [Scenario("sans"), Scenario("casquettes", [ps.Casquette(orientations=ps.COTE_SOLEIL)]),
            Scenario("BSO soleil", [ps.BSO("soleil")]), Scenario("BSO chaleur", [ps.BSO("chaleur")]),
            Scenario("BSO manuels", [ps.BSO("occupants")]), Scenario("BSO baissés", [ps.BSO("toujours")])]


SCENARIOS_RAPIDES = ("sans", "BSO chaleur", "BSO manuels")


def types_connus() -> Dict[str, type]:
    """Les types du dépôt, et ceux que d'autres paquets ont déclarés (rayflect.extensions)."""
    return {**TYPES, **{nom: fiche.classe for nom, fiche in extensions.types().items()}}


def element(fiche: Dict[str, Any], dossier: Optional[Path] = None):
    """Un élément de scénario depuis sa fiche : {"type": "casquette", "profondeur_m": 1.2}.

    `dossier` : celui du fichier d'étude ; un paramètre `fichier` y est cherché s'il est relatif.
    """
    fiche = dict(fiche)
    nom = fiche.pop("type", None)
    connus_ici = types_connus()
    if nom not in connus_ici:
        raise EtudeInvalide(f"type d'élément inconnu : « {nom} ». Connus : {', '.join(connus_ici)}")
    classe = connus_ici[nom]
    if dossier is not None and isinstance(fiche.get("fichier"), str):
        fiche["fichier"] = str((Path(dossier) / fiche["fichier"]).resolve())
    connus = {f.name for f in dataclasses.fields(classe)}
    inconnus = sorted(set(fiche) - connus)
    if inconnus:
        raise EtudeInvalide(
            f"« {nom} » n'a pas de paramètre {', '.join(inconnus)}. Il a : {', '.join(sorted(connus))}")
    if "feuillage" in fiche:
        feuillage = getattr(vegetation, str(fiche["feuillage"]).upper(), None)
        if not isinstance(feuillage, vegetation.Feuillage):
            catalogue = [n for n, v in vars(vegetation).items() if isinstance(v, vegetation.Feuillage)]
            raise EtudeInvalide(f"feuillage inconnu : « {fiche['feuillage']} ». Connus : {', '.join(catalogue)}")
        fiche["feuillage"] = feuillage
    for cle, valeur in fiche.items():
        if isinstance(valeur, dict):
            raise EtudeInvalide(f"« {nom} » : le paramètre {cle} ne se règle pas encore depuis un fichier d'étude")
        if isinstance(valeur, list):
            fiche[cle] = tuple(valeur)
    try:
        return classe(**fiche)
    except (TypeError, ValueError) as erreur:
        raise EtudeInvalide(f"« {nom} » : {erreur}") from erreur


UNE_FOIS_PAR_SCENARIO = (aeration.Ouvrants, ventilation.Mecanique)       # posés à part, avant les autres éléments
# Ceux-là se posent avec les autres, mais un seul par scénario : un second écrirait les mêmes noms dans le fichier.
UN_SEUL_PAR_SCENARIO = UNE_FOIS_PAR_SCENARIO + (trombe.MurTrombe, sondes.Sondes)


def lire(chemin) -> Etude:
    """L'étude écrite dans un fichier TOML. Les chemins y sont relatifs au fichier."""
    chemin = Path(chemin).resolve()
    try:
        donnees = tomllib.loads(chemin.read_text(encoding="utf-8"))
    except OSError as erreur:
        raise EtudeInvalide(f"fichier d'étude illisible : {erreur}") from erreur
    except tomllib.TOMLDecodeError as erreur:
        raise EtudeInvalide(f"{chemin.name} n'est pas du TOML valide : {erreur}") from erreur
    connues = {"maquette", "usage", "periode", "fenetres", "zones", "voisins", "lieu", "ventilation", "scenario",
               "plan", "climatisation", "parois", "energie", "dimensionnement", "consigne", "batiment", "usage_regle", "sol",
               "convection_exterieure", "terrain", "ombres_tous_les_n_jours", "calculs_en_meme_temps", "carbone",
               "objectifs", "propositions"}
    inconnues = sorted(set(donnees) - connues)
    if inconnues:
        raise EtudeInvalide(f"clés inconnues : {', '.join(inconnues)}. Connues : {', '.join(sorted(connues))}")
    if "maquette" in donnees and "batiment" in donnees:
        raise EtudeInvalide("une maquette et une table [batiment] : il faut choisir l'une des 2")
    if "maquette" not in donnees and "batiment" not in donnees:
        raise EtudeInvalide("il manque la maquette : maquette = \"batiment.ifc\", ou le bâtiment par ses chiffres "
                            "dans une table [batiment]")
    ou = donnees.get("lieu", {})
    coordonnees = None
    if ("latitude" in ou) != ("longitude" in ou):
        raise EtudeInvalide("[lieu] : latitude et longitude vont ensemble")
    if "latitude" in ou:
        coordonnees = (float(ou["latitude"]), float(ou["longitude"]))
    air = donnees.get("ventilation", {})
    plan = dict(donnees.get("plan", {}))
    inconnues = sorted(set(plan) - PARAMETRES_DU_PLAN)
    if inconnues:
        raise EtudeInvalide(
            f"[plan] : clés inconnues : {', '.join(inconnues)}. Connues : {', '.join(sorted(PARAMETRES_DU_PLAN))}")
    plan["etages"] = [(chemin.parent / e).resolve() for e in plan.get("etages", [])]
    try:
        parois = hyp.Parois(**donnees.get("parois", {}))
    except (TypeError, ValueError) as erreur:
        raise EtudeInvalide(f"[parois] : {erreur}") from erreur
    try:
        energie = energies.Energie(**donnees["energie"]) if "energie" in donnees else None
    except (TypeError, ValueError) as erreur:
        raise EtudeInvalide(f"[energie] : {erreur}") from erreur
    taille = donnees.get("dimensionnement", {})
    inconnues = sorted(set(taille) - {"temperature_de_base_c"})
    if inconnues:
        raise EtudeInvalide(f"[dimensionnement] : clés inconnues : {', '.join(inconnues)}. "
                            f"Connue : temperature_de_base_c")
    de_base = taille.get("temperature_de_base_c")
    if de_base is not None and (isinstance(de_base, bool) or not isinstance(de_base, (int, float))
                                or not -50.0 <= de_base <= 15.0):
        raise EtudeInvalide(f"[dimensionnement] : temperature_de_base_c = {de_base} n'est pas une température "
                            f"extérieure de base (de -50 à 15 °C)")
    try:
        carbone = carbone_construit.lire_les_reglages(donnees.get("carbone"))
    except ValueError as erreur:
        raise EtudeInvalide(str(erreur)) from erreur
    climat = ou.get("climat", "type")
    for un in climat if isinstance(climat, list) else [climat]:
        if not climats.nom_valide(un):
            raise EtudeInvalide(f"[lieu] climat = {un!r} : type, ete_le_plus_chaud, futur, futur_chaud, ou une année (2022)")
    if isinstance(climat, list) and not climat:
        raise EtudeInvalide("[lieu] climat : une liste vide")
    scenarios = []
    for fiche in donnees.get("scenario", []):
        if "nom" not in fiche:
            raise EtudeInvalide("un scénario n'a pas de nom")
        scenarios += _scenarios(fiche, parois, chemin.parent)
    return Etude(
        maquette=(chemin.parent / donnees["maquette"]).resolve() if "maquette" in donnees else None,
        batiment=dict(donnees.get("batiment", {})), reglages_d_usage=dict(donnees.get("usage_regle", {})),
        sol=dict(donnees.get("sol", {})), convection_exterieure=str(donnees.get("convection_exterieure", "energyplus")),
        terrain=str(donnees["terrain"]) if "terrain" in donnees else None,
        meteo=(chemin.parent / ou["meteo"]).resolve() if "meteo" in ou else None, climat=climat, carbone=carbone,
        objectifs=dict(donnees.get("objectifs", {})), propositions=dict(donnees.get("propositions", {})),
        parois_donnees=tuple(donnees.get("parois", {})),
        usage=donnees.get("usage", "bureau"), periode=donnees.get("periode", "1975_1988"),
        fenetres=donnees.get("fenetres", "ouvrables"), zones=bool(donnees.get("zones", False)),
        voisins=bool(donnees.get("voisins", False)), adresse=ou.get("adresse"), coordonnees=coordonnees,
        double_flux=bool(air.get("double_flux", False)), surventilation=bool(air.get("surventilation", False)),
        scenarios=scenarios, plan=plan, climatisation=bool(donnees.get("climatisation", False)),
        parois=parois, energie=energie, temperature_de_base_c=de_base, consigne=str(donnees.get("consigne", "air")),
        ombres_tous_les_n_jours=donnees.get("ombres_tous_les_n_jours", moteur.OMBRES_TOUS_LES_N_JOURS),
        calculs_en_meme_temps=donnees.get("calculs_en_meme_temps"))


def _scenarios(fiche: Dict[str, Any], parois_de_l_etude: hyp.Parois, dossier: Optional[Path] = None) -> List[Scenario]:
    """Le ou les scénarios d'une fiche : un seul, ou un par âge quand elle porte `annees`."""
    inconnues = sorted(set(fiche) - {"nom", "element", "parois", "annees", "carbone_kg", "carbone"})
    if inconnues:
        raise EtudeInvalide(f"scénario « {fiche['nom']} » : clés inconnues : {', '.join(inconnues)}")
    nom, elements = str(fiche["nom"]), [element(e, dossier) for e in fiche.get("element", [])]
    for classe in UN_SEUL_PAR_SCENARIO:
        if sum(isinstance(e, classe) for e in elements) > 1:
            en_clair = next(n for n, c in types_connus().items() if c is classe)
            raise EtudeInvalide(f"scénario « {nom} » : un seul élément « {en_clair} » par scénario, il vaut pour "
                                f"tout le bâtiment")
    changees = dict(fiche.get("parois", {}))
    try:
        dataclasses.replace(parois_de_l_etude, **changees)
    except (TypeError, ValueError) as erreur:
        raise EtudeInvalide(f"scénario « {nom} », [scenario.parois] : {erreur}") from erreur
    donne = fiche.get("carbone_kg")
    if donne is not None and (isinstance(donne, bool) or not isinstance(donne, (int, float)) or donne < 0):
        raise EtudeInvalide(f"scénario « {nom} » : carbone_kg = {donne!r} : un nombre de kg CO2e, positif")
    propre = dict(fiche.get("carbone", {}))
    try:
        carbone_construit.lire_les_reglages(propre)
    except ValueError as erreur:
        raise EtudeInvalide(f"scénario « {nom} », [scenario.carbone] : {erreur}") from erreur
    if "annees" not in fiche:
        return [Scenario(nom, elements, changees, donne, propre)]
    annees = fiche["annees"]
    if not isinstance(annees, list) or not annees or any(
            isinstance(a, bool) or not isinstance(a, (int, float)) or a < 0 for a in annees):
        raise EtudeInvalide(f"scénario « {nom} » : annees est une liste d'âges en années, par exemple [1, 5, 15]")
    if not any(isinstance(e, _VEGETAL) for e in elements):
        raise EtudeInvalide(f"scénario « {nom} » : annees ne vaut que pour un scénario qui porte une plante")
    suite = []
    for age in annees:
        try:
            vieillis = [vegetation.a_l_age(e, float(age)) if isinstance(e, _VEGETAL) else e for e in elements]
        except ValueError as erreur:
            raise EtudeInvalide(f"scénario « {nom} » : {erreur}") from erreur
        suite.append(Scenario(f"{nom}, à {age:g} an{'s' if age >= 2 else ''}", vieillis, changees, donne, propre,
                              famille=nom, age=float(age)))
    return suite


PARAMETRES_DU_PLAN = {"etages", "hauteur_d_etage_m", "allege_m", "hauteur_de_baie_m", "nord_deg", "unite",
                      "calques_murs", "calques_baies", "calque_emprise"}


def relever(etude: Etude):
    """Le relevé du bâtiment de l'étude : maquette IFC, plans DXF, bâtiment commun (JSON) ou ses chiffres."""
    if etude.batiment:
        from rayflect.io import releve_par_chiffres

        ou = dict(zip(("latitude", "longitude"), etude.coordonnees)) if etude.coordonnees else {}
        try:
            return releve_par_chiffres.lire(**etude.batiment, **ou)
        except TypeError as erreur:
            raise EtudeInvalide(f"[batiment] : {str(erreur).split(') ')[-1]}") from erreur
        except releve_par_chiffres.ChiffresInvalides as erreur:
            raise EtudeInvalide(f"[batiment] : {erreur}") from erreur
    absents = [f for f in [etude.maquette] + list(etude.plan.get("etages", [])) if not Path(f).exists()]
    if absents:
        raise EtudeInvalide(f"maquette introuvable : {', '.join(str(f) for f in absents)}")
    if etude.maquette.suffix.lower() == ".json":
        from rayflect.io import lecture_batiment_commun

        try:
            return lecture_batiment_commun.lire(etude.maquette)
        except lecture_batiment_commun.BatimentNonLu as erreur:
            raise EtudeInvalide(f"bâtiment non lu : {erreur}") from erreur
    if etude.maquette.suffix.lower() in (".dxf", ".dwg"):
        from rayflect.io import lecture_dxf

        parametres = {c: v for c, v in etude.plan.items() if c != "etages"}
        try:
            return lecture_dxf.lire([etude.maquette] + list(etude.plan.get("etages", [])), **parametres)
        except lecture_dxf.PlanNonLu as erreur:
            raise EtudeInvalide(f"plan non lu : {erreur}") from erreur
    from rayflect.io import lecture_ifc

    try:
        return lecture_ifc.lire(etude.maquette)
    except lecture_ifc.FormatNonLu as erreur:
        raise EtudeInvalide(f"maquette non lue : {erreur}") from erreur


MODELE = '''# Une étude Rayflect. La lancer : rayflect etude ce_fichier.toml
maquette = "batiment.ifc"           # chemin relatif à ce fichier
usage = "bureau"                    # bureau, enseignement ou logement
periode = "1975_1988"               # avant_1948, 1949_1974, 1975_1988, 1989_2000, 2001_2005, 2006_2012,
                                    # 2013_2020 ou 2021_et_apres
fenetres = "ouvrables"              # fermees, ouvrables ou nuit (ouvertes aussi la nuit)
zones = false                       # true : zones de façade et noyau sur les grands plateaux
voisins = false                     # true : ombre des bâtiments voisins (BD TOPO, France)
climatisation = false               # true : refroidi à 26 °C, le résultat devient un besoin de froid en kWh
consigne = "air"                    # air : un thermostat courant ; ressentie : air et parois, la lecture haute
# ombres_tous_les_n_jours = 7       # 1 par défaut ; à espacer si le calcul est trop long (voisins, arbres)
# calculs_en_meme_temps = 2         # par défaut la moitié des processeurs du poste ; 1 : l'un après l'autre

[lieu]
adresse = "1 place de la Bourse, Bordeaux"
# ou, hors de France :
# latitude = 44.841
# longitude = -0.570

[ventilation]
double_flux = false
surventilation = false

# Ce qu'on sait des parois. Tout ce qui n'est pas donné vient de la période de construction.
# [parois]
# isolation_des_murs = "interieure"     # aucune, interieure ou exterieure
# isolant_des_murs_cm = 10
# isolant_du_toit_cm = 20
# vitrage = "double_peu_emissif"        # simple, double, double_peu_emissif, triple, controle_solaire
# inertie = "lourde"                    # lourde ou legere

# Pour avoir l'énergie achetée, le CO2 et les euros. Sans cette table, le résultat reste en besoins.
# [energie]
# chauffage = "gaz"                     # gaz, gaz_ancien, fioul, propane, bois, electrique, pac, reseau_de_chaleur
# prix_chauffage_eur_kwh = 0.11         # sinon : prix moyen d'Eurostat pour l'électricité et le gaz

# Sans maquette ni plan : le bâtiment par ses chiffres, à la place de la ligne `maquette`.
# [batiment]
# longueur_m = 30.0
# largeur_m = 12.0
# niveaux = 3
# hauteur_d_etage_m = 3.2
# azimut_avant_deg = 180                # vers où regarde la façade avant, un des 2 grands côtés
# vitrage_m2 = { S = 60.0, N = 30.0 }   # pour tout le bâtiment, par orientation

# Ce qu'on sait de l'usage, au-delà de ses valeurs par défaut.
# [usage_regle]
# apports_w_m2 = 12.0                   # et : air_neuf_m3_h_m2, heures = [8, 19], chauffage_c, froid_c,
# chauffage_reduit_c = 16.0             # part_hors_occupation, jours_ouvres_seuls, ferme_l_ete

# Pour la puissance de chauffage à installer : la température extérieure de base du lieu.
# [dimensionnement]
# temperature_de_base_c = -5.0          # sinon : tirée de la météo de l'étude, trop douce, et demandée

[[scenario]]
nom = "sans"

[[scenario]]
nom = "casquettes"
[[scenario.element]]
type = "casquette"
profondeur_m = 0.8
orientations = ["SE", "S", "SO"]

[[scenario]]
nom = "BSO pilotés"
[[scenario.element]]
type = "bso"
pilotage = "chaleur"                # chaleur, soleil, toujours ou occupants

# Un choix de conception : changer le bâtiment lui-même, et le comparer à la maquette.
# [[scenario]]
# nom = "sud en bandeau"
# [scenario.parois]                     # les mêmes clés que [parois]
# vitrage = "controle_solaire"
# [[scenario.element]]
# type = "facade"
# orientations = ["S"]
# part_vitree = 0.6                     # de 0 à 0.95 ; ou baies_fois = 1.5

# L'air : les fenêtres qu'on ouvre, la ventilation mécanique. Un seul de chaque par scénario.
# [[scenario]]
# nom = "fenêtres ouvertes la nuit"
# [[scenario.element]]
# type = "ouvrants"
# heures = [22, 6]                      # sans cette clé : en occupation ; [0, 24] : jour et nuit
# traversant = false                    # true : des ouvrants sur 2 façades, et rien entre elles
#
# [[scenario]]
# nom = "surventilation de nuit"
# [[scenario.element]]
# type = "ventilation"
# surventilation_vol_h = 4.0            # et : double_flux = true

# Un mur Trombe : l'allège des façades sud devient un mur sombre derrière une vitre.
# [[scenario]]
# nom = "mur Trombe"
# [[scenario.element]]
# type = "mur_trombe"
# tablette_m = 0.4                      # une saillie au-dessus de la vitre, contre le soleil d'été
#
# Des sondes géothermiques posées sur les besoins du scénario : la température de l'eau, suivie 10 ans.
# [[scenario]]
# nom = "sondes"
# [[scenario.element]]
# type = "sondes"
# rangees = [2, 3]                      # 6 sondes en grille
# profondeur_m = 100
# froid = "geocooling"                  # geocooling, machine ou aucun

# Un mur végétalisé : des modules plantés à 5 cm des murs pleins (rayflect.vegetation, d'après des mesures).
# [[scenario]]
# nom = "mur végétal"
# [[scenario.element]]
# type = "mur_vegetal"
# orientations = ["S", "O"]
# lame_d_air = "ventilee"               # ventilee (l'ordinaire) ou fermee ; ou resistance_m2k_w d'un système mesuré
# systeme = "bacs"                      # bacs ou panneaux, pour l'évaporation ; ou kc d'un système mesuré
# arrose = true                         # arrosé d'avril à octobre ; false : aucune évaporation

# Une plantation suivie dans le temps : un calcul par âge, compté depuis la plantation. Le compte rendu la suit âge par
# âge (rayflect.trajectoire) : sa taille, l'ombre qu'elle fait en janvier et en juillet, ce qu'elle change. Une 2e
# plantation de tilleul_lent donne l'autre bord de la pousse.
# [[scenario]]
# nom = "tilleuls"
# annees = [1, 15, 30]
# [[scenario.element]]
# type = "arbre"
# est_m = 6.0                           # position du tronc, en mètres depuis l'origine de la maquette
# nord_m = -8.0
# essence = "tilleul"                   # tilleul, tilleul_lent, robinier ou platane
'''


def _carte_des_voisins(latitude: float, longitude: float, rayon_m: float) -> dict:
    """La carte autour du lieu, gardée dans le cache pour ne pas la redemander."""
    from rayflect import environnement

    fichier = cache.dossier("voisins") / f"bdtopo_{latitude:.5f}_{longitude:.5f}_{rayon_m:.0f}.json"
    if fichier.exists():
        return json.loads(fichier.read_text(encoding="utf-8"))
    carte = environnement.telecharger(latitude, longitude, rayon_m)
    fichier.write_text(json.dumps(carte), encoding="utf-8")
    return carte


def _reglages(epw, avec_production: bool, ombres_tous_les_n_jours: int = moteur.OMBRES_TOUS_LES_N_JOURS):
    from honeybee_energy.simulation.control import SimulationControl
    from honeybee_energy.simulation.parameter import SimulationParameter

    from rayflect import lumiere

    p = SimulationParameter()
    p.location = epw.location
    p.timestep = 4
    p.shadow_calculation.calculation_frequency = ombres_tous_les_n_jours
    p.simulation_control = SimulationControl(
        do_zone_sizing=False, do_system_sizing=False, do_plant_sizing=False,
        run_for_sizing_periods=False, run_for_run_periods=True)
    p.output.reporting_frequency = "Hourly"
    for sortie in (T_RESSENTIE, CHAUFFAGE, FROID, FROID_SENSIBLE) + lumiere.SORTIES:
        p.output.add_output(sortie)
    if avec_production:
        p.output.add_output(ps.PRODUCTION_PHOTOVOLTAIQUE)
    return p


@dataclass(frozen=True)
class Avancement:
    """Où en est le calcul d'une étude, à l'instant où il est rendu."""
    etapes: Tuple[str, ...]                 # toutes les étapes de l'étude, dans l'ordre
    rang: int                               # l'étape en cours, à partir de 1
    part: float                             # la part du calcul faite, de 0 à 1
    reste_s: Optional[float]                # le temps restant estimé, ou None tant qu'on ne peut pas le dire
    en_cours: Dict[str, Optional[float]]    # les scénarios de l'étape : la part de leur année faite, ou None
                                            # pour celui qui attend qu'un processeur se libère

    @property
    def etape(self) -> str:
        return self.etapes[self.rang - 1]


PART_AVANT_D_ANNONCER = 0.03                # [H] en dessous, le temps restant ne serait qu'un tirage au sort


class _Suivi:
    """Tient le compte de ce qui est fait, et le rend à qui suit le calcul. Appelé depuis plusieurs fils."""

    def __init__(self, etude: Etude, a_la_fois: int, suivre: Optional[Callable[[Avancement], None]]) -> None:
        references = [s.nom for s in etude.scenarios if s.est_la_reference]
        autres = [s.nom for s in etude.scenarios if not s.est_la_reference]
        self.etapes = ["lire le bâtiment", "trouver le lieu et la météo"]
        self.etapes += [f"calculer « {nom} », le bâtiment tel qu'il est" for nom in references]
        if len(autres) == 1:
            self.etapes.append(f"calculer le scénario « {autres[0]} »")
        elif autres:
            self.etapes.append(f"calculer les {len(autres)} autres scénarios, {min(a_la_fois, len(autres))} à la fois"
                               if references else
                               f"calculer les {len(autres)} scénarios, {min(a_la_fois, len(autres))} à la fois")
        self.etapes.append("écrire le bilan")
        self._lots = [[nom] for nom in references] + ([autres] if autres else [])
        self._a_la_fois, self._suivre, self._verrou = a_la_fois, suivre, threading.Lock()
        self._parts = {s.nom: 0.0 for s in etude.scenarios}
        self._rang, self._lot, self._debut_du_lot, self._duree_d_un_seul = 0, [], 0.0, None
        self._partis: set = set()

    def etape(self, rang: int, lot: Sequence[str] = ()) -> None:
        """Passe à l'étape `rang`. `lot` : les scénarios qu'elle calcule."""
        with self._verrou:
            if self._lot and len(self._lot) == 1 and self._duree_d_un_seul is None:
                self._duree_d_un_seul = time.time() - self._debut_du_lot
            for nom in self._lot:
                self._parts[nom] = 1.0
            self._rang, self._lot, self._debut_du_lot = rang, list(lot), time.time()
            self._rendre()

    def scenario(self, nom: str, part: float) -> None:
        """Le scénario `nom` en est à `part` de son année. 0 : son calcul vient de partir."""
        with self._verrou:
            self._partis.add(nom)
            self._parts[nom] = max(self._parts[nom], min(part, 1.0))
            self._rendre()

    def _reste(self) -> Optional[float]:
        if not self._lot:
            return None if any(p < 1.0 for p in self._parts.values()) else 0.0
        fait = sum(self._parts[nom] for nom in self._lot) / len(self._lot)
        if fait < PART_AVANT_D_ANNONCER:
            return None
        reste = (time.time() - self._debut_du_lot) * (1.0 - fait) / fait
        for lot in self._lots:
            if lot == self._lot or all(self._parts[nom] >= 1.0 for nom in lot):
                continue
            if self._duree_d_un_seul is None:
                return None
            ensemble = min(self._a_la_fois, len(lot))
            reste += self._duree_d_un_seul * len(lot) / ensemble * (moteur.RALENTI_ENSEMBLE if ensemble > 1 else 1.0)
        return reste

    def _rendre(self) -> None:
        if self._suivre is None:
            return
        part = sum(self._parts.values()) / max(1, len(self._parts))
        if self._rang == len(self.etapes):
            part = 1.0
        self._suivre(Avancement(tuple(self.etapes), self._rang, part, self._reste(),
                                {nom: self._parts[nom] if nom in self._partis else None for nom in self._lot}))


@dataclass
class _Cadre:
    """Ce qui vaut pour tous les scénarios d'une étude : le bâtiment relevé, le lieu, la météo, l'usage."""
    etude: Etude
    sortie: Path
    releve: Any
    lieu: Any
    chemin_epw: Path
    controle: Any                           # ce que le contrôle de la météo a trouvé
    epw: Any
    choix: hyp.Hypotheses
    occupe: List[bool]
    vmc: ventilation.VMC
    base: Any                               # la température extérieure de base, voir rayflect.puissance
    le_sol: Any
    carte: Optional[dict]                   # la carte des voisins, ou None
    feuillage_quelque_part: bool


@dataclass
class _Pret:
    """Un scénario dont le fichier d'EnergyPlus est écrit : il n'y a plus qu'à le lancer."""
    scenario: Scenario
    dossier: Path
    idf: Path
    noms: Dict[str, Any]                    # par pièce : son étiquette (rang de niveau, nom, orientation)
    dit: List[str]                          # ce que le compte rendu dira de ce scénario
    reglages: Dict[str, object]             # les réglages du calcul, en clair
    aire_m2: float
    etendus: List[Tuple[Any, Any]]          # (type étendu, élément) : ceux qui retouchent le fichier ou lisent
    mesures: List[Any] = field(default_factory=list)    # ce que chaque élément a ajouté, voir rayflect.carbone


@dataclass
class _Lu:
    """Ce qu'on a lu du calcul d'un scénario."""
    puissance: dict
    chauffage_kwh: int
    froid_kwh: int
    froid_avec_vapeur_kwh: int
    production_kwh: Optional[int]
    heures_chaudes: Dict[Any, int]          # par pièce : les heures d'occupation au-dessus du seuil
    autonomie: Dict[Any, Any]               # par pièce : la part des heures d'occupation à 300 lux
    temperatures: Dict[str, List[float]]    # par pièce : la température ressentie de l'année
    des_extensions: Dict[str, Any]
    chaleur: dict = dataclasses.field(default_factory=dict)    # le bilan par poste, voir rayflect.bilan
    confort_d_ete: Dict[Any, dict] = dataclasses.field(default_factory=dict)   # par pièce, voir rayflect.confort
    lumiere: Dict[Any, dict] = dataclasses.field(default_factory=dict)         # par pièce, voir rayflect.lumiere


def _cadrer(etude: Etude, sortie, dire: Callable[[str], None],
            etape: Callable[[int], None] = lambda rang: None) -> _Cadre:
    """Le relevé, le lieu, la météo et l'usage : tout ce qui se décide avant le premier scénario."""
    from ladybug.epw import EPW

    from rayflect.io import meteo, releve as releves

    sortie = Path(sortie).resolve()
    etape(1)
    releve = relever(etude)
    dire(releves.resume(releve))
    etape(2)
    if etude.meteo is not None and not etude.meteo.exists():
        raise EtudeInvalide(f"fichier météo introuvable : {etude.meteo}")
    coordonnees = etude.coordonnees
    if etude.meteo is not None and not etude.adresse and coordonnees is None:
        coordonnees = exterieur.position_de_la_meteo(EPW(str(etude.meteo)))     # le lieu est celui du fichier
    try:
        lieu = lieux.choisir(etude.adresse, coordonnees, releve)
    except lieux.LieuIntrouvable as erreur:
        raise EtudeInvalide(f"lieu à demander : {erreur}") from erreur
    lieux.completer(lieu)                   # commune, département, altitude : sans réponse, le calcul continue
    dire(f"lieu : {lieu.resume()}")
    for ligne in lieu.fiche():
        dire(f"lieu, {ligne}")
    for remarque in lieu.remarques:
        dire(f"lieu, à savoir : {remarque}")
    if etude.meteo is not None:
        chemin_epw, controle = etude.meteo, meteo.controler(etude.meteo)
        controle.remarques.insert(0, f"fichier météo donné : {etude.meteo.name}")
    else:
        chemin_epw, controle = meteo.preparer(lieu.latitude, lieu.longitude, cache.dossier("meteo"))
    if not controle.bon:
        raise EtudeInvalide("météo inutilisable : " + " ; ".join(controle.defauts))
    if isinstance(etude.climat, list):
        raise EtudeInvalide("plusieurs climats : les jouer par calculer_par_climat")
    if etude.climat != "type":
        try:
            autre = climats.preparer(etude.climat, lieu.latitude, lieu.longitude, chemin_epw, cache.dossier("meteo"))
        except climats.ClimatIndisponible as erreur:
            raise EtudeInvalide(f"climat « {etude.climat} » : {erreur}") from erreur
        chemin_epw = autre.chemin
        controle = meteo.controler(chemin_epw)
        if not controle.bon:
            raise EtudeInvalide(f"climat « {autre.nom} » inutilisable : " + " ; ".join(controle.defauts))
        controle.remarques = [f"climat : {autre.nom}"] + autre.remarques + controle.remarques
    for remarque in controle.remarques:
        dire(f"météo, à savoir : {remarque}")

    choix = hyp.Hypotheses(etude.usage, etude.periode, etude.fenetres != "fermees", etude.fenetres == "nuit",
                           etude.climatisation, etude.parois, tuple(sorted(
                               (c, tuple(v) if isinstance(v, list) else v) for c, v in etude.reglages_d_usage.items())),
                           zone=climat.zone(lieu.departement))
    vmc = ventilation.VMC("choisie", ventilation.RENDEMENT_DOUBLE_FLUX if etude.double_flux else 0.0,
                          ventilation.SURVENTILATION_VOL_H if etude.surventilation else 0.0)
    epw = EPW(str(chemin_epw))
    carte = _carte_des_voisins(lieu.latitude, lieu.longitude, 200.0) if etude.voisins else None
    # Un seul réglage des ombres pour tous les scénarios comparés : sinon l'écart entre 2 méthodes se lit
    # comme un effet de la protection. La méthode rapide prend tout masque pour opaque : dès qu'un scénario
    # porte un feuillage ou des lames effacées l'hiver, tous passent par la méthode géométrique.
    feuillage_quelque_part = any(isinstance(e, _VEGETAL + (ps.LamesSaisonnieres,))
                                 for s in etude.scenarios for e in s.elements)
    base = puissance.base_du_lieu(epw, etude.temperature_de_base_c)
    du_lieu = climat.temperature_de_base(lieu.departement, lieu.altitude_m)
    if etude.temperature_de_base_c is None and du_lieu is not None:
        # Le département et l'altitude en disent plus que l'année type, qui ne contient pas de vague de froid.
        base = puissance.Base(du_lieu[0], du_lieu[1], f"température extérieure de base : {du_lieu[0]:g} °C pris "
                                                      f"pour le {du_lieu[1]}")
    try:
        le_sol = exterieur.sol(epw, **etude.sol)
    except (TypeError, ValueError) as erreur:
        raise EtudeInvalide(f"[sol] : {erreur}") from erreur
    return _Cadre(etude, sortie, releve, lieu, chemin_epw, controle, epw, choix, hyp.heures_occupees(choix.l_usage()),
                  vmc, base, le_sol, carte, feuillage_quelque_part)


def _construire(cadre: _Cadre, scenario: Scenario, contexte: Dict[str, Any]):
    """Le bâtiment d'un scénario et les réglages de son calcul.

    Rend (modèle, compte rendu de la conversion, réglages, textes à ajouter au fichier, ce qu'il faut en dire,
    éléments étendus posés).
    """
    from rayflect import environnement, lumiere
    from rayflect.io import releve_vers_honeybee

    etude = cadre.etude
    nom_du_modele = etude.maquette.stem if etude.maquette is not None else "batiment"
    modele, rendu = releve_vers_honeybee.convertir(cadre.releve, nom_du_modele, "linteau" if etude.zones else None)
    dossier = cadre.sortie / nom_de_dossier(scenario.nom)
    dossier.mkdir(parents=True, exist_ok=True)
    # Les réglages d'abord : un élément étendu peut ainsi les lire et les changer (contexte["reglages"]).
    reglages = _reglages(cadre.epw, any(isinstance(e, ps.PhotovoltaiqueEnToiture) for e in scenario.elements),
                         etude.ombres_tous_les_n_jours)
    puissance.ajouter_le_jour_de_base(reglages, cadre.epw, cadre.base)
    reglages.terrain_type = etude.le_terrain
    if cadre.carte is not None:
        environnement.regler_le_calcul_des_ombres(reglages)
        if cadre.feuillage_quelque_part:
            reglages.shadow_calculation.calculation_method = "PolygonClipping"
    # Un mur Trombe demande de suivre le soleil jusqu'au mur. Dès qu'un scénario en porte un, tous sont calculés
    # ainsi : sinon l'écart entre 2 répartitions du soleil se lirait comme un effet du mur.
    if any(isinstance(e, trombe.MurTrombe) for s in etude.scenarios for e in s.elements):
        trombe.suivre_le_soleil_dedans(reglages)
    contexte.update(dossier=dossier, rendu=rendu, scenario=scenario.nom, reglages=reglages)
    ajouts, etendus = [], []
    # Les variantes de conception d'abord : les parois, l'aération et les protections se règlent sur les baies.
    dit = []
    mesures: List[carbone_construit.Mesure] = []
    contexte["mesures_carbone"] = mesures
    for pose in scenario.elements:
        if isinstance(pose, variantes.Facade):
            avant_vitrage = _aire_des_baies(modele)
            dit += variantes.poser(modele, pose)
            mesures.append(carbone_construit.Mesure("facade", max(0.0, _aire_des_baies(modele) - avant_vitrage),
                                                    "m² de vitrage ajoutés"))
    du_scenario = cadre.choix
    if scenario.parois:
        du_scenario = dataclasses.replace(cadre.choix, parois=dataclasses.replace(etude.parois, **scenario.parois))
        avant = hyp.parois_retenues(etude.periode, etude.parois, cadre.choix.zone)
        apres = hyp.parois_retenues(etude.periode, du_scenario.parois, cadre.choix.zone)
        dit += [f"{cle} : {avant[cle][0]:g} dans l'étude, {apres[cle][0]:g} ici ({apres[cle][1]})"
                for cle in avant if avant[cle][0] != apres[cle][0]]
        dit += [f"{cle} : {getattr(etude.parois, cle) or 'non donné'} dans l'étude, {scenario.parois[cle]} ici"
                for cle in ("isolation_des_murs", "inertie")
                if cle in scenario.parois and scenario.parois[cle] != getattr(etude.parois, cle)]
    hyp.appliquer(modele, du_scenario)
    if scenario.parois:
        volume = _isolant_ajoute(modele, avant, apres)
        if volume > 0:
            mesures.append(carbone_construit.Mesure("isolant", volume, "m³ d'isolant"))
        if any(scenario.parois.get(c) != getattr(etude.parois, c) for c in ("vitrage", "u_vitrage", "g_vitrage")
               if c in scenario.parois):
            mesures.append(carbone_construit.Mesure("vitrage", _aire_des_baies(modele), "m² de vitrage remplacés"))
        if any(scenario.parois.get(c) != getattr(etude.parois, c) for c in ("absorption_des_murs",)
               if c in scenario.parois):
            mesures.append(carbone_construit.Mesure("teinte", 1.0, ""))
    for piece in modele.rooms:
        if piece.identifier in rendu.non_chauffees:
            hyp.ne_pas_chauffer(piece)
    # La ventilation mécanique et les fenêtres sont celles de l'étude, sauf si le scénario dit les siennes.
    vmc = cadre.vmc
    for pose in scenario.elements:
        if isinstance(pose, ventilation.Mecanique):
            mesures.append(carbone_construit.Mesure("ventilation", 1.0, "machine"))
            vmc = pose.vmc()
            dit.append(f"ventilation mécanique : {vmc.justification()}")
    ventilation.poser(modele, vmc)
    les_siens = [pose for pose in scenario.elements if isinstance(pose, aeration.Ouvrants)]
    if les_siens:
        mesures.append(carbone_construit.Mesure("ouvrants", 1.0, ""))
        texte, a_dire = aeration.poser(modele, les_siens[0], du_scenario.l_usage())
        ajouts.append(texte)
        dit += a_dire
        heures = les_siens[0].heures
        if du_scenario.fenetres_ouvrables and heures is not None and tuple(heures) != (0, 24):
            # Le piège : des ouvrants de nuit seuls ferment les fenêtres que l'étude ouvrait le jour.
            dit.append(f"à savoir : ces ouvrants remplacent ceux de l'étude ; hors de {heures[0]} h à {heures[1]} h, les "
                       f"fenêtres restent fermées, même en occupation. Pour ouvrir aussi le jour : heures = [0, 24]")
    elif du_scenario.fenetres_ouvrables:
        # Les fenêtres de l'étude passent par les mêmes formules : une seule façade, aux heures de l'étude.
        de_l_etude = aeration.Ouvrants(heures=(0, 24) if du_scenario.aeration_nocturne else None)
        ajouts.append(aeration.poser(modele, de_l_etude, du_scenario.l_usage())[0])
    arbres = [pose for pose in scenario.elements if isinstance(pose, vegetation.Arbre)]
    if arbres:
        mesures.append(carbone_construit.Mesure("arbre", float(len(arbres)), "arbres"))
        modele.add_shades(vegetation.masques(arbres, rendu.z_du_sol_m))
    for pose in scenario.elements:
        if isinstance(pose, (variantes.Facade, vegetation.Arbre) + UNE_FOIS_PAR_SCENARIO):
            continue
        etendu = extensions.trouver(pose)
        type_ = etendu.nom if etendu is not None else _type_de(pose)
        ombres, baies = _aire_des_ombres(modele), _constructions_des_baies(modele)
        if isinstance(pose, ps.PhotovoltaiqueEnToiture):
            mesures.append(carbone_construit.Mesure("photovoltaique", 1.0, "toit"))
        if etendu is not None:
            try:
                ajouts.append(etendu.poser(modele, pose, contexte) or "")
                dit += contexte.pop("a_dire", [])
            except ValueError as erreur:
                raise EtudeInvalide(f"scénario « {scenario.nom} », {etendu.nom} : {erreur}") from erreur
            etendus.append((etendu, pose))
        elif isinstance(pose, vegetation.MurVegetal):
            dit += vegetation.poser_le_mur_vegetal(modele, pose)
        elif isinstance(pose, _VEGETAL):
            vegetation.poser(modele, pose)
        else:
            ps.poser(modele, pose, contexte)
        if not isinstance(pose, ps.PhotovoltaiqueEnToiture):
            mesures.append(_mesurer(type_, modele, ombres, baies))
    lumiere.poser_les_capteurs(modele)
    if cadre.carte is not None:
        contexte["voisins"] = environnement.entourer(
            modele, rendu.emprise_m, cadre.lieu.latitude, cadre.lieu.longitude, z_du_sol_m=rendu.z_du_sol_m,
            carte=cadre.carte)
    return modele, rendu, reglages, ajouts, dit, etendus


NOM_DE_DOSSIER_MAX = 60


def nom_de_dossier(nom: str) -> str:
    """Le dossier de calcul d'un scénario : son nom, lettres et chiffres seulement.

    Raccourci au-delà de 60 caractères, avec 8 caractères de son empreinte pour rester unique : sous Windows, un chemin
    de plus de 260 caractères empêche EnergyPlus d'écrire ses fichiers, et le calcul s'arrête sans rien dire de clair
    (une combinaison de 3 propositions y suffisait, le 23/11/2026).
    """
    import hashlib

    propre = "".join(c if c.isalnum() else "_" for c in nom)
    if len(propre) <= NOM_DE_DOSSIER_MAX:
        return propre
    return f"{propre[:NOM_DE_DOSSIER_MAX - 9]}_{hashlib.sha1(nom.encode('utf-8')).hexdigest()[:8]}"


def _type_de(pose) -> str:
    """Le nom d'un élément, tel qu'il s'écrit dans le fichier d'étude."""
    return next((nom for nom, classe in types_connus().items() if isinstance(pose, classe)), type(pose).__name__)


def _aire_des_ombres(modele) -> float:
    return sum(ombre.area for ombre in modele.shades)


def _aire_des_baies(modele) -> float:
    return sum(baie.area for baie in modele.apertures)


def _constructions_des_baies(modele) -> Dict[str, str]:
    return {baie.identifier: baie.properties.energy.construction.identifier for baie in modele.apertures}


def _mesurer(type_: str, modele, ombres_avant: float, baies_avant: Dict[str, str]):
    """Ce qu'un élément vient d'ajouter : des ombres (m²), ou des baies équipées d'un store (m²)."""
    ajoutees = _aire_des_ombres(modele) - ombres_avant
    if ajoutees > 1e-6:
        return carbone_construit.Mesure(type_, ajoutees, "m² de protection")
    equipees = sum(baie.area for baie in modele.apertures
                   if baie.properties.energy.construction.identifier != baies_avant.get(baie.identifier))
    return carbone_construit.Mesure(type_, equipees, "m² de baies équipées")


def _isolant_ajoute(modele, avant: Dict[str, tuple], apres: Dict[str, tuple]) -> float:
    """Le volume d'isolant qu'il faut ajouter pour passer de U à U' : (1/U' − 1/U) × λ × l'aire des parois."""
    from honeybee.boundarycondition import Ground, Outdoors

    aires = {"u_mur": 0.0, "u_toit": 0.0, "u_plancher": 0.0}
    for face in modele.faces:
        if not isinstance(face.boundary_condition, (Outdoors, Ground)):
            continue
        nom = type(face.type).__name__
        cle = "u_mur" if nom == "Wall" else "u_toit" if nom == "RoofCeiling" else "u_plancher" if nom == "Floor" else None
        if cle is not None:
            aires[cle] += face.area - sum(baie.area for baie in face.apertures)
    volume = 0.0
    for cle, aire in aires.items():
        if cle in avant and cle in apres and 0 < apres[cle][0] < avant[cle][0]:
            volume += (1.0 / apres[cle][0] - 1.0 / avant[cle][0]) * hyp.CONDUCTIVITE_ISOLANT * aire
    return volume


def _ecrire(cadre: _Cadre, scenario: Scenario, contexte: Dict[str, Any]) -> _Pret:
    """Construit le scénario et écrit son fichier d'EnergyPlus.

    LE FICHIER SE RETOUCHE ICI, ET NULLE PART AILLEURS : le texte entier, une fois assemblé, passe par la fonction
    `retoucher` de chaque élément étendu qui en déclare une (voir rayflect.extensions).
    """
    etude = cadre.etude
    modele, rendu, reglages, ajouts, dit, etendus = _construire(cadre, scenario, contexte)
    mesures = contexte.pop("mesures_carbone", [])
    dossier = contexte["dossier"]
    texte = (reglages.to_idf() + "\n\n"
             + modele.to.idf(modele, schedule_directory=str(dossier / "plannings"))
             + puissance.consigne_ressentie(modele, etude.consigne == "ressentie")
             + exterieur.texte_du_sol(cadre.le_sol)
             + (exterieur.texte_de_la_convection(modele, cadre.epw, dossier, etude.le_terrain)
                if etude.convection_exterieure == "iso_6946" else "")
             + "".join(ajouts)
             + bilan_de_chaleur.texte_des_sorties()
             + vegetation.texte_des_murs_vegetaux(modele, cadre.epw, dossier))
    texte = lumiere.retoucher(texte, modele)    # le capteur du bord de baie et l'éblouissement
    dit += vegetation.dire_l_eau_des_murs(modele, cadre.epw)
    for etendu, pose in etendus:
        if etendu.retoucher is None:
            continue
        try:
            texte = etendu.retoucher(texte, pose, contexte)
        except ValueError as erreur:
            raise EtudeInvalide(f"scénario « {scenario.nom} », {etendu.nom} : {erreur}") from erreur
        if not isinstance(texte, str) or not texte.strip():
            raise EtudeInvalide(f"scénario « {scenario.nom} », {etendu.nom} : la retouche doit rendre le texte "
                                f"du fichier")
        dit += contexte.pop("a_dire", [])
    idf = dossier / "in.idf"
    idf.write_text(texte, encoding="utf-8")
    dit += [ligne for pose in scenario.elements if isinstance(pose, _VEGETAL) for ligne in vegetation.dire(pose)]
    # Les zones non chauffées ne comptent ni dans les heures chaudes ni dans la lumière : personne n'y travaille.
    noms = {identifiant.upper(): etiquette for identifiant, etiquette in rendu.etiquettes.items()
            if identifiant not in rendu.non_chauffees}
    return _Pret(scenario, dossier, idf, noms, dit, moteur.reglages_en_clair(reglages), modele.floor_area, etendus,
                 mesures)


def _lancer(cadre: _Cadre, pret: _Pret, suivre: Optional[Callable[[float], None]] = None):
    """Lance EnergyPlus sur un scénario écrit. Rend (résultats SQL, journal, durée en secondes)."""
    debut = time.time()
    try:
        sql, journal = moteur.lancer(pret.idf, cadre.chemin_epw, suivre)
    except moteur.CalculFautif as erreur:
        raise EtudeInvalide(f"scénario « {pret.scenario.nom} » : {erreur}") from erreur
    return sql, journal, round(time.time() - debut, 1)


def _lire(cadre: _Cadre, pret: _Pret, sql, contexte: Dict[str, Any]) -> _Lu:
    """Lit les résultats d'un scénario.

    TOUT CE QUI LIT L'ANNÉE PASSE PAR `puissance.Annee` : le calcul joue aussi un jour de base, dont les 24 heures
    ne doivent entrer dans aucun total. Les éléments étendus lisent par le même objet.
    """
    from ladybug.sql import SQLiteResult

    from rayflect import lumiere

    scenario = pret.scenario
    resultats = puissance.Annee(SQLiteResult(sql))
    try:
        resultats.verifier((T_RESSENTIE, CHAUFFAGE, FROID, FROID_SENSIBLE))
    except ValueError as erreur:
        raise EtudeInvalide(f"scénario « {scenario.nom} » : {erreur}. Résultats : {sql}") from erreur

    def total(nom: str) -> int:
        return round(sum(sum(c.values) for c in resultats.data_collections_by_output_name(nom)))

    avec_production = any(isinstance(e, ps.PhotovoltaiqueEnToiture) for e in scenario.elements)
    # LE BESOIN DE FROID EST LE FROID SENSIBLE, celui qui baisse la température : c'est lui que changent une
    # protection solaire ou un vitrage. Un air soufflé froid condense aussi de la vapeur d'eau ; cette part
    # dépend de la machine plus que du bâtiment. Elle est rendue à côté, et comptée dans l'énergie achetée.
    lu = _Lu(puissance.lire(resultats, cadre.epw, cadre.base, CHAUFFAGE, FROID, pret.aire_m2),
             total(CHAUFFAGE), total(FROID_SENSIBLE), total(FROID),
             total(ps.PRODUCTION_PHOTOVOLTAIQUE) if avec_production else None, {}, {}, {}, {})
    for serie in resultats.data_collections_by_output_name(T_RESSENTIE):
        zone = str(serie.header.metadata.get("Zone", "?")).upper()
        if zone.startswith(trombe.PREFIXE.upper()) or zone not in pret.noms:
            continue                        # la lame d'un mur Trombe, une zone non chauffée : pas des pièces
        lu.temperatures[zone] = list(serie.values)
        en_occupation = [t for t, o in zip(serie.values, cadre.occupe) if o]
        lu.heures_chaudes[pret.noms.get(zone, (0, zone, "?"))] = sum(1 for t in en_occupation if t > SEUIL_DE_CHALEUR_C)
    for zone, jour in lumiere.lire(resultats, cadre.occupe).items():
        if zone.upper() not in pret.noms:
            continue
        lu.autonomie[pret.noms.get(zone.upper(), (0, zone, "?"))] = jour["autonomie_300_lux"]
        lu.lumiere[pret.noms.get(zone.upper(), (0, zone, "?"))] = jour
    if not cadre.etude.climatisation:       # la RE2020 calcule le DH sans climatisation : une étude climatisée n'en a pas
        froid_c, habitation = cadre.choix.les_consignes()[1], cadre.etude.usage == "logement"
        seuils = confort.seuils(list(cadre.epw.dry_bulb_temperature.values), froid_c, habitation)
        for zone, valeurs in lu.temperatures.items():
            lu.confort_d_ete[pret.noms[zone]] = confort.indicateurs(valeurs, seuils, cadre.occupe, habitation)
    try:
        lu.chaleur = bilan_de_chaleur.lire(sql, pret.noms, trombe.PREFIXE)
    except ValueError as erreur:
        raise EtudeInvalide(f"scénario « {scenario.nom} » : {erreur}. Résultats : {sql}") from erreur
    # Le contexte est commun à l'étude : le dossier et le nom qu'il porte sont ceux du dernier scénario écrit.
    du_scenario = {**contexte, "dossier": pret.dossier, "scenario": scenario.nom}
    for etendu, pose in pret.etendus:
        if etendu.lire is None:
            continue
        try:
            lu.des_extensions.setdefault(etendu.nom, []).append(etendu.lire(resultats, pose, du_scenario))
        except ValueError as erreur:
            raise EtudeInvalide(f"scénario « {scenario.nom} », {etendu.nom} : {erreur}") from erreur
    return lu


def calculer(etude: Etude, sortie, dire: Callable[[str], None] = print,
             suivre: Optional[Callable[[Avancement], None]] = None) -> dict:
    """Joue l'étude : un calcul EnergyPlus par scénario. Rend les résultats et les écrit dans `sortie`.

    `dire(texte)` reçoit ce que l'étude a à dire en chemin. `suivre(avancement)` reçoit, à mesure, où en est le
    calcul : la liste des étapes, celle en cours, la part faite et le temps restant estimé (voir `Avancement`).

    En 4 temps par scénario : construire le bâtiment, écrire le fichier d'EnergyPlus, le lancer, lire ses
    résultats. Le bâtiment tel qu'il est se calcule d'abord, seul : ses températures servent aux occupants des
    scénarios suivants. Les autres scénarios sont écrits l'un après l'autre, puis lancés ensemble.

    Lève `EtudeInvalide` quand il manque de quoi calculer (maquette, lieu, météo saine).
    """
    ensemble = etude.calculs_en_meme_temps or moteur.calculs_en_meme_temps()
    suivi = _Suivi(etude, ensemble, suivre)
    cadre = _cadrer(etude, sortie, dire, suivi.etape)
    try:
        version = moteur.exiger_energyplus()
    except moteur.CalculFautif as erreur:
        raise EtudeInvalide(str(erreur)) from erreur
    contexte: Dict[str, Any] = {"epw": cadre.epw, "usage": etude.usage, "chemin_epw": cadre.chemin_epw, "dire": dire}
    prets: Dict[str, _Pret] = {}
    lus: Dict[str, _Lu] = {}
    durees: Dict[str, float] = {}
    avertissements: Dict[str, int] = {}

    rang = [2]

    def jouer(scenarios: List[Scenario]) -> None:
        if not scenarios:
            return
        rang[0] += 1
        suivi.etape(rang[0], [scenario.nom for scenario in scenarios])
        lot = [_ecrire(cadre, scenario, contexte) for scenario in scenarios]

        def lancer(pret: _Pret):
            suivi.scenario(pret.scenario.nom, 0.0)
            return _lancer(cadre, pret, lambda part, nom=pret.scenario.nom: suivi.scenario(nom, part))

        for pret, (sql, journal, duree) in zip(lot, moteur.ensemble(lancer, lot, ensemble)):
            nom = pret.scenario.nom
            prets[nom], durees[nom], avertissements[nom] = pret, duree, journal.avertissements
            lus[nom] = _lire(cadre, pret, sql, contexte)
            if pret.scenario.est_la_reference:
                contexte.setdefault("temperatures", {}).update(lus[nom].temperatures)
            dire(f"calculé : {nom} ({duree:.0f} s)")
            if (duree > moteur.CALCUL_LONG_S and etude.ombres_tous_les_n_jours == 1
                    and pret.scenario is etude.scenarios[0]):
                dire("calcul long : les ombres sont recalculées chaque jour. Les espacer le raccourcit, au prix d'une "
                     "ombre moins juste : ombres_tous_les_n_jours = 7 dans le fichier d'étude")

    # Les scénarios sont rangés références d'abord (voir Etude). Chaque référence se joue seule, avant la suite.
    for scenario in etude.scenarios:
        if scenario.est_la_reference:
            jouer([scenario])
    jouer([scenario for scenario in etude.scenarios if not scenario.est_la_reference])
    suivi.etape(len(suivi.etapes))
    return _assembler(cadre, version, ensemble, prets, lus, durees, avertissements, contexte)


def _assembler(cadre: _Cadre, version, ensemble: int, prets: Dict[str, _Pret], lus: Dict[str, _Lu],
               durees: Dict[str, float], avertissements: Dict[str, int], contexte: Dict[str, Any]) -> dict:
    """Le bilan de l'étude, tous scénarios lus. L'écrit dans `resultats.json`."""
    etude, lieu, base, le_sol = cadre.etude, cadre.lieu, cadre.base, cadre.le_sol
    ordre = [s.nom for s in etude.scenarios]
    chauffages = {nom: lus[nom].chauffage_kwh for nom in ordre}
    froids = {nom: lus[nom].froid_kwh for nom in ordre}
    froids_avec_vapeur = {nom: lus[nom].froid_avec_vapeur_kwh for nom in ordre}
    productions = {nom: lus[nom].production_kwh for nom in ordre if lus[nom].production_kwh is not None}
    chaud: Dict[Any, Dict[str, int]] = {}
    clair: Dict[Any, Dict[str, Any]] = {}
    for nom in ordre:
        for piece, heures in lus[nom].heures_chaudes.items():
            chaud.setdefault(piece, {})[nom] = heures
        for piece, part in lus[nom].autonomie.items():
            clair.setdefault(piece, {})[nom] = part
    changements = {nom: list(dict.fromkeys(prets[nom].dit)) for nom in ordre if prets[nom].dit}
    du_calcul = prets[ordre[-1]].reglages
    rendu = contexte["rendu"]

    a_demander = list(cadre.releve.manques) + [f"non repris du bâtiment : {m}" for m in cadre.releve.non_lus]
    a_demander += list(lieu.remarques) + ([base.a_demander] if base.a_demander else [])
    a_demander += [le_sol.a_demander] if le_sol.a_demander else []
    # Le poids d'un défaut lourd se dit, pas seulement sa source : l'étanchéité par défaut a déplacé de 25 % le chauffage
    # d'une étude qui ne la donnait pas (parité des bureaux, 24/11/2026).
    a_demander += hyp.hypotheses_lourdes_non_donnees(etude.periode, etude.parois, cadre.choix.zone, etude.parois_donnees,
                                                     etude.reglages_d_usage)
    sur_la_version = moteur.remarque_sur_la_version(version)
    if sur_la_version:
        a_demander.append(sur_la_version)
    connues = moteur.versions()
    propose = climat.terrain_propose(lieu.population)
    if etude.terrain is None and propose is not None and propose[0] != etude.le_terrain:
        a_demander.append(f"terrain autour du bâtiment : « {etude.le_terrain} » est pris par défaut ; « {propose[0]} » "
                          f"conviendrait mieux ({propose[1]}) [H]. Le fixer par terrain = \"{propose[0]}\"")
    du_dehors = [
        "sol sous le plancher, de janvier à décembre : " + ", ".join(f"{t:g}" for t in le_sol.temperatures_c)
        + f" °C ; {le_sol.origine}", exterieur.dire_la_convection(etude.convection_exterieure, etude.le_terrain),
        moteur.dire_les_reglages(du_calcul, connues)]
    voisinage = None
    if cadre.releve.provenances:
        du_dehors.append("d'où vient le bâtiment : " + " ; ".join(
            f"{p} {n}" for p, n in sorted(_compter(cadre.releve.provenances.values()).items())))
    if "voisins" in contexte:
        v = contexte["voisins"]
        a_demander += v["manques"]
        voisinage = {"batiments_sur_la_carte": v["batiments_sur_la_carte"], "tri": v["tri"],
                     "faces_de_masque": v["faces_de_masque"], "maquette_reconnue": bool(v["calage"].sur)}
    comptes, comment = {}, []
    if etude.energie is not None:
        reference = etude.scenarios[0].nom
        prix = energies.prix_de_l_etude(
            etude.energie, energies.consommations(chauffages[reference], froids_avec_vapeur[reference],
                                                  etude.energie),
            menage=etude.usage == "logement")
        comptes = {nom: energies.bilan(chauffages[nom], froids_avec_vapeur[nom], etude.energie, prix)
                   for nom in chauffages}
        comment = energies.justification(etude.energie, prix, etude.climatisation)
        a_demander += [ligne[len("À DEMANDER : "):] for ligne in comment if ligne.startswith("À DEMANDER : ")]
    pieces = sorted(set(chaud) | set(clair))
    bilan = {
        "format": format_des_resultats.entete(),
        "pieces": [{"cle": " | ".join(map(str, p)), "rang": int(p[0]), "niveau": str(p[1]), "cote": str(p[2])}
                   for p in pieces],
        "maquette": etude.nom, "lieu": lieu.resume(), "lieu_fiche": lieu.fiche(), "meteo": cadre.chemin_epw.name,
        "climat": str(etude.climat),
        "meteo_a_savoir": cadre.controle.remarques, "hypotheses": cadre.choix.justification() + du_dehors,
        "heures_d_occupation": int(sum(cadre.occupe)), "scenarios": ordre,
        "repris": {"zones": rendu.zones, "baies": rendu.baies_reposees, "aire_reposee_m2": rendu.aire_reposee_m2,
                   "aire_relevee_m2": rendu.aire_relevee_m2, "baies_ecartees": len(rendu.baies_ecartees),
                   "niveaux_ecartes": rendu.niveaux_ecartes,
                   "niveaux_non_chauffes": [n.nom for n in cadre.releve.niveaux if not n.chauffe],
                   "murs_mitoyens": rendu.murs_mitoyens, "aire_mitoyenne_m2": rendu.aire_mitoyenne_m2},
        "voisins": voisinage, "bso_manuels": contexte.get("bilan_bso_manuels"), "a_demander": a_demander,
        "heures_au_dessus_de_26": {" | ".join(map(str, k)): v for k, v in sorted(chaud.items())},
        "autonomie_300_lux": {" | ".join(map(str, k)): v for k, v in sorted(clair.items())},
        "chauffage_kwh": chauffages, "froid_kwh": froids if etude.climatisation else {},
        "froid_avec_vapeur_kwh": froids_avec_vapeur if etude.climatisation else {},
        "energie": comptes, "energie_comment": [ligne for ligne in comment if not ligne.startswith("À DEMANDER")],
        "production_pv_kwh": productions, "duree_s": {nom: durees[nom] for nom in ordre}, "changements": changements,
        "puissance": {nom: lus[nom].puissance for nom in ordre},
        "puissance_comment": puissance.expliquer(base, etude.climatisation, etude.consigne),
        "bilan_de_chaleur": {nom: lus[nom].chaleur for nom in ordre},
        "confort_d_ete": _confort_d_ete(cadre, lus, ordre),
        "lumiere": _lumiere(lus, ordre),
        "carbone": _carbone(etude, prets, lus, ordre, comptes, productions),
        "moteur": {"versions": connues, "reglages": du_calcul,
                   "avertissements": {nom: avertissements[nom] for nom in ordre}, "calculs_en_meme_temps": ensemble},
    }
    trajectoires = trajectoire.assembler(etude.scenarios, bilan)
    if trajectoires:
        bilan["trajectoires"] = trajectoires
    des_extensions = {nom: lus[nom].des_extensions for nom in ordre if lus[nom].des_extensions}
    if des_extensions:
        bilan["extensions"] = des_extensions
    # UN RÉSULTAT QUI NE SUIT PAS SON FORMAT N'EST PAS ÉCRIT (rayflect.resultats) : un autre logiciel le lirait de
    # travers sans que rien ne le dise.
    format_des_resultats.controler(bilan)
    (cadre.sortie / "resultats.json").write_text(json.dumps(bilan, indent=2, ensure_ascii=False), encoding="utf-8")
    return bilan


def _carbone(etude: Etude, prets: Dict[str, _Pret], lus: Dict[str, _Lu], ordre: List[str], comptes: dict,
             productions: Dict[str, int]) -> dict:
    """Le carbone construit de chaque scénario, et, si l'énergie est décrite, le CO2 évité et le retour."""
    carbones = {s.nom: carbone_construit.chiffrer(prets[s.nom].mesures, etude.carbone.avec(s.carbone),
                                                 lus[s.nom].production_kwh, s.carbone_kg) for s in etude.scenarios}
    if comptes:
        facteur = etude.energie.facteur_electricite_kgco2_kwh
        if facteur is None and etude.energie.pays == energies.PAYS_DES_FACTEURS:
            facteur = energies.FACTEURS_KGCO2_KWH["electricite_refroidissement"]
        carbone_construit.evite(carbones, ordre, {n: c.get("kgco2") for n, c in comptes.items()}, productions, facteur)
    return carbones


def _lumiere(lus: Dict[str, _Lu], ordre: List[str]) -> Dict[str, Dict[str, dict]]:
    """Par pièce puis par scénario : la lumière au centre et au bord de baie, l'excès et l'éblouissement."""
    par_piece: Dict[Any, Dict[str, dict]] = {}
    for nom in ordre:
        for piece, jour in lus[nom].lumiere.items():
            par_piece.setdefault(piece, {})[nom] = jour
    return {" | ".join(map(str, k)): v for k, v in sorted(par_piece.items())}


def _dire_la_lumiere(lumiere_: Optional[dict], colonnes) -> List[str]:
    """Le trop de lumière et l'éblouissement, en bord de baie, là où une grande baie se fait refuser."""
    if not lumiere_:
        return []

    def part(cle):
        return lambda v: "" if v is None or v.get(cle) is None else f"{v[cle] * 100:.0f} %"

    lignes = _tableau(f"Part des heures d'occupation au-dessus de {lumiere.EXCES_LUX:.0f} lux, à "
                      f"{lumiere.DISTANCE_DU_BORD_M:g} m de la baie (trop de lumière)", lumiere_, colonnes,
                      part("bord_plus_de_3000_lux"))
    lignes += _tableau(f"Part des heures d'occupation où l'éblouissement dépasse l'indice {lumiere.EBLOUISSEMENT_MAXIMAL:g}, "
                       f"à {lumiere.DISTANCE_DU_BORD_M:g} m de la baie, regard le long de la façade", lumiere_, colonnes,
                       part("eblouissement_bord"))
    lignes.append(f"  - au-dessus de {lumiere.UTILE_JUSQU_A_LUX:.0f} à {lumiere.EXCES_LUX:.0f} lux, la lumière du jour "
                  f"éblouit et chauffe (Nabil et Mardaljevic) ; indice d'éblouissement {lumiere.EBLOUISSEMENT_MAXIMAL:g} : "
                  f"le maximum conseillé par EnergyPlus pour le bureau. Méthode simplifiée d'EnergyPlus : pour comparer "
                  f"des protections, pas pour certifier (Radiance pour la norme NF EN 17037)")
    lignes.append("  - l'indice d'éblouissement BAISSE devant une très grande baie, la pièce entière s'éclairant : il compare "
                  "des protections sur un même vitrage ; pour comparer des parts de vitrage, lire le trop de lumière")
    return lignes


def _confort_d_ete(cadre: _Cadre, lus: Dict[str, _Lu], ordre: List[str]) -> dict:
    """Les degrés-heures d'inconfort par pièce et par scénario, la période où ils se comptent, et ce qu'il faut en dire."""
    par_piece: Dict[Any, Dict[str, dict]] = {}
    for nom in ordre:
        for piece, valeurs in lus[nom].confort_d_ete.items():
            par_piece.setdefault(piece, {})[nom] = valeurs
    bornes = confort.periode(confort.moyennes_glissantes(list(cadre.epw.dry_bulb_temperature.values)))
    return {"pieces": {" | ".join(map(str, k)): v for k, v in sorted(par_piece.items())},
            "periode": None if bornes is None else {"premier_jour": bornes[0] + 1, "dernier_jour": bornes[1] + 1},
            "comment": confort.expliquer(bornes, cadre.choix.les_consignes()[1], cadre.etude.usage == "logement",
                                         cadre.etude.climatisation)}


def calculer_par_climat(etude: Etude, sortie, climats_: Optional[Sequence[Any]] = None,
                        dire: Callable[[str], None] = print,
                        suivre: Optional[Callable[[Avancement], None]] = None) -> Dict[str, dict]:
    """Joue la même étude sous plusieurs climats, chacun dans son dossier. Rend {climat : bilan}.

    `climats_` : la liste à jouer ; par défaut celle de l'étude ([lieu] climat = [...]). Les mêmes scénarios, le même
    bâtiment : seul le climat change. C'est sous un été chaud et sous le climat qui vient que la ventilation de nuit,
    l'inertie et les protections solaires se départagent.
    """
    liste = list(climats_ if climats_ is not None else
                 (etude.climat if isinstance(etude.climat, list) else [etude.climat]))
    rendus: Dict[str, dict] = {}
    for un in liste:
        if not climats.nom_valide(un):
            raise EtudeInvalide(f"climat « {un} » : type, ete_le_plus_chaud, futur, futur_chaud, ou une année (2022)")
        dire(f"climat : {un}")
        rendus[str(un)] = calculer(dataclasses.replace(etude, climat=un), Path(sortie) / f"climat_{un}", dire, suivre)
    (Path(sortie)).mkdir(parents=True, exist_ok=True)
    (Path(sortie) / "comparaison_des_climats.txt").write_text(comparer_les_climats(rendus), encoding="utf-8")
    return rendus


def proposer(etude: Etude, sortie, dire: Callable[[str], None] = print,
             suivre: Optional[Callable[[Avancement], None]] = None) -> dict:
    """Cherche les mesures qui tiennent les objectifs de l'étude ([objectifs]) : voir rayflect.propositions.

    Les scénarios du fichier ne sont pas joués : la palette des propositions les remplace.
    """
    from rayflect import propositions

    try:
        reglages = propositions.lire(etude.objectifs, etude.propositions)
    except propositions.PropositionsInvalides as erreur:
        raise EtudeInvalide(str(erreur)) from erreur
    if isinstance(etude.climat, list):
        raise EtudeInvalide("propositions : un seul climat ; climat = \"futur_chaud\" les cherche sous la canicule qui vient")
    if etude.climatisation and any(c in reglages.objectifs for c in ("dh_max",)):
        raise EtudeInvalide("propositions : un objectif de degrés-heures demande climatisation = false, comme la RE2020")

    def fabrique(nom, elements, parois):
        try:
            dataclasses.replace(etude.parois, **parois)
        except (TypeError, ValueError) as erreur:
            raise EtudeInvalide(f"proposition « {nom} » : {erreur}") from erreur
        return Scenario(nom, elements, parois)

    return propositions.proposer(etude, sortie, reglages, lambda e, s: calculer(e, s, dire, suivre),
                                 lambda fiche: element(fiche), fabrique, dire)


def _pire(par_piece: dict, scenario: str, lire) -> Optional[float]:
    valeurs = [lire(v[scenario]) for v in par_piece.values() if v.get(scenario) is not None]
    valeurs = [v for v in valeurs if v is not None]
    return max(valeurs) if valeurs else None


def comparer_les_climats(rendus: Dict[str, dict]) -> str:
    """Chaque scénario sous chaque climat : chauffage, froid, heures chaudes et degrés-heures de la pièce la plus chaude."""
    cles = list(rendus)
    premier = rendus[cles[0]]
    scenarios = premier["scenarios"]

    def nom_du_climat(bilan: dict) -> str:
        dit = [r[len("climat : "):] for r in bilan["meteo_a_savoir"] if r.startswith("climat : ")]
        return dit[0] if dit else "année type"

    noms = {c: nom_du_climat(rendus[c]) for c in cles}
    largeur = max(14, *(len(n) + 2 for n in noms.values()))
    lignes = ["Le même bâtiment sous plusieurs climats"]
    for cle, bilan in rendus.items():
        detail = [r for r in bilan["meteo_a_savoir"] if r.startswith(("été du fichier", "été 1", "été 2"))]
        lignes.append(f"  - {noms[cle]} : {bilan['meteo']}" + (f" ; {detail[0]}" if detail else ""))

    def tableau(titre: str, lire) -> None:
        lignes.extend(["", titre, f"{'scénario':<24}" + "".join(f"{noms[c]:>{largeur}}" for c in cles)])
        for s in scenarios:
            valeurs = [lire(rendus[c], s) for c in cles]
            lignes.append(f"{s[:23]:<24}" + "".join(f"{'' if v is None else round(v):>{largeur}}" for v in valeurs))

    tableau("besoin de chauffage, kWh par an", lambda b, s: b["chauffage_kwh"].get(s))
    if premier.get("froid_kwh"):
        tableau("besoin de froid, kWh par an", lambda b, s: b["froid_kwh"].get(s))
    tableau("heures d'occupation au-dessus de 26 °C, pièce la plus chaude",
            lambda b, s: _pire(b["heures_au_dessus_de_26"], s, lambda v: v) if b["heures_au_dessus_de_26"] else None)
    if any(b.get("confort_d_ete", {}).get("pieces") for b in rendus.values()):
        tableau("degrés-heures d'inconfort à la façon de la RE2020, °C.h, pièce la plus chaude",
                lambda b, s: _pire(b["confort_d_ete"]["pieces"], s, lambda v: v["dh"]) if b["confort_d_ete"]["pieces"]
                else None)
    return "\n".join(lignes)


def _compter(valeurs) -> Dict[str, int]:
    comptes: Dict[str, int] = {}
    for v in valeurs:
        comptes[v] = comptes.get(v, 0) + 1
    return comptes


LARGEUR_D_UN_NOM = 13


def _en_tetes(colonnes) -> Dict[str, str]:
    """L'en-tête de chaque scénario : son nom s'il tient dans la colonne, sinon un numéro pour tous.

    Un nom coupé trompe : « tilleuls, à 1 an » et « tilleuls, à 15 ans » se liraient pareil.
    """
    if all(len(c) <= LARGEUR_D_UN_NOM for c in colonnes):
        return {c: c for c in colonnes}
    return {c: f"({k + 1})" for k, c in enumerate(colonnes)}


def _tableau(titre: str, valeurs: dict, colonnes, forme) -> List[str]:
    noms = _en_tetes(colonnes)
    lignes = ["", titre, f"{'niveau':<20}{'côté':<12}" + "".join(f"{noms[c]:>15}" for c in colonnes)]
    for cle, ligne in valeurs.items():
        _rang, niveau, cote = (cle.split(" | ") + ["", ""])[:3]
        lignes.append(f"{niveau[:19]:<20}{cote:<12}" + "".join(f"{forme(ligne.get(c)):>15}" for c in colonnes))
    return lignes


def _dire_le_confort(confort_d_ete: Optional[dict], colonnes) -> List[str]:
    """Les degrés-heures d'inconfort de la RE2020, en ordre de grandeur, et la part de la nuit en logement."""
    if not confort_d_ete:
        return []
    pieces = confort_d_ete["pieces"]
    lignes = []
    if pieces:
        lignes += _tableau("Degrés-heures d'inconfort à la façon de la RE2020, °C.h par an (ordre de grandeur)", pieces,
                           colonnes, lambda v: "" if v is None else str(v["dh"]))
        lignes += _tableau("Heures d'occupation au-dessus du seuil d'inconfort + 2 °C", pieces, colonnes,
                           lambda v: "" if v is None else str(v["heures_plus_2"]))
        if any(v.get("dh_nuit") is not None for ligne in pieces.values() for v in ligne.values()):
            lignes += _tableau("Dont la nuit, de 22 h à 6 h, au-dessus de 26 °C, °C.h", pieces, colonnes,
                               lambda v: "" if v is None or v.get("dh_nuit") is None else str(v["dh_nuit"]))
        au_dessus = sorted({c for ligne in pieces.values() for c, v in ligne.items() if v["dh"] > confort.SEUIL_BAS_DH})
        if au_dessus:
            lignes.append(f"  - au-dessus du seuil bas de {confort.SEUIL_BAS_DH} °C.h dans au moins une pièce : "
                          + ", ".join(f"« {c} »" for c in colonnes if c in au_dessus))
    elif not confort_d_ete["comment"]:
        return []
    if not pieces:
        lignes.append("")
        lignes.append("Degrés-heures d'inconfort à la façon de la RE2020")
    lignes += [f"  - {c}" for c in confort_d_ete["comment"]]
    return lignes


def presenter(bilan: dict) -> str:
    """Le compte rendu d'une étude, en texte : ce qui manque d'abord, les hypothèses, puis les tableaux."""
    colonnes = bilan["scenarios"]
    lignes = [f"{bilan['maquette']}, {bilan['lieu']}"]
    lignes += [f"  {ligne}" for ligne in bilan.get("lieu_fiche", [])]
    r = bilan["repris"]
    lignes.append(f"repris : {r['zones']} zones, {r['baies']} baies, {r['aire_reposee_m2']} m² de vitrage sur "
                  f"{r['aire_relevee_m2']} relevés ; {r['baies_ecartees']} baies écartées")
    if r.get("niveaux_non_chauffes"):
        lignes.append(f"non chauffé : {', '.join(r['niveaux_non_chauffes'])} ; ni heures chaudes ni lumière n'y sont "
                      f"comptées")
    if r.get("murs_mitoyens"):
        lignes.append(f"mitoyen : {r['murs_mitoyens']} murs, {r['aire_mitoyenne_m2']} m², sans échange avec le dehors "
                      f"(voisin supposé chauffé)")
    if bilan["a_demander"]:
        lignes.append("à demander ou à confirmer :")
        lignes += [f"  - {m}" for m in bilan["a_demander"]]
    lignes.append("hypothèses :")
    lignes += [f"  - {h}" for h in bilan["hypotheses"]]
    for nom, dits in bilan.get("changements", {}).items():
        lignes.append(f"ce que change « {nom} » :")
        lignes += [f"  - {d}" for d in dits]
    noms = _en_tetes(colonnes)
    if any(noms[c] != c for c in colonnes):
        lignes += ["", "scénarios comparés :"] + [f"  {noms[c]} {c}" for c in colonnes]
    titre = f"Heures au-dessus de 26 °C, sur {bilan['heures_d_occupation']} heures d'occupation par an"
    if bilan.get("froid_kwh"):
        # La climatisation tient l'air à sa consigne ; la température ressentie compte aussi les parois et
        # le vitrage chauds, et la dépasse encore.
        titre = (f"Heures où la température ressentie dépasse 26 °C malgré la climatisation, sur "
                 f"{bilan['heures_d_occupation']} heures d'occupation par an")
    lignes += _tableau(titre,
                       bilan["heures_au_dessus_de_26"], colonnes, lambda v: "" if v is None else str(v))
    lignes += _tableau("Part des heures d'occupation avec au moins 300 lux de lumière du jour",
                       bilan["autonomie_300_lux"], colonnes, lambda v: "" if v is None else f"{v * 100:.0f} %")
    lignes += _dire_la_lumiere(bilan.get("lumiere"), colonnes)
    lignes += _dire_le_confort(bilan.get("confort_d_ete"), colonnes)
    lignes.append("")
    if any(noms[c] != c for c in colonnes):
        lignes.append(f"{'':<32}" + "".join(f"{noms[c]:>15}" for c in colonnes))
    lignes.append(f"{'besoin de chauffage, kWh par an':<32}"
                  + "".join(f"{bilan['chauffage_kwh'][c]:>15}" for c in colonnes))
    if bilan.get("froid_kwh"):
        lignes.append(f"{'besoin de froid, kWh par an':<32}" + "".join(f"{bilan['froid_kwh'][c]:>15}" for c in colonnes))
        if bilan.get("froid_avec_vapeur_kwh"):
            lignes.append(f"{'  avec la vapeur condensée':<32}"
                          + "".join(f"{bilan['froid_avec_vapeur_kwh'][c]:>15}" for c in colonnes))
    if bilan.get("energie"):
        def ligne(titre, cle):
            valeurs = [bilan["energie"][c][cle] for c in colonnes]
            return f"{titre:<32}" + "".join(f"{'à demander' if v is None else v:>15}" for v in valeurs)

        achete = bilan["energie"][colonnes[0]]["energie_de_chauffage"].replace("_", " ")
        lignes += ["", "Énergie achetée pour le chauffage et la climatisation, par an",
                   ligne(f"chauffage ({achete}), kWh", "chauffage_kwh")]
        if bilan.get("froid_kwh"):
            lignes.append(ligne("climatisation (électricité), kWh", "climatisation_kwh"))
        lignes += [ligne("émissions, kg de CO2", "kgco2"), ligne("dépense, euros", "euros")]
        lignes += [f"  - {c}" for c in bilan.get("energie_comment", [])]
    if bilan.get("puissance"):
        lignes += puissance.tableau(bilan["puissance"], colonnes, noms)
        lignes += [f"  - {c}" for c in bilan.get("puissance_comment", [])]
    lignes += bilan_de_chaleur.dire(bilan.get("bilan_de_chaleur", {}), colonnes)
    lignes += carbone_construit.dire(bilan.get("carbone", {}), colonnes)
    if bilan.get("trajectoires"):
        reference = colonnes[0]
        lignes += trajectoire.dire(bilan["trajectoires"], {
            "dh": trajectoire._pire((bilan.get("confort_d_ete") or {}).get("pieces") or {}, reference, lambda v: v["dh"]),
            "heures_au_dessus_de_26": trajectoire._pire(bilan["heures_au_dessus_de_26"], reference, lambda v: v),
            "chauffage_kwh": bilan["chauffage_kwh"].get(reference),
            "autonomie_300_lux": trajectoire._pire(bilan["autonomie_300_lux"], reference, lambda v: v, plus_haut=False)})
    for nom, lues in bilan.get("extensions", {}).items():
        for champ in lues.get(sondes.NOM, []):
            lignes += ["", f"Sondes géothermiques, « {nom} »"] + [f"  {ligne}" for ligne in sondes.dire(champ)]
        for mur in lues.get(trombe.NOM, []):
            lignes += ["", f"Mur Trombe, « {nom} »"] + [f"  {ligne}" for ligne in trombe.dire(mur)]
    if bilan["production_pv_kwh"]:
        lignes.append(f"{'production PV, kWh par an':<32}"
                      + "".join(f"{bilan['production_pv_kwh'].get(c, ''):>15}" for c in colonnes))
    return "\n".join(lignes)
