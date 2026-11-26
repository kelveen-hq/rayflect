"""Le carbone de ce que chaque scénario construit : une casquette en béton n'est pas une pergola en bois.

Le carbone d'exploitation se lit dans l'énergie achetée (rayflect.energie). Celui-ci est le carbone des matériaux
ajoutés au bâtiment, de leur extraction à leur sortie d'usine (modules A1 à A3 d'une analyse de cycle de vie, norme
NF EN 15804) : un ordre de grandeur pour arbitrer entre des mesures, pas une analyse de cycle de vie.

CHAQUE ÉLÉMENT SE MESURE DANS LE MODÈLE, au moment où il est posé (rayflect.etude) :
  - une protection en géométrie (casquette, joues, lames fixes ou saisonnières, balcon, pergola) : la surface des
    ombres ajoutées, en m² ;
  - une protection qui se manœuvre (BSO, lames pilotées) : la surface des baies équipées, en m² ;
  - une variante de façade : la surface de vitrage ajoutée, en m² ;
  - des parois mieux isolées : le volume d'isolant ajouté, depuis l'écart de résistance et la surface des parois ;
  - du photovoltaïque : sa production, par le facteur du kWh photovoltaïque sur tout son cycle de vie.
La masse vient de la masse par m² du matériau choisi ; le carbone, de son facteur par kg.

TOUT SE CHANGE dans le fichier d'étude, pour un matériau fait autrement (bas carbone, réemploi, biosourcé) :

    [carbone]
    facteurs = { aluminium = 2.3 }              # kg CO2e par kg : un aluminium recyclé, par exemple
    masses_kg_m2 = { bois = 18.0 }              # kg par m² de protection
    materiaux = { casquette = "bois" }          # le matériau de chaque type d'élément

    [[scenario]]
    nom = "casquettes en bois"
    [scenario.carbone]
    materiaux = { casquette = "bois" }          # le même réglage, pour ce scénario seul

    [[scenario]]
    nom = "casquettes"
    carbone_kg = 950                            # le total d'une déclaration environnementale (FDES) : il remplace
                                                # l'estimation

Chaque valeur dit d'où elle vient : [S] lue dans sa source, [D] déduite, [H] supposée, [U] donnée par l'utilisateur.
Une valeur [H] est à remplacer par celle d'une FDES de la base INIES dès qu'on connaît le produit.

CE QUI N'EST PAS COMPTÉ : le transport, la pose, la fin de vie (modules A4, A5, C), les remplacements au long de la
vie du bâtiment, le carbone stocké dans le bois (il est hors du facteur du bois, comme dans ICE), les plantes, la
ventilation, les sondes, le mur Trombe, la couleur du toit. Ce qui n'est pas chiffré est dit, jamais compté pour 0
sans le dire.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence


@dataclass(frozen=True)
class Materiau:
    nom: str
    kgco2e_par_kg: float
    source: str
    masse_kg_m2: Optional[float] = None     # pour une protection plane : kg par m² de surface
    masse_source: str = ""
    masse_volumique: Optional[float] = None  # pour un isolant, kg/m³


ADEME = "ADEME, Base Empreinte, lue le 23/11/2026"
ICE = "ICE V3 (Hammond et Jones), cité par IStructE, « A brief guide to calculating embodied carbon », 2020, tableau 2"
MATERIAUX: Dict[str, Materiau] = {
    "aluminium": Materiau("aluminium primaire produit en France", 5.193, f"[S] {ADEME}",
                          8.1, "[D] tôle de 3 mm à 2 700 kg/m³ [H : l'épaisseur]"),
    "acier": Materiau("acier", 2.211, f"[S] {ADEME}, FEDEREC ; ICE V3 donne 1,13 à 2,45 selon l'origine",
                      23.6, "[D] tôle de 3 mm à 7 850 kg/m³ [H : l'épaisseur]"),
    "bois": Materiau("bois de construction résineux, hors carbone stocké", 0.263, f"[S] {ICE}",
                     13.5, "[D] lame de 27 mm à 500 kg/m³ [H : l'épaisseur et la masse volumique]"),
    "lamelle_colle": Materiau("bois lamellé-collé, hors carbone stocké", 0.512, f"[S] {ICE}",
                              22.5, "[D] 45 mm à 500 kg/m³ [H]"),
    "beton": Materiau("béton C25/30", 0.088, f"[S] {ADEME}, ATILH", 360.0, "[D] 15 cm à 2 400 kg/m³ [H : l'épaisseur]"),
    "beton_arme": Materiau("béton armé", 0.155, f"[S] {ADEME}, ATILH", 360.0,
                           "[D] 15 cm à 2 400 kg/m³ [H : l'épaisseur]"),
    "verre": Materiau("verre plat flotté", 1.26, f"[S] {ADEME}", 20.0,
                      "[D] double vitrage, 2 verres de 4 mm à 2 500 kg/m³"),
    "pvc": Materiau("PVC", 1.87, f"[S] {ADEME}"),
    "laine_minerale": Materiau("laine minérale", 1.28, "[H] ordre de grandeur, à confirmer dans INIES",
                               masse_volumique=30.0),
    "polystyrene": Materiau("polystyrène expansé", 2.83, f"[S] {ADEME}, plastique PS (le polymère, sans l'expansion)",
                            masse_volumique=20.0),
    "fibre_de_bois": Materiau("fibre de bois, hors carbone stocké", 0.6, "[H] ordre de grandeur, à confirmer dans INIES",
                              masse_volumique=140.0),
}
PHOTOVOLTAIQUE_KG_PAR_KWH = 0.0439      # [S] ADEME, Base Empreinte : électricité photovoltaïque, cycle de vie
# L'électricité du réseau que le photovoltaïque remplace : le DPE ne donne pas de facteur pour elle. Celui de
# l'électricité de refroidissement, 0,064 kg CO2/kWh [S : arrêté du 31 mars 2021, annexe 4, tableau 1.1], est pris
# faute de mieux [H] ; facteur_electricite_kgco2_kwh dans [energie] le remplace.
DUREE_DU_PHOTOVOLTAIQUE_ANS = 30        # [H] la durée sur laquelle ce facteur se répartit
CADRE_KG_M2 = 5.0                       # [H] cadre aluminium d'une baie, par m² de vitrage
BSO_KG_M2 = 5.0                         # [H] lames et coulisses aluminium d'un BSO, par m² de baie

# Le matériau par défaut de chaque type d'élément [H].
PAR_DEFAUT = {"casquette": "aluminium", "joues": "aluminium", "lames_horizontales": "aluminium",
              "lames_verticales": "aluminium", "lames_saisonnieres": "aluminium", "lames_pilotees": "aluminium",
              "bso": "aluminium", "balcon": "beton_arme", "pergola": "bois", "isolant": "laine_minerale",
              "cadre": "aluminium"}
NON_CHIFFRES = {"arbre": "une plantation", "grimpante": "une plantation", "toit": "un revêtement de toit",
                "teinte": "une peinture de façade",
                "mur_vegetal": "les modules, leur substrat et leur arrosage : donner carbone_kg, d'après la FDES du fabricant",
                "ouvrants": "aucun matériau ajouté", "ventilation": "une machine", "mur_trombe": "le mur Trombe",
                "sondes": "les sondes", "apport_horaire": "un apport calculé ailleurs"}


@dataclass(frozen=True)
class Mesure:
    """Ce qu'un élément a ajouté au bâtiment, mesuré dans le modèle."""
    type: str
    quantite: float
    unite: str                          # « m² d'ombres », « m² de baies », « m² de vitrage », « m³ d'isolant », « kWh/an »


