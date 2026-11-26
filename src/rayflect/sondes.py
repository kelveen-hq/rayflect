"""Les sondes géothermiques : ce que le sol rend aux besoins du bâtiment, année après année.

Un champ de sondes verticales est un échangeur avec le sol. On y puise de la chaleur l'hiver, par une pompe à
chaleur ; on peut y rejeter celle du bâtiment l'été, par la même machine ou directement (géocooling). La
question n'est pas « combien de kWh » mais « à quelle température revient l'eau, et où en est-elle au bout de
10 ans » : un champ trop court gèle, un champ déséquilibré dérive d'année en année.

CE QUE FAIT CE MODULE. Un scénario porte un élément `sondes`. Une fois le bâtiment calculé, ses besoins de
chauffage et de froid, heure par heure, deviennent une charge sur une boucle d'eau, et EnergyPlus est relancé
sur cette boucle seule : une pompe, le champ de sondes (`GroundHeatExchanger:System`), et la charge
(`LoadProfile:Plant`), sur plusieurs années de suite. Le bilan rend, pour la première et la dernière année, les
températures extrêmes de l'eau qui revient du sol, la dérive, et la part du froid qu'un géocooling pourrait
servir.

    ce que la pompe à chaleur prend au sol     = besoin de chauffage x (1 - 1 / COP)
    ce que le froid lui rend, par une machine  = besoin de froid x (1 + 1 / EER)
    ce que le froid lui rend, en géocooling    = besoin de froid

CE QUI N'EST PAS MODÉLISÉ. Le bâtiment ne sent pas la boucle : ses besoins sont ceux du calcul idéal, que le
sol suive ou non. Le COP et l'EER sont constants [H], alors qu'ils varient avec la température de l'eau. La
pompe de circulation tourne en continu et sa consommation n'est pas comptée. Le sol est homogène, sans nappe
en mouvement. L'eau chaude sanitaire n'est pas dans les besoins.

PREUVE. `verification/reponse_thermique.py` joue un essai de réponse thermique sur une sonde seule, par ce même montage,
et retrouve la conductivité du sol qu'on lui a donnée. Aucune mesure réelle n'est rejouée : l'essai en bac à
sable de Beier et al. (2011), repris par d'autres outils, reste à faire.

Chaque valeur porte son origine : [S] lue dans une source, [C] citée sans relecture, [D] déduite, [H] hypothèse.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

from rayflect import extensions, moteur
from rayflect.aeration import combien

NOM = "sondes"
HEURES = 8760
FROIDS = ("geocooling", "machine", "aucun")
CHAUFFAGE = "Zone Ideal Loads Supply Air Total Heating Energy"
FROID = "Zone Ideal Loads Supply Air Total Cooling Energy"
SORTIE_DU_SOL = "Ground Heat Exchanger Outlet Temperature"
ENTREE_DU_SOL = "Ground Heat Exchanger Inlet Temperature"
EAU_MOYENNE = "Ground Heat Exchanger Average Fluid Temperature"
PUISSANCE_DU_SOL = "Ground Heat Exchanger Heat Transfer Rate"
PAS_PAR_HEURE = 4

# Le forage et son tube en U. [H] : un forage courant, tube en polyéthylène de 32 mm ; à remplacer par ceux du
# foreur. [C] conductivité du polyéthylène 0,4 W/m.K ; coulis à la bentonite 0,8, coulis amélioré 2,0.
DIAMETRE_DU_FORAGE_M = 0.15
CONDUCTIVITE_DU_COULIS_W_M_K = 1.5
CAPACITE_DU_COULIS_J_M3_K = 3.9e6
CONDUCTIVITE_DU_TUBE_W_M_K = 0.4
CAPACITE_DU_TUBE_J_M3_K = 1.77e6
DIAMETRE_DU_TUBE_M = 0.032
EPAISSEUR_DU_TUBE_M = 0.0029
ECART_DES_TUBES_M = 0.07
TETE_DE_SONDE_M = 1.0                       # [H] profondeur du haut de la sonde
MASSE_VOLUMIQUE_DU_SOL_KG_M3 = 2000.0       # [H] ne sert qu'au profil de température près de la surface
SOL_PLUS_CHAUD_QUE_L_AIR_K = 1.0            # [H] le sol profond est un peu plus chaud que l'air moyen de l'année
JOUR_LE_PLUS_FROID_DU_SOL = 30              # [H] fin janvier, en surface


@dataclass(frozen=True)
class Sondes:
    """Un champ de sondes verticales, en grille, et la façon dont le bâtiment s'en sert."""
    rangees: Tuple[int, int] = (2, 2)                   # le nombre de sondes dans chaque sens de la grille
    profondeur_m: float = 100.0
    entraxe_m: float = 6.0                              # [H] entre 2 sondes voisines
    conductivite_du_sol_w_m_k: float = 2.0              # [H] à tirer d'un essai de réponse thermique sur place
    capacite_du_sol_mj_m3_k: float = 2.2                # [H]
    temperature_du_sol_c: Optional[float] = None        # None : l'air moyen de l'année, plus 1 K [H]
    cop_chauffage: float = 4.0                          # [H] constant sur l'année
    froid: str = "geocooling"                           # geocooling, machine ou aucun
    eer_froid: float = 4.0                              # [H] pour froid = "machine"
    geocooling_au_plus_c: float = 16.0                  # [H] l'eau qui revient du sol doit être plus froide
    debit_l_s_par_sonde: float = 0.3                    # [H]
    antigel: float = 0.25                               # [H] part de propylène glycol dans l'eau ; 0 : eau pure
    annees: int = 10

    def __post_init__(self) -> None:
        rangees = tuple(self.rangees)
        if len(rangees) != 2 or any(isinstance(n, bool) or not isinstance(n, int) or not 1 <= n <= 30 for n in rangees):
            raise ValueError("rangees : 2 nombres entiers de sondes, de 1 à 30, par exemple [2, 3]")
        if self.froid not in FROIDS:
            raise ValueError(f"froid : « {self.froid} » n'est pas dans {', '.join(FROIDS)}")
        bornes = {"profondeur_m": (20.0, 400.0), "entraxe_m": (2.0, 50.0), "conductivite_du_sol_w_m_k": (0.3, 6.0),
                  "capacite_du_sol_mj_m3_k": (0.5, 5.0), "cop_chauffage": (1.5, 10.0), "eer_froid": (1.5, 15.0),
                  "debit_l_s_par_sonde": (0.05, 2.0), "antigel": (0.0, 0.6), "geocooling_au_plus_c": (5.0, 25.0)}
        for cle, (mini, maxi) in bornes.items():
            valeur = getattr(self, cle)
            if isinstance(valeur, bool) or not isinstance(valeur, (int, float)) or not mini <= valeur <= maxi:
                raise ValueError(f"{cle} = {valeur} : attendu de {mini:g} à {maxi:g}")
        if isinstance(self.annees, bool) or not isinstance(self.annees, int) or not 1 <= self.annees <= 50:
            raise ValueError("annees : un nombre entier d'années à simuler, de 1 à 50")

    @property
    def nombre(self) -> int:
        return self.rangees[0] * self.rangees[1]

    @property
    def longueur_m(self) -> float:
        return self.nombre * self.profondeur_m


