"""La ventilation naturelle par les fenêtres : ce qu'un scénario ouvre, quand, et le débit qui en sort.

Sans cet élément, l'étude ouvre les fenêtres selon sa clé `fenetres`, par ce même module : toutes les baies,
une seule façade, aux heures d'occupation ou jour et nuit. Un scénario qui porte un élément `ouvrants` remplace
ce réglage, pour tout le bâtiment : les
baies des orientations visées s'ouvrent comme il le dit, les autres restent fermées. On compare ainsi « fenêtres
fermées », « ouvertes en journée », « ouvertes la nuit », « traversant », sur le même bâtiment.

CE QUE CALCULE ENERGYPLUS (`ZoneVentilation:WindandStackOpenArea`), par ouvrant et à chaque pas de temps :

    débit du vent      Qv = Ce . A . V          V : vitesse du vent à la hauteur de la pièce
    débit du tirage    Qt = Cd . A . racine(2 g H |Ti - Te| / T)     T : la plus chaude des 2, en kelvins
    débit total        Q  = racine(Qv² + Qt²)

Les 2 coefficients et les 2 longueurs sont à nous. Ce module les pose pour 2 situations :

  UNE SEULE FAÇADE (le défaut). L'air entre par le bas de l'ouvrant et sort par le haut. En intégrant la vitesse
  sur la moitié basse d'un ouvrant de hauteur H et d'aire A, on trouve [D] :
        Qt = Cd0 . (A / 3) . racine(g H |Ti - Te| / T)
  où Cd0 est le coefficient de l'orifice. Pour qu'EnergyPlus rende ce débit avec A et H entiers, on lui donne
  Cd = Cd0 / (3 racine(2)), soit 0,141 pour Cd0 = 0,6. Le vent seul fait entrer Qv = 0,025 . A . V.

  TRAVERSANT (`traversant = true`). La pièce a des ouvrants sur 2 façades au moins et rien n'arrête l'air entre
  elles. EnergyPlus calcule alors Ce lui-même, ouvrant par ouvrant, selon l'angle entre le vent et la façade :
  0,55 de face, 0,30 à 45°, 0 à partir de 99° (`efficacite_du_vent`, relevée sur EnergyPlus 25.2 par
  `verification/ouvrants.py`, à 0,2 % près sur l'année). La note du dictionnaire d'EnergyPlus dit autre chose
  (0,30 à 180°) : c'est le calcul qui fait foi, et le banc le rejoue. Seuls les ouvrants au vent comptent
  donc : ceux sous le vent servent de sortie, supposée au moins aussi grande que l'entrée [H]. Le tirage reste
  celui d'une façade.
  Une pièce qui n'a d'ouvrants que d'un côté est traitée comme une seule façade, et le compte rendu le dit.

CE QUI N'EST PAS MODÉLISÉ : le tirage d'un niveau à l'autre (cage d'escalier, atrium, cheminée), qui demande le
réseau de flux d'air d'EnergyPlus ; les portes intérieures ; la pluie, le bruit et la sécurité, qui décident
souvent de l'ouverture réelle ; les occupants, remplacés par une règle de température. Aucun cas normalisé ne
vérifie ces débits : `verification/ouvrants.py` contrôle seulement qu'EnergyPlus applique bien les formules
ci-dessus avec nos coefficients.

Chaque valeur porte son origine : [S] lue dans une source, [C] citée sans relecture, [D] déduite, [H] hypothèse.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from honeybee_energy.ventcool.control import VentilationControl

from rayflect import hypotheses as hyp, ventilation
from rayflect.io.releve import secteur

COEFFICIENT_D_ORIFICE = 0.6             # [C] orifice à bord vif ; valeur d'usage des guides de ventilation
# [C] Warren et Parkins, 1985, repris par le guide CIBSE AM10 : sur une seule façade, le vent fait entrer
# 0,025 . A . V. Cité de mémoire, non relu à la source.
EFFICACITE_DU_VENT_UNE_FACADE = 0.025
ECART_D_AZIMUT_TRAVERSANT_DEG = 90.0    # [H] 2 façades comptent comme opposées à partir de cet écart


@dataclass(frozen=True)
class Ouvrants:
    """Les fenêtres qu'un scénario ouvre. Les valeurs par défaut sont celles de `rayflect.hypotheses`."""
    orientations: Optional[Tuple[str, ...]] = None      # None : toutes les façades
    part_ouvrable: Optional[float] = None               # None : celle de l'usage (hypotheses.USAGES, RE2020)
    part_de_hauteur: float = 1.0                        # part de la hauteur de la baie que prend l'ouvrant
    heures: Optional[Tuple[int, int]] = None            # None : en occupation ; (0, 24) : jour et nuit ; (22, 6)
    seuil_interieur_c: float = hyp.OUVERTURE_T_INTERIEURE_MIN_C     # [S] RE2020 : on ouvre au-dessus, dedans...
    exterieur_minimal_c: float = hyp.OUVERTURE_T_EXTERIEURE_MIN_C   # ...s'il fait au moins cela dehors...
    ecart_minimal_k: float = hyp.OUVERTURE_ECART_MIN_K              # ...et au moins cet écart de fraîcheur
                                                                    # (négatif : il peut faire plus chaud dehors)
    traversant: bool = False
    vent_maximal_m_s: float = 40.0                      # au-delà, on ferme ; 40 : jamais, le défaut d'EnergyPlus

    def __post_init__(self) -> None:
        if self.part_ouvrable is not None and not 0.0 < self.part_ouvrable <= 1.0:
            raise ValueError("part_ouvrable est une part de l'aire de la baie, au-dessus de 0 et jusqu'à 1")
        if not 0.0 < self.part_de_hauteur <= 1.0:
            raise ValueError("part_de_hauteur est une part de la hauteur de la baie, au-dessus de 0 et jusqu'à 1")
        if self.heures is not None:
            heures = tuple(self.heures)
            if len(heures) != 2 or any(isinstance(h, bool) or not isinstance(h, int) or not 0 <= h <= 24
                                       for h in heures) or heures[0] == heures[1]:
                raise ValueError("heures : 2 heures entières de 0 à 24, par exemple [22, 6] ou [0, 24]")
        if not 0.0 < self.vent_maximal_m_s <= 40.0:
            raise ValueError("vent_maximal_m_s : une vitesse de vent, au-dessus de 0 et jusqu'à 40 m/s")

    def quand(self) -> str:
        if self.heures is None:
            return "en occupation"
        return "jour et nuit" if tuple(self.heures) == (0, 24) else f"de {self.heures[0]} h à {self.heures[1]} h"


