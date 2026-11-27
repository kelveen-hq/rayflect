# Rayflect

*[English version](README.en.md)*

## En bref

**Ce qu'il fait.** Rayflect compare des choix de conception sobres sur un bâtiment, heure par heure : protections
solaires, arbres et murs végétalisés, fenêtres qu'on ouvre, ventilation de nuit, parois, mur Trombe, sondes
géothermiques. Il prépare le bâtiment et les hypothèses d'usage, puis confie le calcul à des moteurs vérifiés
(EnergyPlus, par Honeybee et Ladybug). Il rend les heures chaudes et les degrés-heures, les besoins de chauffage et
de froid, d'où vient la chaleur et où elle part, la lumière du jour, son excès et l'éblouissement, le carbone des
matériaux ajoutés, et une plantation âge par âge. La même étude se rejoue sous une année réelle, l'été le plus chaud
ou le climat des années 2040 ; `rayflect proposer` part des objectifs et cherche les mesures qui les tiennent.

**Ce qu'il apporte.** Une physique de référence, ouverte et vérifiable, pour les architectes et les bureaux d'études
en esquisse et en avant-projet : chaque chiffre porte la preuve qui le tient, et une hypothèse lourde prise par
défaut dit son poids. Un outil pour choisir, pas pour attester : il ne remplace pas le calcul réglementaire.

**Où il s'arrête.** Il calcule le bâtiment, pas un produit : un dispositif particulier y entre seulement par son effet
heure par heure. Il ne chiffre aucun dispositif.

**Avec qui il parle.** Il lit un fichier d'étude TOML, une maquette IFC, des plans DXF, quelques chiffres, ou un
bâtiment au format du bâtiment commun, version 1 (`io/lecture_batiment_commun.py`, provenance gardée champ par
champ). Un programme extérieur peut lui donner l'effet d'un produit, heure par heure, en watts (élément
`apport_horaire`, un CSV). Il rend `resultats.json`, décrit par `resultats.schema.json`. Il demande ses données à des
services publics (PVGIS, IGN et BD TOPO, Eurostat, Open-Meteo) et les garde dans un cache hors du dépôt ; ses
facteurs de carbone, lus dans la Base Empreinte de l'ADEME et dans ICE, sont écrits dans le code avec leur source.

## Le détail

**Le carbone de ce qu'on construit compte aussi.** Chaque scénario dit le carbone des matériaux qu'il ajoute
(une casquette en aluminium, en bois ou en béton, un isolant, des panneaux) et en combien d'années le CO2 qu'il
évite le rembourse. Les facteurs viennent de sources publiques et se changent dans le fichier d'étude, pour un
matériau bas carbone, de réemploi ou biosourcé (table `[carbone]`, ou `carbone_kg` tiré d'une FDES).

**Partir du besoin.** Au lieu d'écrire les scénarios, on peut donner ses objectifs (pas plus de 350 degrés-heures,
assez de lumière, pas plus de 5 % de chauffage en plus, un plafond de carbone) : `rayflect proposer` essaie les
mesures passives d'une palette, seules puis combinées, et rend celles qui les tiennent, avec ce que chacune coûte
sur les autres critères.

**Un outil pour choisir, pas pour attester.** Rayflect donne l'ordre de grandeur des indicateurs de la RE2020 (les
degrés-heures d'inconfort, par exemple), sur la météo et les hypothèses de l'étude. Il sert à comparer des choix en
esquisse et en avant-projet. Il ne remplace jamais le calcul réglementaire, qui seul fait foi pour une attestation.

**État : public, en construction.** Tout se lance en ligne de commande ; il n'y a pas encore d'interface.

Pour l'installer et jouer une première étude en 20 minutes : [docs/INSTALLATION.md](docs/INSTALLATION.md).

## Le principe

Rayflect ne recalcule pas la physique du bâtiment. Il prépare le bâtiment, pose les protections solaires et
les hypothèses d'usage, puis confie le calcul à des moteurs existants et vérifiés :

