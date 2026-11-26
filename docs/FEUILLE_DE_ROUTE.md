# Feuille de route

Ce document liste les branches de travail qui ne sont pas encore faites. Pour chacune : ce qu'elle doit
apporter, par quel moyen, ce qui a déjà été vérifié, et ce qui reste inconnu. Une branche n'est pas une
promesse : tant qu'elle est ici, elle n'est pas dans le code.

Repères : **mesuré** veut dire essayé pour de bon, avec la date ; **non essayé** veut dire que le moyen est
connu mais que personne ne l'a encore fait tourner ici.

## Ce qui existe aujourd'hui

- Lecture d'une maquette IFC, conversion en bâtiment calculable, zones de façade et noyau.
- Hypothèses d'usage, d'aération et de parois, chacune avec son origine.
- Protections : casquette, joues, balcon, lames horizontales et verticales, lames à 2 positions, lames
  pilotées, BSO à 4 pilotages dont les occupants réels.
- Végétation : arbres, pergola, plante grimpante, avec un feuillage décrit par son indice foliaire.
- Croissance : un arbre suit la courbe de son essence (tilleul, robinier, platane), une plante grimpante monte
  le long du mur ; une étude compare la même plantation à plusieurs âges.
- Bâtiment décrit par un autre logiciel au format « bâtiment commun » : la provenance de chaque valeur est
  gardée, un niveau peut ne pas être chauffé, une façade peut être mitoyenne.
- Bâtiment par ses chiffres, sans maquette ni plan ; usage réglable (apports, air neuf, horaires, consignes,
  réduit) ; apport de chaleur horaire lu dans un fichier ; point d'extension pour les types d'un autre paquet.
- Le dehors, réglable : température du sol sous le plancher, loi d'échange des parois avec le vent, teinte des
  murs et du toit, fichier météo donné ; air neuf à débit réduit hors occupation, en avance et en maintien.
- Besoin de froid rendu en sensible, la vapeur condensée à côté ; air neuf d'une simple flux entrant tel qu'il
  est dehors.
- Données du lieu : d'un nom de ville ou d'une adresse viennent la commune, le département, l'altitude (IGN),
  la zone climatique, la température de base et un terrain proposé. Une adresse trouvée dans une autre ville
  que celle demandée est signalée.
- Puissance à installer : chauffage au jour de base (température à donner, consigne tenue sur la température
  ressentie), pointes de chauffage et de froid de l'année type, par scénario.
- Variantes de conception : un scénario change le vitrage d'une façade (baies agrandies, bandeau, tout vitré,
  mur plein) ou les parois, et se compare à la maquette.
- Toiture : couleur du toit, photovoltaïque.
- Ventilation mécanique : simple flux, double flux, surventilation de nuit ; réglable scénario par scénario.
- Ventilation naturelle : un scénario dit quelles fenêtres s'ouvrent, à quelles heures, et si la pièce est
  traversante. Le débit vient du vent et du tirage, ouvrant par ouvrant.
- Mur Trombe à lame fermée, en allège, avec tablette ou ouverture d'été ; rejoué contre une cellule mesurée.
- Sondes géothermiques : un champ posé sur les besoins d'un scénario, la température de l'eau suivie sur
  plusieurs années.
- Environnement : bâtiments voisins de la BD TOPO de l'IGN, calage de la maquette sur la carte.
- Lumière du jour au centre de chaque zone et à 1 m de sa façade la plus vitrée ; trop de lumière et éblouissement.
- Vérification : 13 cas de la norme ANSI/ASHRAE 140 (masques, ventilation de nuit, serre), 16 cas de dalle,
  le débit des ouvrants et la réponse thermique d'une sonde contre leurs formules.

## Branche 0 : une météo qui dise vrai sur l'été

**Constat, mesuré le 15/11/2026.** La météo vient aujourd'hui de l'année type de PVGIS. Trois limites :

- Elle assemble 12 mois pris dans des années différentes, choisis pour le soleil. À Lille, le mois de juillet
  retenu est celui de 2011 : 15,8 °C de moyenne, plus froid que le mois de juin retenu (19,3 °C).
