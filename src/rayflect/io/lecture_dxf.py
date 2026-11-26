"""Le relevé d'un bâtiment depuis des plans DXF : un fichier par niveau, du bas vers le haut.

CE QU'UN PLAN DIT, ET CE QU'IL NE DIT PAS. Un plan en 2D donne le contour du niveau et la place des baies
sur ce contour. Il ne donne ni la hauteur d'étage, ni l'allège, ni la hauteur des baies, et rarement le
nord : ces 4 valeurs se donnent en paramètres. Celles qui manquent reçoivent une valeur courante [H] et
entrent dans la liste « à demander ». Elles ne sont jamais devinées en silence.

COMMENT LE PLAN EST LU. Un DXF n'a pas de murs ni de fenêtres, seulement des traits rangés par calques.
  - Le contour : tous les traits des calques de murs et de baies sont épaissis jusqu'à se rejoindre
    par-dessus les portes, et l'enveloppe du plus grand ensemble est ramenée à sa taille. Un calque
    d'emprise, s'il existe (un contour fermé), est pris tel quel et passe avant.
  - Les baies : chaque bloc d'un calque de baies est une baie ; les traits isolés sont regroupés par
    proximité. Une baie est gardée si elle est sur le contour ; les autres sont des baies intérieures.
    Sa largeur se mesure le long de la façade.
Les calques se reconnaissent à leur nom (mur, wall, fenêtre, window, A-GLAZ...) ou se donnent en paramètres.

LIMITES. Les portes vitrées ne sont pas comptées. Les plans des différents niveaux doivent être dessinés
dans le même repère. Un fichier DWG ne se lit pas : l'exporter en DXF depuis le logiciel de dessin.
"""

from __future__ import annotations

import math
import re
from pathlib import Path
from typing import Iterable, List, Optional, Sequence, Tuple, Union

import ezdxf
from ezdxf import path as chemins
from shapely.geometry import LineString, MultiLineString, Point, Polygon
from shapely.ops import unary_union

from .releve import Baie, Niveau, Releve, _azimut, secteur

HAUTEUR_D_ETAGE_M = 3.0             # [H] de plancher à plancher, bâtiment courant
ALLEGE_M = 0.9                      # [H] allège courante d'une fenêtre
HAUTEUR_DE_BAIE_M = 1.35            # [H] fenêtre courante sur allège de 0,9 m, linteau à 2,25 m
MOTS_DES_MURS = ("mur", "wall", "wand", "mauer", "muro", "pared", "alvenaria", "voile", "facade", "façade")
MOTS_DES_BAIES = ("fen", "window", "glaz", "vitr", "baie", "menuis", "chassis", "châssis", "janela", "ventana",
                  "finestr")
# Abréviations trop courtes pour être cherchées au milieu d'un nom : elles doivent en être un morceau entier.
# Vu sur des plans réels : A-WIN (fenêtres), que « win » cherché partout confondrait avec « drawing ».
MORCEAUX_DES_BAIES = ("win", "wind", "wdw", "jan", "vit")
MOTS_DE_L_EMPRISE = ("emprise", "footprint", "outline", "contour")
MOTS_DES_PORTES = ("door", "porte", "tur", "tür", "opening", "ouvert")
TAILLE_PLAUSIBLE_M = (3.0, 1000.0)  # [H] un bâtiment plus petit ou plus grand trahit une unité fausse
METRES_PAR_UNITE = {1: 0.0254, 2: 0.3048, 4: 0.001, 5: 0.01, 6: 1.0}       # $INSUNITS du format DXF
NOMS_D_UNITE = {"mm": 0.001, "cm": 0.01, "m": 1.0, "pouce": 0.0254, "pied": 0.3048}
FERMETURES_M = (1.5, 3.0, 5.0)      # [H] referme les interruptions de mur jusqu'à 3 m, puis 6, puis 10
PART_DES_MURS_MINIMALE = 0.8        # [H] un contour qui laisse dehors plus de 20 % des murs est douteux
EPAISSEUR_D_UN_TRAIT_PERDU_M = 0.3  # [H] un trait isolé qui dépasse du bâtiment ne fait pas une pièce
ECART_A_LA_FACADE_M = 0.6           # [H] au-delà, une baie n'est pas dans le mur du contour
REGROUPEMENT_M = 0.15               # [H] réunit les traits d'une même baie, épais d'un mur
LARGEUR_MINIMALE_M = 0.25
AIRE_MINIMALE_M2 = 10.0
FINESSE_M = 0.01


