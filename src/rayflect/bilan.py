"""Le bilan de chaleur des pièces chauffées, poste par poste et façade par façade : d'où vient la chaleur, où elle part.

Le besoin de chauffage et les heures chaudes disent combien ; ce bilan dit pourquoi. Chaque poste est la chaleur qu'il
apporte aux pièces chauffées, en kWh : positive quand il en apporte, négative quand il en prend. Le chauffage apporte,
le froid prend. Par mois, puis sur l'année.

LES POSTES, et la sortie d'EnergyPlus qui fait chacun [S : EnergyPlus 25.2, Input Output Reference, Surface Outputs
et Zone Outputs ; la même découpe que honeybee_energy.result.loadbalance] :
  - les murs, la toiture, le plancher bas : la chaleur qui traverse la face intérieure de la paroi (Surface Inside
    Face Conduction Heat Transfer Energy). Elle compte aussi ce que la paroi a stocké puis rendu, qui s'annule sur
    l'année ;
  - les baies, soleil : le soleil qui traverse le vitrage (Surface Window Transmitted Solar Radiation Energy) ;
  - les baies, conduction : le reste de ce que la baie apporte ou prend (Surface Window Heat Gain Energy moins Heat
    Loss Energy, moins le soleil transmis) ;
  - les infiltrations, la ventilation et les fenêtres ouvertes : l'air qui entre à la température du dehors (Zone
    Infiltration et Zone Ventilation, Sensible Heat Gain et Loss Energy). La ventilation simple flux et les
    fenêtres ouvertes passent toutes 2 par Zone Ventilation : EnergyPlus ne les sépare pas ;
  - le chauffage et le froid : ce que la machine fournit (Zone Ideal Loads Supply Air Sensible Heating et Cooling
    Energy), celui que compte le besoin de chauffage ;
  - l'air neuf de la double flux : la machine le chauffe ou le rafraîchit avant qu'il entre. C'est l'écart entre ce
    qu'elle fournit et ce que la pièce reçoit (Zone Ideal Loads Zone Sensible Heating et Cooling Energy) : le
    chauffage de l'air neuf, compté dans le chauffage, est rendu ici en perte ;
  - les apports intérieurs : la chaleur sensible des occupants, de l'éclairage et des appareils. Rayflect les pose
    en un seul apport par m², celui de l'usage (rayflect.hypotheses) ;
  - les locaux non chauffés et le mur Trombe : la chaleur qui passe par les parois qui les touchent ;
  - les parois intérieures et mitoyennes : ce que les cloisons, planchers entre pièces et murs mitoyens stockent et
    rendent, et ce qui passe d'une pièce chauffée à l'autre. Sur le bâtiment entier, presque rien.

LE BILAN SE REFERME : la somme des postes vaut l'air qui s'échauffe ou se refroidit, presque rien sur un mois.
L'écart qui reste est rendu (`ecart_kwh`) : un écart fort dirait qu'un échange n'est pas compté.

Seules les pièces chauffées comptent : c'est leur chauffage que le bilan explique. Une pièce non chauffée, la lame
d'air d'un mur Trombe, n'entrent que par ce qu'elles échangent avec elles.
"""

from __future__ import annotations

import sqlite3
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from rayflect.variantes import SECTEURS

EN_KWH = {"J": 1 / 3.6e6, "KWH": 1.0, "GJ": 1e9 / 3.6e6}

# Les sorties lues, toutes par mois.
CONDUCTION = "Surface Inside Face Conduction Heat Transfer Energy"
BAIE_GAIN = "Surface Window Heat Gain Energy"
BAIE_PERTE = "Surface Window Heat Loss Energy"
BAIE_SOLEIL = "Surface Window Transmitted Solar Radiation Energy"
INFILTRATION = ("Zone Infiltration Sensible Heat Gain Energy", "Zone Infiltration Sensible Heat Loss Energy")
VENTILATION = ("Zone Ventilation Sensible Heat Gain Energy", "Zone Ventilation Sensible Heat Loss Energy")
OCCUPANTS = "Zone People Sensible Heating Energy"
ECLAIRAGE = "Zone Lights Total Heating Energy"
APPAREILS = ("Zone Electric Equipment Total Heating Energy", "Zone Gas Equipment Total Heating Energy",
             "Zone Other Equipment Total Heating Energy")
