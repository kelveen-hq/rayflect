"""La passerelle entre le modèle d'occupants et les plannings de BSO d'EnergyPlus."""

import pytest

pytest.importorskip("honeybee_energy")
from rayflect import bso_occupants as bo, hypotheses as hyp  # noqa: E402

TERTIAIRE = (("dynamique", 0.15), ("probabiliste", 0.30), ("toujours_baisse", 0.25), ("jamais_baisse", 0.30))
BUREAU = hyp.USAGES["bureau"]
# Une année de soleil franc de 10 h à 16 h, tous les jours.
SOLEIL = [400.0 if 10 <= h % 24 < 16 else 0.0 for h in range(8760)]


@pytest.mark.parametrize("n", [1, 4, 27, 82])
def test_la_repartition_garde_toutes_les_baies(n):
    assert sum(k for _nom, k in bo.repartir(n, TERTIAIRE)) == n


def test_la_repartition_suit_les_parts():
    assert dict(bo.repartir(100, TERTIAIRE)) == {"dynamique": 15, "probabiliste": 30,
                                                  "toujours_baisse": 25, "jamais_baisse": 30}


def test_les_comportements_fixes_ne_bougent_pas():
    assert set(bo.parts_baissees(BUREAU, False, "toujours_baisse", SOLEIL)) == {1.0}
    assert set(bo.parts_baissees(BUREAU, False, "jamais_baisse", SOLEIL)) == {0.0}


def test_l_occupant_actif_baisse_au_soleil_et_releve_le_matin():
    parts = bo.parts_baissees(BUREAU, False, "dynamique", SOLEIL)
    lundi = 24                                   # le 2 janvier, premier jour ouvré
    assert parts[lundi + 9] == 0.0               # arrivé, pas encore de soleil
    assert parts[lundi + 11] == 1.0              # soleil sur la façade : baissé
    assert parts[lundi + 24 + 9] == 0.0          # relevé en arrivant le lendemain


def test_sans_soleil_personne_ne_baisse():
    assert max(bo.parts_baissees(BUREAU, False, "probabiliste", [0.0] * 8760)) == 0.0


def test_un_planning_par_baie_et_la_part_baissee_suit_le_modele():
    series = bo.plannings(BUREAU, False, 40, SOLEIL)
    assert len(series) == 40
    assert all(set(valeurs) <= {0, 1} and len(valeurs) == 8760 for _c, valeurs in series)
    probabilistes = [v for c, v in series if c == "probabiliste"]
    attendu = bo.parts_baissees(BUREAU, False, "probabiliste", SOLEIL)
    heure = 24 + 13
    obtenu = sum(v[heure] for v in probabilistes) / len(probabilistes)
    assert obtenu == pytest.approx(attendu[heure], abs=0.5 / len(probabilistes) + 1e-9)


def test_le_logement_ne_baisse_que_s_il_fait_chaud():
    logement = hyp.USAGES["logement"]
    frais = bo.parts_baissees(logement, True, "chaleur", SOLEIL, [20.0] * 8760)
    chaud = bo.parts_baissees(logement, True, "chaleur", SOLEIL, [27.0] * 8760)
    assert max(frais) == 0.0
    assert max(chaud) > 0.5