class PlanNonLu(ValueError):
    """Le plan ne permet pas d'établir un relevé : le message dit ce qu'il faut donner."""


def _correspond(calque: str, mots: Iterable[str], morceaux: Iterable[str] = ()) -> bool:
    nom = calque.lower()
    return any(mot in nom for mot in mots) or bool(set(re.split(r"[^a-zà-ÿ]+", nom)) & set(morceaux))


def _traits(entite, echelle: float) -> List[LineString]:
    """Les traits d'une entité, en mètres. Une entité sans trace (texte, cote, point) ne rend rien."""
    try:
        if entite.dxftype() == "HATCH":
            traces = list(chemins.from_hatch(entite))
        else:
            traces = [chemins.make_path(entite)]
    except (TypeError, ValueError, ezdxf.DXFError):
        return []
    rendu = []
    for trace in traces:
        for morceau in trace.sub_paths():
            points = [(p.x * echelle, p.y * echelle) for p in morceau.flattening(FINESSE_M / echelle)]
            if len(points) >= 2 and LineString(points).length > 0:
                rendu.append(LineString(points))
    return rendu


def _deplier(entite, calque_parent: Optional[str] = None, profondeur: int = 0):
    """Les entités simples d'une entité, blocs dépliés, chacune avec son calque effectif."""
    calque = entite.dxf.layer
    if calque == "0" and calque_parent:         # le calque 0 d'un bloc prend le calque de son insertion
        calque = calque_parent
    if entite.dxftype() == "INSERT" and profondeur < 6:
        try:
            for fille in entite.virtual_entities():
                yield from _deplier(fille, calque, profondeur + 1)
        except (ezdxf.DXFError, ValueError, ArithmeticError):
            return                              # vu sur un plan réel : un bloc à l'échelle nulle
    else:
        yield entite, calque


def _echelle(document, espace, unite, manques: List[str], nom: str) -> float:
    if unite is not None:
        if isinstance(unite, (int, float)) and not isinstance(unite, bool) and unite > 0:
            return float(unite)                 # donnée en mètres par unité de dessin
        if unite not in NOMS_D_UNITE:
            raise PlanNonLu(f"unité inconnue : « {unite} ». Connues : {', '.join(NOMS_D_UNITE)}, "
                            f"ou un nombre de mètres par unité de dessin")
        return NOMS_D_UNITE[unite]
    code = int(document.header.get("$INSUNITS", 0) or 0)
    if code in METRES_PAR_UNITE:
        return METRES_PAR_UNITE[code]
    # L'unité n'est pas écrite : on la suppose d'après la taille du dessin, et on le dit.
    xs, ys = [], []
    for entite in espace:
        for sous, _calque in _deplier(entite):
            for trait in _traits(sous, 1.0):
                x0, y0, x1, y1 = trait.bounds
                xs += [x0, x1]
                ys += [y0, y1]
    if not xs:
        raise PlanNonLu(f"{nom} : aucun trait dans le plan")
    taille = max(max(xs) - min(xs), max(ys) - min(ys))
    suppose, echelle = ("mm", 0.001) if taille > 2000 else ("cm", 0.01) if taille > 200 else ("m", 1.0)
    manques.append(f"{nom} : unité du dessin non écrite, « {suppose} » supposé d'après sa taille "
                   f"({taille * echelle:.0f} m de long) : à confirmer")
    return echelle


def _refermer(reunis, fermeture_m: float) -> Optional[Polygon]:
    """L'enveloppe du plus grand ensemble de traits, interruptions refermées jusqu'à 2 fois `fermeture_m`."""
    epaissi = reunis.buffer(fermeture_m, cap_style=3, join_style=2)
    plein = Polygon(max(getattr(epaissi, "geoms", [epaissi]), key=lambda g: g.area).exterior)
    ramene = plein.buffer(-fermeture_m, join_style=2)
    # Un trait isolé qui dépasse (un renvoi, une coupe) laisserait une épine au contour : on l'efface.
    ramene = ramene.buffer(-EPAISSEUR_D_UN_TRAIT_PERDU_M, join_style=2).buffer(EPAISSEUR_D_UN_TRAIT_PERDU_M,
                                                                                join_style=2)
    morceaux = [g for g in getattr(ramene, "geoms", [ramene]) if not g.is_empty]
    if not morceaux:
        return None
    return Polygon(max(morceaux, key=lambda g: g.area).exterior).simplify(0.02)


