"""La puissance à installer : ce que le chauffage et la climatisation doivent pouvoir fournir.

Un besoin annuel en kWh dit ce que le bâtiment consomme ; il ne dit pas la taille de la machine. Celle-ci se
lit sur l'heure la plus dure. 2 lectures, qui ne se remplacent pas :

  - LE CHAUFFAGE AU JOUR DE BASE. EnergyPlus joue, en plus de l'année, un jour sans soleil où il fait dehors
    la température de base du lieu, du matin au soir, jusqu'à l'équilibre. Les apports internes y sont nuls et
    l'air neuf y est à plein débit : c'est la convention du dimensionnement, qui ne compte pas sur des apports
    gratuits [H : convention courante, celle de la norme NF EN 12831-1, à relire dans le texte]. Ces 2
    réglages sont posés par `hypotheses.appliquer`, sur les plannings de l'usage. Une protection
    solaire n'y change rien, faute de soleil ; un vitrage, un isolant ou une récupération de chaleur, si.
  - LES POINTES DE L'ANNÉE. L'heure de l'année type où le chauffage, puis le froid, sont le plus appelés,
    toutes zones ensemble, avec sa date. C'est là que le soleil compte : une protection solaire baisse la
    pointe de froid.

À SAVOIR. L'année type est faite de mois moyens : ni vague de froid, ni canicule. Sa pointe de froid est
celle d'un été ordinaire, et sa pointe de chauffage est en dessous de celle du jour de base. La température
de base, si elle n'est pas donnée, est tirée de cette même année type (dépassée 99,6 % des heures, l'usage
de l'ASHRAE) : elle est alors trop douce, et le compte rendu demande celle du lieu.

AU JOUR DE BASE, LA CONSIGNE EST TENUE SUR LA TEMPÉRATURE RESSENTIE, moyenne de celle de l'air et de celle des
parois. Un thermostat qui ne lit que l'air laisse les parois froides : sur une salle d'essai à -10 °C dehors,
l'air est à 19 °C et la température ressentie à 15,1 °C, pour une puissance 16 % plus basse. Tenir 19 °C
ressentis demande 5,42 kW, là où un calcul des déperditions à la main, au U des parois, donne 5,41 kW
(tests/test_puissance_energyplus.py). C'est la lecture retenue pour dimensionner.

L'ANNÉE, ELLE, RESTE RÉGLÉE SUR L'AIR, comme le fait un thermostat courant, sauf si l'étude demande
`consigne = "ressentie"` : sur la même salle, le besoin de chauffage monte alors de 27 % et celui de froid de
32 %. Les 2 lectures encadrent un bâtiment réel, dont le thermostat sent un peu des 2.

Les puissances sont celles que les LOCAUX demandent, en moyenne sur une heure. La machine se choisit ensuite
avec son rendement, ses pertes de distribution et sa relance après un arrêt, qui ne sont pas comptés ici.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence

HEURES_D_UNE_ANNEE = 8760
LONGUEURS_D_UNE_ANNEE = (8760, 8784)        # une année, bissextile ou non
HEURES_DU_JOUR_DE_BASE = 24
PART_DES_HEURES_PLUS_FROIDES = 0.004    # [S] ASHRAE Handbook of Fundamentals : conditions de calcul à 99,6 %
NOM_DU_JOUR_DE_BASE = "jour_de_base"
CONSIGNES = ("air", "ressentie")
PART_DES_PAROIS = 0.5                   # [S] EnergyPlus, Engineering Reference : la température opérative est la
                                        # moyenne de l'air et des parois quand l'air est calme (moins de 0,2 m/s)
NOM_DU_PLANNING = "part_des_parois_dans_la_consigne"
PRESSION_PA = 101325.0                  # [H] pression au niveau de la mer, à toute altitude
VENT_DU_JOUR_DE_BASE_M_S = 4.0          # [H] un vent moyen ; il règle l'échange des parois avec le dehors


@dataclass(frozen=True)
class Base:
    """La température extérieure de base, et d'où elle vient."""
    temperature_c: float
    origine: str
    a_demander: Optional[str] = None