- [EnergyPlus](https://energyplus.net) pour la chaleur, l'air, le sol et la lumière du jour ;
- [Honeybee](https://www.ladybug.tools/honeybee.html) pour décrire le bâtiment ;
- [Ladybug](https://www.ladybug.tools) pour lire la météo et suivre la course du soleil ;
- [IfcOpenShell](https://ifcopenshell.org) pour lire les maquettes ;
- [ezdxf](https://ezdxf.mozman.at) pour lire les plans DXF.

## D'où viennent les données

Rayflect ne redistribue aucune donnée. Il les demande à des services publics, les contrôle, et les garde dans
un cache hors du dépôt (`rayflect cache` dit où).

| Donnée | Service | Module |
|---|---|---|
| Météo d'une année type, heure par heure, partout en Europe | [PVGIS](https://re.jrc.ec.europa.eu/pvg_tools/fr/) de la Commission européenne, par son interface de programmation | `io/meteo` |
| Position d'une adresse, commune, altitude | Géocodeur et altimétrie de l'[IGN](https://geoservices.ign.fr), France | `lieu` |
| Bâtiments voisins et leur hauteur | BD TOPO de l'IGN, France | `environnement` |
| Prix de l'électricité et du gaz | [Eurostat](https://ec.europa.eu/eurostat) | `energie` |
| Carbone des matériaux | [Base Empreinte](https://base-empreinte.ademe.fr) de l'ADEME, et ICE V3 cité par l'IStructE ; à remplacer par une FDES de la base [INIES](https://www.base-inies.fr) | `carbone` |
| Une année réelle heure par heure, depuis 1950 | Réanalyses ERA5-Land et ERA5 de [Copernicus](https://climate.copernicus.eu), par l'API d'archives d'[Open-Meteo](https://open-meteo.com) | `io/climats` |
| Le climat de 2040 à 2049 | 7 modèles CMIP6 HighResMIP, par l'API climatique d'[Open-Meteo](https://open-meteo.com) | `io/climats` |

Un fichier météo donné (`meteo = "fichier.epw"`) remplace celui de PVGIS : une station proche, un fichier de bureau
d'études. Les limites d'une année type sont écrites dans la feuille de route, branche 0.

Le climat se choisit aussi, sous la table `[lieu]` : `climat = 2022` (une année réelle), `"ete_le_plus_chaud"`
(l'été le plus chaud depuis 2000), `"futur"` (l'année type déformée vers 2040-2049 par la méthode de Belcher, 2005 :
température, humidité, soleil et vent) ou `"futur_chaud"` (l'été le plus chaud depuis 2000, décalé vers 2040-2049 :
une canicule réelle, dans le climat qui vient). Une liste, `climat = ["type", "futur", "futur_chaud"]`, joue la même
étude sous chacun et les compare :
c'est sous un été chaud et sous le climat qui vient que la ventilation de nuit, l'inertie et les protections se
départagent. Les données d'Open-Meteo sont sous licence CC BY 4.0, **gratuites pour un usage non commercial** ; un
usage commercial demande un abonnement à Open-Meteo. L'API gratuite limite aussi le volume par heure : un climat futur
demande les données quotidiennes de 7 modèles sur 25 ans, ce qui en consomme une grande part. Chaque réponse est
gardée en cache ; si l'API refuse, attendre une heure.

## S'en servir

```bash
rayflect modele mon_etude.toml     # écrit un fichier d'étude à remplir : maquette, adresse, usage, scénarios
rayflect etude mon_etude.toml      # joue l'étude et compare les scénarios
rayflect etude mon_etude.toml --climats type,ete_le_plus_chaud,futur    # la même sous 3 climats
rayflect proposer mon_etude.toml   # cherche les mesures qui tiennent les objectifs de l'étude ([objectifs])
rayflect releve batiment.ifc       # dit ce qui a été lu dans la maquette, et ce qui manque
rayflect releve rdc.dxf --dessin controle.svg    # de même depuis un plan, avec un dessin à contrôler à l'œil
```

Une étude tient dans un fichier TOML, qu'on peut rejouer et partager. Son format est décrit en tête de
`src/rayflect/etude.py`. Chaque scénario du fichier change le bâtiment et se compare au bâtiment tel qu'il est :

| Un scénario peut... | Type d'élément |
|---|---|
| poser une protection solaire | `casquette`, `joues`, `lames_horizontales`, `lames_verticales`, `lames_saisonnieres`, `lames_pilotees`, `bso`, `balcon` |
| planter | `arbre`, `pergola`, `grimpante`, `mur_vegetal` (des modules plantés devant les murs pleins) |
| changer la toiture | `toit`, `photovoltaique` |
| changer le vitrage d'une façade ou les parois | `facade`, et la table `[scenario.parois]` |
| ouvrir les fenêtres autrement | `ouvrants` |
| changer la ventilation mécanique | `ventilation` |
| transformer une allège en mur Trombe | `mur_trombe` |
| poser un champ de sondes géothermiques sur ses besoins | `sondes` |
| recevoir la chaleur d'un calcul fait ailleurs | `apport_horaire` |

## Ce que contient ce dépôt

| Module | Rôle |
|---|---|
| `io/lecture_ifc` | Relevé d'une maquette IFC : site, nord, niveaux, baies orientées, et ce qui manque |
| `io/lecture_dxf` | Le même relevé depuis des plans DXF, un par niveau ; hauteurs et nord à donner |
| `io/releve_vers_honeybee` | Du relevé à un bâtiment calculable : un volume par niveau, les baies reposées sur leurs murs |
| `hypotheses` | Usage, aération, chauffage, climatisation et parois (isolant, vitrage, inertie), chaque valeur avec son origine |
| `energie` | Des besoins à l'énergie achetée, au CO2 et aux euros ; prix moyens d'Eurostat, ou ceux qu'on donne |
| `protections_solaires` | Casquette, joues, lames horizontales et verticales, lames à 2 positions, lames pilotées, BSO |
| `bso_occupants` | Des BSO manœuvrés par une population d'occupants tirée de la littérature |
| `lumiere` | Lumière du jour au centre et à 1 m de la baie : autonomie à 300 lux, excès au-dessus de 2 000 et 3 000 lux, éblouissement (indice DGI au-dessus de 22) |
| `etude`, `cli` | Le fichier d'étude et la commande `rayflect` |
| `cache` | Où se rangent la météo et les cartes téléchargées, hors du dépôt |
| `lieu` | Le lieu de l'étude depuis une adresse (géocodeur de l'IGN), avant des coordonnées, avant la position de la maquette |
| `io/meteo` | L'année type de PVGIS pour ce lieu, contrôlée et réparée avant tout calcul |
| `environnement` | Les bâtiments voisins de la BD TOPO de l'IGN, transformés en masques |
| `vegetation` | Arbres, pergola, plante grimpante : un feuillage décrit par son indice foliaire, et une taille qui suit l'âge depuis la plantation |
| `io/releve_par_chiffres` | Le même relevé sans maquette ni plan : un pavé, ses niveaux, son vitrage par orientation |
| `io/lecture_batiment_commun` | Le même relevé depuis un bâtiment décrit par un autre logiciel (format JSON « bâtiment commun », version 1), avec la provenance de chaque valeur, le niveau non chauffé et le mur mitoyen |
| `climat` | Zone climatique et température extérieure de base d'un lieu, par son département et son altitude |
| `exterieur` | Le sol sous le plancher, mois par mois, et le vent sur les parois (loi d'EnergyPlus ou NF EN ISO 6946) |
| `apports` | Un apport de chaleur donné heure par heure dans un fichier : un procédé, ou l'effet d'un dispositif calculé ailleurs |
| `extensions` | Le point d'extension : un autre paquet déclare son propre type d'élément de scénario |
| `puissance` | La puissance à installer : chauffage au jour de base, pointes de chauffage et de froid de l'année |
| `bilan` | D'où vient la chaleur et où elle part, poste par poste et façade par façade, par mois ; ce que chaque scénario change |
| `evaporation` | L'eau qu'un mur végétalisé évapore heure par heure (Penman-Monteith verticalisé, Hoffmann et al. 2023) et la température de ses modules |
| `trajectoire` | Une plantation dans le temps : sa taille, l'ombre qu'elle fait mois par mois, ce qu'elle change, âge par âge |
| `confort` | Les degrés-heures d'inconfort à la façon de la RE2020 : confort adaptatif de 26 à 28 °C, 26 °C la nuit en logement |
| `propositions` | Partir du besoin : des objectifs (degrés-heures, lumière, chauffage, carbone), une palette de mesures essayées seules puis combinées, rangées par objectifs tenus |
| `carbone` | Le carbone des matériaux que chaque scénario ajoute, mesuré dans le modèle ; facteurs sourcés et modifiables ; le retour en CO2 évité |
| `resultats` | Le format de `resultats.json`, version 1 : son schéma (`resultats.schema.json`), son empreinte, son contrôle |
| `variantes` | Les choix de conception : agrandir les baies d'une façade, la passer en bandeau ou en tout vitré, la fermer |
| `ventilation` | Ventilation mécanique : simple flux, double flux, surventilation de nuit |
| `aeration` | Les fenêtres qu'on ouvre : façades, heures, seuils, une façade ou traversant ; le débit du vent et du tirage |
| `trombe` | Le mur Trombe à lame fermée, en allège, avec tablette ou ouverture d'été |
| `sondes` | Un champ de sondes géothermiques : la température de l'eau qui revient du sol, suivie sur plusieurs années |
| `moteur` | EnergyPlus : sa version, ses réglages, et son journal d'erreurs, qui arrête une étude fautive |
| `geometrie` | La découpe d'un masque en morceaux convexes, les seuls qu'EnergyPlus ombre juste |
| `services`, `config`, `io/pvgis_historical` | Physique solaire, confort, constantes sourcées, météo PVGIS |

Comment tout cela s'enchaîne, en schémas, est dans [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).
Ce qui n'est pas encore fait, et par quel moyen le faire, est dans [docs/FEUILLE_DE_ROUTE.md](docs/FEUILLE_DE_ROUTE.md).

`verification/` rejoue à travers cette chaîne des cas dont le résultat est connu par ailleurs :

| Fichier | Ce qu'il rejoue | Référence | Écart mesuré |
|---|---|---|---|
| `bestest.py` | 8 cas de la norme ANSI/ASHRAE 140, dont 4 avec casquette ou joues | EnergyPlus sur les modèles du laboratoire NREL | 0,05 % au plus |
| `bestest_nuit.py` | Les 4 cas de ventilation de nuit (650, 950, 650FF, 950FF) | de même | 0,03 % au plus |
| `bestest_serre.py` | Le cas 960, la serre accolée, 2 pièces | de même | 0,05 % au plus |
| `dalle.py` | Les 16 cas de dalle sur terre-plein, avec le sol calculé d'EnergyPlus | 3 solutions numériques vérifiées | de -2,3 % à +3,5 % selon le cas |
| `ouvrants.py` | Le débit d'air des fenêtres ouvertes, sur une façade puis en traversant | Les formules de `rayflect.aeration`, recalculées à la main à chaque pas de temps | 0,2 % au plus sur l'année |
| `reponse_thermique.py` | Un essai de réponse thermique sur une sonde géothermique seule, 3 sols | La conductivité du sol donnée, à retrouver sur la pente | de +2,6 % à +3,9 % |
| `trombe_los_alamos.py` | Un mur Trombe à lame fermée, cellule d'essai de Los Alamos, février 1982 | Les températures mesurées des 2 faces du mur ; les mesures ne sont pas dans le dépôt | 1 °C en moyenne, flux à travers le mur +14 % |

Les lignes `ouvrants.py` et `reponse_thermique.py` contrôlent un montage contre sa formule : elles ne remplacent pas une mesure. Les 8 premiers cas se jouent avec la série courante ; les autres par `pytest -m lent`. `prototype/` contient les scripts d'essai de bout en bout.

Le fichier météo de la norme n'est pas redistribué ici : `verification/reference.py` le prend chez son
éditeur au premier lancement et contrôle son empreinte.

## Ce qui n'y est pas encore

- Les murs-rideaux, les fenêtres de toit et la forme des toits dans la lecture des maquettes.
- Une interface : tout se lance par la commande `rayflect`.
- Une recherche au-delà de la palette : `rayflect proposer` essaie 9 mesures passives courantes et leurs
  combinaisons, pas toutes les profondeurs de casquette ni tous les isolants.
- Le tirage d'air entre niveaux, la lame ventilée d'un mur Trombe, le sol calculé sous le bâtiment dans une
  étude (il est prouvé à part, dans `verification/dalle.py`).
- Des sources pour plusieurs hypothèses, marquées `[H]` dans le code.
- Un calcul de lumière point par point, et l'éblouissement de la norme NF EN 17037 (probabilité DGP) : ils
  demandent Radiance. L'indice d'EnergyPlus compare des protections, pas des parts de vitrage.

## Installer et essayer

Le guide pas à pas, d'un poste vierge à un premier tableau de résultats, est dans
[docs/INSTALLATION.md](docs/INSTALLATION.md). En bref, avec Python 3.11 ou plus récent et EnergyPlus 25.2 :

```bash
pip install -e ".[essais,energyplus,maquette]"
```

```bash
rayflect modele mon_etude.toml
```

```bash
rayflect etude mon_etude.toml
```

Les versions exactes du poste d'essai sont dans `verrouillage.txt`. La mise en place d'un poste de
développement est dans [CONTRIBUER.md](CONTRIBUER.md).

## Participer

- **Une question, une idée, une étude à partager** : les [Discussions](https://github.com/kelveen-hq/rayflect/discussions).
- **Une erreur dans un résultat, un plantage** : un [ticket](https://github.com/kelveen-hq/rayflect/issues/new/choose),
  avec le fichier d'étude qui la reproduit.
- **Une contribution** : lire [CONTRIBUER.md](CONTRIBUER.md), puis proposer une demande de fusion.
- **Citer Rayflect** dans un rapport ou un article : [CITATION.cff](CITATION.cff).
- Chacun suit les [règles de conduite](CODE_OF_CONDUCT.md).

Ce dont il a le plus besoin : des architectes et des bureaux d'études qui l'éprouvent sur de vrais projets.

## Qui le porte

Ce logiciel est porté par Kelveen, à Bordeaux : [kelveen.com](https://kelveen.com).

## Licence

Copyright (C) 2025-2026 Paul Trément.

Rayflect est un logiciel libre, distribué sous la licence publique générale GNU Affero, version 3 ou
ultérieure (AGPL-3.0-or-later). Le texte est dans le fichier `LICENSE`. Il est fourni sans aucune garantie.

Ce choix découle de Honeybee, sur lequel Rayflect s'appuie et qui est lui-même sous AGPL-3.0. En pratique :
chacun peut utiliser, étudier, modifier et redistribuer Rayflect, à condition de redistribuer ses
modifications sous la même licence, y compris quand il le propose comme service en ligne.

Les autres briques : IfcOpenShell est sous LGPL-3.0, ezdxf sous MIT, Shapely, pvlib et EnergyPlus sous
licences de type BSD.
