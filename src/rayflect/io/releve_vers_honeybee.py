"""Du relevé d'une maquette à un bâtiment calculable par EnergyPlus (un modèle Honeybee).

Le bâtiment reconstruit est volontairement simple : UN volume par niveau, obtenu en extrudant l'emprise du
niveau sur sa hauteur, et chaque baie reposée sur le mur extérieur le plus proche qui regarde du même côté.
Les cloisons, les locaux et la forme du toit ne sont pas repris.

Tout est tourné pour que l'axe Y soit le nord vrai : l'azimut d'un mur du modèle est alors directement
comparable à l'azimut relevé de la baie qu'il porte.

Les niveaux superposés ne s'échangent pas de chaleur : chauffés de la même façon, ils sont à peu près à la même
température. Ce n'est plus vrai quand l'un d'eux n'est pas chauffé : le plancher qui le sépare de ses voisins
devient alors une vraie paroi entre 2 zones. Un mur qui suit un mur mitoyen du relevé n'échange pas avec le
dehors (paroi sans échange : le voisin est supposé chauffé comme le bâtiment) et ne reçoit pas de baie.

Ce qui n'a pas pu être repris est rendu dans le compte rendu, jamais passé sous silence.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from typing import List

from honeybee.aperture import Aperture
from honeybee.boundarycondition import boundary_conditions
from honeybee.facetype import face_types
from honeybee.model import Model
from honeybee.room import Room
from ladybug_geometry.geometry3d import Face3D, Point3D, Polyface3D
from shapely.geometry import LineString, Point as ShapelyPoint, Polygon as ShapelyPolygon
from shapely.ops import nearest_points, polygonize, unary_union

from .releve import Baie, Releve

# LA PROFONDEUR D'UNE ZONE DE FAÇADE. Aucune méthode européenne lue ne fixe la profondeur d'une zone THERMIQUE
# de façade : NCM (Royaume-Uni) et Th-BCE (France) définissent la zone thermique par l'usage et les systèmes.
# La seule valeur chiffrée est américaine. Ce que l'Europe fixe, c'est la profondeur de la zone ÉCLAIRÉE PAR
# LE JOUR, et c'est elle qu'on retient par défaut : c'est aussi la bande où le soleil pèse sur la pièce.
PROFONDEUR_DE_FACADE_M = 4.5    # [S] ASHRAE 90.1, annexe G, table G3.1 : 15 pieds (4,57 m), zone thermique
PLAN_DE_TRAVAIL_M = 0.8         # [S] hauteur du plan de travail des exemples officiels (fiche RT2012, guide dena)
REPERES_DE_PROFONDEUR = {
    "Europe, France, Allemagne, Luxembourg": "2,5 × (hauteur du linteau − hauteur du plan de travail) : "
                                             "EN 15193-1 annexe F, Th-BCE 2020 § 7.1.3, DIN V 18599-4 ; "
                                             "zone d'éclairage naturel",
    "Royaume-Uni, Irlande": "6 m de la façade : NCM Modelling Guide § 203, manuel SBEM ; zone d'éclairage naturel",
    "Espagne": "5 m d'une fenêtre : CTE DB-HE, HE3 § 3.4 ; obligation de régulation de l'éclairage",
    "Belgique (Wallonie)": "0,5 + 3 × (hauteur vitrée utile × transmission lumineuse) : méthode PEN 2026 ; "
                           "zone d'éclairage naturel",
    "États-Unis": "15 pieds, soit 4,57 m : ASHRAE 90.1 annexe G ; zone thermique",
}


def profondeur_selon_le_linteau(hauteur_du_linteau_m: float, plan_de_travail_m: float = PLAN_DE_TRAVAIL_M) -> float:
    """La profondeur éclairée par le jour : 2,5 fois la hauteur du linteau au-dessus du plan de travail.

    [S] EN 15193-1:2017 annexe F ; Th-BCE 2020, fiche éclairage, § 7.1.3 ; DIN V 18599-4 § 5.2.2.
    """
    return max(0.0, 2.5 * (hauteur_du_linteau_m - plan_de_travail_m))


def profondeur_du_releve(releve: Releve):
    """La profondeur de façade tirée des baies du relevé : règle du linteau sur le linteau médian. None sans baie."""
    linteaux = sorted(b.allege_m + b.hauteur_m for b in releve.baies
                      if b.mur_exterieur is not False and b.inclinaison_deg > 60.0 and b.allege_m is not None)
    if not linteaux:
        return None
    return round(profondeur_selon_le_linteau(linteaux[len(linteaux) // 2]), 2)
AIRE_MINIMALE_D_UNE_ZONE_M2 = 15.0   # [H] en dessous, une bande de façade est rattachée à sa voisine
PART_MINIMALE_DU_NOYAU = 0.10   # [H] en dessous, le plateau est trop étroit pour qu'un noyau ait un sens
ECART_AU_MUR_MAX_M = 1.0        # une baie à plus d'un mètre de tout mur du volume n'est pas reposée
ACCORD_DES_NORMALES_MIN = 0.90  # cosinus : le mur et la baie regardent à moins de 26° l'un de l'autre
MARGE_M = 0.05                  # une baie ne touche pas le bord de son mur
HAUTEUR_MAX_SANS_REPERE_M = 4.5
TOLERANCE_MITOYENNE_M = 0.15    # un mur suit un mur mitoyen s'il en reste à moins de 15 cm...
PART_MITOYENNE_MIN = 0.80       # ...sur au moins 80 % de sa longueur


@dataclass
class CompteRendu:
    niveaux_repris: List[str] = field(default_factory=list)
    niveaux_ecartes: List[str] = field(default_factory=list)
    baies_reposees: int = 0
    aire_reposee_m2: float = 0.0
    aire_relevee_m2: float = 0.0
    baies_ecartees: List[str] = field(default_factory=list)
    ecart_azimut_max_deg: float = 0.0
    emprise_m: List[tuple] = field(default_factory=list)    # contour du niveau le plus bas, repère du modèle
    z_du_sol_m: float = 0.0
    zones: int = 0
    etiquettes: dict = field(default_factory=dict)          # par zone : (rang du niveau, nom du niveau, côté)
    profondeur_de_facade: str = "un seul volume par niveau"
    non_chauffees: List[str] = field(default_factory=list)  # les zones des niveaux non chauffés
    murs_mitoyens: int = 0
    aire_mitoyenne_m2: float = 0.0


def _nom(texte: str) -> str:
    return re.sub(r"[^A-Za-z0-9_]", "_", texte)[:40] or "x"


def _tourner(x: float, y: float, angle_deg: float) -> tuple:
    a = math.radians(angle_deg)
    return (x * math.cos(a) - y * math.sin(a), x * math.sin(a) + y * math.cos(a))


def _hauteur(niveau, altitudes) -> float:
    """La hauteur du volume : jusqu'au plafond des locaux, ou jusqu'au prochain repère de niveau s'il est plus bas."""
    au_dessus = [a for a in altitudes if a > niveau.plancher_m + 2.0]
    plafond = min([niveau.plafond_m] + ([min(au_dessus)] if au_dessus else []))
    return min(plafond - niveau.plancher_m, HAUTEUR_MAX_SANS_REPERE_M if not au_dessus else 99.0)