def base_du_lieu(epw, donnee_c: Optional[float] = None) -> Base:
    """La température de base : celle qu'on donne, sinon celle que la météo de l'étude laisse deviner."""
    if donnee_c is not None:
        return Base(float(donnee_c), "donnée")
    froides = sorted(epw.dry_bulb_temperature.values)
    tiree = round(froides[int(PART_DES_HEURES_PLUS_FROIDES * len(froides))], 1)
    return Base(tiree, "tirée de l'année type, dépassée 99,6 % des heures",
                f"température extérieure de base du lieu, pour dimensionner le chauffage : {tiree:g} °C sont "
                f"tirés de l'année type, qui ne contient pas de vague de froid")


def ajouter_le_jour_de_base(reglages, epw, base: Base) -> None:
    """Ajoute aux réglages du calcul un jour sans soleil à la température de base, joué en plus de l'année."""
    from ladybug.designday import DesignDay
    from ladybug.dt import Date

    jour = DesignDay.from_design_day_properties(
        NOM_DU_JOUR_DE_BASE, "WinterDesignDay", epw.location, Date(1, 21), base.temperature_c, 0.0,
        "Wetbulb", base.temperature_c, PRESSION_PA, VENT_DU_JOUR_DE_BASE_M_S, 0.0, "ASHRAEClearSky", [0.0])
    reglages.sizing_parameter.add_design_day(jour)
    reglages.simulation_control.run_for_sizing_periods = True


def consigne_ressentie(modele, toute_l_annee: bool = False) -> str:
    """Le texte à ajouter au fichier d'EnergyPlus pour tenir la consigne sur la température ressentie.

    Au jour de base toujours ; le reste de l'année seulement si `toute_l_annee`. Chaque pièce chauffée reçoit
    le réglage, rattaché à son thermostat, qu'EnergyPlus nomme d'après la pièce.
    """
    reste = PART_DES_PAROIS if toute_l_annee else 0.0
    lignes = [f"""
Schedule:Compact,
  {NOM_DU_PLANNING}, , Through: 12/31,
  For: WinterDesignDay, Until: 24:00, {PART_DES_PAROIS},
  For: AllOtherDays, Until: 24:00, {reste};
"""]
    for piece in modele.rooms:
        if piece.properties.energy.setpoint is None or piece.properties.energy.hvac is None:
            continue
        lignes.append(f"""
ZoneControl:Thermostat:OperativeTemperature,
  {piece.identifier} Thermostat, Scheduled, , {NOM_DU_PLANNING};
""")
    return "".join(lignes)


class Annee:
    """Les résultats d'un calcul, séparés : l'année d'un côté, le jour de base de l'autre.

    Un calcul qui joue aussi un jour de base rend 2 séries par grandeur. Tout ce qui lit l'année passe par ici,
    pour ne pas y mêler les 24 heures du jour de base.
    """

    def __init__(self, resultats) -> None:
        self._resultats = resultats

    def data_collections_by_output_name(self, nom: str) -> list:
        return [s for s in self._resultats.data_collections_by_output_name(nom) if len(s.values) >= HEURES_D_UNE_ANNEE]

    def verifier(self, noms: Sequence[str]) -> None:
        """Lève `ValueError` si une série n'est ni une année entière ni un jour de base, ou si l'année manque.

        L'année se reconnaît à sa longueur. Une série d'une autre longueur (un calcul sur une partie de l'année,
        2 jours de base) serait rangée du mauvais côté sans que rien ne le dise.
        """
        for nom in noms:
            longueurs = sorted({len(s.values) for s in self._resultats.data_collections_by_output_name(nom)})
            inattendues = [n for n in longueurs if n not in LONGUEURS_D_UNE_ANNEE + (HEURES_DU_JOUR_DE_BASE,)]
            if inattendues:
                raise ValueError(f"« {nom} » : des séries de {', '.join(map(str, inattendues))} heures, qui ne sont "
                                 f"ni une année ni un jour de base")
            if longueurs and not any(n in LONGUEURS_D_UNE_ANNEE for n in longueurs):
                raise ValueError(f"« {nom} » : le calcul n'a pas rendu l'année")

    def du_jour_de_base(self, nom: str) -> list:
        return [s for s in self._resultats.data_collections_by_output_name(nom) if len(s.values) < HEURES_D_UNE_ANNEE]


def _ensemble(series: Sequence) -> List[float]:
    """La somme des zones, heure par heure : la puissance appelée par le bâtiment entier."""
    if not series:
        return []
    return [sum(valeurs) for valeurs in zip(*(s.values for s in series))]


def _quand(heure: int) -> str:
    from ladybug.dt import DateTime

    instant = DateTime.from_hoy(heure)
    return f"{instant.day}/{instant.month} à {instant.hour} h"


