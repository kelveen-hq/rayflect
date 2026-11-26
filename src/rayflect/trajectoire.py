"""La trajectoire d'une plantation dans le temps : sa taille, l'ombre qu'elle fait mois par mois, ce qu'elle change.

Une plantation se joue à plusieurs âges (`annees = [1, 5, 15, 30]` dans le scénario, rayflect.etude) : un calcul par âge,
la plante figée à cet âge. La trajectoire les remet bout à bout, du plus jeune au plus vieux :
  - la taille de chaque plante : hauteur et couronne d'un arbre, hauteur couverte d'une grimpante (rayflect.vegetation) ;
  - L'OMBRE VÉGÉTALE MOIS PAR MOIS : la part du soleil des baies que la plantation arrête, face au bâtiment tel qu'il
    est (la référence de l'étude). Elle se lit dans le bilan de chaleur (le poste « baies, soleil », toutes façades),
    sans calcul de plus. Un arbre caduc ombre en juillet et laisse passer en janvier : c'est l'ombre dynamique, qui suit
    les feuilles et la pousse ;
  - ce qu'elle change : degrés-heures et heures au-dessus de 26 °C de la pièce la plus chaude, chauffage, lumière du
    jour de la pièce la moins éclairée.
Une 2e plantation de la même essence, à la courbe de pousse lente (« tilleul_lent »), donne l'autre bord : les 2
trajectoires encadrent ce qu'on peut attendre.
"""

from __future__ import annotations

from typing import Dict, List, Optional, Sequence

JANVIER, JUILLET = 0, 6


def _soleil_des_baies(chaleur: dict) -> List[float]:
    mois = [0.0] * 12
    for ligne in chaleur.get("postes", []):
        if ligne["poste"] == "baies, soleil":
            for k, v in enumerate(ligne["par_mois"]):
                mois[k] += v
    return mois


def ombre_par_mois(chaleur: dict, chaleur_de_reference: dict) -> List[Optional[float]]:
    """La part du soleil des baies arrêtée, mois par mois, de 0 à 1 ; None quand la référence n'en reçoit pas."""
    avec, sans = _soleil_des_baies(chaleur), _soleil_des_baies(chaleur_de_reference)
    return [round(1.0 - a / s, 3) if s > 0 else None for a, s in zip(avec, sans)]


def plantes(elements: Sequence) -> List[dict]:
    """La taille de chaque plante du scénario, à son âge."""
    from rayflect import vegetation

    rendu = []
    for e in elements:
        if isinstance(e, vegetation.Arbre):
            rendu.append({"type": "arbre", "essence": e.essence, "hauteur_m": e.hauteur_m, "couronne_m": e.diametre_m})
        elif isinstance(e, vegetation.Grimpante):
            rendu.append({"type": "grimpante", "essence": e.feuillage.nom, "hauteur_m": e.hauteur_couverte_m,
                          "couronne_m": None})
    return rendu


def _pire(par_piece: dict, nom: str, lire, plus_haut: bool = True) -> Optional[float]:
    valeurs = [lire(v[nom]) for v in (par_piece or {}).values() if v.get(nom) is not None]
    valeurs = [v for v in valeurs if v is not None]
    return (max(valeurs) if plus_haut else min(valeurs)) if valeurs else None


def assembler(scenarios: Sequence, bilan: dict) -> Dict[str, List[dict]]:
    """Par plantation jouée à plusieurs âges : ses points, du plus jeune au plus vieux. Vide sans plantation par âge."""
    reference = next((s.nom for s in scenarios if s.est_la_reference), None)
    chaleur = bilan.get("bilan_de_chaleur") or {}
    confort = (bilan.get("confort_d_ete") or {}).get("pieces") or {}
    rendu: Dict[str, List[dict]] = {}
    for s in scenarios:
        if getattr(s, "famille", None) is None:
            continue
        rendu.setdefault(s.famille, []).append({
            "age_ans": s.age, "scenario": s.nom, "plantes": plantes(s.elements),
            "ombre_par_mois": ombre_par_mois(chaleur.get(s.nom, {}), chaleur.get(reference, {})) if reference else [None] * 12,
            "dh": _pire(confort, s.nom, lambda v: v["dh"]),
            "heures_au_dessus_de_26": _pire(bilan.get("heures_au_dessus_de_26") or {}, s.nom, lambda v: v),
            "chauffage_kwh": bilan["chauffage_kwh"].get(s.nom),
            "autonomie_300_lux": _pire(bilan.get("autonomie_300_lux") or {}, s.nom, lambda v: v, plus_haut=False),
        })
    for points in rendu.values():
        points.sort(key=lambda p: p["age_ans"])
    return rendu


def _part(v: Optional[float]) -> str:
    return "" if v is None else f"{v * 100:.0f} %"


def dire(trajectoires: Dict[str, List[dict]], reference: Optional[dict] = None) -> List[str]:
    """Le compte rendu : chaque plantation, âge par âge, et la référence pour comparer."""
    if not trajectoires:
        return []
    lignes = []
    for famille, points in trajectoires.items():
        lignes += ["", f"La plantation « {famille} » dans le temps (ombre : la part du soleil des baies qu'elle arrête)",
                   f"{'âge':>6}{'hauteur':>10}{'couronne':>10}{'ombre janv.':>13}{'ombre juil.':>13}{'DH':>8}"
                   f"{'>26 °C':>9}{'chauffage':>11}{'lumière':>9}"]
        if reference:
            lignes.append(f"{'sans':>6}{'':>10}{'':>10}{'':>13}{'':>13}{_n(reference.get('dh')):>8}"
                          f"{_n(reference.get('heures_au_dessus_de_26')):>9}{_n(reference.get('chauffage_kwh')):>11}"
                          f"{_part(reference.get('autonomie_300_lux')):>9}")
        for p in points:
            arbre = p["plantes"][0] if p["plantes"] else {}
            lignes.append(f"{p['age_ans']:>5g} {_m(arbre.get('hauteur_m')):>10}{_m(arbre.get('couronne_m')):>10}"
                          f"{_part(p['ombre_par_mois'][JANVIER]):>13}{_part(p['ombre_par_mois'][JUILLET]):>13}"
                          f"{_n(p['dh']):>8}{_n(p['heures_au_dessus_de_26']):>9}{_n(p['chauffage_kwh']):>11}"
                          f"{_part(p['autonomie_300_lux']):>9}")
    lignes.append("  - DH et heures chaudes : la pièce la plus chaude ; lumière : la moins éclairée ; hauteur et couronne : "
                  "la 1re plante de la plantation, en mètres")
    return lignes


def _n(v) -> str:
    return "" if v is None else f"{v:.0f}"


def _m(v) -> str:
    return "" if v is None else f"{v:g} m"
