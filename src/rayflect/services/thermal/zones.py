"""Les zones thermiques d'un bâtiment : la structure interne du calcul multizone.

Un modèle 5R1C monozone n'a qu'un nœud d'air pour tout le bâtiment : un usage, un système, une consigne. Quand
des locaux très différents cohabitent (bureaux chauffés et climatisés, atelier non chauffé), la zone unique les
moyenne. Ce module décrit le bâtiment zone par zone.

`ZonesConfig` porte, pour chaque zone, ses valeurs RETENUES (celles de la zone, ou héritées du bâtiment, avec
leur origine), ses parois calculées (murs extérieurs par orientation, toiture, plancher bas, volume) et les
façades équipées qui la servent ; les adjacences entre zones, déclarées ou implicites, avec leur U et sa source.

Aucune dépendance à une API ni à pydantic. Les entrées sont des dictionnaires simples (le `model_dump` du schéma
de requête).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple

ORIENTATIONS: Tuple[str, ...] = ("south", "north", "east", "west")

# LES U PAR DÉFAUT DES PAROIS ENTRE ZONES (NF EN ISO 6946:2017, résistances superficielles du tableau 7 :
# 0,13 m²K/W en flux horizontal, 0,10 ascendant, 0,17 descendant). Parois NON isolées, le cas courant d'une
# cloison entre bureaux et atelier ; défauts à remplacer par la paroi réelle.
U_ADJACENCE_DEFAUT_W_M2K: Dict[str, Tuple[float, str]] = {
    "mur": (2.0, "bloc creux de béton 20 cm, R 0,23 m²K/W (règles Th-U, Matériaux), Rsi 0,13 + 0,13 "
                 "(NF EN ISO 6946:2017 tableau 7) : U = 1 / 0,49 = 2,0 W/(m²·K)"),
    "plancher": (2.8, "dalle de béton armé 20 cm, λ 2,3 W/(m·K) (NF EN ISO 10456 tableau 3), R 0,087, Rsi "
                      "0,10 + 0,17 (NF EN ISO 6946:2017 tableau 7) : U = 1 / 0,357 = 2,8 W/(m²·K)"),
}
TYPES_ADJACENCE: Tuple[str, ...] = tuple(U_ADJACENCE_DEFAUT_W_M2K)

# LA RÉSISTANCE DE LA PAROI SEULE (sans ses résistances superficielles), celle des défauts ci-dessus : le U d'une
# paroi entre zones se compose au pas de temps, U = 1 / (Rsi face 1 + R + Rsi face 2), les 2 faces étant
# intérieures (NF EN ISO 6946:2017 : Rsi des 2 côtés d'une paroi intérieure ; tableau 7 : ascendant 0,10,
# horizontal 0,13, descendant 0,17 m²K/W). Un U SAISI (`u_w_m2k` de la requête) ne dit pas son R : il est gardé
# tel quel, sans dépendance au sens du flux (r_paroi None).
R_PAROI_DEFAUT_M2KW: Dict[str, float] = {"mur": 0.23, "plancher": 0.087}

# LES APPORTS INTERNES PAR PIÈCE, valeurs normatives de base : W/m² de plancher pendant l'occupation de l'usage
# de la zone ; une zone prend la moyenne pondérée par ses `pieces`. Ce module ne lit pas la table : elle sert à
# l'appelant.
APPORTS_PAR_PIECE_PROPOSES_W_M2: Dict[str, Tuple[float, str]] = {
    "bureaux": (17.4, "NF EN 16798-1:2019 annexe C (bureaux)"),
    "salle_reunion": (17.4, "comme les bureaux, en attendant la valeur de NF EN 16798-1 annexe C (non vérifiée : "
                            "norme non consultée)"),
    "accueil": (8.0, "ISO 13790:2008 annexe G, tableau G.9 : locaux annexes des bureaux, 8 W/m²"),
    "sanitaires": (8.0, "ISO 13790:2008 annexe G, tableau G.9 : locaux annexes des bureaux, 8 W/m²"),
    "atelier": (8.0, "CALÉE sur le besoin de chauffage médian d'un parc de bâtiments d'activité, pas mesurée : "
                     "à présenter en fourchette (APPORTS_ATELIER_FOURCHETTE_W_M2)"),
    "stockage": (4.0, "estimé : local peu occupé, surtout de l'éclairage (3 à 5 W/m²)"),
    "logement": (5.92, "NF EN 16798-1:2019 annexe C : 104,16 Wh/(m²·j) sur le profil du moteur (16 h à x, 8 h à "
                      "0,2·x) ; valeur normative de base"),
    "commerce": (30.8, "NF EN 16798-1:2019 annexe C (308,1 Wh/(m²·j) sur 10 h) ; valeur normative de base"),
}
# L'atelier en fourchette : bas (atelier peu équipé, proche du stockage), central (la valeur calée), haut
# (atelier avec machines). Estimé, à recouper sur des consommations réelles de bâtiments d'activité (agrégats
# publics du décret tertiaire).
APPORTS_ATELIER_FOURCHETTE_W_M2: Tuple[float, float, float] = (4.0, 8.0, 15.0)
PIECES: Tuple[str, ...] = tuple(APPORTS_PAR_PIECE_PROPOSES_W_M2)


class ZonesInvalides(ValueError):
    """Un contrat `zones` incohérent : refusé AVANT le calcul, message en français, champ nommé."""


def tolerance_surface_m2(reference_m2: float) -> float:
    """L'écart admis entre deux surfaces qui doivent se correspondre : le plus grand de 1 m² et 2 %."""
    return max(1.0, 0.02 * abs(float(reference_m2)))


