"""Les hypothèses d'usage d'un bâtiment, posées sur un modèle Honeybee : qui l'occupe et quand, combien de
chaleur on y dégage, comment il est aéré, et de quoi sont faites ses parois.

Chaque valeur porte son origine : [S] lue dans une source citée, [D] déduite par un calcul écrit ici,
[H] hypothèse sans source, à remplacer ou à demander. Rien n'est caché : `Hypotheses.justification()` rend
la liste complète, pour l'afficher à côté du résultat.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from honeybee.altnumber import no_limit
from honeybee_energy.construction.opaque import OpaqueConstruction
from honeybee_energy.construction.window import WindowConstruction
from honeybee_energy.load.equipment import ElectricEquipment
from honeybee_energy.load.infiltration import Infiltration
from honeybee_energy.load.setpoint import Setpoint
from honeybee_energy.load.ventilation import Ventilation
from honeybee_energy.material.glazing import EnergyWindowMaterialSimpleGlazSys
from honeybee_energy.material.opaque import EnergyMaterial, EnergyMaterialNoMass
from honeybee_energy.schedule.day import ScheduleDay
from honeybee_energy.schedule.rule import ScheduleRule
from honeybee_energy.schedule.ruleset import ScheduleRuleset
from honeybee_energy.ventcool.control import VentilationControl
from honeybee_energy.ventcool.opening import VentilationOpening
import honeybee_energy.lib.scheduletypelimits as limites
from ladybug.dt import Date

from .config.consignes import CONSIGNES_PAR_USAGE


@dataclass(frozen=True)
class Usage:
    nom: str
    cle_consignes: str                     # clé de `config.consignes`
    apports_w_m2: float
    source_apports: str
    heures: Tuple[int, int]                # début et fin d'occupation, heure locale
    jours_ouvres_seuls: bool
    ferme_l_ete: bool                      # fermé du 7 juillet au 31 août
    part_hors_occupation: float            # part des apports qui reste quand le bâtiment est vide
    air_neuf_m3_h_m2: float
    source_air_neuf: str
    part_ouvrante: float = 0.4             # part de l'aire des baies que les occupants ouvrent
    source_ouvrante: str = ""


# LES USAGES, d'après les scénarios conventionnels de la RE2020 : annexe III de l'arrêté du 4 août 2021, méthode
# Th-BCE 2020, version consolidée du 19 mars 2026 (« Th-BCE » ci-dessous). Ce sont des conventions de calcul
# réglementaire, pas des mesures. Un niveau du modèle est une seule zone : les valeurs par type de local
# (p. 24) y sont moyennées, pondérées par la part de surface de chaque local que donne la même page [D].
# Chaque occupant dégage 90 W (adulte au repos, §2.1.1, p. 20) ; l'éclairage est celui du projet en tertiaire,
# il n'est pas compté.
CHALEUR_D_UN_OCCUPANT_W = 90.0
# Bureaux (p. 24) : bureau standard 60,47 % de la surface, 0,1 occupant/m², équipements 16 W/m² en occupation et
# 1,77776 hors occupation ; salle de réunion 10,47 %, 0,42 occupant/m², 10 W/m² ; circulations et sanitaires
# vides. Soit 0,1044 occupant/m², 9,40 W/m² d'occupants et 10,72 W/m² d'équipements ; hors occupation 1,075 W/m².
DENSITE_BUREAU = 0.6047 * 0.1 + 0.1047 * 0.42
APPORTS_BUREAU = DENSITE_BUREAU * CHALEUR_D_UN_OCCUPANT_W + 0.6047 * 16.0 + 0.1047 * 10.0
# Enseignement primaire (p. 24) : salle de classe 55 %, 0,66 élève/m², aucun équipement ; bureau 10 %, 0,067/m²,
# 16 W/m² ; réunion 5 %, 0,42/m², 10 W/m² ; salle de repos 15 %, 0,66/m². Soit 0,49 occupant/m².
DENSITE_ENSEIGNEMENT = 0.1 * 0.067 + 0.55 * 0.66 + 0.05 * 0.42 + 0.15 * 0.66
APPORTS_ENSEIGNEMENT = DENSITE_ENSEIGNEMENT * CHALEUR_D_UN_OCCUPANT_W + 0.1 * 16.0 + 0.05 * 10.0
# Logement collectif (p. 21, 24 et 60) : équipements 5,7 W/m² en présence éveillée, 1,14 W/m² en sommeil et en
# absence ; 90 W par adulte équivalent éveillé, 63 W en sommeil avec une présence de 0,7 de 22 h à 6 h ;
# occupé du lundi au vendredi de 17 h à 9 h (le mercredi dès 13 h), et tout le week-end. Le modèle tient
# l'apport constant : c'est la moyenne de la semaine [D], 76 heures éveillées, 56 de sommeil, 36 d'absence. Le
# nombre d'adultes équivalents suit la surface du logement (p. 60) : 1,855 pour un logement de 60 m² [H : la
# surface d'un logement n'est pas une entrée].
ADULTES_D_UN_LOGEMENT_DE_60_M2 = 1.75 + 0.3 * (0.035 * 60.0 - 1.75)
APPORTS_LOGEMENT = ((76 * 5.7 + 92 * 1.14)
                    + ADULTES_D_UN_LOGEMENT_DE_60_M2 / 60.0 * (76 * 90.0 + 56 * 63.0 * 0.7)) / 168.0
# LES FENÊTRES QUE LES OCCUPANTS OUVRENT (Th-BCE §5.9.3.3.1, p. 195) : la moitié des baies en bureau, 70 % en
# enseignement et en logement collectif ; et une baie s'ouvre au plus sur 80 % de son aire, pour une fenêtre à la
# française (§5.13, tableau 44, p. 267) [H : le type d'ouvrant n'est pas une entrée].
OUVRANT_FRANCAISE = 0.8

USAGES = {
    "bureau": Usage(
        "bureau", "office", round(APPORTS_BUREAU, 1),
        "[S] RE2020, Th-BCE, scénarios des bureaux (p. 24) : 0,104 occupant/m² à 90 W et 10,7 W/m² d'équipements, "
        "moyennés sur les locaux types [D]", heures=(8, 18), jours_ouvres_seuls=True, ferme_l_ete=False,
        part_hors_occupation=round(0.6047 * 1.77776 / APPORTS_BUREAU, 3),
        air_neuf_m3_h_m2=round(25.0 * DENSITE_BUREAU, 2),
        source_air_neuf="[S] code du travail, art. R4222-6 : 25 m³/h par occupant en bureau ; 0,104 occupant/m², "
                        "RE2020 (p. 24)",
        part_ouvrante=0.5 * OUVRANT_FRANCAISE,
        source_ouvrante="[S] RE2020 : la moitié des baies manœuvrées en bureau, 80 % de l'aire d'une fenêtre à la "
                        "française"),
    "enseignement": Usage(
        "enseignement", "education", round(APPORTS_ENSEIGNEMENT, 1),
        "[S] RE2020, Th-BCE, scénarios de l'enseignement primaire (p. 24) : 0,49 occupant/m² à 90 W et "
        "2,1 W/m² d'équipements, moyennés sur les locaux types [D]",
        heures=(8, 17), jours_ouvres_seuls=True, ferme_l_ete=True, part_hors_occupation=0.004,
        air_neuf_m3_h_m2=round(15.0 * DENSITE_ENSEIGNEMENT, 2),
        source_air_neuf="[S] règlement sanitaire départemental type, art. 64 : 15 m³/h par élève ; 0,49 "
                        "occupant/m², RE2020 (p. 24)",
        part_ouvrante=round(0.7 * OUVRANT_FRANCAISE, 2),
        source_ouvrante="[S] RE2020 : 70 % des baies manœuvrées en enseignement, 80 % de l'aire d'une fenêtre à "
                        "la française"),
    "logement": Usage(
        "logement", "residential", round(APPORTS_LOGEMENT, 1),
        "[S] RE2020, Th-BCE, logement collectif (p. 21, 24, 60) : équipements et occupants, en moyenne sur la "
        "semaine [D] ; logement de 60 m² [H]", heures=(0, 24), jours_ouvres_seuls=False, ferme_l_ete=False,
        part_hors_occupation=1.0, air_neuf_m3_h_m2=0.5 * 2.5,
        source_air_neuf="[H] 0,5 volume par heure sous 2,5 m de plafond : la RE2020 prend le débit du système du "
                        "projet",
        part_ouvrante=round(0.7 * OUVRANT_FRANCAISE, 2),
        source_ouvrante="[S] RE2020 : 70 % des baies manœuvrées en logement collectif, 80 % de l'aire d'une "
                        "fenêtre à la française"),
}

# LES PAROIS PAR DÉFAUT, quand on ne sait du bâtiment que sa période de construction.
# [S] Méthode 3CL-DPE 2021, annexe 1 de l'arrêté du 31 mars 2021 (version d'octobre 2021, « 3CL » ci-dessous) :
#   murs, tableau Umur_tab (§3.2.1.1, p. 13) ; toit, tableau Uph_tab (§3.2.3.1, p. 21), colonne « terrasse » : le
#   toit du modèle est plat ; plancher bas, tableau Upb_tab (§3.2.2.1, p. 17). Colonne des chauffages « autres »
#   que l'effet Joule [H : choix]. Ce sont des valeurs conventionnelles de diagnostic, prudentes, établies pour le
#   logement : rien de publié n'en donne pour le tertiaire existant.
LIGNES_3CL = ("<=74", "75-77", "78-82", "83-88", "89-00", "01-05", "06-12", ">=13")
U_3CL = {
    "u_mur": {"H1": (2.5, 1.0, 1.0, 0.8, 0.5, 0.4, 0.36, 0.23), "H2": (2.5, 1.05, 1.05, 0.84, 0.53, 0.4, 0.36, 0.23),
              "H3": (2.5, 1.11, 1.11, 0.89, 0.56, 0.47, 0.4, 0.25)},
    "u_toit": {"H1": (2.5, 0.75, 0.75, 0.55, 0.4, 0.3, 0.27, 0.14), "H2": (2.5, 0.79, 0.79, 0.58, 0.42, 0.3, 0.27, 0.14),
               "H3": (2.5, 0.83, 0.83, 0.61, 0.44, 0.3, 0.27, 0.14)},
    "u_plancher": {"H1": (2.0, 0.9, 0.9, 0.8, 0.5, 0.3, 0.27, 0.23), "H2": (2.0, 0.95, 0.95, 0.74, 0.63, 0.3, 0.27, 0.23),
                   "H3": (2.0, 1.0, 1.0, 0.89, 0.56, 0.47, 0.4, 0.25)},
}
# Une période de l'étude couvre une ou plusieurs lignes de la 3CL : la moyenne de ces lignes, pondérée par leur
# nombre d'années [D]. La 3CL n'a pas de ligne après 2012 : 2021_et_apres reprend la dernière, plus prudente que
# la RE2020.
PERIODES_EN_LIGNES_3CL = {
    "avant_1948": {"<=74": 1}, "1949_1974": {"<=74": 1}, "1975_1988": {"75-77": 3, "78-82": 5, "83-88": 6},
    "1989_2000": {"89-00": 1}, "2001_2005": {"01-05": 1}, "2006_2012": {"06-12": 1}, "2013_2020": {">=13": 1},
    "2021_et_apres": {">=13": 1},
}
ZONE_PAR_DEFAUT = "H2"                  # [H] la zone du milieu, quand le lieu n'en dit rien
# LA PERMÉABILITÉ À L'AIR DE L'ENVELOPPE sous 4 Pa, en m³/h par m² de parois déperditives hors plancher bas.
# [S] 3CL §4, p. 39, colonne « appartement ou immeuble » [H : choix ; la colonne « maison » est plus étanche
# avant 1948 et après 2012].
Q4PA_PAR_PERIODE = {"avant_1948": 4.6, "1949_1974": 2.0, "1975_1988": 1.5, "1989_2000": 1.5, "2001_2005": 1.5,
                    "2006_2012": 1.5, "2013_2020": 1.0, "2021_et_apres": 1.0}
# [S] 3CL §4, p. 38-39 : n50 = Q4Pa / ((4/50)^(2/3) V), puis le débit des infiltrations dues au vent vaut e n50 V,
# avec e = 0,07 pour un bâtiment dont plusieurs façades sont exposées (sans écart entre air soufflé et repris).
EXPOSANT_DE_FUITE = 2.0 / 3.0
COEFFICIENT_DE_PROTECTION_E = 0.07
# LE VITRAGE D'ORIGINE, faute de mieux : simple avant 1975, double jusqu'en 2005, double peu émissif à l'argon
# ensuite. [H : choix ; la 3CL dit seulement (p. 25) que les doubles et triples vitrages posés à partir de 2006
# sont réputés à l'argon ou au krypton.] Les valeurs de chaque type sont sourcées (VITRAGES ci-dessous).
VITRAGE_PAR_PERIODE = {"avant_1948": "simple", "1949_1974": "simple", "1975_1988": "double", "1989_2000": "double",
                       "2001_2005": "double", "2006_2012": "double_peu_emissif", "2013_2020": "double_peu_emissif",
                       "2021_et_apres": "double_peu_emissif"}


def _de_la_3cl(grandeur: str, periode: str, zone: str) -> float:
    lignes = PERIODES_EN_LIGNES_3CL[periode]
    valeurs = U_3CL[grandeur][zone]
    total = sum(lignes.values())
    return round(sum(valeurs[LIGNES_3CL.index(ligne)] * poids for ligne, poids in lignes.items()) / total, 3)


def zone_de_calcul(zone: Optional[str]) -> str:
    """H1, H2 ou H3 depuis une zone climatique (H1a...H3), ou la zone par défaut."""
    return zone[:2] if zone and zone[:2] in ("H1", "H2", "H3") else ZONE_PAR_DEFAUT


def parois_de_la_periode(periode: str, zone: Optional[str] = None) -> Dict[str, float]:
    """Les valeurs par défaut de la période : U des parois, du vitrage, facteur solaire, perméabilité sous 4 Pa."""
    z = zone_de_calcul(zone)
    u_vitrage, g_vitrage = VITRAGES[VITRAGE_PAR_PERIODE[periode]]
    return dict(u_mur=_de_la_3cl("u_mur", periode, z), u_toit=_de_la_3cl("u_toit", periode, z),
                u_plancher=_de_la_3cl("u_plancher", periode, z), u_vitrage=u_vitrage, g_vitrage=g_vitrage,
                q4pa=Q4PA_PAR_PERIODE[periode])


# L'OUVERTURE DES FENÊTRES PAR LES OCCUPANTS. [S] RE2020, Th-BCE §5.13, gestion manuelle (p. 255-269) : hors
# saison de chauffe, l'ouverture va de 23 à 25 °C de température ressentie dedans (figure 62) ; rien sous 10 °C
# dehors, tout à 18 °C (figure 61) ; les occupants gardent ouvert tant qu'il ne fait pas plus de 3 °C de plus
# dehors que dedans. EnergyPlus ouvre en tout ou rien : on prend le milieu de chaque rampe [D].
OUVERTURE_T_INTERIEURE_MIN_C = 24.0     # on ouvre quand il fait plus de 24 °C dedans...
OUVERTURE_T_EXTERIEURE_MIN_C = 14.0     # ...qu'il fait plus de 14 °C dehors...
OUVERTURE_ECART_MIN_K = -3.0            # ...et pas plus de 3 °C de plus dehors que dedans
OUVERTURE_PART_DE_BAIE = USAGES["bureau"].part_ouvrante     # sert à qui appelle `appliquer` sans usage
# [D] Le tirage d'une fenêtre ouverte sur une seule façade : voir rayflect.aeration, qui déduit cette valeur
# (0,6 / (3 racine(2))). Honeybee propose 0,45, qui compte toute la hauteur de la baie comme hauteur de tirage et
# donne 3,2 fois ce débit. Une étude passe par rayflect.aeration ; cette valeur sert à qui appelle `appliquer` seul.
OUVERTURE_COEFFICIENT_DE_TIRAGE = 0.1414

# [S] Règles Th-bât, fascicule « Matériaux », 2017 : béton plein de granulats courants, 2 000 < ρ ≤ 2 300 kg/m³,
# λ = 1,65 W/m.K et Cp = 1 000 J/kg.K (§2.2.1.1, p. 7) ; plaque de plâtre à parement carton, 750 ≤ ρ ≤ 900 kg/m³,
# λ = 0,25 W/m.K, « valeur par défaut » (§2.3.1, p. 12). Épaisseurs : [H].
BETON = dict(k=1.65, rho=2300.0, cp=1000.0)
MASSE_BETON = dict(epaisseur=0.15, **BETON)                         # [H] l'épaisseur : 15 cm de béton
PLAQUE = dict(epaisseur=0.013, k=0.25, rho=850.0, cp=1000.0)        # [H] l'épaisseur : 13 mm
R_SURFACES = 0.17                   # [S] Th-bât, Parois opaques, tableau X, p. 14 : Rsi 0,13 + Rse 0,04 (mur)
# [S] Règles Th-U Ex (bâtiments existants, 2008), fascicule 2, p. 5 : « autres isolants thermiques (laine
# minérale, polystyrène expansé...) », 0,04 W/m.K, la valeur par défaut d'un isolant existant non identifié.
CONDUCTIVITE_ISOLANT = 0.040
U_MUR_SANS_ISOLANT = 2.5            # [S] 3CL §3.2.1.1, p. 13 : mur non isolé de type inconnu ; préférer donner u_mur
ISOLATIONS = ("aucune", "interieure", "exterieure")
INERTIES = ("lourde", "legere")

# Vitrages : (Uw, U de la fenêtre entière en W/m².K ; Sw, facteur solaire de la fenêtre entière). Une baie du
# modèle est la fenêtre entière, menuiserie comprise : ce sont les bonnes grandeurs, pas celles du vitrage seul.
# [S] 3CL, fenêtre battante en PVC posée au nu extérieur [H : choix de la menuiserie] :
#   Ug du vitrage (§3.3.1, p. 23-25) : simple 5,8 ; double à lame d'air de 16 mm 2,7 ; double peu émissif à
#   l'argon, 16 mm, 1,1 ; triple peu émissif à l'argon, 16 mm, 0,7 ;
#   Uw selon Ug, menuiserie PVC (§3.3.2, p. 28) ; Sw (§6.2.1, p. 46).
# Le contrôle solaire n'a pas de ligne dans la 3CL : son facteur solaire reste [H], son Uw est celui du double
# peu émissif.
VITRAGES = {
    "simple": (4.9, 0.54),
    "double": (2.6, 0.48),
    "double_peu_emissif": (1.4, 0.42),
    "triple": (1.1, 0.39),
    "controle_solaire": (1.4, 0.30),
}
PAROIS_PAR_PERIODE = {periode: parois_de_la_periode(periode) for periode in PERIODES_EN_LIGNES_3CL}   # en zone H2


@dataclass(frozen=True)
class Parois:
    """Ce qu'on sait des parois. Tout ce qui est laissé vide vient de la période de construction [H].

    Du plus sûr au moins sûr : une valeur de U donnée, une épaisseur d'isolant, un type de vitrage, puis la
    période. La place de l'isolant et l'inertie changent la surchauffe à U égal : un isolant posé à l'intérieur
    cache la masse du mur, qui n'amortit plus les pointes de chaleur.
    """
    isolation_des_murs: Optional[str] = None        # aucune, interieure ou exterieure
    isolant_des_murs_cm: Optional[float] = None
    isolant_du_toit_cm: Optional[float] = None
    isolant_du_plancher_cm: Optional[float] = None
    vitrage: Optional[str] = None                   # clé de VITRAGES
    inertie: str = "lourde"                         # lourde : béton ou maçonnerie ; legere : ossature
    u_mur: Optional[float] = None
    u_toit: Optional[float] = None
    u_plancher: Optional[float] = None
    u_vitrage: Optional[float] = None
    g_vitrage: Optional[float] = None
    n50: Optional[float] = None
    absorption_des_murs: Optional[float] = None     # part du soleil que la face extérieure absorbe : sa teinte
    absorption_du_toit: Optional[float] = None

    def __post_init__(self):
        if self.isolation_des_murs is not None and self.isolation_des_murs not in ISOLATIONS:
            raise ValueError(f"isolation des murs : « {self.isolation_des_murs} » n'est pas dans {', '.join(ISOLATIONS)}")
        if self.inertie not in INERTIES:
            raise ValueError(f"inertie : « {self.inertie} » n'est pas dans {', '.join(INERTIES)}")
        if self.vitrage is not None and self.vitrage not in VITRAGES:
            raise ValueError(f"vitrage inconnu : « {self.vitrage} ». Connus : {', '.join(VITRAGES)}")
        for nom in ("isolant_des_murs_cm", "isolant_du_toit_cm", "isolant_du_plancher_cm", "u_mur", "u_toit",
                    "u_plancher", "u_vitrage", "g_vitrage", "n50"):
            valeur = getattr(self, nom)
            if valeur is not None and (isinstance(valeur, bool) or valeur <= 0):
                raise ValueError(f"{nom} : {valeur} n'est pas une valeur possible")
        for nom in ("absorption_des_murs", "absorption_du_toit"):
            valeur = getattr(self, nom)
            if valeur is not None and (isinstance(valeur, bool) or not 0.0 < valeur <= 1.0):
                raise ValueError(f"{nom} : {valeur} ; une absorption solaire est comprise entre 0 et 1")
        if self.g_vitrage is not None and self.g_vitrage >= 1.0:
            raise ValueError(f"g_vitrage : {self.g_vitrage} ; un facteur solaire est compris entre 0 et 1")
        if self.isolation_des_murs == "aucune" and self.isolant_des_murs_cm:
            raise ValueError("isolation des murs « aucune » et une épaisseur d'isolant : il faut choisir")


def _u_d_un_isolant(epaisseur_cm: float, inertie: str) -> float:
    masse = MASSE_BETON if inertie == "lourde" else PLAQUE
    return 1.0 / (R_SURFACES + epaisseur_cm / 100.0 / CONDUCTIVITE_ISOLANT + masse["epaisseur"] / masse["k"])


def parois_retenues(periode: str, parois: Parois, zone: Optional[str] = None) -> Dict[str, tuple]:
    """Chaque grandeur des parois avec son origine : {"u_mur": (valeur, "d'où elle vient"), ...}.

    L'étanchéité est rendue sous la clé « n50 » quand elle est donnée, « q4pa » sinon (la perméabilité par défaut).
    """
    defaut = parois_de_la_periode(periode, zone)
    z = zone_de_calcul(zone)
    de_la_periode = f"période {periode}, zone {z}{'' if zone else ' supposée'}, méthode 3CL-DPE 2021 [S]"
    retenu = {}
    for cle, epaisseur in (("u_mur", parois.isolant_des_murs_cm), ("u_toit", parois.isolant_du_toit_cm),
                           ("u_plancher", parois.isolant_du_plancher_cm)):
        if getattr(parois, cle) is not None:
            retenu[cle] = (getattr(parois, cle), "donné")
        elif epaisseur is not None:
            inertie = "lourde" if cle == "u_plancher" else parois.inertie
            retenu[cle] = (round(_u_d_un_isolant(epaisseur, inertie), 3),
                           f"{epaisseur:g} cm d'isolant à {CONDUCTIVITE_ISOLANT} W/m.K [S : Th-U Ex]")
        elif cle == "u_mur" and parois.isolation_des_murs == "aucune":
            retenu[cle] = (max(U_MUR_SANS_ISOLANT, defaut[cle]), "mur sans isolant de type inconnu, 3CL [S]")
        else:
            retenu[cle] = (defaut[cle], de_la_periode)
    u_type, g_type = VITRAGES[parois.vitrage] if parois.vitrage else (None, None)
    for cle, du_type in (("u_vitrage", u_type), ("g_vitrage", g_type)):
        if getattr(parois, cle) is not None:
            retenu[cle] = (getattr(parois, cle), "donné")
        elif du_type is not None:
            retenu[cle] = (du_type, f"vitrage {parois.vitrage.replace('_', ' ')}, fenêtre PVC, 3CL [S]")
        else:
            retenu[cle] = (defaut[cle], f"vitrage {VITRAGE_PAR_PERIODE[periode].replace('_', ' ')} supposé pour la "
                                        f"période [H], fenêtre PVC, 3CL [S]")
    if parois.n50 is not None:
        retenu["n50"] = (parois.n50, "donné")
    else:
        retenu["q4pa"] = (defaut["q4pa"], f"période {periode}, appartement ou immeuble, méthode 3CL-DPE 2021 [S]")
    return retenu


# LE POIDS DES HYPOTHÈSES LOURDES, quand l'étude ne les donne pas : de combien le chauffage et les degrés-heures bougent
# si on divise l'hypothèse par 2 puis qu'on la double (l'inertie : lourde puis légère) [D : verification/
# poids_des_hypotheses.py, bureaux de 1975 à 1988 à Bordeaux, 24/11/2026]. Le compte rendu les cite pour que le poids
# d'un défaut se voie, pas seulement sa source. Ceux qui pèsent moins de 15 % (le plancher : 3 % au plus) ne sont pas
# cités. Sur un autre usage ou un autre climat, les poids changent ; leur ordre de grandeur reste.
# clé : (en clair, chauffage (÷2, ×2), degrés-heures (÷2, ×2), comment le donner)
POIDS_DES_HYPOTHESES = {
    "etancheite": ("l'étanchéité à l'air", (-0.18, 0.38), (0.14, -0.20), "[parois] n50"),
    "apports": ("les apports intérieurs", (0.30, -0.44), (-0.36, 0.91), "[usage_regle] apports_w_m2"),
    "inertie": ("l'inertie", (0.15, 0.15), (0.91, 0.91), "[parois] inertie (lourde ou legere)"),
    "u_mur": ("le U des murs", (-0.25, 0.44), (0.11, -0.10), "[parois] u_mur ou isolant_des_murs_cm"),
    "u_toit": ("le U du toit", (-0.17, 0.30), (-0.06, 0.14), "[parois] u_toit ou isolant_du_toit_cm"),
}
POIDS_SOURCE = "verification/poids_des_hypotheses.py, bureaux à Bordeaux"


def hypotheses_lourdes_non_donnees(periode: str, parois: Parois, zone: Optional[str], donnees_parois, usage_regle) -> List[str]:
    """Ce que le compte rendu demande : chaque hypothèse lourde prise par défaut, avec son poids et la façon de la donner."""
    retenu = parois_retenues(periode, parois, zone)
    par_defaut = {
        "etancheite": parois.n50 is None,
        "apports": "apports_w_m2" not in (usage_regle or {}),
        "inertie": "inertie" not in set(donnees_parois or ()),
        "u_mur": retenu["u_mur"][1].startswith("période"),
        "u_toit": retenu["u_toit"][1].startswith("période"),
    }
    lignes = []
    for cle, (nom, chauffage, dh, comment) in POIDS_DES_HYPOTHESES.items():
        if not par_defaut[cle]:
            continue
        if cle == "inertie":
            effet = f"légère plutôt que lourde : chauffage {chauffage[0] * 100:+.0f} %, degrés-heures {dh[0] * 100:+.0f} %"
        else:
            effet = (f"divisée par 2 ou doublée : chauffage de {chauffage[0] * 100:+.0f} à {chauffage[1] * 100:+.0f} %, "
                     f"degrés-heures de {dh[0] * 100:+.0f} à {dh[1] * 100:+.0f} %")
        lignes.append(f"hypothèse prise par défaut, faute d'être donnée : {nom}. Elle pèse lourd ({effet} "
                      f"[D : {POIDS_SOURCE}]) : la donner par {comment}")
    return lignes


def debit_de_fuite_m3_s_par_m2(q4pa_m3_h_m2: float) -> float:
    """Le débit des infiltrations par m² de paroi déperditive hors plancher bas, depuis la perméabilité sous 4 Pa.

    3CL §4 : n50 V = Q4Pa / (4/50)^(2/3), et les infiltrations valent e n50 V.
    """
    return COEFFICIENT_DE_PROTECTION_E * q4pa_m3_h_m2 / (4.0 / 50.0) ** EXPOSANT_DE_FUITE / 3600.0


REGLAGES_D_USAGE = ("apports_w_m2", "part_hors_occupation", "air_neuf_m3_h_m2", "heures", "jours_ouvres_seuls",
                    "ferme_l_ete", "chauffage_c", "froid_c", "chauffage_reduit_c", "air_neuf_reduit_m3_h_m2",
                    "air_neuf_avance_h", "air_neuf_maintien_h")
AIR_NEUF_HORS_OCCUPATION = ("air_neuf_reduit_m3_h_m2", "air_neuf_avance_h", "air_neuf_maintien_h")
DONNE = "donné dans l'étude"


def usage_regle(nom: str, reglages: Optional[Dict[str, object]] = None) -> Usage:
    """L'usage de ce nom, avec ce que l'étude en change. Lève ValueError en disant quel réglage est refusé."""
    from dataclasses import replace

    reglages = dict(reglages or {})
    inconnus = sorted(set(reglages) - set(REGLAGES_D_USAGE))
    if inconnus:
        raise ValueError(f"réglages inconnus : {', '.join(inconnus)}. Connus : {', '.join(REGLAGES_D_USAGE)}")
    u, change = USAGES[nom], {}
    for cle in ("apports_w_m2", "air_neuf_m3_h_m2"):
        if cle in reglages:
            valeur = reglages[cle]
            if isinstance(valeur, bool) or not isinstance(valeur, (int, float)) or valeur < 0:
                raise ValueError(f"{cle} : {valeur!r} n'est pas une valeur possible")
            change[cle] = float(valeur)
            change["source_apports" if cle == "apports_w_m2" else "source_air_neuf"] = DONNE
    if "part_hors_occupation" in reglages:
        part = reglages["part_hors_occupation"]
        if isinstance(part, bool) or not isinstance(part, (int, float)) or not 0.0 <= part <= 1.0:
            raise ValueError(f"part_hors_occupation : {part!r} n'est pas une part, de 0 à 1")
        change["part_hors_occupation"] = float(part)
    if "heures" in reglages:
        heures = reglages["heures"]
        if (not isinstance(heures, (list, tuple)) or len(heures) != 2
                or any(isinstance(h, bool) or not isinstance(h, int) for h in heures)
                or not 0 <= heures[0] < heures[1] <= 24):
            raise ValueError(f"heures : {heures!r} n'est pas un début et une fin d'occupation, par exemple [8, 18]")
        change["heures"] = (heures[0], heures[1])
    for cle in ("jours_ouvres_seuls", "ferme_l_ete"):
        if cle in reglages:
            if not isinstance(reglages[cle], bool):
                raise ValueError(f"{cle} : vrai ou faux")
            change[cle] = reglages[cle]
    for cle in ("chauffage_c", "froid_c", "chauffage_reduit_c"):
        if cle in reglages:
            valeur = reglages[cle]
            if isinstance(valeur, bool) or not isinstance(valeur, (int, float)) or not 0.0 <= valeur <= 40.0:
                raise ValueError(f"{cle} : {valeur!r} n'est pas une consigne, de 0 à 40 °C")
    for cle in AIR_NEUF_HORS_OCCUPATION:
        if cle in reglages:
            valeur = reglages[cle]
            if isinstance(valeur, bool) or not isinstance(valeur, (int, float)) or valeur < 0:
                raise ValueError(f"{cle} : {valeur!r} n'est pas une valeur possible")
    plein = change.get("air_neuf_m3_h_m2", u.air_neuf_m3_h_m2)
    if reglages.get("air_neuf_reduit_m3_h_m2", 0.0) > plein:
        raise ValueError(f"air_neuf_reduit_m3_h_m2 ({reglages['air_neuf_reduit_m3_h_m2']:g}) dépasse le débit en "
                         f"occupation ({plein:g} m³/h par m²)")
    chaud = reglages.get("chauffage_c")
    reduit = reglages.get("chauffage_reduit_c")
    tenu = chaud if chaud is not None else CONSIGNES_PAR_USAGE[u.cle_consignes][0]
    if reduit is not None and reduit > tenu:
        raise ValueError(f"chauffage_reduit_c ({reduit:g} °C) dépasse la consigne de chauffage ({tenu:g} °C)")
    return replace(u, **change)


def consignes_retenues(usage: Usage, reglages: Optional[Dict[str, object]] = None) -> tuple:
    """(chauffage, froid, réduit ou None, origine)."""
    reglages = reglages or {}
    chaud, froid, source = CONSIGNES_PAR_USAGE[usage.cle_consignes]
    donnees = [c for c in ("chauffage_c", "froid_c", "chauffage_reduit_c") if c in reglages]
    return (float(reglages.get("chauffage_c", chaud)), float(reglages.get("froid_c", froid)),
            float(reglages["chauffage_reduit_c"]) if "chauffage_reduit_c" in reglages else None,
            source + (f" ; {DONNE} : {', '.join(donnees)}" if donnees else ""))


@dataclass(frozen=True)
class Hypotheses:
    usage: str = "bureau"
    periode: str = "1975_1988"
    fenetres_ouvrables: bool = True
    aeration_nocturne: bool = False     # fenêtres laissées ouvertes la nuit quand la règle le permet
    climatisation: bool = False         # refroidi à la consigne de l'usage ; sinon la température monte librement
    parois: Parois = field(default_factory=Parois)
    reglages_d_usage: tuple = ()        # ce que l'étude change à l'usage : des paires (réglage, valeur)
    zone: Optional[str] = None          # la zone climatique du lieu (H1a...H3), pour les parois par défaut

    def l_usage(self) -> Usage:
        return usage_regle(self.usage, dict(self.reglages_d_usage))

    def les_consignes(self) -> tuple:
        return consignes_retenues(self.l_usage(), dict(self.reglages_d_usage))

    def l_air_neuf(self) -> tuple:
        """(débit réduit hors occupation, heures d'avance, heures de maintien), en m³/h par m² et en heures."""
        reglages = dict(self.reglages_d_usage)
        return (float(reglages.get("air_neuf_reduit_m3_h_m2", 0.0)), float(reglages.get("air_neuf_avance_h", 0.0)),
                float(reglages.get("air_neuf_maintien_h", 0.0)))

    def _air_neuf_hors_occupation(self) -> str:
        reduit, avance, maintien = self.l_air_neuf()
        if not (reduit or avance or maintien):
            return " ; coupé hors occupation"
        autour = (f", mis en marche {avance:g} h avant l'occupation et maintenu {maintien:g} h après"
                  if avance or maintien else "")
        return f" ; {reduit:.2f} m³/h par m² le reste du temps{autour} ({DONNE})"

    def justification(self) -> List[str]:
        u, p = self.l_usage(), parois_retenues(self.periode, self.parois, self.zone)
        chaud, froid, reduit, source = self.les_consignes()
        place = self.parois.isolation_des_murs or "exterieure"
        if self.parois.inertie == "legere":
            masse = "parois légères : ossature, plaque de plâtre côté intérieur, plancher lourd [H]"
        elif place == "interieure":
            masse = "murs lourds isolés par l'intérieur : la masse du mur est cachée derrière l'isolant [H]"
        elif place == "aucune":
            masse = "murs lourds sans isolant, 15 cm de béton [H]"
        else:
            masse = ("murs lourds, 15 cm de béton côté intérieur, isolant à l'extérieur"
                     + (" [H]" if self.parois.isolation_des_murs else " [H] ; place de l'isolant non donnée"))
        lignes = [
            f"usage {u.nom} : occupé de {u.heures[0]} h à {u.heures[1]} h"
            f"{', jours ouvrés' if u.jours_ouvres_seuls else ', tous les jours'}"
            + (" [S] RE2020 (p. 24)" if (u.nom, u.heures) in (("bureau", (8, 18)), ("enseignement", (8, 17)))
               else " [H]")
            + (", fermé du 7 juillet au 31 août [H : la RE2020 compte 50 % de présence en juillet et août]"
               if u.ferme_l_ete else ""),
            f"apports internes {u.apports_w_m2:.1f} W/m² en occupation : {u.source_apports}",
            f"air neuf {u.air_neuf_m3_h_m2:.2f} m³/h par m² en occupation : {u.source_air_neuf}"
            + self._air_neuf_hors_occupation(),
            f"chauffage à {chaud} °C" + (f", réduit à {reduit:g} °C hors occupation" if reduit is not None else "")
            + (f", climatisation à {froid} °C, à toute heure [H]" if self.climatisation else "")
            + f" : {source}" + ("" if self.climatisation else " ; pas de climatisation"),
        ]
        noms = {"u_mur": "mur", "u_toit": "toit", "u_plancher": "plancher", "u_vitrage": "vitrage"}
        lignes += [f"{nom} : U = {p[cle][0]:g} W/m².K, {p[cle][1]}" for cle, nom in noms.items()]
        for nom, valeur in (("murs", self.parois.absorption_des_murs), ("toit", self.parois.absorption_du_toit)):
            lignes.append(f"absorption solaire des {nom} : {valeur:g}, donnée" if nom == "murs" and valeur is not None
                          else f"absorption solaire du {nom} : {valeur:g}, donnée" if valeur is not None
                          else f"absorption solaire {'des murs' if nom == 'murs' else 'du toit'} : "
                               f"{ABSORPTION_PAR_DEFAUT:g}, teinte moyenne [H]")
        lignes.append(f"facteur solaire de la fenêtre {p['g_vitrage'][0]:g}, {p['g_vitrage'][1]}")
        if "n50" in p:
            lignes.append(f"étanchéité à l'air n50 = {p['n50'][0]:g} vol/h, {p['n50'][1]} ; infiltrations "
                          f"{COEFFICIENT_DE_PROTECTION_E:g} × n50, 3CL [S]")
        else:
            lignes.append(f"perméabilité à l'air {p['q4pa'][0]:g} m³/h par m² de parois sous 4 Pa, {p['q4pa'][1]} ; "
                          f"infiltrations {debit_de_fuite_m3_s_par_m2(p['q4pa'][0]) * 3600:.2f} m³/h par m² de "
                          f"parois exposées")
        lignes.append(masse)
        if self.fenetres_ouvrables:
            quand = "jour et nuit" if self.aeration_nocturne else "en occupation"
            lignes.append(
                f"fenêtres ouvertes {quand} au-dessus de {OUVERTURE_T_INTERIEURE_MIN_C:g} °C dedans, s'il fait au "
                f"moins {OUVERTURE_T_EXTERIEURE_MIN_C:g} °C dehors et pas plus de {-OUVERTURE_ECART_MIN_K:g} °C de plus "
                f"que dedans (RE2020 [S]) ; {100 * u.part_ouvrante:.0f} % de l'aire des baies s'ouvre, "
                f"{u.source_ouvrante} ; débit du tirage et du vent sur une seule façade (rayflect.aeration)")
        else:
            lignes.append("fenêtres jamais ouvertes")
        return lignes


def _occupation(u: Usage, plein: float, vide: float, nom: str, au_jour_de_base: float = 0.0,
                limite=limites.fractional) -> ScheduleRuleset:
    """Un planning : `plein` aux heures d'occupation, `vide` le reste du temps.

    `au_jour_de_base` : sa valeur le jour où se dimensionne le chauffage (voir rayflect.puissance).
    """
    ouvre = ScheduleDay.from_values_at_timestep(
        f"{nom}_ouvre", [plein if u.heures[0] <= h < u.heures[1] else vide for h in range(24)])
    ferme = ScheduleDay(f"{nom}_ferme", [vide])
    regles = []
    if u.ferme_l_ete:
        ete = ScheduleRule(ferme, start_date=Date(7, 7), end_date=Date(8, 31))
        ete.apply_all = True
        regles.append(ete)
    semaine = ScheduleRule(ouvre)
    if u.jours_ouvres_seuls:
        semaine.apply_weekday = True
    else:
        semaine.apply_all = True
    regles.append(semaine)
    return ScheduleRuleset(nom, ferme, regles, limite, winter_designday_schedule=ScheduleDay(
        f"{nom}_au_jour_de_base", [au_jour_de_base]))


def heures_occupees(u: Usage, premier_jour_lundi_0: int = 6) -> List[bool]:
    """Les 8 760 heures de l'année, vraies en occupation. L'année de calcul de Honeybee commence un dimanche."""
    masque = []
    for heure in range(8760):
        jour = heure // 24
        semaine = (jour + premier_jour_lundi_0) % 7
        ouvre = (not u.jours_ouvres_seuls) or semaine < 5
        if u.ferme_l_ete and 187 <= jour <= 242:            # du 7 juillet au 31 août, année de 365 jours
            ouvre = False
        masque.append(ouvre and u.heures[0] <= heure % 24 < u.heures[1])
    return masque


ABSORPTION_PAR_DEFAUT = 0.7         # [H] celle que Honeybee donne à un matériau : une teinte moyenne


def _teinter(paroi: OpaqueConstruction, absorption: Optional[float]) -> OpaqueConstruction:
    """La paroi avec sa face extérieure à l'absorption donnée ; sans valeur, elle garde celle par défaut."""
    if absorption is not None:
        paroi.materials[0].solar_absorptance = absorption
        paroi.materials[0].visible_absorptance = absorption
    return paroi


def _paroi(nom: str, u_cible: float, place: str = "exterieure", inertie: str = "lourde") -> OpaqueConstruction:
    """Une paroi de U donné. Les couches vont du dehors vers le dedans : leur ordre fait l'inertie utile."""
    beton = EnergyMaterial(f"beton_{nom}", MASSE_BETON["epaisseur"], MASSE_BETON["k"], MASSE_BETON["rho"],
                           MASSE_BETON["cp"])
    plaque = EnergyMaterial(f"plaque_{nom}", PLAQUE["epaisseur"], PLAQUE["k"], PLAQUE["rho"], PLAQUE["cp"])
    if inertie == "legere":
        r_isolant = max(0.01, 1.0 / u_cible - R_SURFACES - PLAQUE["epaisseur"] / PLAQUE["k"])
        return OpaqueConstruction(nom, [EnergyMaterialNoMass(f"isolant_{nom}", r_isolant), plaque])
    r_masse = MASSE_BETON["epaisseur"] / MASSE_BETON["k"]
    if place == "interieure":
        r_isolant = max(0.01, 1.0 / u_cible - R_SURFACES - r_masse - PLAQUE["epaisseur"] / PLAQUE["k"])
        return OpaqueConstruction(nom, [beton, EnergyMaterialNoMass(f"isolant_{nom}", r_isolant), plaque])
    r_isolant = max(0.01, 1.0 / u_cible - R_SURFACES - r_masse)
    return OpaqueConstruction(nom, [EnergyMaterialNoMass(f"isolant_{nom}", r_isolant), beton])


# [H] Un plancher entre 2 niveaux : 20 cm de béton, sans isolant. La même couche lue des 2 côtés, pour que les 2
# faces de la paroi aient la même construction, comme EnergyPlus l'attend.
PLANCHER_INTERMEDIAIRE = dict(epaisseur=0.20, **BETON)


def ne_pas_chauffer(piece) -> None:
    """Une zone que rien ne chauffe ni ne refroidit, sans occupant ni air neuf : un atelier, un stockage.

    Elle garde ses parois, ses fuites et ses fenêtres ; sa température suit ce que lui donnent le dehors et les
    niveaux voisins. [H] aucun apport interne : à donner s'il y a des machines.
    """
    energie = piece.properties.energy
    energie.hvac = None
    energie.setpoint = None
    energie.ventilation = None
    energie.electric_equipment = None
    energie.people = None


def appliquer(modele, hypotheses: Hypotheses) -> None:
    """Pose l'usage, l'aération, le chauffage et les parois sur toutes les pièces du modèle."""
    u = hypotheses.l_usage()
    p = {cle: valeur for cle, (valeur, _origine) in
         parois_retenues(hypotheses.periode, hypotheses.parois, hypotheses.zone).items()}
    chaud, froid, reduit, _source = hypotheses.les_consignes()
    choix = hypotheses.parois
    place = "exterieure" if choix.isolation_des_murs in (None, "aucune") else choix.isolation_des_murs
    mur = _teinter(_paroi("mur", p["u_mur"], place, choix.inertie), choix.absorption_des_murs)
    toit = _teinter(_paroi("toit", p["u_toit"], "exterieure", choix.inertie), choix.absorption_du_toit)
    plancher = _paroi("plancher", p["u_plancher"])
    plaque = EnergyMaterial("plaque_de_platre", 0.013, 0.25, 850.0, 1000.0)             # [H] cloison légère
    cloison = OpaqueConstruction("cloison", [plaque, EnergyMaterialNoMass("vide_de_cloison", 0.5), plaque])
    entre_niveaux = OpaqueConstruction("plancher_intermediaire", [EnergyMaterial(
        "dalle_intermediaire", PLANCHER_INTERMEDIAIRE["epaisseur"], PLANCHER_INTERMEDIAIRE["k"],
        PLANCHER_INTERMEDIAIRE["rho"], PLANCHER_INTERMEDIAIRE["cp"])])
    vitrage = WindowConstruction("vitrage", [EnergyWindowMaterialSimpleGlazSys("verre", p["u_vitrage"], p["g_vitrage"])])
    # Au jour de base du chauffage : l'air neuf à plein débit, aucun apport interne.
    presence = _occupation(u, 1.0, 0.0, "presence", au_jour_de_base=1.0)
    apports = _occupation(u, 1.0, u.part_hors_occupation, "apports", au_jour_de_base=0.0)
    toujours = ScheduleRuleset.from_constant_value("toujours", 1.0, limites.fractional)
    # L'air neuf suit l'occupation, sauf si l'étude dit qu'il démarre avant, s'arrête après, ou ne se coupe pas.
    reduit_d_air, avance, maintien = hypotheses.l_air_neuf()
    air_neuf = presence
    if reduit_d_air or avance or maintien:
        from dataclasses import replace
        en_marche = replace(u, heures=(max(0, int(round(u.heures[0] - avance))),
                                       min(24, int(round(u.heures[1] + maintien)))))
        part = reduit_d_air / u.air_neuf_m3_h_m2 if u.air_neuf_m3_h_m2 > 0 else 0.0
        air_neuf = _occupation(en_marche, 1.0, part, "air_neuf_en_marche", au_jour_de_base=1.0)
    # LES FUITES D'AIR passent par les parois exposées (murs et toit ; ni le plancher sur le sol, ni un mur
    # mitoyen). Par défaut, la perméabilité est donnée par m² de ces parois (3CL) : chaque zone reçoit les fuites
    # de ses propres parois. Un n50 donné vaut pour le bâtiment entier : il est réparti sur ses parois exposées.
    # Une zone sans paroi exposée n'en reçoit pas, sans que le total du bâtiment change.
    dehors = sum(piece.exposed_area for piece in modele.rooms)
    if "n50" in p:
        volume = sum(piece.volume for piece in modele.rooms)
        par_m2 = COEFFICIENT_DE_PROTECTION_E * p["n50"] * volume / 3600.0 / dehors if dehors > 0 else 0.0
    else:
        par_m2 = debit_de_fuite_m3_s_par_m2(p["q4pa"])
    fuites = Infiltration("infiltration", par_m2, toujours) if dehors > 0 else None
    consignes = Setpoint(
        "consignes",
        # Avec un réduit, la consigne baisse hors occupation ; au jour de base, elle est tenue toute la journée.
        (ScheduleRuleset.from_constant_value("chauffage", chaud, limites.temperature) if reduit is None else
         _occupation(u, chaud, reduit, "chauffage", au_jour_de_base=chaud, limite=limites.temperature)),
        # Sans climatisation, la consigne de froid est mise hors d'atteinte : la température monte librement.
        ScheduleRuleset.from_constant_value("froid", froid if hypotheses.climatisation else 50.0,
                                            limites.temperature))
    regle_fenetres = VentilationControl(
        OUVERTURE_T_INTERIEURE_MIN_C, 100.0, OUVERTURE_T_EXTERIEURE_MIN_C, 100.0, OUVERTURE_ECART_MIN_K,
        toujours if hypotheses.aeration_nocturne else presence)

    for piece in modele.rooms:
        for face in piece.faces:
            type_face = face.type.name
            if type_face == "AirBoundary":
                continue                    # une limite d'air entre 2 zones d'un même plateau : pas de paroi
            if type_face == "Wall" and face.boundary_condition.name == "Surface":
                face.properties.energy.construction = cloison       # un mur entre 2 zones
                continue
            if type_face in ("Floor", "RoofCeiling") and face.boundary_condition.name == "Surface":
                face.properties.energy.construction = entre_niveaux     # un plancher entre 2 niveaux
                continue
            face.properties.energy.construction = {"Wall": mur, "RoofCeiling": toit}.get(type_face, plancher)
            for baie in face.apertures:
                baie.properties.energy.construction = vitrage
                baie.is_operable = hypotheses.fenetres_ouvrables
        energie = piece.properties.energy
        energie.people = None
        energie.lighting = None
        energie.electric_equipment = ElectricEquipment("apports", u.apports_w_m2, apports, 0.5)   # [H] 50 % radiatif
        energie.ventilation = Ventilation("air_neuf", flow_per_area=u.air_neuf_m3_h_m2 / 3600.0, schedule=air_neuf)
        energie.infiltration = fuites if piece.exposed_area > 0 else None
        energie.setpoint = consignes
        energie.add_default_ideal_air()
        air = energie.hvac.duplicate()
        air.economizer_type = "NoEconomizer"
        air.demand_controlled_ventilation = False
        air.sensible_heat_recovery = 0
        air.latent_heat_recovery = 0
        air.heating_limit = no_limit
        air.cooling_limit = no_limit
        energie.hvac = air
        if hypotheses.fenetres_ouvrables and piece.exterior_aperture_area > 0:
            energie.window_vent_control = regle_fenetres
            energie.assign_ventilation_opening(VentilationOpening(
                u.part_ouvrante, 1.0, discharge_coefficient=OUVERTURE_COEFFICIENT_DE_TIRAGE))