@dataclass
class Reglages:
    """La table [carbone] du fichier d'étude."""
    facteurs: Dict[str, float] = field(default_factory=dict)
    masses_kg_m2: Dict[str, float] = field(default_factory=dict)
    materiaux: Dict[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for nom, table in (("facteurs", self.facteurs), ("masses_kg_m2", self.masses_kg_m2)):
            for cle, valeur in table.items():
                if cle not in MATERIAUX:
                    raise ValueError(f"[carbone] {nom} : matériau « {cle} » inconnu. Connus : {', '.join(MATERIAUX)}")
                if isinstance(valeur, bool) or not isinstance(valeur, (int, float)) or valeur < 0:
                    raise ValueError(f"[carbone] {nom}.{cle} = {valeur!r} : un nombre positif")
        for cle, valeur in self.materiaux.items():
            if valeur not in MATERIAUX:
                raise ValueError(f"[carbone] materiaux.{cle} = « {valeur} » : matériau inconnu. Connus : "
                                 f"{', '.join(MATERIAUX)}")

    def avec(self, table: Optional[dict]) -> "Reglages":
        """Ces réglages, complétés et remplacés par ceux d'un scénario ([scenario.carbone])."""
        propre = lire_les_reglages(table)
        return Reglages({**self.facteurs, **propre.facteurs}, {**self.masses_kg_m2, **propre.masses_kg_m2},
                        {**self.materiaux, **propre.materiaux})

    def facteur(self, materiau: str) -> tuple:
        if materiau in self.facteurs:
            return float(self.facteurs[materiau]), "[U] donné dans l'étude"
        m = MATERIAUX[materiau]
        return m.kgco2e_par_kg, m.source

    def masse(self, materiau: str) -> tuple:
        if materiau in self.masses_kg_m2:
            return float(self.masses_kg_m2[materiau]), "[U] donnée dans l'étude"
        m = MATERIAUX[materiau]
        return m.masse_kg_m2, m.masse_source

    def materiau(self, type_: str) -> str:
        return self.materiaux.get(type_, PAR_DEFAUT.get(type_, "aluminium"))


def lire_les_reglages(table: Optional[dict]) -> Reglages:
    table = dict(table or {})
    inconnues = sorted(set(table) - {"facteurs", "masses_kg_m2", "materiaux"})
    if inconnues:
        raise ValueError(f"[carbone] : clés inconnues : {', '.join(inconnues)}. Connues : facteurs, masses_kg_m2, materiaux")
    return Reglages(dict(table.get("facteurs", {})), dict(table.get("masses_kg_m2", {})), dict(table.get("materiaux", {})))


def _ligne(element: str, materiau: str, masse_kg: float, facteur: float, d_ou: List[str], quantite: str) -> dict:
    return {"element": element, "materiau": MATERIAUX[materiau].nom if materiau in MATERIAUX else materiau,
            "quantite": quantite, "masse_kg": round(masse_kg), "kgco2e": round(masse_kg * facteur),
            "sources": d_ou}


def chiffrer(mesures: Sequence[Mesure], reglages: Reglages, production_kwh: Optional[float] = None,
             donne_kg: Optional[float] = None) -> dict:
    """Le carbone d'un scénario : une ligne par élément, son total, et ce qui n'est pas chiffré."""
    if donne_kg is not None:
        return {"lignes": [{"element": "tout le scénario", "materiau": "donné dans l'étude", "quantite": "",
                            "masse_kg": None, "kgco2e": round(donne_kg), "sources": ["[U] carbone_kg du scénario"]}],
                "kgco2e": round(donne_kg), "non_chiffres": [], "co2_evite_kg_par_an": None, "retour_ans": None}
    lignes, non_chiffres = [], []
    for m in mesures:
        if m.type in NON_CHIFFRES:
            non_chiffres.append(f"{m.type} : {NON_CHIFFRES[m.type]}")
            continue
        if m.quantite <= 0:
            continue
        if m.type == "photovoltaique":
            if production_kwh:
                kg = production_kwh * DUREE_DU_PHOTOVOLTAIQUE_ANS * PHOTOVOLTAIQUE_KG_PAR_KWH
                lignes.append({"element": "photovoltaique", "materiau": "panneaux, onduleur, structure",
                               "quantite": f"{production_kwh:.0f} kWh/an sur {DUREE_DU_PHOTOVOLTAIQUE_ANS} ans",
                               "masse_kg": None, "kgco2e": round(kg),
                               "sources": [f"[S] {ADEME} : {PHOTOVOLTAIQUE_KG_PAR_KWH} kg CO2e/kWh, cycle de vie",
                                           f"[H] {DUREE_DU_PHOTOVOLTAIQUE_ANS} ans de production"]})
            continue
        if m.type == "isolant":
            materiau = reglages.materiau("isolant")
            facteur, source = reglages.facteur(materiau)
            densite = MATERIAUX[materiau].masse_volumique or 30.0
            lignes.append(_ligne("isolant", materiau, m.quantite * densite, facteur,
                                 [source, f"[H] {densite:g} kg/m³"], f"{m.quantite:.1f} {m.unite}"))
            continue
        if m.type == "vitrage":
            verre, source_verre = reglages.facteur("verre")
            masse_verre = reglages.masse("verre")[0] or 20.0
            lignes.append(_ligne("vitrage remplacé", "verre", m.quantite * masse_verre, verre,
                                 [source_verre, MATERIAUX["verre"].masse_source, "[H] les cadres sont gardés"],
                                 f"{m.quantite:.1f} {m.unite}"))
            continue
        if m.type == "facade":
            verre, source_verre = reglages.facteur("verre")
            cadre = reglages.materiau("cadre")
            facteur_cadre, source_cadre = reglages.facteur(cadre)
            masse_verre = reglages.masse("verre")[0] or 20.0
            lignes.append(_ligne("facade, vitrage", "verre", m.quantite * masse_verre, verre,
                                 [source_verre, MATERIAUX["verre"].masse_source], f"{m.quantite:.1f} {m.unite}"))
            lignes.append(_ligne("facade, cadres", cadre, m.quantite * CADRE_KG_M2, facteur_cadre,
                                 [source_cadre, f"[H] {CADRE_KG_M2:g} kg de cadre par m² de vitrage"],
                                 f"{m.quantite:.1f} {m.unite}"))
            continue
        materiau = reglages.materiau(m.type)
        facteur, source = reglages.facteur(materiau)
        if m.type in ("bso", "lames_pilotees") and materiau not in reglages.masses_kg_m2:
            masse_m2, source_masse = BSO_KG_M2, f"[H] {BSO_KG_M2:g} kg par m² de baie équipée"
        else:
            masse_m2, source_masse = reglages.masse(materiau)
        if masse_m2 is None:
            non_chiffres.append(f"{m.type} : pas de masse par m² pour « {materiau} » ; la donner dans "
                                f"[carbone] masses_kg_m2")
            continue
        lignes.append(_ligne(m.type, materiau, m.quantite * masse_m2, facteur, [source, source_masse],
                             f"{m.quantite:.1f} {m.unite}"))
    return {"lignes": lignes, "kgco2e": sum(ligne["kgco2e"] for ligne in lignes),
            "non_chiffres": list(dict.fromkeys(non_chiffres)), "co2_evite_kg_par_an": None, "retour_ans": None}


def evite(carbones: Dict[str, dict], ordre: Sequence[str], co2_par_an: Dict[str, Optional[float]],
          productions_kwh: Dict[str, float], facteur_electricite: Optional[float]) -> None:
    """Le CO2 que chaque scénario évite chaque année face au premier, et le retour de son carbone construit.

    L'exploitation compte le chauffage et le froid achetés (rayflect.energie) ; le photovoltaïque, l'électricité qu'il
    produit, au facteur de l'électricité du réseau qu'elle remplace.
    """
    reference = co2_par_an.get(ordre[0])
    for nom in ordre:
        if nom not in carbones or reference is None or co2_par_an.get(nom) is None:
            continue
        economie = reference - co2_par_an[nom]
        production = productions_kwh.get(nom) or 0.0
        if production and facteur_electricite is not None:
            economie += production * facteur_electricite
        carbones[nom]["co2_evite_kg_par_an"] = round(economie)
        carbones[nom]["retour_ans"] = retour(carbones[nom]["kgco2e"], economie)


def retour(carbone_kg: float, economie_kgco2_par_an: Optional[float]) -> Optional[float]:
    """Les années d'exploitation pour rembourser le carbone construit, ou None sans économie de CO2."""
    if not carbone_kg or economie_kgco2_par_an is None or economie_kgco2_par_an <= 0:
        return None
    return round(carbone_kg / economie_kgco2_par_an, 1)


def dire(carbones: Dict[str, dict], ordre: Sequence[str]) -> List[str]:
    """Le compte rendu : le carbone construit de chaque scénario, élément par élément, et son retour en CO2."""
    autres = [nom for nom in ordre if nom in carbones and (carbones[nom]["lignes"] or carbones[nom]["non_chiffres"])]
    if not autres:
        return []
    lignes = ["", "Carbone des matériaux ajoutés (fabrication, A1 à A3), kg CO2e"]
    reference = ordre[0]
    for nom in autres:
        c = carbones[nom]
        lignes.append(f"  « {nom} » : {c['kgco2e']} kg CO2e")
        for ligne in c["lignes"]:
            masse = f", {ligne['masse_kg']} kg" if ligne["masse_kg"] is not None else ""
            lignes.append(f"    - {ligne['element']} : {ligne['materiau']}, {ligne['quantite']}{masse} : "
                          f"{ligne['kgco2e']} kg CO2e ({' ; '.join(ligne['sources'])})")
        for n in c["non_chiffres"]:
            lignes.append(f"    - non chiffré : {n}")
        if c.get("co2_evite_kg_par_an") is not None:
            economie, ans = c["co2_evite_kg_par_an"], c.get("retour_ans")
            lignes.append(f"    - exploitation, face à « {reference} » : {economie:+d} kg CO2 évités par an"
                          + (f" ; le carbone construit est remboursé en {ans:g} ans" if ans is not None
                             else " ; pas de retour : la mesure n'évite pas de CO2"))
    lignes.append("  - ordre de grandeur : ni transport, ni pose, ni fin de vie, ni remplacements ; une valeur [H] se "
                  "remplace par celle d'une FDES (INIES) dans [carbone] ou par carbone_kg dans le scénario")
    return lignes
