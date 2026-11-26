"""Le relevé d'un bâtiment décrit par quelques chiffres, sans maquette ni plan.

Au début d'un projet il n'y a pas encore de maquette : il y a une emprise, un nombre de niveaux et une idée du
vitrage de chaque façade. C'est aussi ce que sait donner un autre logiciel qui ne connaît le bâtiment que par
ses grandeurs. Ce module en fait le même relevé que la lecture d'une maquette IFC ou d'un plan DXF, et toute
la suite de la chaîne s'en sert de la même façon.

LE BÂTIMENT EST UN PAVÉ. Son plan est un rectangle de `longueur_m` par `largeur_m`, répété sur `niveaux`
niveaux. La façade « avant » est un des 2 grands côtés ; `azimut_avant_deg` dit vers où elle regarde (180 :
plein sud). Les 3 autres en découlent.

LE VITRAGE SE DONNE PAR ORIENTATION, en mètres carrés pour tout le bâtiment : `{"S": 60, "N": 30}`. Il est
réparti également entre les niveaux, en baies de `largeur_de_baie_m` environ, régulièrement espacées. Quand
la façade est trop courte pour les loger, elles deviennent un bandeau ; quand le bandeau lui-même ne suffit
pas, l'aire est plafonnée et le relevé le dit dans ses manques.

UN NIVEAU PEUT NE PAS ÊTRE CHAUFFÉ (`niveaux_non_chauffes = [0]` : un atelier sous des bureaux), et UNE
FAÇADE PEUT ÊTRE MITOYENNE (`mitoyennes = ["E"]`) : elle touche un voisin et n'échange pas avec le dehors.

Ce qu'un pavé ne dit pas reste à demander : les décrochés du plan, les étages différents les uns des autres,
la position de chaque baie. Le relevé l'écrit, pour que le résultat ne soit pas lu comme celui d'une maquette.
"""

from __future__ import annotations

import math
from typing import Dict, Optional, Sequence, Tuple

from rayflect.io.releve import Baie, Niveau, Releve, SECTEURS, _azimut, secteur

MARGE_M = 0.10                  # entre 2 baies, et entre une baie et le bord de sa façade
HAUTEUR_SOUS_PLAFOND_MIN_M = 0.10


class ChiffresInvalides(ValueError):
    """Les chiffres ne décrivent pas un bâtiment : le message dit lequel corriger."""


def _positif(nom: str, valeur) -> float:
    if isinstance(valeur, bool) or not isinstance(valeur, (int, float)) or valeur <= 0:
        raise ChiffresInvalides(f"{nom} : {valeur!r} n'est pas une grandeur positive")
    return float(valeur)


def repartir(aire_m2: float, etendue_m: float, hauteur_d_etage_m: float, allege_m: float = 1.0,
             hauteur_de_baie_m: float = 1.4, largeur_de_baie_m: float = 1.5) -> Tuple[int, float, float, float, bool]:
    """Comment loger `aire_m2` de vitrage sur une façade de `etendue_m`, à un niveau.

    Rend (nombre de baies, largeur, hauteur, allège, vrai si l'aire a dû être plafonnée). Des baies de
    `largeur_de_baie_m` environ, régulièrement espacées ; un bandeau sur toute la façade quand elles ne tiennent
    pas côte à côte, plus haut s'il le faut ; l'aire plafonnée quand le bandeau lui-même ne suffit pas.
    """
    haut, allege = hauteur_de_baie_m, float(allege_m)
    nombre = max(1, math.ceil(aire_m2 / (largeur_de_baie_m * haut)))
    large = aire_m2 / (nombre * haut)
    plafonnee = False
    if nombre * large + (nombre + 1) * MARGE_M > etendue_m:
        nombre, large = 1, etendue_m - 2 * MARGE_M
        haut = aire_m2 / large
        libre = hauteur_d_etage_m - HAUTEUR_SOUS_PLAFOND_MIN_M
        if allege + haut > libre:
            allege = max(MARGE_M, libre - haut)
        if allege + haut > libre:
            haut = libre - allege
            plafonnee = True
    return nombre, large, haut, allege, plafonnee