COEFFICIENT_DE_TIRAGE = COEFFICIENT_D_ORIFICE / (3.0 * 2.0 ** 0.5)       # [D] voir l'en-tête : 0,141


def efficacite_du_vent(traversant: bool, azimut_de_l_ouvrant_deg: float = 0.0, vent_venant_de_deg: float = 0.0) -> float:
    """Ce, la part de la vitesse du vent qui passe par l'ouvrant.

    En traversant, c'est la règle qu'applique EnergyPlus 25.2 quand on le laisse calculer : 0,55 quand le vent
    arrive de face, 0,25 de moins par 45° d'écart, jamais moins de 0.
    """
    if not traversant:
        return EFFICACITE_DU_VENT_UNE_FACADE
    return max(0.0, 0.55 - 0.25 * _ecart_d_azimut(azimut_de_l_ouvrant_deg, vent_venant_de_deg) / 45.0)


def debit_m3_s(aire_m2: float, hauteur_m: float, dedans_c: float, dehors_c: float, vent_m_s: float,
               efficacite: float) -> float:
    """Le débit d'un ouvrant grand ouvert, par les formules de l'en-tête : vent et tirage, en quadrature."""
    du_vent = efficacite * aire_m2 * vent_m_s
    du_tirage = COEFFICIENT_DE_TIRAGE * aire_m2 * (
        2.0 * 9.81 * hauteur_m * abs(dedans_c - dehors_c) / (max(dedans_c, dehors_c) + 273.15)) ** 0.5
    return (du_vent ** 2 + du_tirage ** 2) ** 0.5


def combien(nombre: int, un: str, plusieurs: str) -> str:
    """« 1 pièce », « 3 pièces » : le nombre en chiffres, le nom accordé."""
    return f"{int(nombre)} {un if int(nombre) < 2 else plusieurs}"


def _ecart_d_azimut(a: float, b: float) -> float:
    return abs((a - b + 180.0) % 360.0 - 180.0)


def est_traversante(baies) -> bool:
    """Vrai si ces baies regardent au moins 2 côtés nettement différents."""
    azimuts = [baie.azimuth for baie in baies]
    return any(_ecart_d_azimut(a, b) >= ECART_D_AZIMUT_TRAVERSANT_DEG for a in azimuts for b in azimuts)


