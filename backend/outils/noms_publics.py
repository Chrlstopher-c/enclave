"""Noms publics des outils : ce que le MODÈLE voit, distinct des noms internes du harnais.

Constaté le 2026-11-10 (Ornith 1.5, base Qwen) : le modèle appelait `read_file` — le nom qu'il a
appris — et perdait un tour sur « l'outil n'existe pas ». Les noms internes (`lire_fichier`,
`chemin`…) restent ceux du code, de l'historique enregistré et de l'interface ; cette frontière les
traduit dans les deux sens, à un seul endroit :

- vers le moteur (`publier_outils`, `publier_messages`) : définitions, prompt, résultats, appels
  passés — noms d'outils et d'arguments anglais, ceux des harnais d'agents courants ;
- depuis le moteur (`interne`) : un appel émis redevient interne avant exécution. Les anciens noms
  français et les réflexes courants (`bash`, `cat`, `ls`, `grep`…) sont acceptés en silence.
"""

from __future__ import annotations

import re
from typing import Any

# nom interne -> (nom public, {argument interne: argument public})
_TABLE: dict[str, tuple[str, dict[str, str]]] = {
    "suivre_taches": ("todo_write", {"taches": "tasks", "titre": "title", "etat": "status", "raison": "reason",
                                     "preuve": "evidence"}),
    "recherche_web": ("web_search", {"requete": "query", "nombre_resultats": "max_results"}),
    "recuperer_page": ("web_fetch", {}),
    "ecrire_fichier": ("write_file", {"chemin": "path", "contenu": "content"}),
    "ecrire_fichiers": ("write_files", {"fichiers": "files", "chemin": "path", "contenu": "content"}),
    "plan_fichier": ("file_outline", {"chemin": "path"}),
    "lire_fichier": ("read_file", {"chemin": "path", "ligne_debut": "start_line", "ligne_fin": "end_line"}),
    "modifier_fichier": ("edit_file", {"chemin": "path", "ancien": "old_string", "nouveau": "new_string"}),
    "lister_fichiers": ("list_files", {"motif": "glob"}),
    "chercher_dans_fichiers": ("search_files", {"texte": "pattern", "motif": "glob"}),
    "executer_python": ("run_python", {"fichier": "path"}),
    "executer_commande": ("run_command", {"commande": "command"}),
    "serveur_fond": ("background_process", {"nom": "name", "commande": "command", "lignes": "lines"}),
    "presenter_fichier": ("present_file", {"fichier_id": "file_id"}),
    "mcp_outils": ("mcp_list_tools", {"serveur": "server", "outil": "tool"}),
    "mcp_appeler": ("mcp_call_tool", {"serveur": "server", "outil": "tool"}),
    "creer_artefact": ("create_artifact", {"titre": "title", "contenu": "content", "langage": "language",
                                           "artefact_id": "artifact_id"}),
}

# Réflexes d'autres harnais, ramenés à l'outil qui fait la même chose.
_REFLEXES: dict[str, str] = {
    "bash": "executer_commande", "shell": "executer_commande", "execute_command": "executer_commande",
    "run_shell_command": "executer_commande", "run_terminal_cmd": "executer_commande", "terminal": "executer_commande",
    "exec": "executer_commande",
    "cat": "lire_fichier", "view": "lire_fichier", "open_file": "lire_fichier", "read": "lire_fichier",
    "view_file": "lire_fichier",
    "create_file": "ecrire_fichier", "write": "ecrire_fichier", "save_file": "ecrire_fichier",
    "str_replace": "modifier_fichier", "str_replace_editor": "modifier_fichier", "replace_in_file": "modifier_fichier",
    "edit": "modifier_fichier", "apply_edit": "modifier_fichier",
    "ls": "lister_fichiers", "list_dir": "lister_fichiers", "list_directory": "lister_fichiers",
    "glob": "lister_fichiers",
    "grep": "chercher_dans_fichiers", "search": "chercher_dans_fichiers", "grep_search": "chercher_dans_fichiers",
    "search_code": "chercher_dans_fichiers",
    "python": "executer_python", "execute_python": "executer_python",
    "todowrite": "suivre_taches", "update_plan": "suivre_taches", "todo": "suivre_taches",
    "fetch": "recuperer_page", "webfetch": "recuperer_page",
    "websearch": "recherche_web", "search_web": "recherche_web",
}

PUBLIC = {interne: public for interne, (public, _) in _TABLE.items()}
_INTERNE = {public: interne for interne, public in PUBLIC.items()}
_ARGS_PUBLICS: dict[str, str] = {}
for _interne, (_public, _args) in _TABLE.items():
    _ARGS_PUBLICS.update(_args)

_NOM = re.compile(r"\b(" + "|".join(sorted(PUBLIC, key=len, reverse=True)) + r")\b")
_ARG_CITE = re.compile(r"`(" + "|".join(sorted(_ARGS_PUBLICS, key=len, reverse=True)) + r")`")
_ANNONCE = re.compile(r"\b(" + "|".join(sorted(_INTERNE, key=len, reverse=True)) + r")\(([^()\n]*)\)")


