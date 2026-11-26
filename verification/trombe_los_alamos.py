"""Le mur Trombe à lame fermée face à des mesures : la cellule d'essai n° 1 de Los Alamos, février 1982.

Ce que l'essai prouve : que la lame d'air, la vitre et les 2 faces du mur écrites par `rayflect.trombe.lame`
donnent dans EnergyPlus les températures mesurées sur un vrai mur Trombe, à 1 ou 2 °C près, et un flux à
travers le mur proche de celui que les mesures donnent.

Ce qu'il ne prouve pas : la lame ventilée vers la pièce (aucune mesure exploitable trouvée), ni l'algorithme
`TrombeWall` lui-même, que ce banc distingue mal d'une convection ordinaire. Il prouve le montage.

Source : P. G. Ellis, « Development and Validation of the Unvented Trombe Wall Model in EnergyPlus », mémoire de
master, université de l'Illinois, 2003. Son annexe A donne les mesures heure par heure du 14 au 22 février 1982
(saisies depuis les microfiches de Los Alamos), son annexe B le fichier EnergyPlus de chaque cellule.

LES MESURES NE SONT PAS DANS LE DÉPÔT. Le script lit le texte extrait du PDF de la thèse par
`pdftotext -table` (l'option `-layout` brouille les colonnes), en tire les mesures, fabrique la météo, écrit la
cellule, lance le calcul et compare. Le chemin de ce texte se donne en argument, ou par la variable
d'environnement RAYFLECT_THESE_TROMBE.

La cellule : 1,58 x 2,18 x 3,05 m, très isolée, sur plots. Au sud, un mur de blocs de béton pleins de 0,40 m
peint en noir, derrière un double vitrage, lame d'air fermée de 51 mm. 3 volumes par heure d'air du dehors,
appoint par 2 ampoules pilotées à 18,3 °C, dont la puissance mesurée est imposée au calcul.

Ce qui diffère de la thèse, et pourquoi :
  - le soleil direct et diffus : la thèse prend un ciel clair théorique ; ici le rayonnement horizontal MESURÉ
    est décomposé (modèle DIRINT de pvlib), puis contrôlé contre le pyranomètre vertical mesuré ;
  - l'état initial : la thèse impose les températures de surface mesurées pendant 5 jours en modifiant le code
    d'EnergyPlus ; ici le calcul part du 14 février sans rien imposer, et la comparaison porte sur les 19 à 22 ;
  - la ventilation : un débit constant d'air du dehors avec l'échauffement du ventilateur, sans boucle d'air.
Comme la thèse : toutes les mesures sont décalées de 1 heure (horloge de l'acquisition), et les propriétés du
béton et des isolants sont celles que la thèse a calées sur 2 AUTRES cellules (référence et gain direct).
La réflexion du sol, 0,2, est choisie sur le pyranomètre vertical, qui n'entre pas dans le calcul.

Usage :
    python verification/trombe_los_alamos.py <texte de la thèse> [dossier_de_sortie]
"""
import csv
import json
import re
import sqlite3
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd
import pvlib

from rayflect import moteur, trombe

VARIABLE_DU_TEXTE = "RAYFLECT_THESE_TROMBE"
REFLEXION_DU_SOL = 0.2
LATITUDE, LONGITUDE, FUSEAU, ALTITUDE_M, PRESSION_PA = 35.8, -106.3, -7, 2158.0, 78018.0
DECALAGE_H = 1                                     # l'horloge de l'acquisition retardait de 1 h [thèse, 3.4.2.2]
BTU_H_FT2 = 3.15459                                # W/m2
BETON_K, BETON_EPAISSEUR_M = 1.3848, 0.396875
DEBUT, FIN = datetime(1982, 2, 14), datetime(1982, 2, 23)
COMPARE_DU, COMPARE_AU = datetime(1982, 2, 19), datetime(1982, 2, 22, 6)       # les 3 jours clairs et 6 h
FLUX_DU, FLUX_AU = datetime(1982, 2, 19), datetime(1982, 2, 22)                # les 3 jours clairs
CANAUX = {"sud_f": 1, "nord_f": 3, "appoint_w": 8, "globe_f": 9, "globe_voisine_f": 19, "dehors_inst_f": 150,
          "vertical": 161, "humidite": 169, "dehors_moy_f": 170, "horizontal": 172, "vent_mph": 177,
          "vent_deg": 178, "rosee_f": 179}


