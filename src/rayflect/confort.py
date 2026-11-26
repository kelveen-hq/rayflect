"""Le confort d'été comme la RE2020 le juge : les degrés-heures d'inconfort (DH), sur la température de confort adaptatif.

Les heures au-dessus de 26 °C comptent un seuil fixe. La RE2020 juge autrement : l'occupant s'habitue à la chaleur des
jours passés, et le seuil monte avec elle, de 26 à 28 °C. Ce module refait ce calcul, pièce par pièce, sur la
température ressentie que rend le moteur [S : méthode Th-BCE 2020, annexe III de l'arrêté du 4 août 2021, fiche
C_BAT_Confort_d'été §13.5, p. 1396 à 1403, et fiche climat extérieur §3.1.3, p. 32 et 33] :

  LA MOYENNE GLISSANTE du dehors, au jour j : θrm(j) = 0,8 × θrm(j − 1) + 0,2 × (moyenne des 24 heures du jour j − 1),
  partie de 0 le premier jour (formule 1).

  LA PÉRIODE DE CONFORT ADAPTATIF va du premier au dernier jour de l'année où θrm atteint 16 °C (formule 2). Le DH ne se
  compte que dans cette période.

  LE SEUIL D'INCONFORT, à chaque heure : 0,33 × θrm + 18,8 + 2 (catégorie d'ambiance 1, tous usages, d'après la norme
  NF EN 16798-1), jamais sous la consigne de refroidissement ni plus de 2 °C au-dessus (formules 2543 à 2545). Avec la
  consigne de 26 °C, il va de 26 à 28 °C.

  LA NUIT EN LOGEMENT, de 22 h à 6 h, le seuil est la consigne elle-même, sans confort adaptatif : en dormant, on
  échange moins de chaleur avec l'air (formule 2544).

  LE DH est la somme, sur les heures occupées de la période, de ce qui dépasse le seuil (formule 2551). La méthode
  compte aussi les heures au-dessus du seuil, du seuil + 1 °C et du seuil + 2 °C (formules 2548 à 2550).

LE SEUIL BAS est de 350 °C.h : au-dessus, la RE2020 ajoute au bâtiment une consommation de froid forfaitaire. Le seuil
haut, DHmax, est la limite réglementaire ; il est modulé selon le projet [S : Agence Qualité Construction, fiche
qualité réglementaire C5, confort d'été, janvier 2023]. Sa valeur n'est pas reprise ici.

CE N'EST PAS LE DH RÉGLEMENTAIRE. La RE2020 le calcule sur son année météo conventionnelle, avec une canicule en août,
sur ses propres scénarios, et bâtiment non climatisé. Rayflect le calcule sur la météo et les hypothèses de l'étude :
c'est un ordre de grandeur pour comparer des choix, pas une attestation. Une étude climatisée n'a pas de DH : la
climatisation tient la température, et la RE2020 la retire pour le calcul.
"""

from __future__ import annotations

from typing import Dict, List, Optional, Sequence, Tuple

HEURES_PAR_JOUR = 24
SEUIL_DE_PERIODE_C = 16.0           # [S] Th-BCE §3.1.3, formule 2
PART_DU_JOUR_PASSE = 0.2            # [S] Th-BCE §3.1.3, formule 1
PENTE = 0.33                        # [S] Th-BCE formule 2543, d'après NF EN 16798-1
ORDONNEE_C = 18.8                   # [S] idem
ECART_CATEGORIE_1_K = 2.0           # [S] Th-BCE tableau 339 et 340 : catégorie d'ambiance 1 pour tous les usages
ECART_MAXIMAL_K = 2.0               # [S] Th-BCE tableau 339, Δθop_min_max
NUIT = (22, 6)                      # [S] Th-BCE formule 2544 : sommeil hors de 6 < heure légale ≤ 22
SEUIL_BAS_DH = 350                  # [S] AQC, fiche C5, 2023 : au-dessus, une consommation de froid forfaitaire


def moyennes_glissantes(dehors: Sequence[float]) -> List[float]:
    """θrm(j) pour chaque jour de l'année, depuis les températures horaires du dehors."""
    jours = len(dehors) // HEURES_PAR_JOUR
    rm = [0.0]                      # [S] le premier jour part de 0
    for j in range(1, jours):
        veille = dehors[(j - 1) * HEURES_PAR_JOUR:j * HEURES_PAR_JOUR]
        rm.append((1 - PART_DU_JOUR_PASSE) * rm[-1] + PART_DU_JOUR_PASSE * sum(veille) / HEURES_PAR_JOUR)
    return rm