@dataclass
class ParoisZone:
    """Les parois d'une zone, calculées par `construire_zones_config`."""
    emprise_m2: float
    volume_m3: float
    murs_exterieurs_m2: Dict[str, float]  # aire BRUTE (vitrage compris) par orientation, adjacences retirées
    murs_source: str                      # « plan_carre » ou « longueurs_saisies »
    toiture_m2: float
    toiture_source: str                   # « saisie » ou « emprise_moins_planchers »
    plancher_bas_m2: float
    plancher_bas_source: str              # « saisie », « terre_plein » ou « aucun (sur une autre zone) »
    vitrage_m2: Optional[float]
    vitrage_par_orientation_m2: Optional[Dict[str, float]]
    mitoyennetes: Tuple[str, ...]
    # La longueur de murs extérieurs de la zone (murs extérieurs bruts / hauteur des niveaux de la zone) :
    # le périmètre de ses ponts thermiques.
    perimetre_m: Optional[float] = None


@dataclass
class ZoneConfig:
    """Une zone thermique : ses valeurs retenues et leur origine (« zone », « batiment » ou « defaut »)."""
    id: str
    niveaux: Tuple[int, ...]
    surface_m2: float
    hauteur_m: float
    usage: str
    pieces: Optional[Dict[str, float]]
    apports_internes_w_m2: Optional[float]
    inertie: Optional[str]
    chauffage: Dict[str, Any]
    froid: Dict[str, Any]
    ventilation: Dict[str, Any]
    consignes: Dict[str, Optional[float]]
    libre: bool
    parois: ParoisZone
    facades: List[int] = field(default_factory=list)  # index dans `facades_equipees`
    origine: Dict[str, str] = field(default_factory=dict)


@dataclass
class AdjacenceConfig:
    """Une paroi entre 2 zones. Pour un plancher, `zone_a` est DESSOUS et `zone_b` dessus."""
    zone_a: str
    zone_b: str
    type: str
    surface_m2: float
    u_w_m2k: float
    u_source: str
    implicite: bool = False
    r_paroi_m2kw: Optional[float] = None  # R de la paroi seule (défaut) ; None = U saisi, gardé tel quel

    @property
    def h_w_k(self) -> float:
        """La conductance de la paroi, H = U × A (W/K), au U nominal (sans le sens du flux)."""
        return self.u_w_m2k * self.surface_m2

    def u_selon_sens(self, t_a: float, t_b: float, rsi: Tuple[float, float, float]) -> float:
        """Le U de la paroi pour l'heure, selon le sens du flux de chaleur entre les nœuds d'air de
        `zone_a` (à `t_a`) et `zone_b` (à `t_b`). `rsi` = (ascendant, horizontal, descendant) en m²K/W.

        Mur : flux horizontal, Rsi horizontal sur les 2 faces. Plancher (`zone_a` DESSOUS) : la chaleur monte
        quand le dessous est plus chaud (Rsi ascendant sur les 2 faces), descend sinon (Rsi descendant) ; à écart
        nul le flux est nul, le sens retenu (descendant) est sans effet. U saisi : rendu tel quel."""
        if self.r_paroi_m2kw is None:
            return self.u_w_m2k
        asc, hor, desc = rsi
        if self.type == "plancher":
            r_si = asc if t_a > t_b else desc
        else:
            r_si = hor
        return 1.0 / (2.0 * r_si + self.r_paroi_m2kw)


