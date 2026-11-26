"""Les 8 cas BESTEST à travers Honeybee et EnergyPlus : dans les plages de la norme, et proches du résultat
qu'EnergyPlus obtient sur les modèles du laboratoire NREL. Sauté si Honeybee ou EnergyPlus manque."""

import sys
from pathlib import Path

import pytest

pytest.importorskip("honeybee_energy")
from honeybee_energy.config import folders  # noqa: E402

if not folders.energyplus_exe:
    pytest.skip("EnergyPlus n'est pas installé", allow_module_level=True)

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "verification"))
import bestest  # noqa: E402

ECART_NREL_MAX = 0.005  # 0,5 % : même moteur, autre description du même local ; mesuré : 0,05 % au plus


@pytest.fixture(scope="module")
def resultats(tmp_path_factory):
    sortie = tmp_path_factory.mktemp("bestest")
    return {cas: bestest.calculer(cas, sortie) for cas in bestest.CAS}


@pytest.mark.parametrize("cas", list(bestest.CAS))
def test_dans_la_plage_de_la_norme(resultats, cas):
    plage_chauffage, plage_froid = bestest.PLAGES[cas]
    assert bestest.dans(resultats[cas]["chauffage_mwh"], plage_chauffage)
    assert bestest.dans(resultats[cas]["froid_mwh"], plage_froid)


@pytest.mark.parametrize("cas", list(bestest.CAS))
def test_proche_d_energyplus_au_laboratoire(resultats, cas):
    chauffage, froid = bestest.ENERGYPLUS_NREL[cas]
    assert resultats[cas]["chauffage_mwh"] == pytest.approx(chauffage, rel=ECART_NREL_MAX)
    assert resultats[cas]["froid_mwh"] == pytest.approx(froid, rel=ECART_NREL_MAX)


@pytest.mark.parametrize("sans, avec", [("600", "610"), ("620", "630"), ("900", "910"), ("920", "930")])
def test_un_masque_baisse_le_froid_et_monte_le_chauffage(resultats, sans, avec):
    assert resultats[avec]["froid_mwh"] < resultats[sans]["froid_mwh"]
    assert resultats[avec]["chauffage_mwh"] > resultats[sans]["chauffage_mwh"]