def celsius(f):
    return (f - 32.0) / 1.8


def mesures(texte):
    """Les tableaux de l'annexe A : {canal: {instant: valeur}}, l'instant déjà décalé de 1 heure."""
    rendu, colonnes = {}, None
    for ligne in texte.splitlines():
        if ligne.lstrip().startswith("Date/Time"):
            colonnes = [(m.start(), int(m.group(1))) for m in re.finditer(r"Ch (\d+)", ligne)]
            continue
        m = re.match(r"\s*(\d+)/(\d+)/82 (\d+):00", ligne)
        if not (m and colonnes):
            continue
        instant = datetime(1982, int(m.group(1)), int(m.group(2)), int(m.group(3))) + timedelta(hours=DECALAGE_H)
        for valeur in re.finditer(r"-?\d+\.\d+", ligne[m.end():]):
            position = valeur.start() + m.end()
            ecart, canal = min((abs(position - debut), c) for debut, c in colonnes)
            if ecart > 4:
                raise ValueError(f"valeur hors colonne : {ligne}")
            rendu.setdefault(canal, {})[instant] = float(valeur.group())
    return rendu


def serie(donnees, cle, defaut=None):
    """La série horaire d'un canal du 14 au 22 février ; un trou est comblé par la valeur précédente."""
    canal, rendu, dernier = donnees[CANAUX[cle]], {}, defaut
    t = DEBUT
    while t <= FIN:
        dernier = canal.get(t, dernier)
        rendu[t] = dernier
        t += timedelta(hours=1)
    premier = next(v for v in rendu.values() if v is not None)
    return {t: (premier if v is None else v) for t, v in rendu.items()}


def meteo(donnees, chemin):
    """Le fichier météo : mesures du site, soleil horizontal mesuré décomposé en direct et diffus."""
    dehors, rosee, humidite = serie(donnees, "dehors_inst_f"), serie(donnees, "rosee_f"), serie(donnees, "humidite")
    vent, cap = serie(donnees, "vent_mph"), serie(donnees, "vent_deg")
    horizontal = serie(donnees, "horizontal", 0.0)
    # la moyenne de l'heure qui finit à t : soleil pris au milieu de cette heure
    instants = [t for t in sorted(horizontal) if DEBUT < t <= FIN]
    index = pd.DatetimeIndex([t - timedelta(minutes=30) for t in instants]).tz_localize(f"Etc/GMT{-FUSEAU:+d}")
    soleil = pvlib.solarposition.get_solarposition(index, LATITUDE, LONGITUDE, altitude=ALTITUDE_M)
    ghi = pd.Series([max(0.0, horizontal[t] * BTU_H_FT2) if t in donnees[CANAUX["horizontal"]] else 0.0
                     for t in instants], index=index)
    ghi[soleil["apparent_elevation"] <= 0] = 0.0
    dni = pvlib.irradiance.dirint(ghi, soleil["zenith"], index, pressure=PRESSION_PA,
                                  temp_dew=pd.Series([celsius(rosee[t]) for t in instants], index=index)).fillna(0.0)
    dhi = (ghi - dni * pvlib.tools.cosd(soleil["zenith"]).clip(lower=0)).clip(lower=0)
    lignes = [
        f"LOCATION,Los Alamos cellules d'essai,NM,USA,mesures 1982,999999,{LATITUDE},{LONGITUDE},{FUSEAU}.0,{ALTITUDE_M}",
        "DESIGN CONDITIONS,0", "TYPICAL/EXTREME PERIODS,0", "GROUND TEMPERATURES,0",
        "HOLIDAYS/DAYLIGHT SAVINGS,No,0,0,0", "COMMENTS 1,mesures de l'annexe A, decalees de 1 heure",
        "COMMENTS 2,direct et diffus : horizontal mesure decompose par DIRINT",
        "DATA PERIODS,1,1,Data,Sunday,2/14,2/22"]
    for t, g, n, d in zip(instants, ghi, dni, dhi):
        fin = t - timedelta(hours=1)                    # l'heure 1 à 24 du jour où elle commence
        champs = [1982, fin.month, fin.day, fin.hour + 1, 0, "?",
                  round(celsius(dehors[t]), 2), round(celsius(rosee[t]), 2), round(min(100.0, humidite[t])),
                  PRESSION_PA, 9999, 9999, 9999, round(g), round(n), round(d), 999999, 999999, 999999, 9999,
                  round(cap[t] % 360), round(vent[t] * 0.44704, 2), 0, 0, 9999, 99999, 9, 999999999, 0, 0.0, 0, 88,
                  0.0, 0.0, 0.0]
        lignes.append(",".join(str(c) for c in champs))
    Path(chemin).write_text("\n".join(lignes) + "\n", encoding="ascii")
    return {t: (float(g), float(n), float(d)) for t, g, n, d in zip(instants, ghi, dni, dhi)}