def _contour(traits: Sequence[LineString], nom: str, manques: List[str]) -> Polygon:
    """Le contour extérieur dessiné par des traits de murs, interruptions refermées.

    Les interruptions sont refermées au plus juste : 3 m d'abord, davantage seulement si le contour obtenu
    laisse dehors plus de 20 % des murs. Ce qui reste douteux est dit.
    """
    if not traits:
        raise PlanNonLu(f"{nom} : aucun trait de mur")
    reunis = unary_union(traits)
    essais = []
    for fermeture in FERMETURES_M:
        contour = _refermer(reunis, fermeture)
        if contour is None or contour.area < AIRE_MINIMALE_M2:
            continue
        part = reunis.intersection(contour.buffer(0.5)).length / reunis.length
        essais.append((fermeture, contour, part))
        if part >= PART_DES_MURS_MINIMALE:
            break
    if not essais:
        raise PlanNonLu(f"{nom} : les traits de murs ne dessinent aucun contour d'au moins {AIRE_MINIMALE_M2:g} m². "
                        f"Dessiner le contour du niveau sur un calque d'emprise, ou revoir calques_murs")
    bons = [e for e in essais if e[2] >= PART_DES_MURS_MINIMALE]
    fermeture, contour, part = bons[0] if bons else essais[0]
    if fermeture > FERMETURES_M[0]:
        manques.append(f"{nom} : murs interrompus sur plus de {2 * FERMETURES_M[0]:g} m, contour refermé jusqu'à "
                       f"{2 * fermeture:g} m : à contrôler sur le dessin")
    if part < PART_DES_MURS_MINIMALE:
        manques.append(f"{nom} : le contour gardé ne contient que {part * 100:.0f} % des murs dessinés. Le fichier "
                       f"porte sans doute plusieurs dessins, ou le contour n'est pas fermé : à contrôler sur le dessin")
    return contour


def _emprise_dessinee(traits: Sequence[LineString]) -> Optional[Polygon]:
    fermes = [Polygon(t.coords) for t in traits if len(t.coords) >= 4 and t.is_ring]
    fermes = [p.buffer(0) for p in fermes if p.area >= AIRE_MINIMALE_M2]
    return Polygon(max(fermes, key=lambda p: p.area).exterior) if fermes else None


def _baie_sur_le_contour(groupe, contour: Polygon) -> Optional[Tuple[tuple, tuple, float]]:
    """(centre sur la façade, normale vers le dehors, largeur le long de la façade), ou None si elle n'y est pas."""
    centre = groupe.centroid
    bord = list(contour.exterior.coords)
    cote = min((LineString([bord[k], bord[k + 1]]) for k in range(len(bord) - 1)), key=centre.distance)
    if cote.distance(centre) > ECART_A_LA_FACADE_M:
        return None
    (x0, y0), (x1, y1) = cote.coords
    longueur = math.hypot(x1 - x0, y1 - y0)
    ux, uy = (x1 - x0) / longueur, (y1 - y0) / longueur
    points = [p for g in getattr(groupe, "geoms", [groupe]) for p in g.coords]
    le_long = [(x - x0) * ux + (y - y0) * uy for x, y in points]
    gauche, droite = max(min(le_long), 0.0), min(max(le_long), longueur)
    if droite - gauche < LARGEUR_MINIMALE_M:
        return None
    milieu = (gauche + droite) / 2.0
    cx, cy = x0 + milieu * ux, y0 + milieu * uy
    nx, ny = uy, -ux
    if contour.contains(Point(cx + 0.3 * nx, cy + 0.3 * ny)):
        nx, ny = -nx, -ny
    return (cx, cy), (nx, ny), droite - gauche