@dataclass
class ZonesConfig:
    """Le bâtiment découpé en zones."""
    zones: List[ZoneConfig]
    adjacences: List[AdjacenceConfig]
    n_niveaux: int

    @property
    def n_zones(self) -> int:
        return len(self.zones)

    def zone(self, identifiant: str) -> ZoneConfig:
        for z in self.zones:
            if z.id == identifiant:
                return z
        raise KeyError(identifiant)

    def resume(self) -> Dict[str, Any]:
        """Ce que `hypotheses_retenues.zones` rend : les zones, leurs parois et les adjacences."""
        def _arrondi(v: Any) -> Any:
            if isinstance(v, float):
                return round(v, 2)
            if isinstance(v, dict):
                return {k: _arrondi(x) for k, x in v.items()}
            if isinstance(v, (list, tuple)):
                return [_arrondi(x) for x in v]
            return v

        zones = []
        for z in self.zones:
            p = z.parois
            zones.append(_arrondi({
                "id": z.id, "niveaux": list(z.niveaux), "surface_m2": z.surface_m2, "hauteur_m": z.hauteur_m,
                "usage": z.usage, "libre": z.libre, "chauffage": z.chauffage, "froid": z.froid,
                "ventilation": z.ventilation, "consignes": z.consignes, "inertie": z.inertie,
                "apports_internes_w_m2": z.apports_internes_w_m2, "pieces": z.pieces,
                "facades": list(z.facades), "origine": dict(z.origine),
                "parois": {"emprise_m2": p.emprise_m2, "volume_m3": p.volume_m3,
                           "murs_exterieurs_m2": p.murs_exterieurs_m2, "murs_source": p.murs_source,
                           "toiture_m2": p.toiture_m2, "toiture_source": p.toiture_source,
                           "plancher_bas_m2": p.plancher_bas_m2, "plancher_bas_source": p.plancher_bas_source,
                           "vitrage_m2": p.vitrage_m2, "vitrage_par_orientation_m2": p.vitrage_par_orientation_m2,
                           "mitoyennetes": list(p.mitoyennetes), "perimetre_m": p.perimetre_m},
            }))
        adj = [_arrondi({"zones": [a.zone_a, a.zone_b], "type": a.type, "surface_m2": a.surface_m2,
                         "u_w_m2k": a.u_w_m2k, "u_source": a.u_source, "implicite": a.implicite})
               for a in self.adjacences]
        return {"n_zones": self.n_zones, "n_niveaux": self.n_niveaux, "zones": zones, "adjacences": adj}


# =============================================================================
# LA CONSTRUCTION, AVEC LES CONTRÔLES QUI DEMANDENT TOUT LE BÂTIMENT
# =============================================================================

def _emprise(z: Dict[str, Any]) -> float:
    n = len(z["niveaux"])
    return float(z["emprise_m2"]) if z.get("emprise_m2") is not None else float(z["surface_m2"]) / n


def _herite(zone_val: Any, batiment: Dict[str, Any], cle: str, nom: str, origine: Dict[str, str]) -> Any:
    """La valeur de la zone, sinon celle du bâtiment ; l'origine dit « zone », « batiment » (champ donné par la
    requête) ou « defaut » (valeur par défaut du bâtiment, champ absent de la requête)."""
    if zone_val is not None:
        origine[nom] = "zone"
        return zone_val
    origine[nom] = "batiment" if cle in batiment.get("_donnes", ()) else "defaut"
    return batiment.get(cle)


