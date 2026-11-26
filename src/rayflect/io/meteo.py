"""La météo d'un lieu : la prendre à PVGIS, la contrôler avant tout calcul, la réparer quand c'est possible.

POURQUOI UN CONTRÔLE. Un fichier météo faux donne un résultat faux sans prévenir. Mesuré le 15/11/2026 : sur
7 années types demandées à PVGIS, celle du port de Marseille portait un rayonnement du ciel de 13 W/m² en
moyenne au lieu d'environ 320. Pour le calcul, c'est un ciel à −189 °C : le bâtiment y perdait une chaleur
absurde, et un panneau posé au-dessus du toit paraissait économiser 22 % de chauffage.

CE QU'UNE ANNÉE TYPE N'EST PAS. PVGIS assemble 12 mois pris dans des années différentes, choisis pour être
représentatifs du soleil. Rien ne garantit que les températures d'été le soient : à Lille, le mois de juillet
retenu est celui de 2011, plus froid que le mois de juin retenu (15,8 °C contre 19,3). Près de la mer, les
maximums d'été sont de plus écrêtés. Une année type convient pour comparer des protections entre elles ;
elle ne convient pas pour dire combien d'heures un bâtiment surchauffera lors d'un été chaud.
"""

from __future__ import annotations

import math
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import List

SIGMA = 5.670374e-8
LIGNES_D_EN_TETE = 8
COLONNE_TEMPERATURE, COLONNE_ROSEE, COLONNE_HUMIDITE = 6, 7, 8
COLONNE_CIEL, COLONNE_SOLEIL = 12, 13
CIEL_MINIMAL_W_M2 = 100.0           # un ciel terrestre rayonne toujours plus : 100 W/m² correspond à −68 °C
ECART_AIR_CIEL_MAXIMAL_K = 35.0     # en moyenne annuelle ; les fichiers sains lus donnent 11 à 13 K
CLARTE_D_UN_JOUR_SANS_NUAGE = 0.72  # [H] part du soleil hors atmosphère qui arrive au sol un jour clair


@dataclass
class Controle:
    defauts: List[str] = field(default_factory=list)        # ce qui fausse le calcul
    remarques: List[str] = field(default_factory=list)      # ce qu'il faut savoir pour lire le résultat

    @property
    def bon(self) -> bool:
        return not self.defauts


def telecharger_pvgis(latitude: float, longitude: float, dossier, delai_s: float = 120.0) -> Path:
    """L'année type de PVGIS pour ce point, au format EPW. Gardée dans `dossier` pour ne pas la redemander."""
    dossier = Path(dossier)
    dossier.mkdir(parents=True, exist_ok=True)
    chemin = dossier / f"pvgis_{latitude:.3f}_{longitude:.3f}.epw"
    if not chemin.exists():
        url = f"https://re.jrc.ec.europa.eu/api/v5_2/tmy?lat={latitude:.4f}&lon={longitude:.4f}&outputformat=epw"
        with urllib.request.urlopen(url, timeout=delai_s) as reponse:
            chemin.write_bytes(reponse.read())
    return chemin


def _donnees(chemin) -> List[List[str]]:
    lignes = Path(chemin).read_text(encoding="utf-8", errors="replace").splitlines()
    return [ligne.split(",") for ligne in lignes[LIGNES_D_EN_TETE:] if ligne.strip()]


def controler(chemin) -> Controle:
    """Ce qui ne va pas dans un fichier météo, et ce qu'il faut savoir pour lire un résultat qui en sort."""
    rendu = Controle()
    donnees = _donnees(chemin)
    if len(donnees) != 8760:
        rendu.defauts.append(f"{len(donnees)} heures au lieu de 8 760")
        return rendu
    temperature = [float(d[COLONNE_TEMPERATURE]) for d in donnees]
    ciel = [float(d[COLONNE_CIEL]) for d in donnees]
    soleil = [float(d[COLONNE_SOLEIL]) for d in donnees]
    if min(temperature) < -60.0 or max(temperature) > 60.0:
        rendu.defauts.append(f"températures hors du possible : de {min(temperature):g} à {max(temperature):g} °C")
    if sum(soleil) <= 0:
        rendu.defauts.append("aucun soleil dans le fichier")
    froides = sum(1 for v in ciel if v < CIEL_MINIMAL_W_M2)
    ecart = sum(t - ((max(v, 1.0) / SIGMA) ** 0.25 - 273.15) for t, v in zip(temperature, ciel)) / 8760.0
    if froides or ecart > ECART_AIR_CIEL_MAXIMAL_K:
        rendu.defauts.append(
            f"rayonnement du ciel faux : {sum(ciel) / 8760.0:.0f} W/m² en moyenne, {froides} heures sous "
            f"{CIEL_MINIMAL_W_M2:g} W/m², soit un ciel {ecart:.0f} K plus froid que l'air en moyenne")

    annees = sorted({d[0] for d in donnees})
    if len(annees) > 1:
        rendu.remarques.append(
            f"année type : 12 mois pris dans {len(annees)} années différentes ({annees[0]} à {annees[-1]}), "
            f"choisis pour le soleil ; à ne pas lire comme un été chaud")
    jours_avant = (0, 31, 59, 90, 120, 151, 181, 212, 243, 273, 304, 334, 365)
    moyennes = [sum(temperature[jours_avant[m] * 24:jours_avant[m + 1] * 24]) / ((jours_avant[m + 1] - jours_avant[m]) * 24)
                for m in range(12)]
    if moyennes[6] < moyennes[5] - 1.0 and moyennes[7] < moyennes[5]:
        rendu.remarques.append(
            f"l'été du fichier est atypique : juillet à {moyennes[6]:.1f} °C et août à {moyennes[7]:.1f} °C, "
            f"plus froids que juin à {moyennes[5]:.1f} °C")
    return rendu