def _lire_un_plan(chemin: Path, unite, calques_murs, calques_baies, calque_emprise, manques: List[str]):
    """(contour, liste de (centre, normale, largeur), nombre de baies écartées, logiciel) d'un fichier."""
    if chemin.suffix.lower() == ".dwg":
        raise PlanNonLu(f"{chemin.name} : un fichier DWG ne se lit pas, l'exporter en DXF depuis le logiciel de dessin")
    try:
        document = ezdxf.readfile(str(chemin))
    except (OSError, ezdxf.DXFError) as erreur:
        raise PlanNonLu(f"{chemin.name} : fichier illisible ({erreur})") from erreur
    espace = document.modelspace()
    echelle = _echelle(document, espace, unite, manques, chemin.name)
    calques = sorted({calque for entite in espace for _sous, calque in _deplier(entite)})

    def choisis(donnes, mots, morceaux=()):
        if donnes:
            absents = [c for c in donnes if c not in calques]
            if absents:
                raise PlanNonLu(f"{chemin.name} : calque absent : {', '.join(absents)}. "
                                f"Calques du plan : {', '.join(calques)}")
            return set(donnes)
        return {c for c in calques if _correspond(c, mots, morceaux)}

    murs = choisis(calques_murs, MOTS_DES_MURS)
    baies = choisis(calques_baies, MOTS_DES_BAIES, MORCEAUX_DES_BAIES) - murs
    if len(murs) > 1 and not calques_murs:
        manques.append(f"{chemin.name} : contour tiré de {len(murs)} calques de murs ({', '.join(sorted(murs))}). "
                       f"Si l'un porte des murets ou des clôtures, ne donner que les bons par calques_murs")
    melanges = sorted(c for c in baies if _correspond(c, MOTS_DES_PORTES))
    if melanges:
        manques.append(f"{chemin.name} : le calque {', '.join(melanges)} mêle portes et fenêtres : des portes "
                       f"pleines sont peut-être comptées comme des baies")
    emprise = choisis([calque_emprise] if calque_emprise else None, MOTS_DE_L_EMPRISE) - murs - baies

    traits_murs, traits_emprise, groupes, isoles = [], [], [], []
    for entite in espace:
        if entite.dxftype() == "INSERT" and entite.dxf.layer in baies:
            traits = [t for sous, _c in _deplier(entite) for t in _traits(sous, echelle)]
            if traits:
                groupes.append(MultiLineString(traits))
            continue
        for sous, calque in _deplier(entite):
            if calque in murs:
                traits_murs += _traits(sous, echelle)
            elif calque in baies:
                isoles += _traits(sous, echelle)
            elif calque in emprise:
                traits_emprise += _traits(sous, echelle)
    if isoles:
        reunis = unary_union([t.buffer(REGROUPEMENT_M) for t in isoles])
        for tache in getattr(reunis, "geoms", [reunis]):
            groupes.append(MultiLineString([t for t in isoles if t.intersects(tache)]))

    contour = _emprise_dessinee(traits_emprise)
    if contour is None:
        if not traits_murs:
            raise PlanNonLu(
                f"{chemin.name} : aucun calque de murs ni d'emprise reconnu. Les nommer par calques_murs. "
                f"Calques du plan : {', '.join(calques)}")
        x0, y0, x1, y1 = unary_union(traits_murs).bounds
        taille = max(x1 - x0, y1 - y0)
        if not (TAILLE_PLAUSIBLE_M[0] <= taille <= TAILLE_PLAUSIBLE_M[1]):
            ecrite = "celle écrite dans le fichier" if unite is None else f"« {unite} »"
            possibles = [n for n, m in NOMS_D_UNITE.items() if 6.0 <= taille / echelle * m <= 300.0]
            piste = (f"« {possibles[0]} » donnerait {taille / echelle * NOMS_D_UNITE[possibles[0]]:.0f} m"
                     if possibles else "aucune unité courante ne donne une taille de bâtiment")
            raise PlanNonLu(
                f"{chemin.name} : avec l'unité retenue ({ecrite}, 1 unité = {echelle:g} m), les murs s'étendent "
                f"sur {taille:.4g} m. L'unité est sans doute fausse ({piste}) : la donner par unite "
                f"({', '.join(NOMS_D_UNITE)}, ou un nombre de mètres par unité de dessin)")
        contour = _contour(traits_murs + [t for g in groupes for t in g.geoms], chemin.name, manques)
    if contour.exterior.is_ccw is False:
        contour = Polygon(list(contour.exterior.coords)[::-1])
    if not baies:
        manques.append(f"{chemin.name} : aucun calque de baies reconnu, le niveau est lu sans fenêtre. "
                       f"Les nommer par calques_baies. Calques du plan : {', '.join(calques)}")

    posees, ecartees, dehors = [], 0, 0
    large = contour.buffer(ECART_A_LA_FACADE_M)
    for groupe in groupes:
        pose = _baie_sur_le_contour(groupe, contour)
        if pose is not None:
            posees.append(pose)
        elif large.contains(groupe.centroid):
            ecartees += 1
        else:
            dehors += 1
    if dehors:
        # Vu sur des plans réels : une partie des murs est sur un calque non reconnu, le contour ne couvre
        # qu'un morceau du niveau et rien d'autre ne le trahit que ces baies restées dehors.
        manques.append(f"{chemin.name} : {dehors} baies sont dessinées EN DEHORS du contour trouvé. Le contour est "
                       f"sans doute incomplet : des murs sont sur un calque non reconnu, à nommer par calques_murs. "
                       f"Calques du plan : {', '.join(calques)}")
    # 2 groupes au même endroit de la même façade sont la même baie, dessinée en 2 fois.
    uniques = []
    for pose in sorted(posees, key=lambda p: -p[2]):
        if not any(math.hypot(pose[0][0] - u[0][0], pose[0][1] - u[0][1]) < (pose[2] + u[2]) / 2.0 * 0.5
                   and pose[1][0] * u[1][0] + pose[1][1] * u[1][1] > 0.9 for u in uniques):
            uniques.append(pose)
    logiciel = str(document.header.get("$ACADVER", "?"))
    return contour, uniques, ecartees, logiciel