def annee(valeurs, defaut, chemin):
    """Un fichier de 8 760 lignes pour Schedule:File : la valeur de l'heure qui finit, `defaut` hors période."""
    t, lignes = datetime(1982, 1, 1, 1), []
    for _heure in range(8760):
        lignes.append([round(valeurs.get(t, defaut), 3)])
        t += timedelta(hours=1)
    with open(chemin, "w", newline="", encoding="ascii") as f:
        csv.writer(f).writerows(lignes)


def matiere(nom, rugosite, epaisseur, conductivite, masse, chaleur, emission, absorption):
    return (f"Material,{nom},{rugosite},{epaisseur},{conductivite},{masse},{chaleur},{emission},{absorption},"
            f"{absorption};")


def paroi(nom, genre, construction, zone, limite, objet, soleil, vent, points):
    plat = ",".join(f"{v}" for p in points for v in p)
    return (f"BuildingSurface:Detailed,{nom},{genre},{construction},{zone},,{limite},{objet},{soleil},{vent},"
            f"Autocalculate,4,{plat};")


def cellule(reflexion_du_sol, convection_de_la_lame="TrombeWall"):
    """La cellule n° 1, d'après l'annexe B de la thèse, au format d'EnergyPlus 25.2."""
    dehors, soleil = ("Outdoors", ""), ("SunExposed", "WindExposed")
    ombre = ("NoSun", "NoWind")
    L, P, H, h, x0, x1, y = 1.578, 2.184, 3.048, 2.140, 0.142, 1.436, -0.0510
    lignes = [
        "Version,25.2;",
        "SimulationControl,No,No,No,No,Yes;",
        "Building,Cellule 1 de Los Alamos,0,Suburbs,0.04,0.01,FullInteriorAndExterior,25,6;",
        "Timestep,6;",
        "ShadowCalculation,PolygonClipping,Periodic,1,15000;",
        "SurfaceConvectionAlgorithm:Inside,TARP;",
        "SurfaceConvectionAlgorithm:Outside,TARP;",
        "HeatBalanceAlgorithm,ConductionTransferFunction;",
        f"Site:Location,Los Alamos,{LATITUDE},{LONGITUDE},{FUSEAU},{ALTITUDE_M};",
        "Site:GroundReflectance," + ",".join([f"{reflexion_du_sol}"] * 12) + ";",
        "RunPeriod,fevrier 1982,2,14,1982,2,22,1982,Sunday,No,No,No,Yes,Yes;",
        "GlobalGeometryRules,UpperLeftCorner,Counterclockwise,World;",
        "ScheduleTypeLimits,libre;",
        "Schedule:Constant,toujours,libre,1.0;",
        "Schedule:File,appoint,libre,appoint.csv,1,0,8760,Comma,No,60;",
        "Schedule:File,voisine,libre,voisine.csv,1,0,8760,Comma,No,60;",
        matiere("beton_noir", "MediumRough", BETON_EPAISSEUR_M, BETON_K, 2189.06, 510.188, 0.9, 0.95),
        matiere("contreplaque_blanc", "Smooth", 0.01588008, 0.1153628, 544.6277, 1213.36, 0.9, 0.25),
        matiere("contreplaque", "Smooth", 0.01588008, 0.1153628, 544.6277, 1213.36, 0.9, 0.7),
        matiere("contreplaque_fin", "Smooth", 0.00635, 0.1153628, 544.6277, 1213.36, 0.9, 0.7),
        matiere("laine", "VeryRough", 0.0889, 0.040, 84.8, 963.7, 0.9, 0.5),
        matiere("polystyrene", "Rough", 0.0252984, 0.025, 28.83323, 1213.36, 0.8, 0.5),
        matiere("polystyrene_89", "Rough", 0.0889, 0.025, 28.83323, 1213.36, 0.8, 0.5),
        matiere("tole", "Smooth", 0.0158496, 45.31492, 7833.028, 502.08, 0.2, 0.23),
        matiere("feutre", "Rough", 0.0095402403, 0.1902535, 1121.292, 1673.6, 0.9, 0.75),
        matiere("etancheite", "VeryRough", 0.0031699201, 0.1158817, 1121.292, 836.8, 0.9, 0.8),
        "WindowMaterial:Glazing,verre,SpectralAverage,,0.0047625,0.83066,0.075,0.075,0.898,0.081,0.081,0.0,0.84,"
        "0.84,0.9;",
        "WindowMaterial:Gas,lame_du_vitrage,Air,0.0127;",
        "Construction,mur,contreplaque_blanc,laine,polystyrene;",
        "Construction,mur_sud,contreplaque_blanc,polystyrene_89,polystyrene;",
        "Construction,cloison,polystyrene,laine,polystyrene;",
        "Construction,plancher,contreplaque_fin,laine,laine,contreplaque;",
        "Construction,toit,etancheite,feutre,contreplaque,laine,laine,tole,polystyrene;",
        "Construction,double_vitrage,verre,lame_du_vitrage,verre;",
        "Construction,mur_trombe,beton_noir;",
        "Construction,bord_de_lame,contreplaque_blanc,laine,polystyrene;",
        "Zone,piece,0,0,0,0,1,1,3.048;",
        "SurfaceProperty:OtherSideCoefficients,cellule_voisine,1,18.4,1,0,0,0,0,voisine;",
        paroi("piece_est", "Wall", "mur", "piece", *dehors, *soleil, [(L, 0, H), (L, 0, 0), (L, P, 0), (L, P, H)]),
        paroi("piece_nord", "Wall", "mur", "piece", *dehors, *soleil, [(L, P, H), (L, P, 0), (0, P, 0), (0, P, H)]),
        paroi("piece_ouest", "Wall", "cloison", "piece", "OtherSideCoefficients", "cellule_voisine", *ombre,
              [(0, P, H), (0, P, 0), (0, 0, 0), (0, 0, H)]),
        paroi("piece_sud_ouest", "Wall", "mur_sud", "piece", *dehors, *soleil,
              [(0, 0, h), (0, 0, 0), (x0, 0, 0), (x0, 0, h)]),
        paroi("piece_sud_haut", "Wall", "mur_sud", "piece", *dehors, *soleil,
              [(0, 0, H), (0, 0, h), (L, 0, h), (L, 0, H)]),
        paroi("piece_sud_est", "Wall", "mur_sud", "piece", *dehors, *soleil,
              [(x1, 0, h), (x1, 0, 0), (L, 0, 0), (L, 0, h)]),
        paroi("piece_plancher", "Floor", "plancher", "piece", *dehors, "NoSun", "WindExposed",
              [(L, 0, 0), (0, 0, 0), (0, P, 0), (L, P, 0)]),
        paroi("piece_toit", "Roof", "toit", "piece", *dehors, *soleil, [(0, P, H), (0, 0, H), (L, 0, H), (L, P, H)]),
        "Shading:Building:Detailed,debord,,4,0,0,3.556,0,-0.3556,3.556,1.578,-0.3556,3.556,1.578,0,3.556;",
        "Lights,ampoules,piece,appoint,LightingLevel,1.0,,,0,0.70,0.10,0;",
        "ZoneVentilation:DesignFlowRate,air_du_dehors,piece,toujours,Flow/Zone,0.00875,,,,Intake,300,0.63,1,0,0,0;",
        "Output:SQLite,Simple;",
    ]
    for sortie in ("Zone Mean Air Temperature", "Zone Mean Radiant Temperature", "Surface Inside Face Temperature",
                   "Surface Outside Face Incident Solar Radiation Rate per Area",
                   "Site Outdoor Air Drybulb Temperature"):
        lignes.append(f"Output:Variable,*,{sortie},Hourly;")
    # Le mur Trombe lui-même : la même fonction que celle qui équipe un bâtiment dans une étude.
    du_mur, _face = trombe.lame(
        "mur", "piece", (x0, 0.0, 0.0), (x1, 0.0, 0.0), h, (0.0, -1.0, 0.0), -y, "mur_trombe", "mur_trombe",
        "bord_de_lame", "double_vitrage", (0.2175 - x0, x1 - 1.3605, 0.010, h - 1.915),
        convection=convection_de_la_lame)
    return "\n".join(lignes) + "\n" + du_mur


