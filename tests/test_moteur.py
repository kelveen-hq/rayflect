"""Le journal d'EnergyPlus, sa version, et la découpe des masques en morceaux convexes. Sans lancer de calcul."""

import pytest

from rayflect import geometrie, moteur

PROPRE = """Program Version,EnergyPlus, Version 25.2.0-cf7368216c, YMD=2026.11.15 14:18,
   ** Warning ** Version: missing in IDF, processing for EnergyPlus version="25.2"
   ** Warning ** GetHTSurfaceData: Surfaces with interface to Ground found but no "Ground Temperatures" were input.
   **   ~~~   ** Defaults, constant throughout the year of (18.0) will be used.
   ************* EnergyPlus Warmup Error Summary. During Warmup: 0 Warning; 0 Severe Errors.
   ************* EnergyPlus Completed Successfully-- 2 Warning; 0 Severe Errors; Elapsed Time=00hr 00min 58.28sec
"""
GRAVE = """Program Version,EnergyPlus, Version 25.2.0-cf7368216c, YMD=2026.11.15 14:18,
   ** Warning ** Version: missing in IDF, processing for EnergyPlus version="25.2"
   ** Severe  ** DetermineShadowingCombinations: There are 1 surfaces which are casting surfaces and are non-convex.
   **   ~~~   ** ...Shadowing values may be inaccurate. Check .shd report file for more surface shading details
   ************* Testing Individual Branch Integrity
   ************* EnergyPlus Completed Successfully-- 1 Warning; 1 Severe Errors; Elapsed Time=00hr 00min  1.45sec
"""
FATALE = """Program Version,EnergyPlus, Version 25.2.0-cf7368216c, YMD=2026.11.15 14:18,
   ** Severe  ** <root>[Zone][SALLE] - Missing required property 'x'.
   **  Fatal  ** Errors occurred on processing input file. Preceding condition(s) cause termination.
   ...Summary of Errors that led to program termination:
   ************* EnergyPlus Terminated--Fatal Error Detected. 0 Warning; 1 Severe Errors; Elapsed Time=00hr 00min  0.20sec
"""


def _journal(tmp_path, texte):
    fichier = tmp_path / "eplusout.err"
    fichier.write_text(texte, encoding="utf-8")
    return moteur.lire_le_journal(fichier)


def test_un_journal_propre_compte_ses_avertissements_et_n_est_pas_fautif(tmp_path):
    journal = _journal(tmp_path, PROPRE)
    assert (journal.avertissements, journal.graves, journal.fatales, journal.termine) == (2, [], [], True)
    assert not journal.fautif


def test_une_erreur_grave_rend_le_calcul_fautif_meme_termine(tmp_path):
    journal = _journal(tmp_path, GRAVE)
    assert journal.termine and journal.fautif
    assert len(journal.graves) == 1
    # Le message est rendu entier, avec ses lignes de suite : c'est lui qu'on lira.
    assert "non-convex" in journal.graves[0] and "Shadowing values may be inaccurate" in journal.graves[0]
    assert "grave : DetermineShadowingCombinations" in journal.dire()


def test_une_erreur_fatale_se_dit_avant_les_graves(tmp_path):
    journal = _journal(tmp_path, FATALE)
    assert journal.fautif and not journal.termine
    assert journal.dire().startswith("fatale : Errors occurred on processing input file")


def test_un_journal_absent_est_un_calcul_fautif(tmp_path):
    journal = moteur.lire_le_journal(tmp_path / "rien.err")
    assert journal.fautif
    assert journal.dire() == "le calcul ne s'est pas terminé"
    assert moteur.lire_le_journal(None).fautif


def test_la_version_verifiee_ne_dit_rien_une_autre_se_dit():
    assert moteur.remarque_sur_la_version((25, 2, 0)) is None
    autre = moteur.remarque_sur_la_version((24, 1, 0))
    assert "24.1.0" in autre and "25.2" in autre
    assert "inconnue" in moteur.remarque_sur_la_version(None)


def test_les_ombres_se_recalculent_chaque_jour():
    # Le sens physique : le soleil d'un jour ne vaut pas pour le mois. À 30 jours, le cas 950 de la norme
    # ANSI/ASHRAE 140 s'écarte de 2,7 % de la référence en froid.
    assert moteur.OMBRES_TOUS_LES_N_JOURS == 1


def test_les_versions_nomment_le_paquet_et_python():
    connues = moteur.versions()
    assert {"energyplus", "python"} <= set(connues)


def _face(points):
    from ladybug_geometry.geometry3d import Face3D, Point3D
    return Face3D([Point3D(*p) for p in points])


def test_une_face_convexe_est_rendue_telle_quelle():
    carre = _face([(0, 0, 3), (4, 0, 3), (4, 4, 3), (0, 4, 3)])
    assert geometrie.convexes(carre) == [carre]


def test_un_toit_en_l_devient_des_morceaux_convexes_de_meme_aire():
    toit = _face([(0, 0, 9), (10, 0, 9), (10, 4, 9), (4, 4, 9), (4, 10, 9), (0, 10, 9)])
    assert not toit.is_convex
    morceaux = geometrie.convexes(toit)
    assert 2 <= len(morceaux) <= 3                      # un L se couvre de 2 rectangles ; jamais de 4 triangles
    assert all(m.is_convex for m in morceaux)
    assert sum(m.area for m in morceaux) == pytest.approx(toit.area, rel=1e-6)
    assert all(m.min.z == pytest.approx(9) and m.max.z == pytest.approx(9) for m in morceaux)


def test_un_mur_perce_d_une_baie_devient_des_morceaux_convexes_dans_son_plan():
    from ladybug_geometry.geometry3d import Face3D, Point3D
    mur = Face3D([Point3D(0, 0, 0), Point3D(6, 0, 0), Point3D(6, 0, 3), Point3D(0, 0, 3)],
                 holes=[[Point3D(2, 0, 1), Point3D(4, 0, 1), Point3D(4, 0, 2), Point3D(2, 0, 2)]])
    morceaux = geometrie.convexes(mur)
    assert all(m.is_convex for m in morceaux)
    assert sum(m.area for m in morceaux) == pytest.approx(16.0, rel=1e-6)       # 18 m2 de mur, 2 m2 de baie
    assert all(abs(p.y) < 1e-9 for m in morceaux for p in m.vertices)           # resté dans le plan du mur
    assert len(morceaux) <= 5


def test_l_etude_regle_l_espacement_des_ombres_et_refuse_une_valeur_folle(tmp_path):
    from rayflect import etude

    base = 'usage = "bureau"\n{}[batiment]\nlongueur_m = 20.0\nlargeur_m = 10.0\nniveaux = 2\nhauteur_d_etage_m = 3.0\n'
    fichier = tmp_path / "etude.toml"
    fichier.write_text(base.format(""), encoding="utf-8")
    assert etude.lire(fichier).ombres_tous_les_n_jours == 1
    fichier.write_text(base.format("ombres_tous_les_n_jours = 7\n"), encoding="utf-8")
    assert etude.lire(fichier).ombres_tous_les_n_jours == 7
    for folle in ("0", "45", "2.5", "true"):
        fichier.write_text(base.format(f"ombres_tous_les_n_jours = {folle}\n"), encoding="utf-8")
        with pytest.raises(etude.EtudeInvalide, match="ombres_tous_les_n_jours"):
            etude.lire(fichier)