def dessin_de_controle(chemin, releve: Releve, rang: int = 0, unite: Optional[str] = None) -> str:
    """Le plan d'un niveau redessiné en SVG, avec ce qui en a été lu : contour en rouge, baies en vert.

    Une lecture de plan repose sur des noms de calques et des seuils : elle se contrôle à l'œil avant de
    s'en servir.
    """
    chemin = Path(chemin)
    document = ezdxf.readfile(str(chemin))
    espace = document.modelspace()
    echelle = _echelle(document, espace, unite, [], chemin.name)
    niveau = releve.niveaux[rang]
    xs, ys = zip(*niveau.emprise_m)
    marge = 0.15 * max(max(xs) - min(xs), max(ys) - min(ys))
    x0, y0, x1, y1 = min(xs) - marge, min(ys) - marge, max(xs) + marge, max(ys) + marge

    def ligne(points, couleur, epaisseur, ferme=False):
        trace = " ".join(f"{x - x0:.3f},{y1 - y:.3f}" for x, y in points)
        return (f'<{"polygon" if ferme else "polyline"} points="{trace}" fill="none" stroke="{couleur}" '
                f'stroke-width="{epaisseur}"/>')

    lignes = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {x1 - x0:.2f} {y1 - y0:.2f}" '
              f'style="background:white">']
    for entite in espace:
        for sous, calque in _deplier(entite):
            couleur = "#222" if _correspond(calque, MOTS_DES_MURS) else "#bbb"
            for trait in _traits(sous, echelle):
                bx0, by0, bx1, by1 = trait.bounds
                if bx1 >= x0 and bx0 <= x1 and by1 >= y0 and by0 <= y1:
                    lignes.append(ligne(trait.coords, couleur, 0.03))
    lignes.append(ligne(niveau.emprise_m, "#d22", 0.08, ferme=True))
    for baie in releve.baies:
        if baie.niveau != niveau.nom:
            continue
        (cx, cy), (nx, ny), demi = baie.centre_m[:2], baie.normale_xy, baie.largeur_m / 2.0
        lignes.append(ligne([(cx + ny * demi, cy - nx * demi), (cx - ny * demi, cy + nx * demi)], "#1a1", 0.25))
        lignes.append(ligne([(cx, cy), (cx + 0.8 * nx, cy + 0.8 * ny)], "#1a1", 0.08))
    lignes.append("</svg>")
    return "\n".join(lignes)