def construire_zones_config(zones: Sequence[Dict[str, Any]],
                            adjacences: Optional[Sequence[Dict[str, Any]]],
                            batiment: Dict[str, Any],
                            facades: Optional[Sequence[Dict[str, Any]]],
                            zones_max: int) -> ZonesConfig:
    """Contrôle le contrat dans son ENSEMBLE et le traduit en `ZonesConfig`.

    `zones`, `adjacences`, `facades` : les entrées de la requête, en dictionnaires (champs déjà contrôlés un
    à un par le schéma). `batiment` : les champs du bâtiment dont une zone hérite, plus `n_floors_donne`,
    `floor_area_m2`, `window_area_m2`, `windows_by_orientation`, `party_wall_orientations`.
    Lève `ZonesInvalides` au premier défaut, le champ nommé.
    """
    if not zones:
        raise ZonesInvalides("zones : liste vide ; l'omettre pour un calcul monozone")
    if len(zones) > zones_max:
        raise ZonesInvalides(f"zones : {len(zones)} zones, {zones_max} au plus (réglage zones_max)")
    ids = [z["id"] for z in zones]
    doublons = sorted({i for i in ids if ids.count(i) > 1})
    if doublons:
        raise ZonesInvalides(f"zones : identifiant en double : {', '.join(doublons)}")
    par_id = {z["id"]: z for z in zones}
    multi = len(zones) > 1

    # ── Les niveaux et les surfaces ──────────────────────────────────────
    for z in zones:
        n = len(z["niveaux"])
        e = _emprise(z)
        s = float(z["surface_m2"])
        if e > s * (1 + 1e-9) or e * n < s * (1 - 1e-9):
            raise ZonesInvalides(
                f"zones[{z['id']}] : emprise de {e:g} m² incompatible avec {s:g} m² de plancher sur {n} "
                f"niveau(x) : l'emprise est comprise entre le plancher / {n} et le plancher")
    n_niveaux = max(max(z["niveaux"]) for z in zones) + 1
    couverts = {k for z in zones for k in z["niveaux"]}
    trous = [k for k in range(n_niveaux) if k not in couverts]
    if trous:
        raise ZonesInvalides(
            f"zones : niveau(x) {', '.join(map(str, trous))} sans zone ; une partie non chauffée se décrit "
            "par une zone libre (chauffage.systeme = « aucun »)")
    n_donne = batiment.get("n_floors_donne")
    if n_donne is not None and int(n_donne) != n_niveaux:
        raise ZonesInvalides(
            f"n_floors = {n_donne} contredit les zones, qui occupent {n_niveaux} niveau(x) (0 à {n_niveaux - 1})")
    fa = batiment.get("floor_area_m2")
    if fa is not None:
        au_sol = sum(_emprise(z) for z in zones if 0 in z["niveaux"])
        if abs(au_sol - float(fa)) > tolerance_surface_m2(fa):
            raise ZonesInvalides(
                f"floor_area_m2 = {float(fa):g} m² (emprise au sol) contredit les zones : leurs emprises au "
                f"niveau 0 totalisent {au_sol:g} m²")
    wa = batiment.get("window_area_m2")
    if wa is not None and all(z.get("vitrage_m2") is not None for z in zones):
        somme = sum(float(z["vitrage_m2"]) for z in zones)
        if abs(somme - float(wa)) > tolerance_surface_m2(wa):
            raise ZonesInvalides(
                f"window_area_m2 = {float(wa):g} m² contredit les zones : leurs vitrages totalisent {somme:g} m²")
    if multi:
        for champ in ("windows_by_orientation", "party_wall_orientations"):
            if batiment.get(champ) is not None:
                raise ZonesInvalides(
                    f"{champ} au niveau du bâtiment avec plusieurs zones : ambigu, le donner par zone "
                    f"({'vitrage_par_orientation_m2' if champ == 'windows_by_orientation' else 'mitoyennetes'})")

    # ── Les façades équipées ─────────────────────────────────────────────
    facades = list(facades or [])
    if multi and not facades:
        raise ZonesInvalides(
            "facades_equipees obligatoire avec plusieurs zones : chaque façade équipée nomme sa zone")
    facades_par_zone: Dict[str, List[int]] = {i: [] for i in ids}
    entrees_vues: List[Tuple[float, str, set]] = []
    for k, f in enumerate(facades):
        nom = f.get("zone")
        if nom is None:
            if multi:
                raise ZonesInvalides(
                    f"facades_equipees[{k}] (azimut {float(f['azimuth_deg']):g}) : « zone » obligatoire avec "
                    "plusieurs zones")
            nom = ids[0]
        if nom not in par_id:
            raise ZonesInvalides(
                f"facades_equipees[{k}] : zone « {nom} » inconnue (zones : {', '.join(ids)})")
        sbf = f.get("shutters_by_floor")
        niveaux_zone = list(par_id[nom]["niveaux"])
        if sbf is not None:
            hors = [i for i, v in enumerate(sbf) if v and i not in niveaux_zone]
            if hors:
                raise ZonesInvalides(
                    f"facades_equipees[{k}] : volets au(x) niveau(x) {', '.join(map(str, hors))}, que la zone "
                    f"« {nom} » n'occupe pas (niveaux {niveaux_zone})")
            niveaux_entree = {i for i, v in enumerate(sbf) if v}
        else:
            # Sans répartition, les volets sont répartis sur TOUS les niveaux du bâtiment.
            if len(niveaux_zone) != n_niveaux:
                raise ZonesInvalides(
                    f"facades_equipees[{k}] : shutters_by_floor obligatoire, la zone « {nom} » n'occupe que les "
                    f"niveaux {niveaux_zone} sur {n_niveaux}")
            niveaux_entree = set(niveaux_zone)
        # UNE FAÇADE QUI LONGE 2 ZONES (pignon devant les bureaux en R+1 et l'atelier au RDC) : 2 entrées de même
        # azimut, une par zone. Deux entrées de même azimut et de MÊME zone sur un même niveau compteraient deux
        # fois les mêmes baies.
        az = float(f["azimuth_deg"]) % 360.0
        for j, (az_j, nom_j, niv_j) in enumerate(entrees_vues):
            ecart = abs(az - az_j) % 360.0
            if nom_j == nom and min(ecart, 360.0 - ecart) < 0.5 and niv_j & niveaux_entree:
                raise ZonesInvalides(
                    f"facades_equipees[{k}] recouvre facades_equipees[{j}] : même azimut ({az:g}), même zone "
                    f"« {nom} », niveau(x) {', '.join(map(str, sorted(niv_j & niveaux_entree)))} en commun ; "
                    "les réunir en une entrée")
        entrees_vues.append((az, nom, niveaux_entree))
        facades_par_zone[nom].append(k)
    if multi:
        for z in zones:
            if z.get("vitrage_m2") is None and not facades_par_zone[z["id"]]:
                raise ZonesInvalides(
                    f"zones[{z['id']}] : ni façade équipée ni vitrage_m2 ; donner son vitrage (0 s'il n'y en a pas)")

    # ── Les adjacences déclarées ─────────────────────────────────────────
    adj: List[AdjacenceConfig] = []
    vues = set()
    for k, a in enumerate(adjacences or []):
        za, zb = a["zones"]
        if za == zb:
            raise ZonesInvalides(f"adjacences[{k}] : une zone ne touche pas elle-même (« {za} »)")
        for nom in (za, zb):
            if nom not in par_id:
                raise ZonesInvalides(f"adjacences[{k}] : zone « {nom} » inconnue (zones : {', '.join(ids)})")
        cle = (frozenset((za, zb)), a["type"])
        if cle in vues:
            raise ZonesInvalides(f"adjacences[{k}] : {a['type']} entre « {za} » et « {zb} » déclaré deux fois")
        vues.add(cle)
        na, nb = par_id[za]["niveaux"], par_id[zb]["niveaux"]
        surface = float(a["surface_m2"])
        if a["type"] == "mur":
            if not set(na) & set(nb):
                raise ZonesInvalides(
                    f"adjacences[{k}] : un mur relie 2 zones qui partagent un niveau ; « {za} » {list(na)} et "
                    f"« {zb} » {list(nb)} n'en partagent aucun (un plancher ?)")
        else:
            if max(na) + 1 != min(nb):
                raise ZonesInvalides(
                    f"adjacences[{k}] : un plancher relie [dessous, dessus] ; « {za} » {list(na)} n'est pas "
                    f"juste sous « {zb} » {list(nb)}")
            borne = min(_emprise(par_id[za]), _emprise(par_id[zb]))
            if surface > borne + tolerance_surface_m2(borne):
                raise ZonesInvalides(
                    f"adjacences[{k}] : plancher de {surface:g} m², plus grand que l'emprise de l'une des 2 "
                    f"zones ({borne:g} m²)")
        u_def, src = U_ADJACENCE_DEFAUT_W_M2K[a["type"]]
        u = a.get("u_w_m2k")
        adj.append(AdjacenceConfig(za, zb, a["type"], surface, float(u) if u is not None else u_def,
                                   "saisi" if u is not None else src,
                                   r_paroi_m2kw=None if u is not None else R_PAROI_DEFAUT_M2KW[a["type"]]))

    # ── Les planchers implicites : une zone qui ne touche pas le sol repose sur une autre ──
    for z in zones:
        bas = min(z["niveaux"])
        if bas == 0 or z.get("plancher_bas_m2") is not None:
            continue
        if any(a.type == "plancher" and a.zone_b == z["id"] for a in adj):
            continue
        dessous = [c["id"] for c in zones if (bas - 1) in c["niveaux"] and bas not in c["niveaux"]]
        if len(dessous) != 1:
            raise ZonesInvalides(
                f"zones[{z['id']}] : commence au niveau {bas} et repose sur "
                + (f"{len(dessous)} zones possibles ({', '.join(dessous)}) : déclarer les adjacences "
                   "« plancher » [dessous, dessus]" if dessous else
                   "aucune zone : déclarer plancher_bas_m2 (porche, pilotis) ou une adjacence « plancher »"))
        c = par_id[dessous[0]]
        u_def, src = U_ADJACENCE_DEFAUT_W_M2K["plancher"]
        adj.append(AdjacenceConfig(c["id"], z["id"], "plancher", min(_emprise(c), _emprise(z)), u_def, src,
                                   implicite=True, r_paroi_m2kw=R_PAROI_DEFAUT_M2KW["plancher"]))

    # ── Les zones, leurs valeurs retenues et leurs parois ────────────────
    sorties: List[ZoneConfig] = []
    _vide: Dict[str, Any] = {}
    for z in zones:
        origine: Dict[str, str] = {}
        zid = z["id"]
        n = len(z["niveaux"])
        e = _emprise(z)
        h = float(_herite(z.get("hauteur_m"), batiment, "floor_height_m", "hauteur_m", origine))
        usage = _herite(z.get("usage"), batiment, "building_type", "usage", origine)
        ch = dict(z.get("chauffage") or {})
        fr = dict(z.get("froid") or {})
        cs = dict(z.get("consignes") or {})
        libre = ch.get("systeme") == "aucun"
        chauffage = {
            "systeme": _herite(ch.get("systeme"), batiment, "hvac_type", "chauffage.systeme", origine),
            "cop": None if libre else _herite(ch.get("cop"), batiment, "cop_heating", "chauffage.cop", origine),
            "installation": None if libre else _herite(ch.get("installation"),
                                                      batiment, "installation_chauffage",
                                                      "chauffage.installation", origine),
            "puissance_w_m2": None if libre else _herite(ch.get("puissance_w_m2"),
                                                        batiment, "heating_capacity_w_m2",
                                                        "chauffage.puissance_w_m2", origine),
        }
        froid = {
            "systeme": "aucun" if libre else _herite(fr.get("systeme"), batiment, "froid_systeme",
                                                     "froid.systeme", origine),
            "eer": None if libre else _herite(fr.get("eer"), batiment, "eer_cooling", "froid.eer", origine),
            "couverture": None if libre else _herite(fr.get("couverture"), batiment, "froid_couverture",
                                                     "froid.couverture", origine),
            "part_climatisee": None if libre else _herite(fr.get("part_climatisee"),
                                                         batiment, "part_climatisee",
                                                         "froid.part_climatisee", origine),
            "puissance_w_m2": None if libre else _herite(fr.get("puissance_w_m2"),
                                                        batiment, "cooling_capacity_w_m2",
                                                        "froid.puissance_w_m2", origine),
        }
        ventilation = {
            "type": _herite(z.get("ventilation"), batiment, "ventilation_type", "ventilation", origine),
            "ach": _herite(z.get("ventilation_ach"), batiment, "ventilation_ach_override",
                           "ventilation_ach", origine),
            "recuperation": _herite(z.get("recuperation"), batiment, "ventilation_heat_recovery_override",
                                    "recuperation", origine),
            "horaires": _herite(z.get("ventilation_horaires"), batiment, "ventilation_horaires",
                                "ventilation_horaires", origine),
        }
        consignes = {
            "chauffage_c": None if libre else _herite(cs.get("chauffage_c"), batiment, "setpoint_heating_c",
                                                      "consignes.chauffage_c", origine),
            "froid_c": None if libre else _herite(cs.get("froid_c"), batiment, "setpoint_cooling_c",
                                                  "consignes.froid_c", origine),
            "reduit_c": None if libre else _herite(cs.get("reduit_c"),
                                                   batiment, "setpoint_heating_setback_c",
                                                   "consignes.reduit_c", origine),
        }
        apports = _herite(z.get("apports_internes_w_m2"), batiment, "apports_internes_w_m2",
                          "apports_internes_w_m2", origine)
        inertie = _herite(z.get("inertie"), batiment, "thermal_mass_level", "inertie", origine)

        # Plancher bas et toiture.
        if z.get("plancher_bas_m2") is not None:
            pb, pb_src = float(z["plancher_bas_m2"]), "saisie"
        elif 0 in z["niveaux"]:
            pb, pb_src = e, "terre_plein"
        else:
            pb, pb_src = 0.0, "aucun (sur une autre zone)"
        if z.get("toiture_m2") is not None:
            toit, toit_src = float(z["toiture_m2"]), "saisie"
        else:
            couvert = sum(a.surface_m2 for a in adj if a.type == "plancher" and a.zone_a == zid)
            toit, toit_src = max(0.0, e - couvert), "emprise_moins_planchers"

        # Murs extérieurs par orientation, aire brute.
        mitoy = tuple(_herite(z.get("mitoyennetes"), (_vide if multi else batiment), "party_wall_orientations",
                              "mitoyennetes", origine) or ())
        longueurs = z.get("longueurs_facade_m")
        if longueurs is not None:
            murs = {o: float(longueurs.get(o, 0.0)) * h * n for o in ORIENTATIONS}
            murs_src = "longueurs_saisies"
        else:
            cote = math.sqrt(e)
            murs = {o: cote * h * n for o in ORIENTATIONS}
            murs_src = "plan_carre"
        for o in mitoy:
            murs[o] = 0.0
        if longueurs is None:
            a_mur = sum(a.surface_m2 for a in adj if a.type == "mur" and zid in (a.zone_a, a.zone_b))
            total = sum(murs.values())
            if a_mur > 0 and total > 0:
                if a_mur > total + tolerance_surface_m2(total):
                    raise ZonesInvalides(
                        f"zones[{zid}] : {a_mur:g} m² de murs vers d'autres zones pour {total:g} m² de murs au "
                        "plan carré ; donner longueurs_facade_m")
                k = max(0.0, 1.0 - a_mur / total)
                murs = {o: v * k for o, v in murs.items()}

        vit_or = _herite(z.get("vitrage_par_orientation_m2"),
                         (_vide if multi else batiment), "windows_by_orientation",
                         "vitrage_par_orientation_m2", origine)
        vit = _herite(z.get("vitrage_m2"), (_vide if multi else batiment), "window_area_m2", "vitrage_m2", origine)
        parois = ParoisZone(emprise_m2=e, volume_m3=e * h * n, murs_exterieurs_m2=murs, murs_source=murs_src,
                            toiture_m2=toit, toiture_source=toit_src, plancher_bas_m2=pb,
                            plancher_bas_source=pb_src, vitrage_m2=None if vit is None else float(vit),
                            vitrage_par_orientation_m2=None if vit_or is None else dict(vit_or),
                            mitoyennetes=mitoy, perimetre_m=sum(murs.values()) / (h * n))
        sorties.append(ZoneConfig(
            id=zid, niveaux=tuple(z["niveaux"]), surface_m2=float(z["surface_m2"]), hauteur_m=h, usage=usage,
            pieces=z.get("pieces"), apports_internes_w_m2=apports, inertie=inertie, chauffage=chauffage,
            froid=froid, ventilation=ventilation, consignes=consignes, libre=libre, parois=parois,
            facades=facades_par_zone[zid], origine=origine))
    return ZonesConfig(zones=sorties, adjacences=adj, n_niveaux=n_niveaux)