def lire(sql):
    """{(variable, clé): {instant de fin d'heure: valeur}} pour la période calculée."""
    base = sqlite3.connect(sql)
    rendu = {}
    for nom, cle, mois, jour, heure, valeur in base.execute(
            "SELECT d.Name, d.KeyValue, t.Month, t.Day, t.Hour, r.Value FROM ReportData r "
            "JOIN ReportDataDictionary d ON r.ReportDataDictionaryIndex = d.ReportDataDictionaryIndex "
            "JOIN Time t ON r.TimeIndex = t.TimeIndex WHERE t.WarmupFlag = 0 OR t.WarmupFlag IS NULL"):
        instant = datetime(1982, mois, jour) + timedelta(hours=heure)
        rendu.setdefault((nom, cle.upper()), {})[instant] = valeur
    return rendu


def ecarts(calcule, mesure, du, au):
    paires = [(calcule[t], mesure[t]) for t in sorted(mesure) if du < t <= au and t in calcule]
    n = len(paires)
    biais = sum(c - m for c, m in paires) / n
    return {"heures": n, "mesure_moyenne": round(sum(m for _c, m in paires) / n, 2),
            "calcul_moyen": round(sum(c for c, _m in paires) / n, 2), "biais": round(biais, 2),
            "ecart_quadratique": round((sum((c - m) ** 2 for c, m in paires) / n) ** 0.5, 2),
            "ecart_max": round(max(abs(c - m) for c, m in paires), 2)}


