"""Le relevé d'un bâtiment écrit au format du bâtiment commun, version 1 (un fichier JSON).

Ce format décrit un bâtiment existant tel que d'autres logiciels le connaissent : dessiné par son propriétaire,
proposé d'après des bases publiques, ou relevé dans une maquette. Il reprend les noms du relevé de ce dépôt
(`rayflect.io.releve`) et ajoute à chaque grandeur sa PROVENANCE :

    "nombre_de_niveaux": {"valeur": 2, "provenance": "saisie"}

Ce module en fait un `Releve`, comme la lecture d'une maquette IFC ou d'un plan DXF.

CE QUI EST LU.
  - Le lieu (position, altitude) et le nord du repère (`repere.nord_deg`, même sens que le relevé).
  - Les niveaux : leur emprise (celle du niveau, sinon celle du bâtiment), leurs altitudes (sinon la hauteur
    d'étage, sinon 3 m supposés et demandés), et s'ils sont chauffés : `"chauffage": "aucun"` donne un niveau
    non chauffé.
  - Les façades : leur trait au sol (`segment_m`, sinon le côté de l'emprise qui regarde vers leur azimut), et
    si elles sont mitoyennes : un mur mitoyen n'échange pas avec le dehors.
  - Les baies : leur position dans l'espace quand la source la donne ; sinon leur façade, leur niveau, leur
    décalage le long de la façade (`position_m`, du début du trait jusqu'au bord gauche de la baie ; le trait
    `segment_m` va de gauche à droite vu du dehors [S : schéma du format, version 1]), leur taille et leur
    allège. Une baie sans azimut prend celui de sa façade.
  - Une façade qui annonce un vitrage sans aucune baie : ce vitrage est réparti entre les niveaux comme pour un
    bâtiment décrit par ses chiffres (`releve_par_chiffres.repartir`), et c'est dit.

LA PROVENANCE est gardée, champ par champ, dans `Releve.provenances`. Toute valeur supposée (personne ne l'a
dite) ou inconnue (`je_ne_sais_pas`) devient une ligne de ce qui manque.

CE QUI N'EST PAS LU est listé dans `Releve.non_lus`, jamais perdu en silence : l'usage et le chauffage de
chaque partie, la teinte des murs et le toit tels qu'ils sont, les protections et les obstacles déjà là, les
masques et les voisins de chaque façade. Ce qui décrit l'étude plutôt que le bâtiment (usage, période,
vitrage, inertie, énergie) y est rendu avec la ligne à écrire dans le fichier d'étude.

LA VERSION. Ce lecteur sait lire la version 1, d'empreinte `EMPREINTE_LUE` : les 16 premiers caractères du
SHA-256 du schéma, sans sa propre clé d'empreinte, clés triées. Les empreintes antérieures de la même version
restent acceptées (`EMPREINTES_ACCEPTEES`) : un champ facultatif ajouté ne rend pas faux un fichier d'avant. Un
fichier qui annonce une autre version ou une autre empreinte est refusé : ce qu'il contient pourrait être lu de
travers.

L'INERTIE « MOYENNE » (brique, parpaing), que le format accepte depuis le 20/11/2026, n'a pas d'équivalent ici :
l'inertie de ce dépôt est lourde ou légère. Elle n'est jamais ramenée à l'une des 2 : elle se demande.
"""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from rayflect import energie as energies, hypotheses as hyp
from rayflect.io.releve import Baie, Niveau, Releve, _azimut, secteur
from rayflect.io.releve_par_chiffres import repartir

