"""Les consignes de chauffage et de froid par usage.

Le réglage `consignes_par_usage` vaut « sourcees » (défaut) : chaque usage reçoit les consignes de la table
ci-dessous, avec leur source. La valeur « uniformes » est l'ancien comportement, conservé pour compatibilité :
les mêmes consignes par défaut pour tous les usages. La requête peut surcharger les consignes
(`setpoint_heating_c`, `setpoint_cooling_c`) ; `consignes_retenues` rend la consigne retenue et sa source.

LES SOURCES.
  - Code de l'énergie, art. R241-26 : dans les locaux d'habitation, d'enseignement, de bureaux, recevant du
    public et tous autres locaux, la température de chauffage est limitée en moyenne à 19 °C en occupation.
    Art. R241-30 : la climatisation ne se met en marche que si la température intérieure dépasse 26 °C.
  - Art. R241-28 : les établissements sanitaires et les locaux où sont hébergées des personnes âgées échappent
    à la limite de 19 °C. Les recommandations du secteur (guides des ARS et fiches d'hygiène des EHPAD, plan
    grand froid) visent 21 à 22 °C dans les chambres et les lieux de vie : la table retient 21 °C, le bas de la
    fourchette.
  - Hôtel : R241-26 s'applique (19 °C) ; la pratique hôtelière est souvent 20 à 21 °C, sans source publiée à
    citer : 19 °C gardé.
"""
from __future__ import annotations

from typing import Any, Dict, Optional, Tuple

CONSIGNES_REGLAGES = ("sourcees", "uniformes")

SOURCE_CODE_ENERGIE = ("code de l'énergie, art. R241-26 (chauffage limité à 19 °C en moyenne) et R241-30 "
                       "(climatisation au-delà de 26 °C)")
SOURCE_SANTE = ("code de l'énergie, art. R241-28 (santé et hébergement de personnes âgées hors de la limite "
                "de 19 °C) ; recommandations du secteur (ARS, EHPAD) : 21 à 22 °C, bas de la fourchette retenu ; "
                "froid : R241-30 (26 °C)")

# usage (`building_type` de la requête) -> (chauffage °C, froid °C, source)
CONSIGNES_PAR_USAGE: Dict[str, Tuple[float, float, str]] = {
    "residential": (19.0, 26.0, SOURCE_CODE_ENERGIE),
    "residential_individual": (19.0, 26.0, SOURCE_CODE_ENERGIE),
    "residential_collective": (19.0, 26.0, SOURCE_CODE_ENERGIE),
    "office": (19.0, 26.0, SOURCE_CODE_ENERGIE),
    "education": (19.0, 26.0, SOURCE_CODE_ENERGIE),
    "retail": (19.0, 26.0, SOURCE_CODE_ENERGIE),
    "hotel": (19.0, 26.0, SOURCE_CODE_ENERGIE + " ; pratique hôtelière 20 à 21 °C non sourcée, non retenue"),
    "industrial": (19.0, 26.0, SOURCE_CODE_ENERGIE),
    "healthcare": (21.0, 26.0, SOURCE_SANTE),
}


def consignes_retenues(building_type: Optional[str], chauffage_demande: Optional[float],
                       froid_demande: Optional[float], reglage: str,
                       defaut_chauffage: float, defaut_froid: float) -> Dict[str, Any]:
    """Les consignes retenues pour l'usage, et d'où elles viennent."""
    if reglage not in CONSIGNES_REGLAGES:
        raise ValueError(f"consignes_par_usage inconnu : {reglage!r} (attendu : {', '.join(CONSIGNES_REGLAGES)})")
    bt = str(building_type or "residential").strip().lower()
    if reglage == "sourcees" and bt in CONSIGNES_PAR_USAGE:
        ch, fr, src = CONSIGNES_PAR_USAGE[bt]
        source = f"usage « {bt} » : {src}"
    else:
        ch, fr = float(defaut_chauffage), float(defaut_froid)
        source = ("réglage « uniformes » (ancien comportement) : 19 / 26 °C pour tous les usages"
                  if reglage == "uniformes" else f"usage « {bt} » hors table : 19 / 26 °C")
    out = {
        "reglage": reglage,
        "chauffage_c": float(chauffage_demande) if chauffage_demande is not None else ch,
        "froid_c": float(froid_demande) if froid_demande is not None else fr,
        "chauffage_source": "requête : setpoint_heating_c" if chauffage_demande is not None else source,
        "froid_source": "requête : setpoint_cooling_c" if froid_demande is not None else source,
        "usage_chauffage_c": ch,
        "usage_froid_c": fr,
    }
    if out["froid_c"] <= out["chauffage_c"]:
        raise ValueError(f"consigne de froid ({out['froid_c']} °C) sous la consigne de chauffage "
                         f"({out['chauffage_c']} °C)")
    return out