def jouer(texte, sortie, reflexion_du_sol, convection_de_la_lame="TrombeWall"):
    donnees = mesures(texte)
    sortie.mkdir(parents=True, exist_ok=True)
    soleil = meteo(donnees, sortie / "meteo.epw")
    annee({t: v for t, v in serie(donnees, "appoint_w", 0.0).items()}, 0.0, sortie / "appoint.csv")
    annee({t: celsius(v) for t, v in serie(donnees, "globe_voisine_f").items()}, 18.4, sortie / "voisine.csv")
    (sortie / "in.idf").write_text(cellule(reflexion_du_sol, convection_de_la_lame), encoding="ascii")
    try:
        sql, journal = moteur.lancer(sortie / "in.idf", sortie / "meteo.epw")
    except moteur.CalculFautif as erreur:
        raise RuntimeError(f"cellule de Los Alamos : {erreur}") from erreur
    r = lire(sql)
    air, rayonnante = r[("Zone Mean Air Temperature", "PIECE")], r[("Zone Mean Radiant Temperature", "PIECE")]
    globe = {t: (air[t] + rayonnante[t]) / 2 for t in air}           # le globe : moyenne des 2, comme la thèse
    sud = r[("Surface Inside Face Temperature", "MUR_COTE_LAME")]       # face du mur dans la lame
    nord = r[("Surface Inside Face Temperature", "MUR_COTE_PIECE")]     # face du mur dans la pièce
    m_sud = {t: celsius(v) for t, v in donnees[CANAUX["sud_f"]].items()}
    m_nord = {t: celsius(v) for t, v in donnees[CANAUX["nord_f"]].items()}
    m_globe = {t: celsius(v) for t, v in donnees[CANAUX["globe_f"]].items()}
    vertical = r[("Surface Outside Face Incident Solar Radiation Rate per Area", "PIECE_SUD_HAUT")]
    m_vertical = {t: v * BTU_H_FT2 for t, v in donnees[CANAUX["vertical"]].items()}
    m_horizontal = {t: v * BTU_H_FT2 for t, v in donnees[CANAUX["horizontal"]].items()}
    dehors = r[("Site Outdoor Air Drybulb Temperature", "ENVIRONMENT")]
    m_dehors = {t: celsius(v) for t, v in donnees[CANAUX["dehors_moy_f"]].items()}

    def flux(s, n):
        heures = [t for t in s if FLUX_DU < t <= FLUX_AU and t in n]
        return BETON_K / BETON_EPAISSEUR_M * sum(s[t] - n[t] for t in heures) / len(heures)
    rendu = {
        "reflexion_du_sol": reflexion_du_sol, "convection_de_la_lame": convection_de_la_lame,
        "avertissements": journal.avertissements,
        "meteo": {
            "soleil_vertical_sud_w_m2": ecarts(vertical, m_vertical, COMPARE_DU, COMPARE_AU),
            "dehors_c": ecarts(dehors, m_dehors, COMPARE_DU, COMPARE_AU)},
        "face_dans_la_lame_c": ecarts(sud, m_sud, COMPARE_DU, COMPARE_AU),
        "face_dans_la_piece_c": ecarts(nord, m_nord, COMPARE_DU, COMPARE_AU),
        "globe_c": ecarts(globe, m_globe, COMPARE_DU, COMPARE_AU),
        "flux_moyen_a_travers_le_mur_w_m2": {"mesure": round(flux(m_sud, m_nord), 1),
                                              "calcul": round(flux(sud, nord), 1),
                                              "these_mesure": 48.7, "these_energyplus_2003": 54.9},
    }
    rendu["flux_moyen_a_travers_le_mur_w_m2"]["ecart_pourcent"] = round(
        100 * (rendu["flux_moyen_a_travers_le_mur_w_m2"]["calcul"]
               / rendu["flux_moyen_a_travers_le_mur_w_m2"]["mesure"] - 1), 1)
    with open(sortie / "heure_par_heure.csv", "w", newline="", encoding="ascii") as f:
        ecrit = csv.writer(f)
        ecrit.writerow(["instant", "dehors_mesure", "soleil_horizontal_mesure", "direct", "diffus",
                        "vertical_mesure", "vertical_calcule", "sud_mesure", "sud_calcule", "nord_mesure",
                        "nord_calcule", "globe_mesure", "globe_calcule", "appoint_w"])
        for t in sorted(air):
            ecrit.writerow([t.isoformat(), *(round(x, 2) if x is not None else "" for x in (
                m_dehors.get(t), m_horizontal.get(t), soleil.get(t, (0, 0, 0))[1], soleil.get(t, (0, 0, 0))[2],
                m_vertical.get(t), vertical.get(t), m_sud.get(t), sud.get(t), m_nord.get(t), nord.get(t),
                m_globe.get(t), globe.get(t), donnees[CANAUX["appoint_w"]].get(t)))])
    return rendu