def charge_sur_le_sol(chauffage_w: Sequence[float], froid_w: Sequence[float], sondes: Sondes) -> List[float]:
    """Heure par heure, ce que le bâtiment prend au sol (positif) ou lui rend (négatif), en watts."""
    prise = 1.0 - 1.0 / sondes.cop_chauffage
    rendue = {"geocooling": 1.0, "machine": 1.0 + 1.0 / sondes.eer_froid, "aucun": 0.0}[sondes.froid]
    return [c * prise - f * rendue for c, f in zip(chauffage_w, froid_w)]


def sol_du_lieu(epw) -> Tuple[float, float]:
    """(température moyenne du sol profond, demi-amplitude annuelle en surface), tirées de l'air de la météo [H]."""
    mois = epw.dry_bulb_temperature.average_monthly().values
    return sum(mois) / len(mois) + SOL_PLUS_CHAUD_QUE_L_AIR_K, (max(mois) - min(mois)) / 2.0


def texte(sondes: Sondes, planning: Path, sol_c: float, amplitude_k: float) -> str:
    """Le fichier d'EnergyPlus d'une boucle d'eau seule : la pompe, le champ de sondes, la charge du bâtiment."""
    debit = sondes.nombre * sondes.debit_l_s_par_sonde / 1000.0
    capacite = sondes.capacite_du_sol_mj_m3_k * 1.0e6
    if sondes.antigel > 0:
        fluide = ("UserDefinedFluidType", "eau_glycolee")
        glycol = f"FluidProperties:GlycolConcentration,\n  eau_glycolee, PropyleneGlycol, , {sondes.antigel:g};\n\n"
    else:
        fluide, glycol = ("Water", ""), ""

    def tuyau(nom: str, entree: str, sortie: str) -> str:
        return (f"Branch,\n  {nom}, , Pipe:Adiabatic, tuyau_{nom}, {entree}, {sortie};\n\n"
                f"Pipe:Adiabatic,\n  tuyau_{nom}, {entree}, {sortie};\n\n")

    def cote(nom: str, branches: Sequence[str]) -> str:
        return (f"BranchList,\n  branches_{nom}, {', '.join(branches)};\n\n"
                f"ConnectorList,\n  raccords_{nom}, Connector:Splitter, depart_{nom}, Connector:Mixer, retour_{nom};\n\n"
                f"Connector:Splitter,\n  depart_{nom}, {branches[0]}, {branches[1]};\n\n"
                f"Connector:Mixer,\n  retour_{nom}, {branches[2]}, {branches[1]};\n\n")

    return (
        "Version,\n  25.2;\n\n"
        "Building,\n  boucle_de_sol, 0, Suburbs, 0.04, 0.4, FullExterior, 25, 6;\n\n"
        f"Timestep,\n  {PAS_PAR_HEURE};\n\n"
        "GlobalGeometryRules,\n  UpperLeftCorner, CounterClockWise, Relative;\n\n"
        "SimulationControl,\n  No, No, No, No, Yes;\n\n"
        f"RunPeriod,\n  annees, 1, 1, 2001, 12, 31, {2000 + sondes.annees}, , No, No, No, No, No;\n\n"
        "Site:GroundTemperature:Undisturbed:KusudaAchenbach,\n"
        f"  sol, {sondes.conductivite_du_sol_w_m_k:g}, {MASSE_VOLUMIQUE_DU_SOL_KG_M3:g}, "
        f"{capacite / MASSE_VOLUMIQUE_DU_SOL_KG_M3:g}, {sol_c:.3f}, {amplitude_k:.3f}, {JOUR_LE_PLUS_FROID_DU_SOL};\n\n"
        "GroundHeatExchanger:System,\n"
        f"  champ, sondes_entree, sondes_sortie, {debit:.6f}, Site:GroundTemperature:Undisturbed:KusudaAchenbach, sol, "
        f"{sondes.conductivite_du_sol_w_m_k:g}, {capacite:g}, , UHFcalc, , , grille;\n\n"
        "GroundHeatExchanger:Vertical:Properties,\n"
        f"  sonde, {TETE_DE_SONDE_M:g}, {sondes.profondeur_m:g}, {DIAMETRE_DU_FORAGE_M:g}, "
        f"{CONDUCTIVITE_DU_COULIS_W_M_K:g}, {CAPACITE_DU_COULIS_J_M3_K:g}, {CONDUCTIVITE_DU_TUBE_W_M_K:g}, "
        f"{CAPACITE_DU_TUBE_J_M3_K:g}, {DIAMETRE_DU_TUBE_M:g}, {EPAISSEUR_DU_TUBE_M:g}, {ECART_DES_TUBES_M:g};\n\n"
        "GroundHeatExchanger:Vertical:Array,\n"
        f"  grille, sonde, {sondes.rangees[0]}, {sondes.rangees[1]}, {sondes.entraxe_m:g};\n\n"
        + glycol +
        "PlantLoop,\n"
        f"  boucle, {fluide[0]}, {fluide[1] if sondes.antigel > 0 else ''}, commande, sol_fin, 80, -15, {debit:.6f}, 0, "
        "autocalculate, sol_debut, sol_fin, branches_sol, raccords_sol, usage_debut, usage_fin, branches_usage, "
        "raccords_usage, Optimal;\n\n"
        "PlantEquipmentOperationSchemes,\n  commande, PlantEquipmentOperation:Uncontrolled, sans_commande, toujours;\n\n"
        "PlantEquipmentOperation:Uncontrolled,\n  sans_commande, equipements;\n\n"
        "PlantEquipmentList,\n  equipements, GroundHeatExchanger:System, champ;\n\n"
        # EnergyPlus exige une consigne sur la boucle ; sans commande, elle ne sert à rien.
        "SetpointManager:Scheduled,\n  consigne_de_boucle, Temperature, consigne_sans_effet, sol_fin;\n\n"
        "Schedule:Constant,\n  consigne_sans_effet, sans_limite, 10;\n\n"
        + cote("sol", ("sol_pompe", "sol_sondes", "sol_retour"))
        + "Branch,\n  sol_pompe, , Pump:ConstantSpeed, pompe, sol_debut, pompe_sortie;\n\n"
        # Une pompe qui ne chauffe pas l'eau : sa hauteur et sa puissance sont mises à presque rien.
        f"Pump:ConstantSpeed,\n  pompe, sol_debut, pompe_sortie, {debit:.6f}, 1, {debit / 0.7:.6f}, 0.9, 0, "
        "Continuous;\n\n"
        "Branch,\n  sol_sondes, , GroundHeatExchanger:System, champ, sondes_entree, sondes_sortie;\n\n"
        + tuyau("sol_retour", "sol_retour_entree", "sol_fin")
        + cote("usage", ("usage_aller", "usage_charge", "usage_retour"))
        + tuyau("usage_aller", "usage_debut", "usage_aller_sortie")
        + "Branch,\n  usage_charge, , LoadProfile:Plant, charge, charge_entree, charge_sortie;\n\n"
        f"LoadProfile:Plant,\n  charge, charge_entree, charge_sortie, charge_w, {debit:.6f}, toujours, Water;\n\n"
        + tuyau("usage_retour", "usage_retour_entree", "usage_fin")
        + "ScheduleTypeLimits,\n  sans_limite;\n\n"
        "Schedule:Constant,\n  toujours, sans_limite, 1;\n\n"
        f"Schedule:File,\n  charge_w, sans_limite, {Path(planning).resolve()}, 1, 1, {HEURES}, Comma, No, 60, No;\n\n"
        + "".join(f"Output:Variable,\n  *, {nom}, Hourly;\n\n"
                  for nom in (SORTIE_DU_SOL, ENTREE_DU_SOL, EAU_MOYENNE, PUISSANCE_DU_SOL))
        + "Output:SQLite,\n  Simple;\n")