def periode(rm: Sequence[float]) -> Optional[Tuple[int, int]]:
    """Le premier et le dernier jour (à partir de 0) de la période de confort adaptatif, ou None si l'été n'y arrive pas."""
    chauds = [j for j, t in enumerate(rm) if t >= SEUIL_DE_PERIODE_C]
    return (chauds[0], chauds[-1]) if chauds else None


def est_la_nuit(heure: int) -> bool:
    """`heure` de 0 à 23 au début de l'heure ; l'heure légale de la méthode va de 1 à 24 à sa fin."""
    legale = heure + 1
    return not (NUIT[1] < legale <= NUIT[0])


def seuils(dehors: Sequence[float], froid_c: float, habitation: bool) -> List[Optional[float]]:
    """Le seuil d'inconfort de chaque heure de l'année, None hors de la période de confort adaptatif."""
    rm = moyennes_glissantes(dehors)
    bornes = periode(rm)
    rendu: List[Optional[float]] = []
    for h in range(len(rm) * HEURES_PAR_JOUR):
        j = h // HEURES_PAR_JOUR
        if bornes is None or not bornes[0] <= j <= bornes[1]:
            rendu.append(None)
        elif habitation and est_la_nuit(h % HEURES_PAR_JOUR):
            rendu.append(froid_c)
        else:
            adaptatif = max(froid_c, PENTE * rm[j] + ORDONNEE_C + ECART_CATEGORIE_1_K)
            rendu.append(min(froid_c + ECART_MAXIMAL_K, adaptatif))
    return rendu


def indicateurs(ressentie: Sequence[float], seuils_: Sequence[Optional[float]], occupe: Sequence[bool],
                habitation: bool) -> Dict[str, Optional[int]]:
    """Le DH d'une pièce et ses compagnons, sur les heures occupées de la période de confort adaptatif."""
    dh = dh_nuit = 0.0
    heures = [0, 0, 0]
    for h, (t, seuil, present) in enumerate(zip(ressentie, seuils_, occupe)):
        if seuil is None or not present:
            continue
        depasse = t - seuil
        if depasse > 0:
            dh += depasse
            if habitation and est_la_nuit(h % HEURES_PAR_JOUR):
                dh_nuit += depasse
        for k in range(3):
            if depasse >= k:        # la méthode compte le seuil atteint, à 0, 1 et 2 °C près
                heures[k] += 1
    return {"dh": round(dh), "heures": heures[0], "heures_plus_1": heures[1], "heures_plus_2": heures[2],
            "dh_nuit": round(dh_nuit) if habitation else None}


def dire_la_periode(bornes: Optional[Tuple[int, int]]) -> str:
    if bornes is None:
        return "période de confort adaptatif : aucune, la moyenne glissante du dehors n'atteint jamais 16 °C"
    return f"période de confort adaptatif : du jour {bornes[0] + 1} au jour {bornes[1] + 1} de l'année ({_date(bornes[0])} " \
           f"au {_date(bornes[1])}), quand la moyenne glissante du dehors dépasse 16 °C"


_MOIS = ((31, "janvier"), (28, "février"), (31, "mars"), (30, "avril"), (31, "mai"), (30, "juin"), (31, "juillet"),
         (31, "août"), (30, "septembre"), (31, "octobre"), (30, "novembre"), (31, "décembre"))


def _date(jour: int) -> str:
    for longueur, nom in _MOIS:
        if jour < longueur:
            return f"{jour + 1} {nom}"
        jour -= longueur
    return "31 décembre"


def expliquer(bornes: Optional[Tuple[int, int]], froid_c: float, habitation: bool, climatisation: bool) -> List[str]:
    """Ce que le compte rendu dit du calcul, avant les chiffres."""
    lignes = [dire_la_periode(bornes),
              f"seuil d'inconfort : 0,33 × moyenne glissante + 20,8 °C, de {froid_c:g} à {froid_c + ECART_MAXIMAL_K:g} °C"
              + (f" le jour, {froid_c:g} °C de 22 h à 6 h" if habitation else "") + " [S] Th-BCE 2020, §13.5",
              f"seuil bas de la RE2020 : {SEUIL_BAS_DH} °C.h ; le seuil haut (DHmax) dépend du projet et n'est pas repris",
              "ordre de grandeur sur la météo et les hypothèses de l'étude, pas le DH réglementaire : la RE2020 le calcule "
              "sur son année conventionnelle avec une canicule en août"]
    if climatisation:
        lignes.append("étude climatisée : pas de DH, la climatisation tient la température ; le jouer avec "
                      "climatisation = false, comme la RE2020")
    return lignes
