# Contribuer

## Mettre le poste en état

```bash
python -m venv .venv
.venv/Scripts/python -m pip install -e ".[essais,energyplus,maquette]"    # sous Linux et macOS : .venv/bin/python
git config core.hooksPath .githooks
```

Pour les calculs, installer [EnergyPlus](https://energyplus.net) 25.2. Sans lui, les essais qui en dépendent
sont sautés et le reste passe.

Les versions exactes du poste d'essai sont dans `verrouillage.txt`. Après la mise à jour d'un paquet : rejouer la suite,
puis refaire ce fichier par `pip freeze --exclude-editable`.

## Avant de proposer un changement

```bash
python -m ruff check .
python -m pytest                    # la série courante, environ 4 minutes avec EnergyPlus
python -m pytest -m lent            # en plus, quand le calcul, le découpage en zones ou les formes sont touchés
```

## Les règles de la maison

1. **Ne pas recalculer la physique.** Le calcul thermique et lumineux est celui d'EnergyPlus. Ce dépôt
   prépare le bâtiment, pose les protections et lit le résultat. Un calcul maison ne se garde que s'il est
   rapide et que son écart à EnergyPlus est mesuré et écrit.
2. **Chaque valeur dit d'où elle vient.** `[S]` sourcée (la source est citée), `[D]` déduite d'une valeur
   sourcée, `[H]` hypothèse à remplacer, `[C]` citée de seconde main. Une valeur sans marque est refusée.
3. **Ce qui manque se demande.** Une donnée absente de la maquette va dans la liste « à demander » ; elle
   n'est jamais devinée en silence.
4. **Un piège mesuré s'écrit là où il mord.** Quand un réglage d'EnergyPlus ou un format de fichier a trompé,
   le commentaire dit ce qui a été mesuré, à côté du code qui l'évite.
5. **Un essai par comportement**, nommé par ce qu'il prouve. Les essais ne sortent pas sur le réseau.
6. **Les données ne se redistribuent pas d'ici.** Maquettes, fichiers météo et sorties de calcul restent hors
   du dépôt ; ce qui se télécharge va dans le cache (`rayflect cache` dit où).

## Le contrôle avant commit

`outils/controle_avant_commit.py` refuse les fichiers de données, les fichiers de plus de 300 ko et les mots
interdits du poste. Ces mots se rangent dans `.git/info/motifs_interdits.txt`, une expression régulière par
ligne : le fichier reste sur le poste, il n'est ni versionné ni poussé.

## Licence

Le dépôt est sous AGPL-3.0-or-later, comme Honeybee dont il dépend. Toute contribution est reçue sous cette
licence.