def nom_interne(nom: str) -> str | None:
    """Nom interne d'un outil émis par le modèle (public, interne ou réflexe), ou `None` s'il est inconnu."""
    cle = nom.strip()
    if cle in _TABLE:
        return cle
    return _INTERNE.get(cle) or _REFLEXES.get(cle.lower())


def _renommer(valeur: Any, table: dict[str, str]) -> Any:
    """Renomme les clés d'arguments, y compris dans les objets d'une liste (`files[].path`)."""
    if isinstance(valeur, dict):
        return {table.get(cle, cle): _renommer(v, table) for cle, v in valeur.items()}
    if isinstance(valeur, list):
        return [_renommer(v, table) for v in valeur]
    return valeur


def interne(nom: str, arguments: Any) -> tuple[str, Any]:
    """Appel émis par le modèle -> appel interne. Un nom inconnu passe tel quel (le registre le refusera)."""
    cible = nom_interne(nom)
    if cible is None:
        return nom, arguments
    inverse = {public: interne_ for interne_, public in _TABLE[cible][1].items()}
    return cible, _renommer(arguments, inverse) if isinstance(arguments, (dict, list)) else arguments


def parametres_internes(nom_public: str, parametres: dict[str, str]) -> tuple[str, dict[str, str]]:
    """Version pour l'aperçu en direct : nom et clés de premier niveau ramenés à l'interne."""
    cible, args = interne(nom_public, dict(parametres))
    return cible, args if isinstance(args, dict) else parametres


def publier_texte(texte: str) -> str:
    """Prompt, description ou résultat : noms d'outils et arguments cités (`chemin`) en noms publics."""
    if not texte:
        return texte
    texte = _NOM.sub(lambda m: PUBLIC[m.group(1)], texte)
    texte = _ARG_CITE.sub(lambda m: f"`{_ARGS_PUBLICS[m.group(1)]}`", texte)

    def annonce(m: re.Match[str]) -> str:
        args = _TABLE[_INTERNE[m.group(1)]][1]
        corps = re.sub(r"\b(\w+)(\s*:)", lambda a: args.get(a.group(1), a.group(1)) + a.group(2), m.group(2))
        return f"{m.group(1)}({corps})"

    return _ANNONCE.sub(annonce, texte)


def _publier_schema(schema: Any, args: dict[str, str]) -> Any:
    if isinstance(schema, dict):
        sortie: dict[str, Any] = {}
        for cle, valeur in schema.items():
            if cle == "properties" and isinstance(valeur, dict):
                sortie[cle] = {args.get(k, k): _publier_schema(v, args) for k, v in valeur.items()}
            elif cle == "required" and isinstance(valeur, list):
                sortie[cle] = [args.get(k, k) for k in valeur]
            elif cle == "description" and isinstance(valeur, str):
                sortie[cle] = publier_texte(valeur)
            else:
                sortie[cle] = _publier_schema(valeur, args)
        return sortie
    if isinstance(schema, list):
        return [_publier_schema(v, args) for v in schema]
    return schema


def publier_outils(outils: list[dict[str, Any]] | None) -> list[dict[str, Any]] | None:
    """Définitions `tools=` du registre -> noms et arguments publics, descriptions comprises."""
    if not outils:
        return outils
    publies = []
    for outil in outils:
        fonction = outil.get("function", {})
        nom = fonction.get("name", "")
        public, args = _TABLE.get(nom, (nom, {}))
        publies.append({**outil, "function": {**_publier_schema(fonction, args), "name": public}})
    return publies


def _publier_appel(appel: Any) -> Any:
    fonction = getattr(appel, "function", None) if not isinstance(appel, dict) else appel.get("function")
    if not isinstance(fonction, dict):
        return appel
    nom = fonction.get("name", "")
    public, args = _TABLE.get(nom, (nom, {}))
    arguments = fonction.get("arguments")
    if isinstance(arguments, str):
        import json

        try:
            arguments = json.dumps(_renommer(json.loads(arguments), args), ensure_ascii=False)
        except ValueError:
            pass
    else:
        arguments = _renommer(arguments, args)
    return {**appel, "function": {**fonction, "name": public, "arguments": arguments}}


def publier_messages(messages: list[Any]) -> list[Any]:
    """Messages repassés au moteur : textes et appels natifs en noms publics. Les originaux ne bougent pas."""
    publies = []
    for message in messages:
        changes: dict[str, Any] = {}
        contenu = getattr(message, "content", None)
        if isinstance(contenu, str):
            changes["content"] = publier_texte(contenu)
        elif isinstance(contenu, list):
            changes["content"] = [
                {**p, "text": publier_texte(p["text"])} if isinstance(p, dict) and isinstance(p.get("text"), str)
                else p for p in contenu
            ]
        appels = getattr(message, "tool_calls", None)
        if appels:
            changes["tool_calls"] = [_publier_appel(a) for a in appels]
        publies.append(message.model_copy(update=changes) if changes else message)
    return publies


def noms_publics(internes: list[str]) -> list[str]:
    return [PUBLIC.get(nom, nom) for nom in internes]


__all__ = ["PUBLIC", "interne", "nom_interne", "noms_publics", "parametres_internes", "publier_messages",
           "publier_outils", "publier_texte"]