def lire(fichiers: Union[str, Path, Sequence], hauteur_d_etage_m: Optional[float] = None,
         allege_m: Optional[float] = None, hauteur_de_baie_m: Optional[float] = None,
         nord_deg: Optional[float] = None, unite: Optional[str] = None,
         calques_murs: Optional[Sequence[str]] = None, calques_baies: Optional[Sequence[str]] = None,
         calque_emprise: Optional[str] = None) -> Releve:
    """Le relevé d'un bâtiment depuis ses plans, un fichier par niveau du bas vers le haut.

    Le même fichier peut être répété pour des étages identiques. `nord_deg` : angle du nord par rapport à
    l'axe Y du dessin, dans le sens des aiguilles d'une montre. `unite` : mm, cm, m, pouce ou pied, quand
    le fichier ne le dit pas.
    """
    if isinstance(fichiers, (str, Path)):
        fichiers = [fichiers]
    fichiers = [Path(f) for f in fichiers]
    if not fichiers:
        raise PlanNonLu("aucun plan donné")
    manques: List[str] = []

    def valeur(donnee, defaut, quoi):
        if donnee is not None:
            if donnee <= 0:
                raise PlanNonLu(f"{quoi} : {donnee} m n'est pas une hauteur")
            return float(donnee)
        manques.append(f"{quoi} non donnée : {defaut:g} m pris par défaut, à confirmer")
        return defaut

    etage = valeur(hauteur_d_etage_m, HAUTEUR_D_ETAGE_M, "hauteur d'étage")
    allege = valeur(allege_m, ALLEGE_M, "allège des baies") if allege_m != 0 else 0.0
    hauteur_baie = valeur(hauteur_de_baie_m, HAUTEUR_DE_BAIE_M, "hauteur des baies")
    if allege + hauteur_baie > etage - 0.2:
        raise PlanNonLu(f"une baie de {hauteur_baie:g} m sur une allège de {allege:g} m ne tient pas dans un "
                        f"étage de {etage:g} m")
    if nord_deg is None:
        manques.append("nord non donné : pris vers le haut du dessin, à confirmer")
        nord_deg = 0.0
    nord = (math.sin(math.radians(nord_deg)), math.cos(math.radians(nord_deg)))

    releve = Releve(fichier=", ".join(dict.fromkeys(f.name for f in fichiers)), schema="DXF", logiciel="?",
                    latitude=None, longitude=None, altitude_m=None, nord_deg=round(nord_deg % 360.0, 2),
                    n_murs_exterieurs=None)
    lus = {}
    for rang, chemin in enumerate(fichiers):
        if chemin not in lus:
            lus[chemin] = _lire_un_plan(chemin, unite, calques_murs, calques_baies, calque_emprise, manques)
        contour, baies, ecartees, releve.logiciel = lus[chemin]
        plancher = round(rang * etage, 3)
        nom = f"niveau {rang} ({chemin.stem})"
        releve.niveaux.append(Niveau(
            nom=nom, altitude_m=plancher, n_baies=len(baies),
            emprise_m=[(round(x, 3), round(y, 3)) for x, y in list(contour.exterior.coords)[:-1]],
            plancher_m=plancher, plafond_m=round(plancher + etage, 3), aire_emprise_m2=round(contour.area, 1)))
        for numero, (centre, normale, largeur) in enumerate(baies, 1):
            azimut = _azimut(normale, nord)
            releve.baies.append(Baie(
                identifiant=f"N{rang}-B{numero}", nom=f"baie {numero} du niveau {rang}", niveau=nom,
                largeur_m=round(largeur, 3), hauteur_m=hauteur_baie, aire_m2=round(largeur * hauteur_baie, 3),
                allege_m=allege, azimut_deg=round(azimut, 1), secteur=secteur(azimut), inclinaison_deg=90.0,
                centre_m=(round(centre[0], 3), round(centre[1], 3), round(plancher + allege + hauteur_baie / 2, 3)),
                normale_xy=(round(normale[0], 4), round(normale[1], 4)), z_bas_m=round(plancher + allege, 3),
                z_haut_m=round(plancher + allege + hauteur_baie, 3), mur=None, mur_exterieur=True,
                taille_declaree_m=None))
        if ecartees:
            manques.append(f"{chemin.name} : {ecartees} baies hors du contour, prises pour des baies intérieures")
    manques = list(dict.fromkeys(manques))
    manques.append("position du site absente d'un plan : adresse à demander")
    manques.append("portes vitrées non comptées : un plan ne les distingue pas des portes pleines")
    if len(lus) > 1:
        manques.append("les plans des niveaux sont supposés dessinés dans le même repère : à confirmer")
    releve.manques = manques
    return releve