def _decouper(sol: Face3D, profondeur_m):
    """Le plancher d'un niveau, entier ou découpé en zones de façade et noyau : (suffixe du nom, plancher).

    Le noyau est le plateau rétréci de `profondeur_m` sur tout son pourtour. La couronne qui reste est coupée
    à chaque angle du contour, par un trait qui va de l'angle au point le plus proche du noyau : cela donne une
    bande par pan de façade. Les bandes voisines qui regardent du même côté sont ensuite réunies.
    Un plateau trop étroit pour avoir un noyau reste d'un seul tenant.
    """
    if not profondeur_m:
        return [("", sol)]
    z = sol.vertices[0].z
    contour = ShapelyPolygon([(v.x, v.y) for v in sol.vertices]).simplify(0.10)
    if not contour.is_valid:
        contour = contour.buffer(0)
    coeur = contour.buffer(-profondeur_m, join_style=2)
    if coeur.is_empty or coeur.area < PART_MINIMALE_DU_NOYAU * contour.area:
        return [("", sol)]
    noyaux = [g for g in (coeur.geoms if hasattr(coeur, "geoms") else [coeur]) if g.area >= 1.0]
    couronne = contour.difference(coeur)
    traits = []
    for x, y in list(contour.exterior.coords)[:-1]:
        cible = nearest_points(ShapelyPoint(x, y), coeur.boundary)[1]
        dx, dy = cible.x - x, cible.y - y
        longueur = math.hypot(dx, dy)
        if longueur < 1e-6:
            continue
        ux, uy = dx / longueur, dy / longueur          # le trait dépasse d'un centimètre de chaque côté
        traits.append(LineString([(x - 0.01 * ux, y - 0.01 * uy), (cible.x + 0.01 * ux, cible.y + 0.01 * uy)]))
    dedans = couronne.buffer(1e-6)
    bandes = [m for m in polygonize(unary_union([couronne.boundary] + traits))
              if m.area > 0.01 and dedans.contains(m.representative_point())]

    # LES BANDES QUI REGARDENT DU MÊME CÔTÉ SONT RÉUNIES quand elles se touchent. Un contour réel a beaucoup
    # de petits pans : sans cela, un plateau de 15 pans donne 15 zones par niveau, et le calcul d'un immeuble
    # de 10 niveaux passe de quelques secondes à près de 10 minutes.
    # Une bande minuscule (un pan coupé, un petit décroché) ne mérite pas sa zone : elle rejoint la voisine
    # avec laquelle elle partage le plus long bord.
    bandes.sort(key=lambda b: b.area)
    while len(bandes) > 1 and bandes[0].area < AIRE_MINIMALE_D_UNE_ZONE_M2:
        petite = bandes.pop(0)
        voisine = max(range(len(bandes)), key=lambda k: petite.boundary.intersection(bandes[k].boundary).length)
        if petite.boundary.intersection(bandes[voisine].boundary).length <= 0:
            bandes.append(petite)       # isolée : on la garde, et on arrête pour ne pas tourner en rond
            break
        bandes[voisine] = bandes[voisine].union(petite)
        bandes.sort(key=lambda b: b.area)
    bord = contour.exterior
    par_cote = {}
    for bande in bandes:
        par_cote.setdefault(_cote(bande, bord), []).append(bande)
    zones = []
    for cote, formes in sorted(par_cote.items()):
        reunion = unary_union(formes)
        for k, morceau in enumerate(reunion.geoms if hasattr(reunion, "geoms") else [reunion]):
            if morceau.area >= 1.0 and not morceau.interiors:
                zones.append((f"_facade_{cote}_{k}", _plancher(list(morceau.simplify(0.001).exterior.coords)[:-1], z)))
    for k, noyau in enumerate(noyaux):
        if not noyau.interiors:
            zones.append((f"_noyau_{k}", _plancher(list(noyau.exterior.coords)[:-1], z)))
    # Garde-fou : un découpage qui perd ou invente du plancher est refusé, le plateau reste d'un seul tenant.
    if abs(sum(plancher.area for _s, plancher in zones) - contour.area) > 0.02 * contour.area:
        return [("", sol)]
    return zones