def lire_une_sortie(sql, nom: str) -> List[float]:
    """Les valeurs horaires d'une sortie, sur toutes les années du calcul, dans l'ordre."""
    with sqlite3.connect(str(sql)) as base:
        return [v for (v,) in base.execute(
            "SELECT d.Value FROM ReportData d JOIN ReportDataDictionary n USING (ReportDataDictionaryIndex) "
            "WHERE n.Name = ? ORDER BY d.TimeIndex", (nom,))]


def simuler(sondes: Sondes, charge_w: Sequence[float], epw, dossier, sol: Optional[Tuple[float, float]] = None):
    """Lance la boucle seule sur `sondes.annees` années. Rend (retours du sol heure par heure en °C, sol en °C).

    `charge_w` : les 8 760 heures de `charge_sur_le_sol`. `epw` : le chemin de la météo, qui ne sert ici qu'au
    calendrier. `sol` : (température, demi-amplitude), sinon tirées de la météo.
    Lève `moteur.CalculFautif` si EnergyPlus refuse la boucle.
    """
    if len(charge_w) != HEURES:
        raise ValueError(f"la charge sur le sol a {len(charge_w)} heures, {HEURES} attendues")
    dossier = Path(dossier)
    dossier.mkdir(parents=True, exist_ok=True)
    planning = dossier / "charge_sur_le_sol.csv"
    planning.write_text("prise_au_sol_w\n" + "\n".join(f"{v:.2f}" for v in charge_w) + "\n", encoding="utf-8")
    if sol is None:
        from ladybug.epw import EPW

        sol = sol_du_lieu(EPW(str(epw)))
        if sondes.temperature_du_sol_c is not None:
            sol = (sondes.temperature_du_sol_c, sol[1])
    idf = dossier / "in.idf"
    idf.write_text(texte(sondes, planning, *sol), encoding="utf-8")
    sql, _journal = moteur.lancer(idf, epw)
    retours = lire_une_sortie(sql, SORTIE_DU_SOL)
    if len(retours) != HEURES * sondes.annees:
        raise moteur.CalculFautif(f"la boucle de sol a rendu {len(retours)} heures, {HEURES * sondes.annees} attendues")
    return retours, sol[0]


