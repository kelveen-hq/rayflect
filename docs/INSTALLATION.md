# Installer Rayflect et jouer une première étude

Ce guide part d'un poste vierge et finit sur un tableau de résultats. Compter 20 minutes, dont l'essentiel en
téléchargements.

Rayflect se lance en ligne de commande : il n'a pas encore de fenêtre ni de boutons. Il a été joué sous
Windows 11 avec Python 3.13 et EnergyPlus 25.2. Les commandes pour Linux et macOS sont données quand elles
diffèrent ; elles n'ont pas été essayées sur ces systèmes.

## 1. Ce qu'il faut sur le poste

| Logiciel | Version | Où le prendre | À quoi il sert |
|---|---|---|---|
| Python | 3.11 ou plus récent ; essayé en 3.13 | [python.org](https://www.python.org/downloads/) | Faire tourner Rayflect |
| EnergyPlus | 25.2 | [energyplus.net](https://energyplus.net/downloads) | Le calcul thermique et lumineux |
| Git | toute version récente | [git-scm.com](https://git-scm.com) | Récupérer le code |

Sous Windows, prendre le Python de python.org plutôt que celui du Microsoft Store : ce dernier range ses
fichiers dans un dossier à lui, qu'EnergyPlus ne sait pas lire.

EnergyPlus s'installe à son emplacement par défaut (`C:\EnergyPlusV25-2-0` sous Windows). Rayflect le trouve
là sans réglage. Une autre version peut marcher, mais les résultats ne sont vérifiés qu'avec la 25.2 : le
compte rendu d'une étude le signale.

## 2. Installer

Dans un terminal, depuis le dossier où ranger le code :

```bash
git clone <adresse du dépôt> rayflect
```

```bash
cd rayflect
```

```bash
python -m venv .venv
```

Sous Windows :

```bash
.venv\Scripts\python -m pip install -e ".[essais,energyplus,maquette]"
```

Sous Linux et macOS :

```bash
.venv/bin/python -m pip install -e ".[essais,energyplus,maquette]"
```

Les 3 groupes entre crochets : `energyplus` pour calculer, `maquette` pour lire les fichiers IFC et DXF,
`essais` pour rejouer les essais du dépôt. Pour retrouver exactement les versions du poste d'essai :

```bash
.venv\Scripts\python -m pip install -r verrouillage.txt
```

## 3. Vérifier que tout est en place

Sous Windows, la commande est `.venv\Scripts\rayflect` ; ailleurs, `.venv/bin/rayflect`. La suite du guide
écrit `rayflect` tout court.

```bash
rayflect cache
```

rend le dossier où seront rangées la météo et les cartes téléchargées. Si cette ligne s'affiche, Rayflect est
installé.

```bash
.venv\Scripts\python -m pytest
```

rejoue les essais du dépôt, en 4 minutes environ. Sans EnergyPlus, ceux qui en dépendent sont sautés : un grand
nombre d'essais « skipped » veut dire qu'EnergyPlus n'a pas été trouvé.

## 4. Une première étude, sans maquette

Créer un fichier `essai.toml` avec ce contenu. Il décrit un immeuble de bureaux de 2 niveaux à Bordeaux par
ses chiffres, et compare 4 façons de le tenir au frais.

```toml
usage = "bureau"
periode = "1975_1988"
ombres_tous_les_n_jours = 30        # un calcul rapide pour un premier essai ; 1 par défaut

[lieu]
latitude = 44.841
longitude = -0.570

[batiment]
longueur_m = 30.0
largeur_m = 12.0
niveaux = 2
hauteur_d_etage_m = 3.0
vitrage_m2 = { S = 60.0, N = 40.0 }

[[scenario]]
nom = "tel quel"

[[scenario]]
nom = "casquettes"
[[scenario.element]]
type = "casquette"
profondeur_m = 1.0
orientations = ["S"]

[[scenario]]
nom = "nuit ouverte"
[[scenario.element]]
type = "ouvrants"
heures = [0, 24]
traversant = true

[[scenario]]
nom = "les 2"
[[scenario.element]]
type = "casquette"
profondeur_m = 1.0
orientations = ["S"]
[[scenario.element]]
type = "ouvrants"
heures = [0, 24]
traversant = true
```

Puis :

```bash
rayflect etude essai.toml
```

Le premier lancement demande le réseau : la météo du lieu est prise à PVGIS, le service de la Commission
européenne, puis gardée dans le cache. La commande annonce ses étapes, puis un pourcentage et le temps restant.
Sur le poste d'essai, cette étude prend moins d'une minute.

À la fin s'affichent : ce qui a été supposé et d'où vient chaque valeur, ce qui reste à demander, puis les
tableaux. Les mêmes résultats sont écrits dans `sorties/essai/resultats.json`, à côté du fichier d'étude.

## 5. Avec une vraie maquette

```bash
rayflect releve batiment.ifc
```

dit ce qui a été lu dans la maquette, et ce qui y manque. Puis :

```bash
rayflect modele mon_etude.toml
```

écrit un fichier d'étude commenté, à remplir : la maquette, l'adresse, l'usage, les scénarios. Tout ce qu'une
étude peut régler est décrit en tête de `src/rayflect/etude.py`.

## 6. Quand ça ne marche pas

| Ce qui s'affiche | Ce que ça veut dire | Quoi faire |
|---|---|---|
| `ÉTUDE NON JOUÉE : ...` | Le fichier d'étude a un défaut ; la suite du message dit lequel | Corriger la ligne nommée |
| Un message sur EnergyPlus introuvable | EnergyPlus n'est pas installé, ou pas à son emplacement par défaut | L'installer comme au point 1 |
| `météo inutilisable` | Le fichier rendu par PVGIS a un défaut que le contrôle n'a pas pu réparer | Donner un fichier météo par `meteo = "fichier.epw"` dans `[lieu]` |
| `lieu à demander` | L'adresse n'a pas été trouvée | Donner `latitude` et `longitude` |
| `EnergyPlus a rendu un calcul fautif` | EnergyPlus a signalé une erreur grave | Lire le fichier `eplusout.err` du scénario, dont le chemin est donné |
| Un calcul très long | Les ombres sont recalculées chaque jour, et le bâtiment a beaucoup de masques | `ombres_tous_les_n_jours = 7` dans le fichier d'étude |

## 7. Ce que Rayflect va chercher sur le réseau

Rien n'est envoyé d'autre que la position du bâtiment ou l'adresse tapée. Tout ce qui est reçu est gardé dans
le cache et n'est pas redemandé.

| Donnée | Service | Quand |
|---|---|---|
| Météo d'une année type | [PVGIS](https://re.jrc.ec.europa.eu/pvg_tools/fr/), Commission européenne | À chaque nouveau lieu, sauf si un fichier météo est donné |
| Position d'une adresse | Géocodeur de l'[IGN](https://geoservices.ign.fr), France | Si le lieu est donné par une adresse |
| Commune, altitude | Services de l'IGN | Pour compléter le lieu ; sans réponse, le calcul continue |
| Bâtiments voisins | BD TOPO de l'IGN, France | Si l'étude demande `voisins = true` |
| Prix de l'énergie | Eurostat | Si l'étude porte une table `[energie]` sans prix |

Sans réseau, une étude se joue avec des coordonnées, un fichier météo donné et `voisins = false`.