def _pointe(series: Sequence, epw) -> Optional[dict]:
    ensemble = _ensemble(series)
    if not ensemble or max(ensemble) <= 0:
        return None
    heure = max(range(len(ensemble)), key=ensemble.__getitem__)
    return {"kw": round(ensemble[heure], 2), "quand": _quand(heure),
            "dehors_c": round(epw.dry_bulb_temperature.values[heure], 1)}


def lire(annee: Annee, epw, base: Optional[Base], chauffage: str, froid: str, aire_m2: float) -> dict:
    """Les puissances d'un scénario. Une valeur absente est None : rien n'est appelé, ou rien n'a été joué.

    Les séries d'EnergyPlus sont des kWh par heure : une heure à 3 kWh est une heure à 3 kW en moyenne.
    """
    de_base = _ensemble(annee.du_jour_de_base(chauffage))
    chauffage_de_base = round(max(de_base), 2) if de_base else None
    return {
        "chauffage_au_jour_de_base_kw": chauffage_de_base,
        "chauffage_au_jour_de_base_w_m2": (round(1000.0 * chauffage_de_base / aire_m2)
                                           if chauffage_de_base is not None and aire_m2 > 0 else None),
        "temperature_de_base_c": base.temperature_c if base is not None else None,
        "pointe_de_chauffage": _pointe(annee.data_collections_by_output_name(chauffage), epw),
        "pointe_de_froid": _pointe(annee.data_collections_by_output_name(froid), epw),
    }


def expliquer(base: Base, climatisation: bool, consigne: str = "air") -> List[str]:
    """Ce qu'il faut dire à côté des puissances, pour qu'elles ne soient pas lues de travers."""
    lignes = [
        f"chauffage au jour de base : {base.temperature_c:g} °C dehors ({base.origine}), sans soleil ni apports "
        f"internes, air neuf à plein débit, consigne tenue sur la température ressentie ; c'est la puissance à "
        f"retenir pour le chauffage",
        "pointes de l'année : l'heure la plus chargée de l'année type, toutes zones ensemble ; un été "
        "ordinaire, pas une canicule",
        "puissances demandées par les locaux, en moyenne sur une heure : le rendement de la machine, les pertes "
        "de distribution et la relance après un arrêt ne sont pas comptés",
        ("le reste de l'année, la consigne est tenue sur la température ressentie, comme au jour de base"
         if consigne == "ressentie" else
         "le reste de l'année, la consigne est tenue sur l'air, comme le fait un thermostat courant : les pointes "
         "de l'année sont lues ainsi ; consigne = \"ressentie\" donne la lecture haute"),
    ]
    if not climatisation:
        lignes.append("pas de climatisation dans l'étude : aucune puissance de froid")
    else:
        lignes.append("la pointe de froid compte la vapeur d'eau que condense un air soufflé à 13 °C ; c'est la "
                      "puissance que la machine doit fournir, plus haute que le seul froid sensible")
    return lignes


def tableau(puissances: Dict[str, dict], colonnes: Sequence[str], en_tetes: Dict[str, str]) -> List[str]:
    """Les lignes du compte rendu : une ligne par grandeur, une colonne par scénario."""
    def ligne(titre: str, lecture) -> str:
        valeurs = [lecture(puissances.get(c, {})) for c in colonnes]
        return f"{titre:<32}" + "".join(f"{'' if v is None else v:>15}" for v in valeurs)

    def de_pointe(cle: str, champ: str):
        return lambda p: (p.get(cle) or {}).get(champ)

    lignes = ["", "Puissance à installer",
              f"{'':<32}" + "".join(f"{en_tetes[c]:>15}" for c in colonnes),
              ligne("chauffage au jour de base, kW", lambda p: p.get("chauffage_au_jour_de_base_kw")),
              ligne("  soit en W par m²", lambda p: p.get("chauffage_au_jour_de_base_w_m2")),
              ligne("pointe de chauffage, kW", de_pointe("pointe_de_chauffage", "kw")),
              ligne("  le", de_pointe("pointe_de_chauffage", "quand"))]
    if any(p.get("pointe_de_froid") for p in puissances.values()):
        lignes += [ligne("pointe de froid, kW", de_pointe("pointe_de_froid", "kw")),
                   ligne("  le", de_pointe("pointe_de_froid", "quand")),
                   ligne("  dehors, °C", de_pointe("pointe_de_froid", "dehors_c"))]
    return lignes