def bilan(sondes: Sondes, retours_c: Sequence[float], chauffage_w: Sequence[float], froid_w: Sequence[float],
          sol_c: float) -> Dict[str, object]:
    """Ce qu'on retient de la boucle : les extrêmes de la première et de la dernière année, et ce qu'ils disent."""
    charge = charge_sur_le_sol(chauffage_w, froid_w, sondes)
    annees = [retours_c[k * HEURES:(k + 1) * HEURES] for k in range(sondes.annees)]

    def extremes(annee) -> Dict[str, float]:
        return {"retour_du_sol_min_c": round(min(annee), 2), "retour_du_sol_max_c": round(max(annee), 2),
                "retour_du_sol_moyen_c": round(sum(annee) / len(annee), 2)}

    premiere, derniere = extremes(annees[0]), extremes(annees[-1])
    pris = sum(v for v in charge if v > 0) / 1000.0
    rendu = -sum(v for v in charge if v < 0) / 1000.0
    rendu_bilan: Dict[str, object] = {
        "sondes": sondes.nombre, "longueur_m": sondes.longueur_m, "sol_c": round(sol_c, 2), "annees": sondes.annees,
        "pris_au_sol_kwh_an": round(pris), "rendu_au_sol_kwh_an": round(rendu),
        "pointe_prise_w_m": round(max(max(charge), 0.0) / sondes.longueur_m, 1),
        "pointe_rendue_w_m": round(max(-min(charge), 0.0) / sondes.longueur_m, 1) + 0.0,       # jamais « -0 »
        "premiere_annee": premiere, "derniere_annee": derniere,
        "derive_du_retour_moyen_k": round(derniere["retour_du_sol_moyen_c"] - premiere["retour_du_sol_moyen_c"], 2),
    }
    a_dire = []
    gel = 0.0 if sondes.antigel == 0 else None
    if gel is not None and derniere["retour_du_sol_min_c"] <= gel + 1.0:
        a_dire.append(f"l'eau revient du sol à {derniere['retour_du_sol_min_c']:g} °C au plus froid : sans antigel, "
                      f"le champ est trop court")
    elif derniere["retour_du_sol_min_c"] < 0.0:
        a_dire.append(f"l'eau revient du sol à {derniere['retour_du_sol_min_c']:g} °C au plus froid : le terrain gèle "
                      f"autour des sondes, le champ est court")
    if sondes.froid == "geocooling":
        besoin = sum(froid_w)
        servi = sum(f for f, t in zip(froid_w, annees[-1]) if f > 0 and t <= sondes.geocooling_au_plus_c)
        rendu_bilan["geocooling_part_du_froid_servie"] = round(servi / besoin, 3) if besoin > 0 else None
        if besoin > 0 and servi < 0.9 * besoin:
            a_dire.append(f"géocooling : la dernière année, l'eau revient à {sondes.geocooling_au_plus_c:g} °C ou "
                          f"moins pendant {100 * servi / besoin:.0f} % du froid demandé seulement")
    if abs(rendu_bilan["derive_du_retour_moyen_k"]) >= 2.0:
        sens = "se refroidit" if rendu_bilan["derive_du_retour_moyen_k"] < 0 else "s'échauffe"
        a_dire.append(f"le sol {sens} de {abs(rendu_bilan['derive_du_retour_moyen_k']):g} K en {sondes.annees} ans : "
                      f"ce qu'on lui prend et ce qu'on lui rend ne s'équilibrent pas")
    rendu_bilan["a_savoir"] = a_dire
    return rendu_bilan