def _rosee(temperature_c: float, humidite_pc: float) -> float:
    """La température de rosée, par la formule de Magnus."""
    humidite = min(100.0, max(1.0, humidite_pc))
    a, b = 17.62, 243.12
    gamma = math.log(humidite / 100.0) + a * temperature_c / (b + temperature_c)
    return b * gamma / (a - gamma)


def reparer_le_ciel(chemin, sortie=None) -> Path:
    """Recalcule le rayonnement du ciel d'un fichier dont la colonne est fausse. Rend le fichier réparé.

    Méthode : émissivité d'un ciel clair d'après la température de rosée (Clark et Allen, 1978, la formule
    qu'EnergyPlus emploie quand la colonne manque), corrigée de la nébulosité. La nébulosité du jour est
    tirée de sa clarté : la part du soleil hors atmosphère arrivée au sol. La rosée est recalculée depuis
    l'humidité, la colonne de rosée d'un fichier défectueux n'étant pas sûre non plus.

    Confrontée à 6 fichiers sains de PVGIS (France et Allemagne) : la moyenne annuelle retrouvée s'écarte de
    −2,5 à +13 W/m² de la vraie, soit 4 % au plus, avec un écart type horaire d'environ 20 W/m².
    """
    from ladybug.epw import EPW
    from ladybug.sunpath import Sunpath

    chemin = Path(chemin)
    sortie = Path(sortie) if sortie else chemin.with_name(chemin.stem + "_ciel_repare.epw")
    lignes = chemin.read_text(encoding="utf-8", errors="replace").splitlines()
    course = Sunpath.from_location(EPW(str(chemin)).location)
    hors_atmosphere = [max(0.0, 1361.0 * math.sin(math.radians(course.calculate_sun_from_hoy(h + 0.5).altitude)))
                       for h in range(8760)]
    donnees = [ligne.split(",") for ligne in lignes[LIGNES_D_EN_TETE:LIGNES_D_EN_TETE + 8760]]
    for jour in range(365):
        heures = range(jour * 24, jour * 24 + 24)
        recu = sum(float(donnees[h][COLONNE_SOLEIL]) for h in heures)
        possible = sum(hors_atmosphere[h] for h in heures)
        clarte = recu / possible if possible > 0 else 0.4
        nebulosite = max(0.0, min(10.0, 10.0 * (1.0 - clarte / CLARTE_D_UN_JOUR_SANS_NUAGE)))    # en dixièmes
        nuages = 1.0 + 0.0224 * nebulosite - 0.0035 * nebulosite ** 2 + 0.00028 * nebulosite ** 3
        for h in heures:
            temperature = float(donnees[h][COLONNE_TEMPERATURE])
            rosee = _rosee(temperature, float(donnees[h][COLONNE_HUMIDITE]))
            emissivite = min(1.0, (0.787 + 0.764 * math.log(max(rosee + 273.15, 200.0) / 273.0)) * nuages)
            donnees[h][COLONNE_CIEL] = f"{emissivite * SIGMA * (temperature + 273.15) ** 4:.2f}"
            donnees[h][COLONNE_ROSEE] = f"{rosee:.2f}"
    sortie.write_text("\n".join(lignes[:LIGNES_D_EN_TETE] + [",".join(d) for d in donnees]) + "\n", encoding="utf-8")
    return sortie


def preparer(latitude: float, longitude: float, dossier) -> tuple:
    """(fichier météo prêt pour le calcul, contrôle). Répare le ciel s'il est faux, et le dit."""
    chemin = telecharger_pvgis(latitude, longitude, dossier)
    controle = controler(chemin)
    if any("rayonnement du ciel" in d for d in controle.defauts):
        repare = reparer_le_ciel(chemin)
        apres = controler(repare)
        apres.remarques.insert(0, "le rayonnement du ciel du fichier d'origine était faux : il a été recalculé "
                                  "depuis l'humidité et la clarté du jour")
        return repare, apres
    return chemin, controle