FORMAT = "batiment_commun"
VERSION = 1
EMPREINTE_LUE = "6867d7997dbe0355"                         # version 1, avec l'inertie « moyenne » (20/11/2026)
EMPREINTES_ACCEPTEES = (EMPREINTE_LUE, "920221dc9b39776b")  # et la version 1 du 18/11/2026
CLE_EMPREINTE = "x-empreinte"
HAUTEUR_D_ETAGE_SUPPOSEE_M = 3.0        # [H] une hauteur d'étage courante, demandée quand elle sert
ALLEGE_SUPPOSEE_M = 1.0                 # [H]
ECART_D_AZIMUT_MAX_DEG = 30.0           # une façade sans trait prend le côté de l'emprise le plus proche en azimut
ECART_SIGNALE_DEG = 20.0                # au-delà, l'azimut annoncé et celui du trait se contredisent : c'est dit


class BatimentNonLu(ValueError):
    """Le fichier ne peut pas être lu comme un bâtiment commun : le message dit pourquoi."""


def empreinte_du_schema(schema: Dict[str, Any]) -> str:
    """L'empreinte d'un schéma du bâtiment commun, comme le calcule son validateur."""
    valeurs = {k: v for k, v in schema.items() if k != CLE_EMPREINTE}
    return hashlib.sha256(json.dumps(valeurs, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()[:16]


def _valeur(champ) -> Any:
    return champ.get("valeur") if isinstance(champ, dict) else None


def _aire(points) -> float:
    return abs(sum(x1 * y2 - x2 * y1 for (x1, y1), (x2, y2) in zip(points, points[1:] + points[:1]))) / 2.0


def _controler(objet, chemin: str = "") -> None:
    """Ce que le schéma exige et qu'il serait grave de lire de travers : la provenance de chaque valeur, et des
    azimuts entre 0 et 360°. Le reste du schéma n'est pas contrôlé ici."""
    if isinstance(objet, dict):
        if "valeur" in objet and "provenance" not in objet:
            raise BatimentNonLu(f"{chemin or 'la racine'} : une valeur sans provenance")
        if objet.get("valeur") is None and "valeur" in objet and not objet.get("je_ne_sais_pas"):
            raise BatimentNonLu(f"{chemin} : une valeur vide doit dire je_ne_sais_pas")
        for cle, valeur in objet.items():
            if cle == "azimut_deg":
                azimut = _valeur(valeur) if isinstance(valeur, dict) else valeur
                if azimut is not None and not 0.0 <= float(azimut) < 360.0:
                    raise BatimentNonLu(f"{chemin}.{cle} : {azimut} n'est pas un azimut (de 0 inclus à 360 exclu)")
            if isinstance(valeur, (dict, list)) and cle != "sources":
                _controler(valeur, f"{chemin}.{cle}" if chemin else cle)
    elif isinstance(objet, list):
        for rang, valeur in enumerate(objet):
            _controler(valeur, f"{chemin}[{rang}]")


def _relever_les_provenances(objet, chemin: str, provenances: Dict[str, str], manques: List[str]) -> None:
    """Chaque grandeur du fichier : d'où elle vient ; et si personne ne l'a dite, il faut la demander."""
    if isinstance(objet, dict):
        if "provenance" in objet and chemin:
            provenance = str(objet["provenance"]) + (", confirmée" if objet.get("confirmee") else "")
            provenances[chemin] = provenance
            if objet.get("je_ne_sais_pas"):
                manques.append(f"{chemin} : inconnue, à demander")
            elif objet["provenance"] == "supposee" and "valeur" in objet:
                manques.append(f"{chemin} : {objet['valeur']} supposé, personne ne l'a dit ; à confirmer")
        for cle, valeur in objet.items():
            if cle not in ("valeur", "sources", "intervalle") and isinstance(valeur, (dict, list)):
                _relever_les_provenances(valeur, f"{chemin}.{cle}" if chemin else cle, provenances, manques)
    elif isinstance(objet, list):
        for rang, valeur in enumerate(objet):
            nom = valeur.get("id") or valeur.get("identifiant") if isinstance(valeur, dict) else None
            _relever_les_provenances(valeur, f"{chemin}[{nom if nom is not None else rang}]", provenances, manques)


# Les pompes à chaleur que le format distingue et que ce dépôt ne distingue pas : toutes deviennent « pac »,
# avec le même rendement de saison (rayflect.energie).
POMPES_A_CHALEUR = ("pac_air_air", "pac_air_eau", "pac_eau_eau")


def _ligne(champ: str, valeur, cle: str, connus, table: str = "") -> str:
    """La ligne à écrire dans le fichier d'étude, ou, pour une valeur que l'étude refuserait, ce qu'il en est.

    Une ligne proposée doit être acceptée telle quelle : on ne propose jamais une valeur hors du vocabulaire.
    """
    dans = f" dans {table}" if table else ""
    if valeur in connus:
        return f"{champ} « {valeur} » : à reporter par {cle} = \"{valeur}\"{dans}"
    return f"{champ} « {valeur} » : pas d'équivalent ici ; choisir {cle}{dans} parmi {', '.join(connus)}"


def _a_l_etude(donnees: Dict[str, Any]) -> List[str]:
    """Ce que le fichier dit de l'étude plutôt que du bâtiment : la ligne à écrire dans le fichier d'étude."""
    lignes = []
    usage = _valeur(donnees.get("usage"))
    if usage is not None:
        lignes.append(_ligne("usage", usage, "usage", tuple(hyp.USAGES)))
    enveloppe = donnees.get("enveloppe", {})
    for cle, connus, table in (("periode", tuple(hyp.PAROIS_PAR_PERIODE), ""),
                               ("vitrage", tuple(hyp.VITRAGES), "[parois]"), ("inertie", hyp.INERTIES, "[parois]")):
        valeur = _valeur(enveloppe.get(cle))
        if valeur is not None and not (cle == "inertie" and valeur == "moyenne"):     # celle-là se demande
            lignes.append(_ligne(f"enveloppe.{cle}", valeur, cle, connus, table))
    if _valeur(enveloppe.get("annee_construction")) is not None and _valeur(enveloppe.get("periode")) is None:
        lignes.append(f"enveloppe.annee_construction {_valeur(enveloppe['annee_construction'])} : à traduire en "
                      f"période de construction")
    chauffage = donnees.get("chauffage", {})
    systeme = _valeur(chauffage.get("systeme"))
    if systeme == "aucun":
        lignes.append("chauffage.systeme « aucun » : pas de table [energie] ; le résultat reste en besoins")
    elif systeme in POMPES_A_CHALEUR:
        lignes.append(f"chauffage.systeme « {systeme} » : à reporter par chauffage = \"pac\" dans [energie] ; le "
                      f"type de pompe à chaleur n'est pas distingué ici, un seul rendement de saison vaut pour toutes")
    elif systeme is not None:
        lignes.append(_ligne("chauffage.systeme", systeme, "chauffage", tuple(energies.SYSTEMES_DE_CHAUFFAGE),
                             "[energie]"))
    climatisation = _valeur(chauffage.get("climatisation"))
    if climatisation is not None:
        lignes.append(f"chauffage.climatisation « {climatisation} » : "
                      + ("climatisation = true" if climatisation == "totale" else
                         "climatisation = false" if climatisation == "aucune" else
                         "une climatisation partielle n'est pas calculée ici"))
    return lignes


def _non_lus(donnees: Dict[str, Any]) -> List[str]:
    """Ce que le fichier dit et que le calcul ne prend pas encore."""
    lignes = []
    usage_du_batiment = _valeur(donnees.get("usage"))
    for niveau in donnees.get("niveaux", []):
        usage = _valeur(niveau.get("usage"))
        if usage is not None and usage != usage_du_batiment:
            lignes.append(f"niveau {niveau.get('ordre')} : usage « {usage} », autre que celui du bâtiment ; le calcul "
                          f"prend l'usage de l'étude pour tous les niveaux chauffés")
        for cle in ("trous_m", "autres_emprises_m"):
            if niveau.get(cle):
                lignes.append(f"niveau {niveau.get('ordre')} : {cle} (cours, corps séparés) ; seul le contour "
                              f"extérieur est repris")
    for cle in ("part_chauffee", "surface_chauffee_m2"):
        if _valeur(donnees.get("chauffage", {}).get(cle)) is not None:
            lignes.append(f"chauffage.{cle} : seul le niveau entier se dit non chauffé ici")
    enveloppe = donnees.get("enveloppe", {})
    for cle in ("teinte_murs", "absorptance_murs"):
        if _valeur(enveloppe.get(cle)) is not None:
            lignes.append(f"enveloppe.{cle} : la teinte des murs se donne dans [parois], absorption_des_murs")
    toit = donnees.get("toit", {})
    if any(_valeur(toit.get(c)) is not None for c in ("type_toit", "absorptance_toit", "genre", "pente_deg")):
        lignes.append("toit : le toit tel qu'il est n'est pas repris (toit plat, teinte de l'étude) ; un toit clair "
                      "se compare par l'élément « toit » d'un scénario")
    for facade in donnees.get("facades", []):
        nom = facade.get("id")
        if facade.get("protections"):
            lignes.append(f"façade {nom} : {len(facade['protections'])} protection(s) déjà posée(s), non reprises")
        if facade.get("masque") or facade.get("voisin"):
            lignes.append(f"façade {nom} : masque ou voisin décrit, non repris (voisins = true les prend de la "
                          f"carte, en France)")
        if _valeur(facade.get("chauffee")) is False:
            lignes.append(f"façade {nom} : une partie non chauffée derrière elle, non reprise")
    if donnees.get("obstacles"):
        lignes.append(f"{len(donnees['obstacles'])} obstacle(s) dessiné(s), non repris : un arbre se pose par "
                      f"l'élément « arbre » d'un scénario")
    for cle in ("parties", "desaccords"):
        if donnees.get(cle):
            lignes.append(f"{cle} : {len(donnees[cle])}, non repris")
    if _valeur(donnees.get("longueur_mitoyenne_m")) and not any(_valeur(f.get("mitoyenne")) for f in
                                                                donnees.get("facades", [])):
        lignes.append(f"longueur_mitoyenne_m {_valeur(donnees['longueur_mitoyenne_m'])} m sans façade mitoyenne "
                      f"désignée : le mur mitoyen n'est pas placé")
    for baie in donnees.get("baies", []):
        details = [c for c in ("type", "vitrage", "occultation", "modele") if baie.get(c)]
        if details:
            lignes.append("baies : " + ", ".join(sorted({c for b in donnees["baies"] for c in
                                                        ("type", "vitrage", "occultation", "modele") if b.get(c)}))
                          + " de chaque baie, non repris (le vitrage de l'étude vaut pour toutes)")
            break
    return lignes + _a_l_etude(donnees)


def _cotes(emprise: List[Tuple[float, float]]):
    """Les côtés d'un contour : (début, fin, normale vers le dehors)."""
    sens = 1.0 if sum(x1 * y2 - x2 * y1 for (x1, y1), (x2, y2) in zip(emprise, emprise[1:] + emprise[:1])) > 0 else -1.0
    for a, b in zip(emprise, emprise[1:] + emprise[:1]):
        dx, dy = b[0] - a[0], b[1] - a[1]
        longueur = math.hypot(dx, dy)
        if longueur > 1e-6:
            # Un contour tourné dans le sens trigonométrique a son dehors à droite de chaque côté.
            yield a, b, (sens * dy / longueur, -sens * dx / longueur)


def _normale_d_un_trait(a, b, emprise) -> Tuple[float, float]:
    """La normale d'un trait de façade qui s'éloigne du bâtiment."""
    dx, dy = b[0] - a[0], b[1] - a[1]
    longueur = math.hypot(dx, dy) or 1.0
    n = (dy / longueur, -dx / longueur)
    cx = sum(p[0] for p in emprise) / len(emprise)
    cy = sum(p[1] for p in emprise) / len(emprise)
    milieu = ((a[0] + b[0]) / 2.0, (a[1] + b[1]) / 2.0)
    if n[0] * (milieu[0] - cx) + n[1] * (milieu[1] - cy) < 0:
        n = (-n[0], -n[1])
    return n


def lire(chemin) -> Releve:
    """Le relevé d'un fichier au format du bâtiment commun. Lève `BatimentNonLu` en disant pourquoi."""
    chemin = Path(chemin)
    try:
        donnees = json.loads(chemin.read_text(encoding="utf-8"))
    except OSError as erreur:
        raise BatimentNonLu(f"fichier illisible : {erreur}") from erreur
    except json.JSONDecodeError as erreur:
        raise BatimentNonLu(f"{chemin.name} n'est pas du JSON valide : {erreur}") from erreur
    return depuis(donnees, chemin.name)


def depuis(donnees: Dict[str, Any], nom: str = "bâtiment commun") -> Releve:
    """Le relevé d'un bâtiment commun déjà lu."""
    if not isinstance(donnees, dict) or donnees.get("schema") != FORMAT:
        raise BatimentNonLu(f"{nom} n'est pas un bâtiment commun : la clé schema doit valoir « {FORMAT} »")
    if donnees.get("version") != VERSION:
        raise BatimentNonLu(f"{nom} est en version {donnees.get('version')} du bâtiment commun ; ce lecteur sait lire "
                            f"la version {VERSION}")
    suivie = donnees.get("empreinte_schema")
    if suivie is not None and suivie not in EMPREINTES_ACCEPTEES:
        raise BatimentNonLu(f"{nom} suit le schéma d'empreinte {suivie} ; ce lecteur sait lire "
                            f"{', '.join(EMPREINTES_ACCEPTEES)}")
    repere = donnees.get("repere", {})
    if repere.get("axes", "x_droite_y_haut") != "x_droite_y_haut" or repere.get("unite", "m") != "m":
        raise BatimentNonLu(f"{nom} : repère {repere.get('axes')} en {repere.get('unite')} ; attendu x_droite_y_haut "
                            f"en mètres")

    _controler(donnees)
    provenances: Dict[str, str] = {}
    manques: List[str] = []
    _relever_les_provenances(donnees, "", provenances, manques)
    manques += [str(m) for m in donnees.get("manques", [])]
    if _valeur(donnees.get("enveloppe", {}).get("inertie")) == "moyenne":
        manques.append("inertie « moyenne » (brique, parpaing) : ce calcul ne connaît que lourde et légère ; choisir "
                       "inertie = \"lourde\" ou \"legere\" dans [parois], sans quoi la période de construction décide")

    position = _valeur(donnees.get("lieu", {}).get("position")) or {}
    latitude, longitude = position.get("latitude"), position.get("longitude")
    if latitude is None or longitude is None:
        manques.append("position du site absente : adresse à demander")
    nord_deg = _valeur(repere.get("nord_deg"))
    if nord_deg is None:
        nord_deg = 0.0
        manques.append("nord du repère absent : pris sur l'axe y, à confirmer")
    nord = (math.sin(math.radians(nord_deg)), math.cos(math.radians(nord_deg)))

    # LES NIVEAUX
    decrits = {n.get("ordre"): n for n in donnees.get("niveaux", [])}
    nombre = _valeur(donnees.get("nombre_de_niveaux")) or len(decrits)
    if not nombre:
        raise BatimentNonLu(f"{nom} : ni nombre_de_niveaux, ni niveaux décrits")
    if decrits and set(decrits) != set(range(len(decrits))):
        raise BatimentNonLu(f"{nom} : les niveaux ont les ordres {sorted(decrits, key=str)} ; attendu de 0 à "
                            f"{len(decrits) - 1}")
    if decrits and len(decrits) != nombre:
        raise BatimentNonLu(f"{nom} : {len(decrits)} niveaux décrits pour nombre_de_niveaux = {nombre}")
    hauteur_commune = _valeur(donnees.get("hauteur_d_etage_m"))
    il_en_faut_une = any(_valeur(decrits.get(o, {}).get("plafond_m")) is None
                         and _valeur(decrits.get(o, {}).get("hauteur_d_etage_m")) is None for o in range(nombre))
    if hauteur_commune is None and il_en_faut_une:
        totale = _valeur(donnees.get("hauteur_m"))
        if totale:
            hauteur_commune = float(totale) / nombre
            manques.append(f"hauteur d'étage : {hauteur_commune:.2f} m, la hauteur du bâtiment ({float(totale):g} m) "
                           f"partagée en {nombre} niveaux égaux ; à mesurer")
        else:
            hauteur_commune = HAUTEUR_D_ETAGE_SUPPOSEE_M
            manques.append(f"hauteur d'étage absente : {HAUTEUR_D_ETAGE_SUPPOSEE_M:g} m supposés, à mesurer")
    emprise_commune = _valeur(donnees.get("emprise_m"))
    niveaux: List[Niveau] = []
    plancher = 0.0
    for ordre in range(nombre):
        decrit = decrits.get(ordre, {})
        emprise = _valeur(decrit.get("emprise_m")) or emprise_commune
        if not emprise or len(emprise) < 3:
            raise BatimentNonLu(f"{nom} : aucune emprise pour le niveau {ordre} ni pour le bâtiment")
        emprise = [(float(x), float(y)) for x, y in emprise]
        if emprise[0] == emprise[-1]:
            emprise = emprise[:-1]
        bas = _valeur(decrit.get("plancher_m"))
        bas = float(bas) if bas is not None else float(_valeur(decrit.get("altitude_m")) or plancher)
        hauteur = _valeur(decrit.get("hauteur_d_etage_m")) or hauteur_commune
        haut = _valeur(decrit.get("plafond_m"))
        haut = float(haut) if haut is not None else bas + float(hauteur)
        chauffage = _valeur(decrit.get("chauffage"))
        niveaux.append(Niveau(
            nom=str(decrit.get("nom") or f"niveau {ordre}"), altitude_m=bas, plancher_m=bas, plafond_m=haut,
            emprise_m=emprise, aire_emprise_m2=round(_aire(emprise), 2),
            aire_espaces_m2=_valeur(decrit.get("aire_espaces_m2")), chauffe=chauffage != "aucun"))
        plancher = haut

    # LES FAÇADES : un trait au sol et une normale vers le dehors
    base = niveaux[0].emprise_m
    facades: Dict[str, Dict[str, Any]] = {}
    mitoyens: List[tuple] = []
    for facade in donnees.get("facades", []):
        ident = facade.get("id")
        azimut = _valeur(facade.get("azimut_deg"))
        trait = facade.get("segment_m")
        if trait:
            a, b = tuple(map(float, trait[0])), tuple(map(float, trait[1]))
            normale = _normale_d_un_trait(a, b, base)
        else:
            if azimut is None:
                manques.append(f"façade {ident} : ni trait au sol ni azimut, ses baies ne peuvent pas être placées")
                continue
            proches = [(abs((_azimut(n, nord) - azimut + 180.0) % 360.0 - 180.0), -math.dist(a, b), a, b, n)
                       for a, b, n in _cotes(base)]
            ecart, _l, a, b, normale = min(proches)
            if ecart > ECART_D_AZIMUT_MAX_DEG:
                manques.append(f"façade {ident} : aucun côté de l'emprise ne regarde vers {azimut:g}°, ses baies ne "
                               f"peuvent pas être placées")
                continue
        calcule = _azimut(normale, nord)
        if azimut is not None and abs((calcule - azimut + 180.0) % 360.0 - 180.0) > ECART_SIGNALE_DEG:
            manques.append(f"façade {ident} : annoncée vers {azimut:g}°, son trait regarde vers {calcule:.0f}° ; c'est "
                           f"le trait qui est pris")
        facades[ident] = {"debut": a, "fin": b, "normale": normale, "azimut": calcule, "fiche": facade}
        if _valeur(facade.get("mitoyenne")):
            mitoyens.append((a, b))

    # LES BAIES
    baies: List[Baie] = []
    par_facade: Dict[str, int] = {}

    def niveau_de(rang) -> Optional[Niveau]:
        return niveaux[rang] if isinstance(rang, int) and 0 <= rang < len(niveaux) else None

    for k, fiche in enumerate(donnees.get("baies", [])):
        ident = str(fiche.get("identifiant") or f"baie_{k}")
        niveau = niveau_de(fiche.get("niveau", 0))
        if niveau is None:
            raise BatimentNonLu(f"{nom} : la baie {ident} est au niveau {fiche.get('niveau')}, hors des {nombre} niveaux")
        largeur, hauteur = float(fiche.get("largeur_m") or 0.0), float(fiche.get("hauteur_m") or 0.0)
        aire = float(fiche.get("aire_m2") or largeur * hauteur)
        commun = dict(identifiant=ident, nom=str(fiche.get("nom") or ident), niveau=niveau.nom, largeur_m=largeur,
                      hauteur_m=hauteur, aire_m2=round(aire, 3), taille_declaree_m=None)
        if fiche.get("centre_m") is not None and fiche.get("normale_xy") is not None and fiche.get("z_bas_m") is not None:
            # La source dit où est la baie dans l'espace : elle est reprise telle quelle.
            baies.append(Baie(**commun, allege_m=fiche.get("allege_m"), azimut_deg=fiche.get("azimut_deg"),
                              secteur=fiche.get("secteur"), inclinaison_deg=float(fiche.get("inclinaison_deg", 90.0)),
                              centre_m=tuple(fiche["centre_m"]), normale_xy=tuple(fiche["normale_xy"]),
                              z_bas_m=float(fiche["z_bas_m"]), z_haut_m=float(fiche.get("z_haut_m") or
                                                                              fiche["z_bas_m"] + hauteur),
                              mur=fiche.get("mur"), mur_exterieur=fiche.get("mur_exterieur", True)))
            continue
        facade = facades.get(fiche.get("facade"))
        if facade is None:
            manques.append(f"baie {ident} : sa façade « {fiche.get('facade')} » n'est pas placée, la baie est écartée")
            continue
        par_facade[fiche["facade"]] = par_facade.get(fiche["facade"], 0) + 1
        a, b, normale = facade["debut"], facade["fin"], facade["normale"]
        longueur = math.dist(a, b)
        if fiche.get("position_m") is None:
            decalage = (longueur - largeur) / 2.0
            manques.append(f"baie {ident} : position le long de la façade absente, mise au milieu")
        else:
            decalage = float(fiche["position_m"])
        allege = fiche.get("allege_m")
        if allege is None:
            allege = ALLEGE_SUPPOSEE_M
            manques.append(f"baie {ident} : allège absente, {ALLEGE_SUPPOSEE_M:g} m supposé")
        t = (decalage + largeur / 2.0) / longueur
        z_bas = niveau.plancher_m + float(allege)
        azimut = fiche.get("azimut_deg")
        azimut = float(azimut) if azimut is not None else facade["azimut"]
        baies.append(Baie(**commun, allege_m=float(allege), azimut_deg=round(azimut, 1), secteur=secteur(azimut),
                          inclinaison_deg=float(fiche.get("inclinaison_deg", 90.0)),
                          centre_m=(a[0] + t * (b[0] - a[0]), a[1] + t * (b[1] - a[1]), z_bas + hauteur / 2.0),
                          normale_xy=normale, z_bas_m=z_bas, z_haut_m=z_bas + hauteur, mur=fiche.get("facade"),
                          mur_exterieur=not _valeur(facade["fiche"].get("mitoyenne"))))

    for ident, facade in facades.items():
        annonce = _valeur(facade["fiche"].get("vitrage_m2"))
        decrit = sum(b.aire_m2 for b in baies if b.mur == ident)
        if annonce and par_facade.get(ident) and decrit < 0.9 * float(annonce):
            manques.append(f"façade {ident} : {float(annonce):g} m² de vitrage annoncés, {decrit:.1f} m² de baies "
                           f"décrites ; seules les baies décrites sont reprises")

    # UNE FAÇADE QUI ANNONCE UN VITRAGE SANS BAIE : il est réparti entre les niveaux, comme pour des chiffres.
    for ident, facade in facades.items():
        vitrage = _valeur(facade["fiche"].get("vitrage_m2"))
        if not vitrage or par_facade.get(ident) or _valeur(facade["fiche"].get("mitoyenne")):
            continue
        a, b, normale = facade["debut"], facade["fin"], facade["normale"]
        longueur = math.dist(a, b)
        for niveau in niveaux:
            n, large, haut, allege, plafonnee = repartir(float(vitrage) / len(niveaux), longueur,
                                                         niveau.plafond_m - niveau.plancher_m)
            pas = longueur / n
            for j in range(n):
                t = (j + 0.5) * pas / longueur
                z_bas = niveau.plancher_m + allege
                baies.append(Baie(
                    identifiant=f"{ident}_{niveau.nom}_{j}", nom=f"baie répartie {ident} {j + 1}", niveau=niveau.nom,
                    largeur_m=round(large, 3), hauteur_m=round(haut, 3), aire_m2=round(large * haut, 3),
                    allege_m=round(allege, 3), azimut_deg=round(facade["azimut"], 1), secteur=secteur(facade["azimut"]),
                    inclinaison_deg=90.0, centre_m=(a[0] + t * (b[0] - a[0]), a[1] + t * (b[1] - a[1]),
                                                    z_bas + haut / 2.0),
                    normale_xy=normale, z_bas_m=z_bas, z_haut_m=z_bas + haut, mur=ident, mur_exterieur=True,
                    taille_declaree_m=None))
            if plafonnee:
                manques.append(f"façade {ident} : {vitrage:g} m² de vitrage ne tiennent pas sur {longueur:.1f} m, "
                               f"l'aire est plafonnée")
        manques.append(f"façade {ident} : {vitrage:g} m² de vitrage sans baie décrite, répartis en baies régulières "
                       f"sur les {len(niveaux)} niveaux")

    for niveau in niveaux:
        niveau.n_baies = sum(1 for baie in baies if baie.niveau == niveau.nom)
    source = donnees.get("source_geometrie", {})
    ecrit_par = donnees.get("ecrit_par", {})
    lieu = donnees.get("lieu", {})
    return Releve(
        fichier=str(source.get("fichier") or donnees.get("nom") or donnees.get("id") or nom),
        schema=f"{FORMAT} v{VERSION}" + (f", depuis {source['type']}" if source.get("type") else ""),
        logiciel=str(ecrit_par.get("outil", "inconnu")), latitude=latitude, longitude=longitude,
        altitude_m=_valeur(lieu.get("altitude_m")), nord_deg=float(nord_deg), niveaux=niveaux, baies=baies,
        n_murs=int(source.get("n_murs", 0)), n_murs_exterieurs=source.get("n_murs_exterieurs"),
        n_espaces=int(source.get("n_espaces", len(niveaux))),
        n_protections_solaires=int(source.get("n_protections_solaires", 0)),
        altitude_du_zero_m=float(source.get("altitude_du_zero_m", 0.0)),
        n_murs_rideaux=int(source.get("n_murs_rideaux", 0)), manques=manques, mitoyens_m=mitoyens,
        provenances=provenances, non_lus=_non_lus(donnees))