def dire(champ: Dict[str, object]) -> List[str]:
    """Le bilan d'un champ de sondes, en lignes pour le compte rendu."""
    premiere, derniere = champ["premiere_annee"], champ["derniere_annee"]
    lignes = [
        f"{combien(champ['sondes'], 'sonde', 'sondes')}, {champ['longueur_m']:g} m en tout, dans un sol à {champ['sol_c']:g} °C",
        f"pris au sol {champ['pris_au_sol_kwh_an']} kWh par an (pointe {champ['pointe_prise_w_m']:g} W par mètre), "
        f"rendu {champ['rendu_au_sol_kwh_an']} kWh par an (pointe {champ['pointe_rendue_w_m']:g} W par mètre)",
        f"eau qui revient du sol, année 1 : de {premiere['retour_du_sol_min_c']:g} à "
        f"{premiere['retour_du_sol_max_c']:g} °C ; année {champ['annees']} : de {derniere['retour_du_sol_min_c']:g} à "
        f"{derniere['retour_du_sol_max_c']:g} °C ; dérive de la moyenne : {champ['derive_du_retour_moyen_k']:+g} K",
    ]
    part = champ.get("geocooling_part_du_froid_servie")
    if part is not None:
        lignes.append(f"géocooling : {100 * part:.0f} % du froid demandé tombe quand l'eau revient assez froide")
    lignes += [f"À SAVOIR : {ligne}" for ligne in champ["a_savoir"]]
    lignes.append("besoins du bâtiment inchangés par la boucle ; COP constant [H] ; pompe de circulation non comptée")
    return lignes


