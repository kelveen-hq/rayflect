"""La ventilation mécanique, vue comme un produit qu'on choisit : simple flux, double flux, surventilation.

Les hypothèses d'usage (`rayflect.hypotheses`) posent déjà l'air neuf réglementaire dans chaque pièce
occupée, noyau compris : c'est une ventilation simple flux. Ce module y ajoute 2 leviers, que le moteur de
calcul sait traiter :

  LA RÉCUPÉRATION DE CHALEUR (double flux) : l'air neuf est réchauffé par l'air extrait. Elle baisse le
  chauffage. Elle ne joue que quand elle réduit un besoin : l'été, sans climatisation, l'échangeur est
  contourné de lui-même.

  LA SURVENTILATION : un débit d'air en plus, bien supérieur à l'air neuf, quand il fait plus frais dehors
  que dedans et que la pièce est chaude. Faite la nuit, elle décharge la chaleur accumulée dans les murs.
  C'est le seul moyen de rafraîchir un noyau sans fenêtre, hors climatisation.

L'AIR NEUF D'UNE SIMPLE FLUX ENTRE TEL QU'IL EST DEHORS. Le système idéal d'EnergyPlus, lui, souffle l'air
neuf à la température de la pièce dès qu'il n'a ni à chauffer ni à refroidir : l'air frais d'une nuit d'été ou
d'un matin de mi-saison ne rafraîchit alors rien. Sur un immeuble de bureaux climatisé à Bordeaux, cela
gonflait le besoin de froid de 12 % (mesuré en rejouant le même bâtiment des 2 façons). `poser` sort donc
l'air neuf du système et le fait entrer directement dans la pièce, sauf en double flux, où il passe par
l'échangeur du système.

Chaque valeur porte son origine : [S] lue dans une source, [R] résumé non relu, [H] hypothèse.
La consommation des ventilateurs n'est pas comptée.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Tuple

from honeybee_energy.schedule.day import ScheduleDay
from honeybee_energy.schedule.ruleset import ScheduleRuleset
from honeybee_energy.ventcool.control import VentilationControl
from honeybee_energy.ventcool.fan import VentilationFan
import honeybee_energy.lib.scheduletypelimits as limites


@dataclass(frozen=True)
class VMC:
    nom: str
    recuperation: float = 0.0                   # part de la chaleur de l'air extrait rendue à l'air neuf
    surventilation_vol_h: float = 0.0           # débit de rafraîchissement, en volumes de la pièce par heure
    heures_de_surventilation: Tuple[int, int] = (22, 6)     # [S] de 22 h à 6 h ; (0, 24) : à toute heure
    seuil_interieur_c: float = 23.0             # [S] ne surventile que si la pièce dépasse cette température...
    exterieur_minimal_c: float = 12.0           # [S] ...qu'il fait au moins cette température dehors...
    ecart_minimal_k: float = 2.0                # [S] ...et au moins cet écart de fraîcheur dehors

    def __post_init__(self) -> None:
        if not 0.0 <= self.recuperation < 1.0:
            raise ValueError("le rendement de récupération est une part, entre 0 et 1")
        if self.surventilation_vol_h < 0:
            raise ValueError("le débit de surventilation ne peut pas être négatif")

    def justification(self) -> str:
        morceaux = [self.nom]
        if self.recuperation:
            morceaux.append(f"échangeur à {100 * self.recuperation:.0f} %")
        if self.surventilation_vol_h:
            debut, fin = self.heures_de_surventilation
            quand = "à toute heure" if (debut, fin) == (0, 24) else f"de {debut} h à {fin} h"
            morceaux.append(
                f"surventilation de {self.surventilation_vol_h:g} vol/h {quand}, au-dessus de "
                f"{self.seuil_interieur_c:g} °C dedans s'il fait au moins {self.ecart_minimal_k:g} K de moins dehors")
        return " ; ".join(morceaux)


@dataclass(frozen=True)
class Mecanique:
    """La ventilation mécanique d'un scénario : elle remplace, pour lui, celle de l'étude (`[ventilation]`)."""
    double_flux: bool = False
    recuperation: Optional[float] = None                # None : RENDEMENT_DOUBLE_FLUX si double flux
    surventilation_vol_h: float = 0.0                   # 0 : pas de surventilation
    heures_de_surventilation: Tuple[int, int] = (22, 6)
    seuil_interieur_c: float = 23.0
    exterieur_minimal_c: float = 12.0
    ecart_minimal_k: float = 2.0

    def __post_init__(self) -> None:
        if self.recuperation is not None and not self.double_flux:
            raise ValueError("recuperation ne vaut que pour un double flux : ajouter double_flux = true")
        heures = tuple(self.heures_de_surventilation)
        if len(heures) != 2 or any(isinstance(h, bool) or not isinstance(h, int) or not 0 <= h <= 24
                                   for h in heures) or heures[0] == heures[1]:
            raise ValueError("heures_de_surventilation : 2 heures entières de 0 à 24, par exemple [22, 6]")
        self.vmc()                                      # refuse un rendement ou un débit impossible

    def vmc(self) -> "VMC":
        rendement = 0.0
        if self.double_flux:
            rendement = RENDEMENT_DOUBLE_FLUX if self.recuperation is None else self.recuperation
        nom = ("double flux" if self.double_flux else "simple flux") + (
            ", surventilation" if self.surventilation_vol_h else "")
        return VMC(nom, rendement, self.surventilation_vol_h, tuple(self.heures_de_surventilation),
                   self.seuil_interieur_c, self.exterieur_minimal_c, self.ecart_minimal_k)


# L'efficacité thermique d'un échangeur [S : règlement (UE) n° 1253/2014, annexe III] : au moins 73 % pour une
# unité double flux non résidentielle depuis le 1er janvier 2018 (67 % de 2016 à 2018 ; 68 % pour les
# systèmes à fluide caloporteur). C'est un minimum mesuré à sec, débits équilibrés, 20 K d'écart. En service,
# sur des logements : 70 à 85 % en Belgique [S : Pecceu et Caillou, CSTC], mais 0,65 ± 0,24 au Luxembourg
# [C : Merzkirch et al. 2016]. Aucune mesure en service trouvée pour le tertiaire.
RENDEMENT_DOUBLE_FLUX = 0.73
# La surventilation de nuit [S : IEA EBC Annex 62, Ventilative Cooling Design Guide, 2018] : plus de 3 volumes
# par heure pour un effet, plus de 5 recommandés, 8 à 10 en dimensionnement maximal ; en France, tabler sur
# 2 à 6. La commande par défaut reprend l'étude de cas n° 8 du guide : de 22 h à 6 h, pièce au-dessus de
# 22 à 23 °C, au moins 2 K de moins dehors, au moins 12 °C dehors.
SURVENTILATION_VOL_H = 4.0

SIMPLE_FLUX = VMC("simple flux")
DOUBLE_FLUX = VMC("double flux", recuperation=RENDEMENT_DOUBLE_FLUX)
SIMPLE_FLUX_SURVENTILATION = VMC("simple flux, surventilation de nuit", surventilation_vol_h=SURVENTILATION_VOL_H)
DOUBLE_FLUX_SURVENTILATION = VMC("double flux, surventilation de nuit", recuperation=RENDEMENT_DOUBLE_FLUX,
                                 surventilation_vol_h=SURVENTILATION_VOL_H)
CATALOGUE = (SIMPLE_FLUX, DOUBLE_FLUX, SIMPLE_FLUX_SURVENTILATION, DOUBLE_FLUX_SURVENTILATION)


def _heures(debut: int, fin: int, nom: str) -> ScheduleRuleset:
    """Un planning qui vaut 1 entre `debut` et `fin`, la plage pouvant passer minuit."""
    if (debut, fin) == (0, 24):
        return ScheduleRuleset.from_constant_value(nom, 1.0, limites.fractional)
    dedans = (lambda h: debut <= h < fin) if debut < fin else (lambda h: h >= debut or h < fin)
    jour = ScheduleDay.from_values_at_timestep(f"{nom}_jour", [1.0 if dedans(h) else 0.0 for h in range(24)])
    return ScheduleRuleset(nom, jour, None, limites.fractional)


def poser(modele, vmc: VMC) -> int:
    """Équipe toutes les pièces chauffées du modèle. À appeler après `hypotheses.appliquer`. Rend leur nombre."""
    planning = _heures(*vmc.heures_de_surventilation, "surventilation") if vmc.surventilation_vol_h else None
    regle = (VentilationControl(vmc.seuil_interieur_c, 100.0, vmc.exterieur_minimal_c, 100.0, vmc.ecart_minimal_k,
                                planning) if planning is not None else None)
    equipees = 0
    for piece in modele.rooms:
        energie = piece.properties.energy
        if energie.hvac is None:
            continue                                    # une pièce non chauffée n'est pas ventilée
        equipees += 1
        if vmc.recuperation:
            air = energie.hvac.duplicate()
            air.sensible_heat_recovery = vmc.recuperation
            energie.hvac = air
        elif energie.ventilation is not None and energie.ventilation.flow_per_area > 0:
            # Simple flux : l'air neuf entre directement, à la température du dehors, au même débit et aux
            # mêmes heures. Le ventilateur ne chauffe pas l'air (sa consommation n'est pas comptée).
            neuf = energie.ventilation
            toujours = VentilationControl(-100.0, 100.0, -100.0, 100.0, -100.0, neuf.schedule)
            energie.add_fan(VentilationFan(f"air_neuf_{piece.identifier}", neuf.flow_per_area * piece.floor_area,
                                           "Balanced", 0.0, 1.0, toujours))
            energie.ventilation = None
        if regle is not None:
            debit_m3_s = vmc.surventilation_vol_h * piece.volume / 3600.0
            energie.add_fan(VentilationFan(f"surventilation_{piece.identifier}", debit_m3_s, "Balanced",
                                           control=regle))
    return equipees