def _plancher(points, z: float) -> Face3D:
    plancher = Face3D([Point3D(x, y, z) for x, y in points])
    return plancher if plancher.normal.z > 0 else plancher.flip()


def _cote(forme, bord) -> str:
    """Le côté que regarde une bande de façade : celui vers lequel est tourné son plus long mur extérieur."""
    commun = forme.boundary.intersection(bord.buffer(0.02))
    segments = []
    for ligne in (commun.geoms if hasattr(commun, "geoms") else [commun]):
        points = list(getattr(ligne, "coords", []))
        segments.extend(zip(points, points[1:]))
    if not segments:
        return "N"
    (x1, y1), (x2, y2) = max(segments, key=lambda s: math.hypot(s[1][0] - s[0][0], s[1][1] - s[0][1]))
    nx, ny = (y2 - y1), -(x2 - x1)                      # une des 2 normales du mur
    milieu = ((x1 + x2) / 2.0, (y1 + y2) / 2.0)
    if nx * (milieu[0] - forme.centroid.x) + ny * (milieu[1] - forme.centroid.y) < 0:
        nx, ny = -nx, -ny                               # la bonne est celle qui s'éloigne de la bande
    azimut = math.degrees(math.atan2(nx, ny)) % 360.0
    return ("N", "NE", "E", "SE", "S", "SO", "O", "NO")[int(((azimut + 22.5) % 360.0) // 45.0)]



def convertir(releve: Releve, nom: str = "batiment", profondeur_facade_m=None, cloisons: bool = False) -> tuple:
    """(modèle Honeybee, compte rendu).

    `profondeur_facade_m` : None donne un seul volume par niveau ; « linteau » applique la règle européenne
    aux baies du relevé. Une profondeur en mètres (PROFONDEUR_DE_FACADE_M est
    l'usage) découpe chaque plateau assez grand en zones de façade et noyau.
    `cloisons` : faux, les zones d'un plateau communiquent par l'air ; vrai, elles sont séparées par des murs.
    """
    rendu = CompteRendu()
    if profondeur_facade_m == "linteau":
        tiree = profondeur_du_releve(releve)
        profondeur_facade_m = tiree if tiree else PROFONDEUR_DE_FACADE_M
        rendu.profondeur_de_facade = (
            f"{profondeur_facade_m} m, règle européenne du linteau (2,5 fois sa hauteur au-dessus du plan de travail)"
            if tiree else f"{profondeur_facade_m} m, valeur américaine faute de baies relevées")
    elif profondeur_facade_m:
        rendu.profondeur_de_facade = f"{profondeur_facade_m} m, donnée par l'appelant"
    angle = releve.nord_deg                 # tourner de cet angle, sens trigonométrique, amène le nord sur Y
    altitudes = [n.altitude_m for n in releve.niveaux]
    retenus = []
    for niveau in releve.niveaux:
        if not niveau.emprise_m:
            if niveau.n_baies:
                rendu.niveaux_ecartes.append(f"{niveau.nom} : pas de local, donc pas d'emprise")
            continue
        hauteur = _hauteur(niveau, altitudes)
        if niveau.plancher_m + hauteur <= 0.3:
            rendu.niveaux_ecartes.append(f"{niveau.nom} : enterré, écarté du calcul solaire")
            continue
        retenus.append((niveau, hauteur))

    # LES COMBLES. Un dernier niveau sans aucune baie n'est pas un étage de bureaux ou de logements : ce sont
    # des combles ou des locaux techniques. Le calculer comme un étage occupé, sans fenêtre pour l'aérer, en
    # fait une étuve qui n'existe pas. On le retire : l'étage du dessous reçoit le toit, ce qui est la façon
    # courante de traiter des combles perdus. La question est posée à l'utilisateur, pas tranchée en silence.
    def a_des_baies(niveau, hauteur) -> bool:
        return any(b.mur_exterieur is not False and b.inclinaison_deg > 60.0
                   and niveau.plancher_m <= (b.z_bas_m + b.z_haut_m) / 2.0 <= niveau.plancher_m + hauteur
                   for b in releve.baies)

    if releve.baies:
        while len(retenus) > 1 and not a_des_baies(*retenus[-1]):
            niveau = retenus.pop()[0]
            rendu.niveaux_ecartes.append(
                f"{niveau.nom} : aucune baie, traité comme des combles non occupés ; l'étage du dessous reçoit "
                f"le toit (à confirmer)")

    pieces = []
    for rang, (niveau, hauteur) in enumerate(retenus):
        sol = Face3D([Point3D(*_tourner(x, y, angle), niveau.plancher_m) for x, y in niveau.emprise_m])
        if sol.normal.z < 0:
            sol = sol.flip()
        base = f"{_nom(nom)}_{rang}_{_nom(niveau.nom)}"
        du_niveau = []
        for suffixe, plancher in _decouper(sol, profondeur_facade_m):
            piece = Room.from_polyface3d(f"{base}{suffixe}", Polyface3D.from_offset_face(plancher, hauteur))
            for face in piece.faces:
                if face.type.name == "Floor":
                    face.boundary_condition = boundary_conditions.ground if rang == 0 else boundary_conditions.adiabatic
                elif face.type.name == "RoofCeiling" and rang < len(retenus) - 1:
                    face.boundary_condition = boundary_conditions.adiabatic
            du_niveau.append(piece)
            cote = ("noyau" if suffixe.startswith("_noyau") else
                    "façade " + suffixe.split("_")[2] if suffixe.startswith("_facade") else "entier")
            rendu.etiquettes[piece.identifier] = (rang, niveau.nom, cote)
        if len(du_niveau) > 1:
            # Les zones d'un même plateau se touchent : leurs murs communs deviennent des limites entre zones.
            # Sans cloisons, ce sont des limites d'air : l'air et la chaleur passent, comme dans un plateau ouvert.
            du_niveau = list(Room.intersect_adjacency(du_niveau, 0.01, 1) or du_niveau)
            Room.solve_adjacency(du_niveau, 0.01)
            if not cloisons:
                for piece in du_niveau:
                    for face in piece.faces:
                        if face.type.name == "Wall" and face.boundary_condition.name == "Surface":
                            face.type = face_types.air_boundary
        if rang == 0:
            rendu.emprise_m = [(round(p.x, 3), round(p.y, 3)) for p in sol.vertices]
            rendu.z_du_sol_m = niveau.plancher_m
        pieces.extend((piece, niveau, hauteur) for piece in du_niveau)
        if not niveau.chauffe:
            rendu.non_chauffees += [piece.identifier for piece in du_niveau]
        rendu.zones += len(du_niveau)
        rendu.niveaux_repris.append(f"{niveau.nom} : {niveau.aire_emprise_m2} m², {hauteur:.2f} m de haut, "
                                    f"{len(du_niveau)} zone(s)")

    _relier_les_niveaux_non_chauffes(pieces, rendu)
    _rendre_mitoyens(releve, pieces, angle, rendu)

    numero = 0
    for baie in releve.baies:
        if baie.mur_exterieur is False:
            continue
        rendu.aire_relevee_m2 += baie.aire_m2
        if baie.inclinaison_deg <= 60.0:
            rendu.baies_ecartees.append(f"{baie.nom or baie.identifiant} : fenêtre de toit, non reprise")
            continue
        pose = _poser(baie, pieces, angle)
        if pose is None:
            rendu.baies_ecartees.append(f"{baie.nom or baie.identifiant} : aucun mur du volume ne lui correspond")
            continue
        face, rectangle, ecart = pose
        numero += 1
        face.add_aperture(Aperture(f"baie_{numero}", rectangle))
        rendu.baies_reposees += 1
        rendu.aire_reposee_m2 += rectangle.area
        rendu.ecart_azimut_max_deg = max(rendu.ecart_azimut_max_deg, ecart)
    rendu.aire_reposee_m2 = round(rendu.aire_reposee_m2, 2)
    rendu.aire_relevee_m2 = round(rendu.aire_relevee_m2, 2)
    rendu.ecart_azimut_max_deg = round(rendu.ecart_azimut_max_deg, 1)
    modele = Model(_nom(nom), rooms=[p for p, _n, _h in pieces])
    if modele.rooms and modele.check_degenerate_rooms(0.01, raise_exception=False):
        modele.remove_degenerate_geometry(0.01)
    return modele, rendu


def _relier_les_niveaux_non_chauffes(pieces, rendu: CompteRendu) -> None:
    """Le plancher entre un niveau non chauffé et ses voisins devient une paroi entre les 2 zones."""
    if not rendu.non_chauffees:
        return
    niveaux = []
    for piece, niveau, _h in pieces:
        if not niveaux or niveaux[-1][0] is not niveau:
            niveaux.append((niveau, []))
        niveaux[-1][1].append(piece)
    for (bas, du_bas), (haut, du_haut) in zip(niveaux, niveaux[1:]):
        if bas.chauffe and haut.chauffe:
            continue
        paire = du_bas + du_haut
        Room.intersect_adjacency(paire, 0.01, 1)
        for piece in paire:
            for face in piece.faces:
                # Les planchers et plafonds entre niveaux ont été mis sans échange : on les rouvre pour la paire.
                if face.type.name in ("Floor", "RoofCeiling") and face.boundary_condition.name == "Adiabatic":
                    face.boundary_condition = boundary_conditions.outdoors
        Room.solve_adjacency(paire, 0.01)
        for piece in paire:
            for face in piece.faces:
                if face.type.name in ("Floor", "RoofCeiling") and face.boundary_condition.name == "Outdoors":
                    # Ce qui ne touche pas l'autre niveau (un décroché) reste comme avant.
                    plus_bas = piece in du_bas
                    if face.type.name == "Floor" and plus_bas and bas is niveaux[0][0]:
                        face.boundary_condition = boundary_conditions.ground
                    elif not (face.type.name == "RoofCeiling" and not plus_bas and haut is niveaux[-1][0]):
                        face.boundary_condition = boundary_conditions.adiabatic


def _rendre_mitoyens(releve: Releve, pieces, angle: float, rendu: CompteRendu) -> None:
    """Les murs du volume qui suivent un mur mitoyen du relevé n'échangent plus avec le dehors."""
    if not releve.mitoyens_m:
        return
    traits = [LineString([_tourner(*a, angle), _tourner(*b, angle)]) for a, b in releve.mitoyens_m]
    for piece, _niveau, _h in pieces:
        for face in piece.faces:
            if face.type.name != "Wall" or face.boundary_condition.name != "Outdoors":
                continue
            bas = min(v.z for v in face.geometry.vertices)
            pied = [(v.x, v.y) for v in face.geometry.vertices if abs(v.z - bas) < 1e-6]
            if len(pied) != 2:
                continue
            mur = LineString(pied)
            if mur.length < 1e-6:
                continue
            for trait in traits:
                if mur.buffer(TOLERANCE_MITOYENNE_M).intersection(trait).length >= PART_MITOYENNE_MIN * mur.length:
                    face.boundary_condition = boundary_conditions.adiabatic
                    rendu.murs_mitoyens += 1
                    rendu.aire_mitoyenne_m2 = round(rendu.aire_mitoyenne_m2 + face.area, 2)
                    break


def _poser(baie: Baie, pieces, angle: float):
    """Le mur qui porte la baie et son rectangle dans le plan de ce mur, ou None."""
    cx, cy = _tourner(baie.centre_m[0], baie.centre_m[1], angle)
    nx, ny = _tourner(baie.normale_xy[0], baie.normale_xy[1], angle)
    norme = math.hypot(nx, ny)
    nx, ny = nx / norme, ny / norme
    z_milieu = (baie.z_bas_m + baie.z_haut_m) / 2.0
    meilleur = None
    for piece, niveau, hauteur in pieces:
        if not (niveau.plancher_m <= z_milieu <= niveau.plancher_m + hauteur):
            continue
        for face in piece.faces:
            if face.type.name != "Wall" or face.boundary_condition.name != "Outdoors":
                continue
            m = face.normal
            if m.x * nx + m.y * ny < ACCORD_DES_NORMALES_MIN:
                continue
            p0 = face.geometry.vertices[0]
            distance = (cx - p0.x) * m.x + (cy - p0.y) * m.y
            if abs(distance) > ECART_AU_MUR_MAX_M:
                continue
            ux, uy = -m.y, m.x                               # le long du mur, vu de dehors : de gauche à droite
            le_long = [v.x * ux + v.y * uy for v in face.geometry.vertices]
            hauts = [v.z for v in face.geometry.vertices]
            s = cx * ux + cy * uy
            gauche = max(s - baie.largeur_m / 2.0, min(le_long) + MARGE_M)
            droite = min(s + baie.largeur_m / 2.0, max(le_long) - MARGE_M)
            bas = max(baie.z_bas_m, min(hauts) + MARGE_M)
            haut = min(baie.z_haut_m, max(hauts) - MARGE_M)
            if droite - gauche < 0.2 or haut - bas < 0.2:
                continue
            if meilleur is None or abs(distance) < meilleur[0]:
                # Un point du plan du mur : p0 ; on s'y déplace le long de u.
                base = p0.x * m.x + p0.y * m.y

                def point(t, z, _m=m, _base=base, _ux=ux, _uy=uy):
                    return Point3D(_base * _m.x + t * _ux, _base * _m.y + t * _uy, z)
                rectangle = Face3D([point(gauche, bas), point(droite, bas), point(droite, haut), point(gauche, haut)])
                ecart = abs((face.azimuth - (baie.azimut_deg or 0.0) + 180.0) % 360.0 - 180.0)
                meilleur = (abs(distance), face, rectangle, ecart)
    if meilleur is None:
        return None
    return meilleur[1], meilleur[2], meilleur[3]