- Près de la mer, les maximums d'été sont écrêtés : 25,8 °C de maximum moyen en juillet sur le port de
  Marseille, contre 30,1 °C à Aix-en-Provence.
- Un fichier sur 7 était défectueux : rayonnement du ciel de 13 W/m² au lieu d'environ 320. Le contrôle et la
  réparation sont faits (`io/meteo`).

**Ce que la branche doit faire.** Calculer sur des années réelles, dont un été chaud, et dire sur quelle
année porte chaque résultat. Une année type reste bonne pour comparer des protections entre elles.

**Fait (23/11/2026, `io/climats`).** Une année réelle d'ERA5 (Copernicus) par Open-Meteo, l'été le plus chaud depuis
2000, et le climat 2040-2049 : l'année type déformée par la méthode de Belcher avec les écarts de 7 modèles CMIP6.
Une étude se rejoue sous plusieurs climats et les compare (`[lieu] climat = [...]`). À Bordeaux, l'été le plus chaud
depuis 2000 est celui de 2003 (23,7 °C de moyenne de juin à août, contre 21,9 °C dans l'année type) ; celui de
2040-2049 gagne +1,6 °C en moyenne des modèles, de +1,1 à +2,9 °C selon le modèle.

L'humidité relative, le soleil et le vent sont déformés comme la température. « futur_chaud » décale l'été réel le
plus chaud depuis 2000 vers 2040-2049 : une canicule réelle dans le climat qui vient.

**Ce qui reste.** L'API climatique s'arrête au 1er janvier 2050 : rien pour 2070 ou 2100. L'îlot de chaleur urbain
n'est pas compté : une réanalyse de 11 km voit la campagne autour de la ville autant que la ville. Les données
d'Open-Meteo sont gratuites pour un usage non commercial seulement, et limitées en volume par heure.

## Le mur végétalisé (fait le 23/11/2026, `vegetation.MurVegetal`)

Des modules plantés à 5 cm des murs pleins : leur ombre opaque, la résistance mesurée en caisson chaud (0,155 m².K/W
lame ventilée, 0,35 fermée), et le mur qui voit le dos des modules plutôt que le ciel [S : Weinläder et al., EuroSun
2024]. À Bordeaux, mur sud d'absorption 0,6, peu isolé : degrés-heures de 260 à 210, chauffage +4 % ; un enduit
clair fait mieux l'été (130) et perd plus l'hiver.

**L'évaporation (fait le 23/11/2026, `evaporation`).** L'eau évaporée heure par heure, par la méthode de Hoffmann et al.
(HESS 2023, Penman-Monteith verticalisé, validé sur lysimètre), donne la température des modules que voit le mur. À
Bordeaux, mur sud : 2,8 L par m² et par jour l'été, dans les 2,5 à 5 L mesurés sur des murs arrosés ; degrés-heures de
232 sans arrosage à 215 arrosé.

**La confrontation au banc de Würzburg (24/11/2026, `verification/mur_vegetal_wurzburg.py`).** Les mêmes murs, la
météo réelle d'ERA5, les mêmes périodes. L'hiver tient (U effectif +8 % pour −4 à +16 % mesurés). L'été ne tient pas,
d'abord pour le mur nu : l'enduit clair y retire 86 % des gains de chaleur du mur face à l'enduit moyen, 35 % sur le
banc. Tant que cet écart n'est pas compris, l'été du mur végétalisé n'est pas validé ; ses gains d'été y sont sans doute
trop forts (le dos des modules est traité comme un écran mince au soleil, pas abrité par le substrat).

**Ce qui reste.** Comprendre l'écart d'été du mur nu (les données horaires du banc, auprès du projet U-green du CAE de
Würzburg, trancheraient) ; l'épaisseur du substrat derrière le feuillage ; le rayonnement de grande longueur d'onde du
couvert ; le vent de la rue ; la pluie ; les ponts thermiques des fixations ; le carbone des modules (carbone_kg).

## Branche 1 : la végétation existante autour du bâtiment, en France

**Ce qu'elle doit faire.** Trouver d'elle-même les arbres et les haies qui ombrent le bâtiment, au lieu de
les faire saisir un par un.

**Par quel moyen.**

| Donnée | Source | État |
|---|---|---|
| Emprise des bois et des haies, feuillus ou conifères | BD TOPO de l'IGN, couche `zone_de_vegetation` | Mesuré le 15/11/2026 : 13 objets dans 200 m autour d'un parc de Bordeaux (9 haies, 2 bois, 2 forêts dont 1 de feuillus). La nature distingue feuillus, conifères et mixte, ce qui donne caduc ou persistant. **Aucune hauteur.** |
| Hauteur de la végétation | Modèle numérique de hauteur tiré du LiDAR HD de l'IGN | Non essayé. C'est une image, pas une liste d'objets : il faut la lire sous chaque emprise. |
| Arbres de rue, un par un | Inventaires publiés par les villes sur data.gouv.fr | Non essayé. Un jeu par ville, chacun avec ses champs : hauteur, essence et diamètre n'y sont pas toujours. |

**Ce qui reste inconnu.** L'indice foliaire par essence : le catalogue actuel porte des ordres de grandeur
non sourcés. La densité réelle d'une haie ou d'un bois vu de côté.

## Branche 2 : l'Europe

**Ce qu'elle doit faire.** Rendre le même service hors de France : météo, voisins, hypothèses du pays.

**Est-ce faisable ?** Oui, mais de façon inégale, et pays par pays pour la qualité.

| Sujet | Moyen | État |
|---|---|---|
| Météo | PVGIS couvre déjà toute l'Europe | Fait : la chaîne prend la météo à la position de la maquette, où qu'elle soit. |
| Lecture des maquettes | L'IFC est un format international | Fait : les maquettes d'essai sont allemandes et américaines. |
| Bâtiments voisins, en direct | OpenStreetMap par le service Overpass, gratuit, sans clé, licence ODbL | Mesuré le 23/08/2026 sur un carré de 180 m au centre de 6 villes : 55 bâtiments à Bordeaux dont 10 avec hauteur, 114 à Bruxelles dont 13, 17 à Madrid dont 6, 35 à Lisbonne dont 2, mais 2 à Berlin et 3 à Milan. Réponse en 1,4 à 9,3 secondes. La hauteur manque le plus souvent. |
| Bâtiments voisins, en base | EUBUCCO : 322 millions de bâtiments de l'Union, de la Norvège, de la Suisse et du Royaume-Uni, avec type, hauteur, étages et année ; licence ODbL pour l'essentiel | Non branché. C'est un téléchargement, pas un service : il faut un serveur, ou n'extraire que les pays visés. |
| Bâtiments voisins, par pays | Registres nationaux ouverts, que la directive européenne sur les données ouvertes oblige à publier | Non essayé hors de France. Le chemin le plus solide, mais une intégration par pays. |
| Hypothèses du pays | Typologies nationales de bâtiments du projet européen TABULA / EPISCOPE pour les parois par période ; réglementations nationales pour les consignes et les débits d'air | Non fait. Les valeurs actuelles sont françaises, et celles des parois ne sont pas sourcées. |
| Règles de calcul | Profondeur de la zone éclairée par le jour : même formule en France, en Allemagne, au Luxembourg et dans la norme européenne ; 6 m au Royaume-Uni et en Irlande ; 5 m en Espagne | Fait pour la formule européenne. Les autres sont relevées dans le code, pas encore sélectionnables par pays. |

**La règle à tenir.** Un voisin sans hauteur connue n'est pas repris comme masque, et il est compté dans ce
qui manque. Deux bâtiments trouvés au centre d'une grande ville ne sont pas un résultat mais une absence de
données, et l'outil doit le dire.

**Ordre proposé.** 1. Une interface commune « source de voisins », avec la BD TOPO en France et Overpass
ailleurs en repli. 2. EUBUCCO pour un premier pays, extrait une fois. 3. Les hypothèses nationales, pays
par pays.

## Branche 3 : la lecture des maquettes réelles

- Les murs-rideaux, qui ne sont pas des fenêtres dans l'IFC : relever leur vitrage.
- Les fenêtres de toit et les toits en pente, aujourd'hui ignorés ou aplatis.
- Les cours intérieures.
- Un essai sur des maquettes d'architectes français. Cherché le 15/11/2026 : aucun portail public français ne
  publie de maquette IFC de bâtiment en téléchargement direct. Essayées à la place : des bureaux à
  Aix-la-Chapelle et à Tallinn, des logements à Tallinn, sous licence ouverte. Elles ont révélé 4 défauts,
  corrigés : le zéro du bâtiment décalé de l'altitude du terrain, les niveaux sans locaux, les murs qui ne
  ferment pas, le niveau de toiture pris pour un étage.
- Les fenêtres dont la géométrie ne se lit pas, et celles qu'aucun mur du volume simplifié ne porte : 9 baies
  sur 66 sur les bureaux de Tallinn.
- Une extension pour SketchUp.

### Les plans DXF

`io/lecture_dxf` lit un plan par niveau et en tire le même relevé qu'une maquette. Éprouvé le 15/11/2026 sur 13
plans publics pris au hasard : maisons nord-américaines, bâtiments universitaires brésiliens dont un sur 3
niveaux, logements coréens, une villa à terrasses, des plans produits par des générateurs.

| Sans aucun réglage | Plans |
|---|---|
| Lus juste | 3 |
| Lus avec un écart, signalé | 4 (murs en partie sur un calque non reconnu, murets pris dans le contour, planche à plusieurs dessins) |
| Refusés avec la marche à suivre | 6 (calques au nom inconnu, unité écrite fausse) |

« Juste » veut dire : contour et baies conformes au dessin, jugés à l'œil sur une planche de contrôle.
Une fois les calques ou l'unité nommés comme le message le demande, 12 sur 13 sont lus juste. Le 13e est une
planche qui porte plusieurs dessins : le lecteur en garde un seul et le dit. Aucun des 3 bâtiments
universitaires n'a de calque de baies : leurs fenêtres ne peuvent pas être lues.

Ce que ces plans ont appris, et qui est traité : une unité écrite fausse dans le fichier, des calques qui
mêlent portes et fenêtres, des abréviations de calque (A-WIN), un bloc à l'échelle nulle qui faisait tomber la
lecture, un trait perdu qui laissait une épine au contour, des murs interrompus sur plus de 3 m, et le cas le
plus traître : un contour incomplet que seules des baies restées dehors trahissent. Reste à faire :

- Un essai sur des plans d'architectes français, avec leurs noms de calques.
- Les cours intérieures et les bâtiments en plusieurs corps : seul le plus grand contour est gardé.
- Les planches qui portent plusieurs dessins : choisir le bon, ou les séparer.
- Les plans dont tout est sur un seul calque : leurs fenêtres ne se distinguent pas des murs.
- Les baies sans calque à elles, à reconnaître aux interruptions des murs.
- Les portes vitrées, les murs-rideaux dessinés d'un seul trait.
- Le calage entre les plans de 2 niveaux qui ne partagent pas le même repère.
- Les hauteurs lues dans une coupe ou une façade, aujourd'hui données à la main.
- Le DWG, qui demande un convertisseur ; le PDF vectoriel, qui n'a pas de calques sûrs.

## Branche 4 : la bibliothèque de composants

Ce qui manque, avec le moyen connu :

| Composant | Moyen dans le moteur de calcul |
|---|---|
| Store banne, store vertical en toile | Store d'EnergyPlus devant la vitre, avec la transmission de la toile |
| Volet roulant, volet battant | Écran opaque piloté ; isolation de nuit par résistance ajoutée |
| Vitrage à contrôle solaire, film, vitrage électrochrome | Changement de vitrage, fixe ou piloté |
| Résille, tôle perforée, moucharabieh | Masque à transparence constante, ou store à lames fines |
| Double peau | Zone tampon vitrée devant la façade |
| Toiture végétalisée | EnergyPlus a un modèle de toiture plantée, avec évaporation |
| Ombrière de parking, auvent détaché | Masque détaché, avec ou sans photovoltaïque |

## Branche 5 : ce que la physique ne couvre pas encore

- La fraîcheur que donne la végétation par évaporation. Seule l'ombre est calculée.
- L'indice foliaire selon l'âge : il garde sa valeur d'adulte. La seule mesure trouvée dit qu'il double chez
  le tilleul entre moins de 20 ans et 60 à 80 ans, et ne bouge pas chez le platane ; un jeune tilleul fait donc
  une ombre moins dense que celle calculée.
- La croissance d'une pergola, et celle des essences sans courbe lue : érable, févier, pin. La base de
  McPherson et al. 2016 (USDA, PSW-GTR-253) les donnerait ; elle n'a pas pu être lue.
- Des courbes de croissance mesurées en France : celles du catalogue viennent de Bavière et de Copenhague.
- Les cadres et les ponts thermiques propres à un mur-rideau : une façade passée en tout vitré garde le
  vitrage de l'étude.
- La lumière point par point et l'éblouissement de la norme (DGP), qui demandent Radiance. L'indice DGI
  d'EnergyPlus baisse devant une très grande baie : il ne compare pas des parts de vitrage.
- Le thermostat réel, qui sent un peu l'air et un peu les parois selon l'émetteur : l'étude choisit entre
  les 2 bornes, `consigne = "air"` ou `"ressentie"`. Le type d'émetteur n'est pas une entrée.
- La puissance de froid un jour de canicule : la pointe rendue est celle d'un été ordinaire. Un jour de base
  d'été demande que les plannings des protections et des feuillages y soient réglés un par un.
- La température du sol sous la dalle par le calcul (préprocesseur de dalle d'EnergyPlus, ou ISO 13370) : elle
  est donnée, ou prise à 18 °C.
- La vapeur d'eau condensée par la climatisation : elle sort d'un air soufflé à 13 °C, réglage par défaut du
  système idéal, et pèse la moitié du froid sensible sur un immeuble de bureaux à Bordeaux. À relier à une
  machine réelle.
- La température extérieure de base lue dans la norme NF P52-612/CN : celle du dépôt vient de recopies qui
  concordent, et porte la mention « à confirmer ». La correction côtière de la norme n'est pas reprise.
- Le terrain autour du bâtiment : il est proposé d'après la population de la commune, faute de mieux. La
  densité bâtie de la BD TOPO, déjà téléchargée pour les voisins, en dirait plus.
- Les données du lieu hors de France : commune, altitude, zone et température de base viennent de sources
  françaises.
- La consommation des ventilateurs et des pompes.
- Une protection à géométrie mobile au-delà d'une lame d'un mètre.

### Climatisation, parois et énergie

Faits le 15/11/2026 : le bâtiment climatisé (besoin de froid en kWh), les parois décrites par l'utilisateur
(place et épaisseur de l'isolant, type de vitrage, inertie), et la conversion des besoins en énergie achetée,
en CO2 et en euros. Les facteurs d'émission sont lus dans l'arrêté du 31 mars 2021 relatif au DPE. Les prix de
l'électricité et du gaz viennent d'Eurostat. Reste à faire :

- Fait le 22/11/2026 : les valeurs par défaut des parois, du vitrage, de l'étanchéité, des matériaux, des
  usages et de l'ouverture des fenêtres sont lues dans des textes publics : méthode 3CL-DPE 2021 (annexe 1 de
  l'arrêté du 31 mars 2021), règles Th-bât 2017 et Th-U Ex 2008, méthode Th-BCE 2020 de la RE2020 (annexe III de
  l'arrêté du 4 août 2021, consolidée en mars 2026). Les études jouées avant cette date sont à rejouer : sur des
  bureaux de 1975 à 1988 à Bordeaux, les heures au-dessus de 26 °C baissent de 13 % et le chauffage monte de
  2 % ; sur ceux de 2006 à 2012, le chauffage est multiplié par 3,4, l'étanchéité par défaut de la 3CL étant bien
  moins bonne que l'ancienne hypothèse.
- Ce qui reste supposé, et pourquoi :
  - la 3CL est écrite pour le logement : rien de publié ne donne de valeurs par défaut pour le tertiaire existant ;
  - la colonne des chauffages « autres » que l'effet Joule, la colonne « immeuble » de la perméabilité, une
    fenêtre battante en PVC, un vitrage d'origine par période : des choix, signalés comme tels ;
  - la zone H2 quand le lieu n'est pas en France métropolitaine ;
  - l'école fermée l'été, quand la RE2020 compte 50 % de présence en juillet et août ;
  - l'air neuf d'un logement (0,5 volume par heure) : la RE2020 prend le débit du système du projet ;
  - la surface d'un logement (60 m²) pour le nombre d'occupants ;
  - le facteur solaire d'un vitrage à contrôle solaire, l'épaisseur des parois lourdes, la teinte des murs et
    du toit ;
  - le rendement des systèmes de chauffage et de climatisation, et les valeurs des modules de sondes, du mur
    Trombe, de la végétation et de la lecture des plans.
- Une climatisation aux heures d'occupation seulement, et une consigne de nuit pour le chauffage : aujourd'hui
  les 2 consignes valent à toute heure.
- Le rendement d'une pompe à chaleur selon la température du dehors, heure par heure : la courbe existe dans
  `services/analysis/pac_model`, elle n'est pas branchée.
- Le prix des autres énergies (fioul, bois, propane, réseau de chaleur) : aucun n'est supposé, il se donne.
- Les facteurs d'émission hors de France, et celui de chaque réseau de chaleur.
- L'électricité produite par des panneaux en toiture, à déduire de l'électricité achetée.
- Les autres usages (éclairage, ventilateurs, eau chaude), pour approcher la facture entière et choisir la
  bonne tranche de prix.

## Branche 5 bis : l'air et le sol, ce qui reste après les lots E et F

État au 19/11/2026. Les lots E (ventilation naturelle) et F (sondes) sont dans le code ; voici ce qu'ils ne
font pas.

**Ventilation naturelle.**

- Le tirage d'un niveau à l'autre (cage d'escalier, atrium, cheminée) et les portes intérieures : ils demandent
  le réseau de flux d'air d'EnergyPlus (`AirflowNetwork`), que Honeybee n'écrit pas dans le fichier. Non essayé.
- Le débit réel d'une fenêtre : `verification/ouvrants.py` contrôle les formules, pas la réalité. Aucun cas
  normalisé n'existe ; les 15 bâtiments suivis de l'annexe 62 de l'AIE ne sont pas ouverts.
- Jusqu'au 19/11/2026, l'étude sans élément `ouvrants` ouvrait ses fenêtres avec les réglages de Honeybee :
  toute la hauteur de la baie comptée comme hauteur de tirage, coefficient 0,45, aucun vent, soit 3,2 fois le
  débit de tirage des formules [D]. Elle passe maintenant par `rayflect.aeration`. Sur des bureaux de 2 niveaux
  à Bordeaux, fenêtres ouvertes en occupation, les heures au-dessus de 26 °C passent de 409 et 786 par niveau
  à 530 et 875 : les études sans climatisation jouées avant cette date sont à rejouer.
- La pluie, le bruit, la sécurité, et le geste des occupants, remplacés par une règle de température.

**Sondes géothermiques.**

- Une mesure réelle : l'essai en bac à sable de Beier et al. (2011), sonde de 18 m, 1 142 W pendant 52 heures.
  Ses relevés sont publics ; ils ne sont pas dans le dépôt.
- Le rendement de la pompe à chaleur selon la température de l'eau : il est constant.
- Le bâtiment qui sent la boucle : un géocooling dont l'eau revient trop chaude ne rafraîchit plus, et le calcul
  du bâtiment ne le sait pas. Le bilan dit seulement quelle part du froid tombe quand l'eau est assez froide.
- La consommation de la pompe de circulation ; l'eau chaude sanitaire ; une nappe qui s'écoule ; un champ qui
  n'est pas une grille ; les capteurs horizontaux.

## Branche 5 ter : le lot G

**Fait le 19/11/2026 : le mur Trombe à lame fermée** (`rayflect.trombe`). Ce qu'il ne fait pas :

- La lame ventilée vers la pièce : EnergyPlus n'a pas de convection validée pour elle, et le seul jeu de
  mesures ouvert trouvé (cellules d'essai au Chili) ne donne ni débit ni température de surface.
- Le mur ailleurs qu'en allège d'un mur droit : un trumeau entre 2 baies, un mur en biais.
- Un store ou un isolant de nuit devant la vitre ; les ponts thermiques du cadre.
- La preuve dans le dépôt : les mesures de Los Alamos viennent d'une thèse, et le banc ne se joue que si on
  lui donne son texte. Le banc prouve le montage, il distingue mal l'algorithme `TrombeWall` d'une convection
  ordinaire.
- Le soleil suivi à l'intérieur change aussi le bâtiment de référence : une étude qui porte un mur Trombe ne
  rend pas les mêmes chiffres pour « sans » qu'une étude qui n'en porte pas.

**Reste à faire.** Pour chacun : le moyen dans EnergyPlus, la preuve possible, ce que ça coûte.

| Sujet | Moyen | Preuve possible | Ce que ça demande |
|---|---|---|---|
| Matériaux à changement de phase | Une couche de plus côté intérieur, calcul des parois en différences finies, 20 pas par heure | Aucun cas normalisé ; des validations publiées du modèle d'EnergyPlus, non lues | Tous les scénarios d'une étude passent en différences finies, pour rester comparables : un calcul de l'ordre de 15 fois plus long [H, non mesuré]. |
| Cheminée solaire | `ZoneThermalChimney`, une zone vitrée de plus | Aucune trouvée | Sans stratification dans le modèle, le résultat est un ordre de grandeur. |
| Fraîcheur des arbres | Aucun modèle dans EnergyPlus : il faudrait corriger la météo autour du bâtiment | Aucune à l'échelle d'un bâtiment | Un sujet de recherche. Les outils de quartier existants sont sous licence GPL ou MPL. |

Ordre proposé : le changement de phase ensuite. La cheminée solaire et la fraîcheur des arbres n'ont pas de
preuve en vue : à ne pas coder tant qu'il n'y en a pas.

## Branche 5 quater : le bâtiment commun, ce qui n'est pas encore lu

Fait le 20/11/2026 : `io/lecture_batiment_commun` lit la version 1 du format. Ce qu'il dit sans le calculer :

- L'usage de chaque niveau : un niveau chauffé prend l'usage de l'étude. Un atelier chauffé sous des bureaux
  est calculé comme des bureaux.
- Une partie chauffée d'un niveau (`part_chauffee`, `surface_chauffee_m2`) : seul un niveau entier se dit non
  chauffé.
- La teinte des murs et le toit tels qu'ils sont ; les protections déjà posées ; les obstacles dessinés ; le
  masque et le voisin de chaque façade.
- Le détail de chaque baie (type, vitrage, occultation) : le vitrage de l'étude vaut pour toutes.
- Les cours et les corps séparés (`trous_m`, `autres_emprises_m`).
- Ce qui décrit l'étude plutôt que le bâtiment (usage, période, vitrage, inertie, énergie) : le compte rendu
  donne la ligne à écrire dans le fichier d'étude, rien n'est repris d'office.
- Le contrôle complet du schéma : seuls la provenance de chaque valeur et les azimuts sont contrôlés ici.

Hypothèses à sourcer : le plancher entre un niveau non chauffé et ses voisins est en béton de 20 cm sans
isolant ; le voisin mitoyen est chauffé comme le bâtiment ; un niveau non chauffé n'a aucun apport interne.

Mesuré le 20/11/2026, bureaux sur atelier à Bordeaux, 2 niveaux de 288 m² : dire l'atelier non chauffé baisse
le chauffage du bâtiment de 10 % avec le sol à 18 °C (16 434 à 14 759 kWh), de 16 % avec un sol qui suit l'air
(21 246 à 17 815 kWh). Le chauffage des bureaux seuls monte de 16 % et de 40 % : leur plancher donne sur un
atelier froid. Avant ce lecteur, l'atelier était calculé comme chauffé.

## Branche 6 : la vérification

- Des cas d'épreuve pour les protections mobiles et la lumière : la série ANSI/ASHRAE 140 n'en a pas.
- Les critères d'acceptation de la norme, qui portent sur les écarts entre cas.
- Des sources pour chaque hypothèse marquée `[H]` dans le code.
- Une relecture par des pairs.