def poser(modele, ouvrants: Ouvrants, usage: hyp.Usage) -> Tuple[str, List[str]]:
    """Remplace l'ouverture des fenêtres du modèle. À appeler après `hypotheses.appliquer`.

    Rend (le texte à ajouter au fichier d'EnergyPlus, ce que le compte rendu doit en dire).
    """
    if ouvrants.heures is None:
        planning = hyp._occupation(usage, 1.0, 0.0, "ouvrants_en_occupation")
    else:
        planning = ventilation._heures(*ouvrants.heures, "ouvrants_aux_heures")
    if ouvrants.part_ouvrable is not None:
        part, d_ou = ouvrants.part_ouvrable, "donnée"
    elif usage is not None:
        part, d_ou = usage.part_ouvrante, "RE2020 [S]"
    else:
        part, d_ou = hyp.OUVERTURE_PART_DE_BAIE, "RE2020, bureau [S]"
    lignes: List[str] = []
    comptes: Dict[str, float] = {"ouvrants": 0, "aire_m2": 0.0, "traversantes": 0, "une_facade": 0}
    for piece in modele.rooms:
        energie = piece.properties.energy
        energie.remove_ventilation_opening()
        energie.window_vent_control = None
        baies = [baie for face in piece.faces for baie in face.apertures
                 if face.boundary_condition.name == "Outdoors" and face.type.name == "Wall"]
        for baie in baies:
            baie.is_operable = False
        ouvertes = [baie for baie in baies
                    if ouvrants.orientations is None or secteur(baie.azimuth) in ouvrants.orientations]
        if not ouvertes:
            continue
        # Le planning entre dans le fichier par la règle d'ouverture de la pièce, que Honeybee écrit ; sans
        # ouvrant de Honeybee, cette règle ne fait rien d'autre.
        energie.window_vent_control = VentilationControl(schedule=planning)
        traversante = ouvrants.traversant and est_traversante(ouvertes)
        comptes["traversantes" if traversante else "une_facade"] += 1
        vent = "Autocalculate" if traversante else EFFICACITE_DU_VENT_UNE_FACADE
        for baie in ouvertes:
            baie.is_operable = True
            aire = baie.area * part
            hauteur = (baie.geometry.max.z - baie.geometry.min.z) * ouvrants.part_de_hauteur
            comptes["ouvrants"] += 1
            comptes["aire_m2"] += aire
            lignes.append(
                "ZoneVentilation:WindandStackOpenArea,\n"
                f"  ouvrant_{baie.identifier},  !- Name\n"
                f"  {piece.identifier},  !- Zone Name\n"
                f"  {aire:.4f},  !- Opening Area\n"
                f"  {planning.identifier},  !- Opening Area Fraction Schedule Name\n"
                f"  {vent},  !- Opening Effectiveness\n"
                f"  {baie.azimuth % 360.0:.1f},  !- Effective Angle\n"
                f"  {hauteur:.3f},  !- Height Difference\n"
                f"  {COEFFICIENT_DE_TIRAGE:.4f},  !- Discharge Coefficient for Opening\n"
                f"  {ouvrants.seuil_interieur_c:g},  !- Minimum Indoor Temperature\n"
                "  ,  !- Minimum Indoor Temperature Schedule Name\n"
                "  100,  !- Maximum Indoor Temperature\n"
                "  ,  !- Maximum Indoor Temperature Schedule Name\n"
                f"  {ouvrants.ecart_minimal_k:g},  !- Delta Temperature\n"
                "  ,  !- Delta Temperature Schedule Name\n"
                f"  {ouvrants.exterieur_minimal_c:g},  !- Minimum Outdoor Temperature\n"
                "  ,  !- Minimum Outdoor Temperature Schedule Name\n"
                "  100,  !- Maximum Outdoor Temperature\n"
                "  ,  !- Maximum Outdoor Temperature Schedule Name\n"
                f"  {ouvrants.vent_maximal_m_s:g};  !- Maximum Wind Speed\n")
    ou = "toutes les façades" if ouvrants.orientations is None else "façades " + ", ".join(ouvrants.orientations)
    if not comptes["ouvrants"]:
        return "", [f"fenêtres : aucune baie à ouvrir sur les {ou} ; toutes restent fermées"]
    dit = [f"fenêtres ouvertes {ouvrants.quand()} sur {ou} : {combien(comptes['ouvrants'], 'ouvrant', 'ouvrants')}, "
           f"{comptes['aire_m2']:.1f} m² libres ({100 * part:.0f} % de la baie, {d_ou}), au-dessus de "
           f"{ouvrants.seuil_interieur_c:g} °C dedans, s'il fait au moins {ouvrants.ecart_minimal_k:g} K de moins "
           f"dehors et au moins {ouvrants.exterieur_minimal_c:g} °C"]
    if comptes["traversantes"]:
        dit.append(f"ventilation traversante dans {combien(comptes['traversantes'], 'pièce', 'pièces')} : le vent entre par les "
                   f"ouvrants qui lui font face et sort par les autres ; rien n'arrête l'air entre les façades [H], "
                   f"à confirmer sur place")
    if comptes["une_facade"]:
        cause = ("ouvrants d'un seul côté" if ouvrants.traversant else "une seule façade")
        dit.append(f"{combien(comptes['une_facade'], 'pièce ventilée', 'pièces ventilées')} par {cause} : l'air entre "
                   f"par le bas de l'ouvrant et sort par le haut [D], le vent ajoute "
                   f"{EFFICACITE_DU_VENT_UNE_FACADE:g} × aire × vitesse [C]")
    dit.append("fenêtres : le tirage entre niveaux, la pluie, le bruit et la sécurité ne sont pas comptés")
    return "\n".join(lignes) + "\n", dit