def lire(longueur_m: float, largeur_m: float, niveaux: int = 1, hauteur_d_etage_m: float = 3.0,
         azimut_avant_deg: float = 180.0, vitrage_m2: Optional[Dict[str, float]] = None,
         allege_m: float = 1.0, hauteur_de_baie_m: float = 1.4, largeur_de_baie_m: float = 1.5,
         latitude: Optional[float] = None, longitude: Optional[float] = None, nom: str = "bâtiment",
         niveaux_non_chauffes: Sequence[int] = (), mitoyennes: Sequence[str] = ()) -> Releve:
    """Le relevé d'un pavé. Lève `ChiffresInvalides` quand un chiffre ne peut pas être celui d'un bâtiment."""
    longueur, largeur = _positif("longueur_m", longueur_m), _positif("largeur_m", largeur_m)
    hauteur = _positif("hauteur_d_etage_m", hauteur_d_etage_m)
    haut_de_baie, large_de_baie = _positif("hauteur_de_baie_m", hauteur_de_baie_m), _positif(
        "largeur_de_baie_m", largeur_de_baie_m)
    if isinstance(niveaux, bool) or not isinstance(niveaux, int) or niveaux < 1:
        raise ChiffresInvalides(f"niveaux : {niveaux!r} n'est pas un nombre entier de niveaux")
    if isinstance(allege_m, bool) or not isinstance(allege_m, (int, float)) or allege_m < 0:
        raise ChiffresInvalides(f"allege_m : {allege_m!r} n'est pas une hauteur d'allège")
    vitrage = dict(vitrage_m2 or {})
    inconnues = [c for c in vitrage if c not in SECTEURS]
    if inconnues:
        raise ChiffresInvalides(f"vitrage_m2 : orientation inconnue {', '.join(inconnues)}. "
                                f"Connues : {', '.join(SECTEURS)}")
    for cote, aire in vitrage.items():
        if isinstance(aire, bool) or not isinstance(aire, (int, float)) or aire < 0:
            raise ChiffresInvalides(f"vitrage_m2.{cote} : {aire!r} n'est pas une aire")

    # Le plan : un rectangle posé sur les axes, l'avant le long de y = 0. Le nord est tourné pour que l'avant
    # regarde vers `azimut_avant_deg`.
    nord_deg = (180.0 - float(azimut_avant_deg)) % 360.0
    nord = (math.sin(math.radians(nord_deg)), math.cos(math.radians(nord_deg)))
    cotes = [
        ("avant", (0.0, -1.0), longueur, lambda t: (t, 0.0)),
        ("droite", (1.0, 0.0), largeur, lambda t: (longueur, t)),
        ("arriere", (0.0, 1.0), longueur, lambda t: (longueur - t, largeur)),
        ("gauche", (-1.0, 0.0), largeur, lambda t: (0.0, largeur - t)),
    ]
    regards = {nom_cote: secteur(_azimut(normale, nord)) for nom_cote, normale, _l, _p in cotes}
    manques = [
        "bâtiment décrit par ses chiffres : plan rectangulaire, niveaux identiques, baies réparties "
        "régulièrement ; à remplacer par une maquette ou un plan dès qu'il y en a un",
    ]
    sans_facade = sorted(set(vitrage) - set(regards.values()))
    if sans_facade:
        raise ChiffresInvalides(
            f"vitrage_m2 : aucune façade ne regarde vers {', '.join(sans_facade)}. Avec azimut_avant_deg = "
            f"{azimut_avant_deg:g}, les façades regardent vers {', '.join(regards[c] for c, *_r in cotes)}")
    if latitude is None or longitude is None:
        manques.append("position du site absente : adresse à demander")
    if isinstance(niveaux_non_chauffes, (str, bytes)) or any(
            isinstance(r, bool) or not isinstance(r, int) or not 0 <= r < niveaux for r in niveaux_non_chauffes):
        raise ChiffresInvalides(f"niveaux_non_chauffes : des rangs de niveau, de 0 à {niveaux - 1}")
    if isinstance(mitoyennes, (str, bytes)):
        raise ChiffresInvalides("mitoyennes : une liste d'orientations, par exemple [\"E\"]")
    inconnues = sorted(set(mitoyennes) - set(regards.values()))
    if inconnues:
        raise ChiffresInvalides(f"mitoyennes : aucune façade ne regarde vers {', '.join(inconnues)}. Les façades "
                                f"regardent vers {', '.join(regards[c] for c, *_r in cotes)}")
    vitrees = sorted(set(mitoyennes) & {c for c, aire in vitrage.items() if aire > 0})
    if vitrees:
        raise ChiffresInvalides(f"la façade {', '.join(vitrees)} est mitoyenne : elle ne porte pas de vitrage")
    mitoyens = [(point(0.0), point(etendue)) for nom_cote, _n, etendue, point in cotes
                if regards[nom_cote] in mitoyennes]

    etages, baies = [], []
    for rang in range(niveaux):
        plancher = rang * hauteur
        nom_du_niveau = f"niveau {rang}"
        du_niveau = 0
        for nom_cote, normale, etendue, point in cotes:
            aire = float(vitrage.get(regards[nom_cote], 0.0)) / niveaux
            if aire <= 0:
                continue
            nombre, large, haut, allege, plafonnee = repartir(aire, etendue, hauteur, allege_m, haut_de_baie,
                                                              large_de_baie)
            if plafonnee and rang == 0:
                manques.append(
                    f"façade {regards[nom_cote]} : {vitrage[regards[nom_cote]]:g} m² de vitrage demandés, "
                    f"{large * haut * niveaux:.1f} m² au plus sur cette façade ; l'aire est plafonnée")
            pas = etendue / nombre
            z_bas = plancher + allege
            azimut = _azimut(normale, nord)
            for k in range(nombre):
                x, y = point((k + 0.5) * pas)
                baies.append(Baie(
                    identifiant=f"baie_{rang}_{nom_cote}_{k}", nom=f"baie {regards[nom_cote]} {k + 1}",
                    niveau=nom_du_niveau, largeur_m=round(large, 3), hauteur_m=round(haut, 3),
                    aire_m2=round(large * haut, 3), allege_m=round(allege, 3), azimut_deg=round(azimut, 1),
                    secteur=regards[nom_cote], inclinaison_deg=90.0, centre_m=(x, y, z_bas + haut / 2.0),
                    normale_xy=normale, z_bas_m=z_bas, z_haut_m=z_bas + haut, mur=None, mur_exterieur=True,
                    taille_declaree_m=None))
                du_niveau += 1
        etages.append(Niveau(
            nom=nom_du_niveau, altitude_m=plancher, n_baies=du_niveau, aire_espaces_m2=round(longueur * largeur, 2),
            emprise_m=[(0.0, 0.0), (longueur, 0.0), (longueur, largeur), (0.0, largeur)], plancher_m=plancher,
            plafond_m=plancher + hauteur, aire_emprise_m2=round(longueur * largeur, 2),
            chauffe=rang not in niveaux_non_chauffes))
    return Releve(fichier=nom, schema="chiffres", logiciel="rayflect", latitude=latitude, longitude=longitude,
                  altitude_m=None, nord_deg=nord_deg, niveaux=etages, baies=baies, n_murs=4 * niveaux,
                  n_murs_exterieurs=(4 - len(mitoyens)) * niveaux, n_espaces=niveaux, manques=manques,
                  mitoyens_m=mitoyens)