def texte_de_la_these(chemin=None) -> Path:
    """Le fichier des mesures, ou `FileNotFoundError` avec la marche à suivre."""
    chemin = chemin or os.environ.get(VARIABLE_DU_TEXTE)
    if not chemin or not Path(chemin).exists():
        raise FileNotFoundError(
            f"les mesures de Los Alamos ne sont pas dans le dépôt : extraire le texte de la thèse d'Ellis (2003) par "
            f"« pdftotext -table », et donner son chemin en argument ou dans {VARIABLE_DU_TEXTE}")
    return Path(chemin)


def calculer(sortie, chemin=None, convection_de_la_lame="TrombeWall") -> dict:
    texte = texte_de_la_these(chemin).read_text(encoding="latin-1")
    return jouer(texte, Path(sortie).resolve(), REFLEXION_DU_SOL, convection_de_la_lame)


def main(argv: list[str]) -> int:
    try:
        source = texte_de_la_these(argv[1] if len(argv) > 1 else None)
    except FileNotFoundError as erreur:
        print(erreur)
        return 1
    sortie = Path(argv[2]).resolve() if len(argv) > 2 else Path("verification/sorties/trombe_los_alamos").resolve()
    rendu = calculer(sortie, source)
    for cle in ("face_dans_la_lame_c", "face_dans_la_piece_c", "globe_c"):
        e = rendu[cle]
        print(f"{cle:22s} mesuré {e['mesure_moyenne']:6.2f}   calculé {e['calcul_moyen']:6.2f}   biais {e['biais']:+.2f}   "
              f"écart quadratique {e['ecart_quadratique']:.2f}   écart maximal {e['ecart_max']:.2f}")
    flux = rendu["flux_moyen_a_travers_le_mur_w_m2"]
    print(f"flux à travers le mur  mesuré {flux['mesure']} W/m2   calculé {flux['calcul']} W/m2   "
          f"({flux['ecart_pourcent']:+.1f} %)")
    (sortie / "trombe_los_alamos.json").write_text(json.dumps(rendu, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
