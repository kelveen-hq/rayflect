"""Le format des résultats d'une étude : ce que `resultats.json` contient, sa version, et son contrôle.

Un autre logiciel (une visualisation, un serveur) lit `resultats.json` sans lire ce code. Le format est donc écrit
à part, dans `resultats.schema.json` (JSON Schema 2020-12), et chaque fichier dit le format qu'il suit :

    "format": {"nom": "rayflect-resultats", "version": 1, "empreinte": "…"}

L'EMPREINTE est celle du schéma : les 16 premiers caractères du SHA-256 du schéma sans sa clé `x-empreinte`, clés
triées. Elle change dès que le schéma change ; un lecteur garde celle qu'il sait lire.

CHANGER LE FORMAT. Ajouter une clé facultative : même version, nouvelle empreinte. Retirer ou renommer une clé, en
rendre une obligatoire, changer le sens d'une valeur : version suivante. Dans les 2 cas, réécrire `x-empreinte`
(`python -m rayflect.resultats --ecrire-empreinte`) et le dire à ceux qui lisent.

LE CONTRÔLE. `etude.calculer` contrôle chaque bilan avant de l'écrire : un résultat qui ne suit pas son format
n'est pas écrit. Ce module contrôle la partie de JSON Schema dont le schéma se sert (type, required, properties,
additionalProperties, items, minItems, maxItems, const, minimum,
$ref local) ; il ne remplace pas un validateur complet.
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from typing import Any, Dict, List

NOM = "rayflect-resultats"
VERSION = 1
SCHEMA = Path(__file__).resolve().parent / "resultats.schema.json"
CLE_EMPREINTE = "x-empreinte"
_TYPES = {"object": dict, "array": list, "string": str, "integer": int, "number": (int, float), "null": type(None),
          "boolean": bool}


class ResultatsHorsFormat(ValueError):
    """Un bilan qui ne suit pas le format : le message dit où."""


def lire_le_schema() -> Dict[str, Any]:
    return json.loads(SCHEMA.read_text(encoding="utf-8"))


def empreinte(schema: Dict[str, Any]) -> str:
    valeurs = {k: v for k, v in schema.items() if k != CLE_EMPREINTE}
    return hashlib.sha256(json.dumps(valeurs, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()[:16]


def entete() -> Dict[str, Any]:
    """La clé « format » d'un bilan."""
    return {"nom": NOM, "version": VERSION, "empreinte": lire_le_schema()[CLE_EMPREINTE]}


def _est(valeur, nom_du_type: str) -> bool:
    if nom_du_type in ("integer", "number") and isinstance(valeur, bool):
        return False
    return isinstance(valeur, _TYPES[nom_du_type])


def _controler(valeur, schema: Dict[str, Any], racine: Dict[str, Any], chemin: str, erreurs: List[str]) -> None:
    if "$ref" in schema:
        _controler(valeur, racine["$defs"][schema["$ref"].split("/")[-1]], racine, chemin, erreurs)
        schema = {k: v for k, v in schema.items() if k != "$ref"}
    if "const" in schema and valeur != schema["const"]:
        erreurs.append(f"{chemin} : {valeur!r} au lieu de {schema['const']!r}")
    if "type" in schema:
        types = schema["type"] if isinstance(schema["type"], list) else [schema["type"]]
        if not any(_est(valeur, t) for t in types):
            erreurs.append(f"{chemin} : {type(valeur).__name__} au lieu de {' ou '.join(types)}")
            return
    if "minimum" in schema and isinstance(valeur, (int, float)) and valeur < schema["minimum"]:
        erreurs.append(f"{chemin} : {valeur} sous le minimum {schema['minimum']}")
    if isinstance(valeur, dict):
        for cle in schema.get("required", []):
            if cle not in valeur:
                erreurs.append(f"{chemin}.{cle} : manque")
        connues = schema.get("properties", {})
        en_plus = schema.get("additionalProperties", True)
        for cle, sous in valeur.items():
            if cle in connues:
                _controler(sous, connues[cle], racine, f"{chemin}.{cle}", erreurs)
            elif en_plus is False:
                erreurs.append(f"{chemin}.{cle} : clé hors du format")
            elif isinstance(en_plus, dict):
                _controler(sous, en_plus, racine, f"{chemin}.{cle}", erreurs)
    if isinstance(valeur, list) and len(valeur) < schema.get("minItems", 0):
        erreurs.append(f"{chemin} : {len(valeur)} valeurs, moins que {schema['minItems']}")
    if isinstance(valeur, list) and "maxItems" in schema and len(valeur) > schema["maxItems"]:
        erreurs.append(f"{chemin} : {len(valeur)} valeurs, plus que {schema['maxItems']}")
    if isinstance(valeur, list) and "items" in schema:
        for rang, sous in enumerate(valeur):
            _controler(sous, schema["items"], racine, f"{chemin}[{rang}]", erreurs)


def erreurs(bilan: Dict[str, Any], schema: Dict[str, Any] = None) -> List[str]:
    """Les écarts d'un bilan à son format ; une liste vide : il le suit."""
    schema = schema or lire_le_schema()
    trouvees: List[str] = []
    _controler(bilan, schema, schema, "resultats", trouvees)
    return trouvees


def controler(bilan: Dict[str, Any]) -> None:
    """Lève `ResultatsHorsFormat` si le bilan ne suit pas son format."""
    trouvees = erreurs(bilan)
    if trouvees:
        raise ResultatsHorsFormat("le bilan ne suit pas le format des résultats : " + " ; ".join(trouvees[:8]))


def main(argv: List[str]) -> int:
    schema = lire_le_schema()
    if "--ecrire-empreinte" in argv:
        texte = SCHEMA.read_text(encoding="utf-8")
        ancienne, nouvelle = schema[CLE_EMPREINTE], empreinte(schema)
        SCHEMA.write_text(texte.replace(f'"{CLE_EMPREINTE}": "{ancienne}"', f'"{CLE_EMPREINTE}": "{nouvelle}"'),
                          encoding="utf-8", newline="\n")
        print(f"{CLE_EMPREINTE} : {ancienne} -> {nouvelle}")
        return 0
    code = 0
    for fichier in argv:
        trouvees = erreurs(json.loads(Path(fichier).read_text(encoding="utf-8")), schema)
        print(f"{fichier} : {'suit le format' if not trouvees else f'{len(trouvees)} écart(s)'}")
        for ligne in trouvees:
            print(f"  {ligne}")
        code = code or (1 if trouvees else 0)
    return code


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