CHAUFFAGE_FOURNI = "Zone Ideal Loads Supply Air Sensible Heating Energy"
CHAUFFAGE_RECU = "Zone Ideal Loads Zone Sensible Heating Energy"
FROID_FOURNI = "Zone Ideal Loads Supply Air Sensible Cooling Energy"
FROID_RECU = "Zone Ideal Loads Zone Sensible Cooling Energy"

SORTIES = (CONDUCTION, BAIE_GAIN, BAIE_PERTE, BAIE_SOLEIL) + INFILTRATION + VENTILATION + (OCCUPANTS, ECLAIRAGE) \
    + APPAREILS + (CHAUFFAGE_FOURNI, CHAUFFAGE_RECU, FROID_FOURNI, FROID_RECU)

# Les postes, dans l'ordre du compte rendu. Ceux d'une façade portent son côté.
MURS = "murs"
BAIES_SOLEIL = "baies, soleil"
BAIES_CONDUCTION = "baies, conduction"
TOITURE = "toiture"
PLANCHER_BAS = "plancher bas"
NON_CHAUFFES = "locaux non chauffés"
TROMBE = "mur Trombe"
INFILTRATIONS = "infiltrations"
VENTILATION_ET_FENETRES = "ventilation et fenêtres ouvertes"
DOUBLE_FLUX = "air neuf de la double flux"
APPORTS = "apports intérieurs"
INTERIEUR = "parois intérieures et mitoyennes"
CHAUFFAGE = "chauffage"
FROID = "froid"
POSTES = (MURS, BAIES_SOLEIL, BAIES_CONDUCTION, TOITURE, PLANCHER_BAS, NON_CHAUFFES, TROMBE, INFILTRATIONS,
          VENTILATION_ET_FENETRES, DOUBLE_FLUX, APPORTS, INTERIEUR, CHAUFFAGE, FROID)
PAR_FACADE = (MURS, BAIES_SOLEIL, BAIES_CONDUCTION)

HIVER = (11, 12, 1, 2, 3)       # [H] la saison de chauffe en France, de novembre à mars
ETE = (6, 7, 8)                 # [H] l'été, de juin à août
ECART_SUPPORTE = 0.03           # [H] au-delà de 3 % des échanges, le bilan ne se referme pas : un échange manque


MOIS = ("JANUARY", "FEBRUARY", "MARCH", "APRIL", "MAY", "JUNE", "JULY", "AUGUST", "SEPTEMBER", "OCTOBER",
        "NOVEMBER", "DECEMBER")
TABLEAU = "RAYFLECT_BILAN_"


def texte_des_sorties() -> str:
    """Les sorties à demander à EnergyPlus, sommées par mois : à ajouter au fichier du calcul.

    PAR SES TABLEAUX MENSUELS (Output:Table:Monthly), PAS PAR Output:Variable : une sortie par mois écrit ses lignes
    dans la table du temps, au milieu des heures, et la lecture des séries horaires (ladybug) ne s'y retrouve plus.
    Les tableaux ne comptent que l'année sur la météo, pas le jour de base.
    """
    return "".join(f"\nOutput:Table:Monthly,\n  {TABLEAU}{k},\n  2,\n  {nom},\n  SumOrAverage;\n"
                   for k, nom in enumerate(SORTIES))


