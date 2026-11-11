"""Le modèle voit des noms d'outils anglais standard ; le harnais garde ses noms internes.

Constaté le 2026-11-10 (Ornith 1.5) : `read_file` appelé, refusé faute d'exister — un tour perdu.
"""

from __future__ import annotations

import json

from backend.inference.engines_adapters.contrat import MessageChat
from backend.outils import format_moteur
from backend.outils.noms_publics import PUBLIC, interne, publier_messages, publier_outils, publier_texte


def test_le_moteur_ne_voit_que_des_noms_publics() -> None:
    publies = publier_outils(format_moteur(None)) or []
    noms = {o["function"]["name"] for o in publies}
    assert {"read_file", "write_file", "edit_file", "run_command", "list_files"} <= noms
    brut = json.dumps(publies, ensure_ascii=False)
    for interne_ in PUBLIC:
        assert interne_ not in brut, f"{interne_} fuit vers le modèle"
    lire = next(o for o in publies if o["function"]["name"] == "read_file")["function"]["parameters"]
    assert set(lire["properties"]) == {"path", "start_line", "end_line"} and lire["required"] == ["path"]
    groupe = next(o for o in publies if o["function"]["name"] == "write_files")["function"]["parameters"]
    assert groupe["properties"]["files"]["type"] == "string" and groupe["required"] == ["files"]


def test_un_appel_public_redevient_interne() -> None:
    assert interne("read_file", {"path": "a.py", "start_line": 3}) == ("lire_fichier",
                                                                      {"chemin": "a.py", "ligne_debut": 3})
    nom, args = interne("write_files", {"files": [{"path": "a", "content": "x"}]})
    assert nom == "ecrire_fichiers" and args == {"fichiers": [{"chemin": "a", "contenu": "x"}]}


def test_anciens_noms_et_reflexes_acceptes() -> None:
    assert interne("lire_fichier", {"chemin": "a"}) == ("lire_fichier", {"chemin": "a"})
    assert interne("bash", {"command": "ls"}) == ("executer_commande", {"commande": "ls"})
    assert interne("grep", {"pattern": "x"})[0] == "chercher_dans_fichiers"
    assert interne("inconnu", {"a": 1}) == ("inconnu", {"a": 1})


def test_textes_et_appels_passes_traduits() -> None:
    assert publier_texte("Relis avec `lire_fichier` + `ligne_debut`.") == "Relis avec `read_file` + `start_line`."
    assert publier_texte("Result of lire_fichier(chemin : a.py):") == "Result of read_file(path : a.py):"
    message = MessageChat(role="assistant", content="", tool_calls=[{"id": "1", "type": "function", "function": {
        "name": "executer_commande", "arguments": json.dumps({"commande": "ls"})}}])
    publie = publier_messages([message])[0]
    assert publie.tool_calls[0]["function"] == {"name": "run_command", "arguments": '{"command": "ls"}'}
    assert message.tool_calls[0]["function"]["name"] == "executer_commande", "l'original ne bouge pas"


def test_liste_recue_en_texte_json_traduite() -> None:
    nom, args = interne("write_files", {"files": '[{"path": "a.py", "content": "x"}]'})
    assert nom == "ecrire_fichiers" and args == {"fichiers": [{"chemin": "a.py", "contenu": "x"}]}


def test_faute_de_frappe_rattachee_a_l_outil_proche() -> None:
    assert interne("chercher_dans_fichings", {})[0] == "chercher_dans_fichiers"
    assert interne("read_fil", {"path": "a"}) == ("lire_fichier", {"chemin": "a"})
    assert interne("totalement_autre", {})[0] == "totalement_autre"