def _poser(modele, sondes: Sondes, contexte: dict) -> None:
    contexte.setdefault("a_dire", []).append(
        f"sondes géothermiques : {combien(sondes.nombre, 'sonde', 'sondes')} de {sondes.profondeur_m:g} m "
        f"({sondes.longueur_m:g} m en tout), "
        f"entraxe {sondes.entraxe_m:g} m, sol à {sondes.conductivite_du_sol_w_m_k:g} W/m.K [H] ; pompe à chaleur de "
        f"COP {sondes.cop_chauffage:g} [H], froid : {sondes.froid} ; le bâtiment lui-même n'est pas changé")
    return None


def _lire(annee, sondes: Sondes, contexte: dict) -> Dict[str, object]:
    def du_batiment(nom: str) -> List[float]:
        series = annee.data_collections_by_output_name(nom)
        if not series:
            return [0.0] * HEURES
        if any(len(s.values) != HEURES for s in series):
            raise ValueError(f"les sondes se calculent sur une année de {HEURES} heures ; la météo de l'étude en "
                             f"compte {len(series[0].values)} (année bissextile ?)")
        return [1000.0 * sum(valeurs) for valeurs in zip(*(s.values for s in series))]     # kWh par h -> W

    chauffage, froid = du_batiment(CHAUFFAGE), du_batiment(FROID)
    dossier = Path(contexte["dossier"]) / "sondes"
    contexte.get("dire", lambda _texte: None)(
        f"sondes de « {contexte.get('scenario', '?')} » : la boucle de sol se calcule sur {sondes.annees} ans")
    try:
        retours, sol_c = simuler(sondes, charge_sur_le_sol(chauffage, froid, sondes), contexte["chemin_epw"], dossier)
    except moteur.CalculFautif as erreur:
        raise ValueError(f"la boucle de sol n'a pas pu être calculée : {erreur}") from erreur
    return bilan(sondes, retours, chauffage, froid, sol_c)


def declarer() -> None:
    extensions.enregistrer(NOM, Sondes, _poser, lire=_lire)


declarer()