def secteur(azimut: float) -> str:
    """Le côté d'une façade, en 8 secteurs, depuis son azimut (0 au nord, 90 à l'est)."""
    return SECTEURS[int(((azimut % 360.0) + 22.5) // 45.0) % 8]


def _par_mois(connexion, noms: Sequence[str]) -> Dict[Tuple[str, str], List[float]]:
    """(clé, sortie) : les 12 mois de l'année, en kWh, lus dans les tableaux mensuels du calcul."""
    lignes = connexion.execute(
        "SELECT ReportName, ReportForString, RowName, Value, Units FROM TabularDataWithStrings "
        "WHERE ReportName LIKE ?", (TABLEAU + "%",)).fetchall()
    rendu: Dict[Tuple[str, str], List[float]] = {}
    for rapport, cle, mois, valeur, unite in lignes:
        mois = str(mois).strip().upper()
        if mois not in MOIS:
            continue                        # la somme de l'année, le mois le plus bas, le plus haut
        nom = noms[int(str(rapport)[len(TABLEAU):])]
        facteur = EN_KWH.get(str(unite).strip().upper())
        if facteur is None:
            raise ValueError(f"tableau du bilan en « {unite} », une unité inattendue")
        rendu.setdefault((str(cle).strip().upper(), nom), [0.0] * 12)[MOIS.index(mois)] += float(valeur) * facteur
    return rendu


def _ajouter(postes: Dict[Tuple[str, Optional[str]], List[float]], poste: str, cote: Optional[str],
             mois: Iterable[float], signe: float = 1.0) -> None:
    cumul = postes.setdefault((poste, cote), [0.0] * 12)
    for k, valeur in enumerate(mois):
        cumul[k] += signe * valeur


def lire(sql, pieces_chauffees: Iterable[str], prefixe_trombe: str = "TROMBE") -> dict:
    """Le bilan d'un calcul, depuis son fichier de résultats SQL. `pieces_chauffees` : les noms des zones à compter.

    Lève `ValueError` si le calcul n'a pas rendu les sorties du bilan (voir `texte_des_sorties`).
    """
    chauffees = {nom.upper() for nom in pieces_chauffees}
    connexion = sqlite3.connect(f"file:{sql}?mode=ro", uri=True)
    try:
        zones = {index: str(nom).upper() for index, nom in connexion.execute("SELECT ZoneIndex, ZoneName FROM Zones")}
        parois = connexion.execute(
            "SELECT SurfaceIndex, SurfaceName, ClassName, Azimuth, ZoneIndex, ExtBoundCond FROM Surfaces "
            "WHERE HeatTransferSurf = 1").fetchall()
        lu = _par_mois(connexion, SORTIES)
    finally:
        connexion.close()
    if not any(nom == CONDUCTION for _cle, nom in lu):
        raise ValueError("le calcul n'a pas rendu les sorties du bilan de chaleur")

    def serie(cle: str, nom: str) -> List[float]:
        return lu.get((cle.upper(), nom), [0.0] * 12)

    zone_de = {index: zones.get(zone, "") for index, _n, _c, _a, zone, _b in parois}
    postes: Dict[Tuple[str, Optional[str]], List[float]] = {}
    for index, nom, classe, azimut, zone, derriere in parois:
        if zones.get(zone) not in chauffees:
            continue
        classe = str(classe).lower()
        if classe == "window":
            soleil = serie(nom, BAIE_SOLEIL)
            net = [g - p - s for g, p, s in zip(serie(nom, BAIE_GAIN), serie(nom, BAIE_PERTE), soleil)]
            if derriere == 0:
                cote = secteur(azimut)
                _ajouter(postes, BAIES_SOLEIL, cote, soleil)
                _ajouter(postes, BAIES_CONDUCTION, cote, net)
            else:                           # une baie entre 2 pièces
                _ajouter(postes, INTERIEUR, None, [n + s for n, s in zip(net, soleil)])
            continue
        flux = serie(nom, CONDUCTION)
        if derriere <= 0:                   # le dehors (0), le sol (négatif)
            if classe == "wall":
                _ajouter(postes, MURS, secteur(azimut), flux)
            elif classe in ("roof", "ceiling"):
                _ajouter(postes, TOITURE, None, flux)
            else:
                _ajouter(postes, PLANCHER_BAS, None, flux)
        elif derriere == index:             # adiabatique : un mur mitoyen, une masse intérieure
            _ajouter(postes, INTERIEUR, None, flux)
        else:
            autre = zone_de.get(derriere, "")
            if autre in chauffees:
                _ajouter(postes, INTERIEUR, None, flux)
            elif autre.startswith(prefixe_trombe.upper()):
                _ajouter(postes, TROMBE, None, flux)
            else:
                _ajouter(postes, NON_CHAUFFES, None, flux)
    for cle, nom in list(lu):
        if cle not in chauffees:
            continue
        if nom == INFILTRATION[0]:
            _ajouter(postes, INFILTRATIONS, None, serie(cle, nom))
        elif nom == INFILTRATION[1]:
            _ajouter(postes, INFILTRATIONS, None, serie(cle, nom), -1.0)
        elif nom == VENTILATION[0]:
            _ajouter(postes, VENTILATION_ET_FENETRES, None, serie(cle, nom))
        elif nom == VENTILATION[1]:
            _ajouter(postes, VENTILATION_ET_FENETRES, None, serie(cle, nom), -1.0)
        elif nom in (OCCUPANTS, ECLAIRAGE) + APPAREILS:
            _ajouter(postes, APPORTS, None, serie(cle, nom))
    # Le chauffage et le froid : la machine d'une pièce porte son nom de zone dans le sien. Ce qu'elle fournit est le
    # besoin compté ; ce qu'elle fournit de plus que la pièce ne reçoit a servi à l'air neuf de la double flux.
    for cle, nom in list(lu):
        if nom not in (CHAUFFAGE_RECU, FROID_RECU) or not any(cle.startswith(z) for z in chauffees):
            continue
        if nom == CHAUFFAGE_RECU:
            recu, fourni = serie(cle, CHAUFFAGE_RECU), serie(cle, CHAUFFAGE_FOURNI)
            _ajouter(postes, CHAUFFAGE, None, fourni)
            _ajouter(postes, DOUBLE_FLUX, None, [r - f for r, f in zip(recu, fourni)])
        else:
            recu, fourni = serie(cle, FROID_RECU), serie(cle, FROID_FOURNI)
            _ajouter(postes, FROID, None, fourni, -1.0)
            _ajouter(postes, DOUBLE_FLUX, None, [f - r for r, f in zip(recu, fourni)])
    return _rendre(postes)


def _rendre(postes: Dict[Tuple[str, Optional[str]], List[float]]) -> dict:
    """Les postes rangés, arrondis au kWh, et l'écart de fermeture."""
    rang = {p: k for k, p in enumerate(POSTES)}
    lignes = []
    for (poste, cote), mois in sorted(postes.items(),
                                      key=lambda e: (rang[e[0][0]], SECTEURS.index(e[0][1]) if e[0][1] else 0)):
        if all(abs(v) < 0.5 for v in mois):
            continue
        lignes.append({"poste": poste, "cote": cote, "kwh": round(sum(mois)), "par_mois": [round(v) for v in mois]})
    ecart = sum(sum(mois) for mois in postes.values())
    echanges = sum(abs(v) for mois in postes.values() for v in mois) / 2.0
    return {"postes": lignes, "ecart_kwh": round(ecart), "ecart_part": round(abs(ecart) / echanges, 4) if echanges else 0.0}


def _somme(ligne: dict, mois: Sequence[int]) -> int:
    return sum(ligne["par_mois"][m - 1] for m in mois)


def _nom(ligne: dict) -> str:
    return f"{ligne['poste']} {ligne['cote']}" if ligne["cote"] else ligne["poste"]


def tableau(bilan: dict) -> List[str]:
    """Le bilan d'un scénario en tableau : l'année, l'hiver, l'été."""
    lignes = [f"{'poste':<40}{'année':>10}{'hiver':>10}{'été':>10}"]
    for ligne in bilan["postes"]:
        lignes.append(f"{_nom(ligne):<40}{ligne['kwh']:>10}{_somme(ligne, HIVER):>10}{_somme(ligne, ETE):>10}")
    return lignes


def principaux(bilan: dict, mois: Sequence[int], combien: int = 3) -> Tuple[List[dict], List[dict]]:
    """Les postes qui apportent le plus et ceux qui prennent le plus sur ces mois, chauffage et froid exclus."""
    du_batiment = [ligne for ligne in bilan["postes"] if ligne["poste"] not in (CHAUFFAGE, FROID, INTERIEUR)]
    apports = sorted((ligne for ligne in du_batiment if _somme(ligne, mois) > 0), key=lambda e: -_somme(e, mois))
    pertes = sorted((ligne for ligne in du_batiment if _somme(ligne, mois) < 0), key=lambda e: _somme(e, mois))
    return apports[:combien], pertes[:combien]


def ecarts(bilan: dict, reference: dict, combien: int = 3) -> List[Tuple[str, int]]:
    """Les postes qui changent le plus sur l'année d'un scénario à sa référence : (nom, écart en kWh)."""
    def par_nom(b: dict) -> Dict[str, int]:
        return {_nom(ligne): ligne["kwh"] for ligne in b["postes"]}

    un, autre = par_nom(bilan), par_nom(reference)
    changes = [(nom, un.get(nom, 0) - autre.get(nom, 0)) for nom in dict.fromkeys(list(autre) + list(un))]
    changes = [(nom, e) for nom, e in changes if e and nom not in (CHAUFFAGE, FROID)]
    return sorted(changes, key=lambda e: -abs(e[1]))[:combien]


def dire(bilans: Dict[str, dict], ordre: Sequence[str]) -> List[str]:
    """Le compte rendu du bilan : la référence en tableau, puis ce que chaque autre scénario change."""
    if not bilans or ordre[0] not in bilans:
        return []
    reference = bilans[ordre[0]]
    lignes = ["", f"D'où vient la chaleur des pièces chauffées et où elle part, « {ordre[0]} », kWh "
                  f"(positif : apporté, négatif : perdu ; hiver de novembre à mars, été de juin à août)"]
    lignes += tableau(reference)

    def en_clair(liste: List[dict], mois: Sequence[int]) -> str:
        return ", ".join(f"{_nom(e)} ({_somme(e, mois):+d})" for e in liste) or "rien"

    apports, pertes = principaux(reference, HIVER)
    lignes.append(f"  - en hiver, la chaleur part surtout par : {en_clair(pertes, HIVER)}")
    lignes.append(f"  - en hiver, elle vient surtout de : {en_clair(apports, HIVER)}")
    apports, pertes = principaux(reference, ETE)
    lignes.append(f"  - en été, la chaleur vient surtout de : {en_clair(apports, ETE)}")
    lignes.append(f"  - en été, elle part surtout par : {en_clair(pertes, ETE)}")
    for nom in ordre[1:]:
        if nom in bilans:
            changes = ecarts(bilans[nom], reference)
            lignes.append(f"  - « {nom} » change surtout : "
                          + (", ".join(f"{poste} ({e:+d})" for poste, e in changes) or "rien"))
    trop = [nom for nom in ordre if nom in bilans and bilans[nom]["ecart_part"] > ECART_SUPPORTE]
    if trop:
        lignes.append(f"  - À VÉRIFIER : le bilan ne se referme pas à {ECART_SUPPORTE * 100:g} % près pour "
                      + ", ".join(f"« {nom} » ({bilans[nom]['ecart_part'] * 100:.1f} %)" for nom in trop))
    return lignes
