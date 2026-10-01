"""`ecrire_fichiers` pose plusieurs fichiers d'un appel, avec la frontière du bac de `ecrire_fichier`."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from backend.chat.modeles import ResumeConversation
from backend.inference.harnais_outils import _apercu_valeur
from backend.outils.contrat import ContexteExecution, EchecOutil
from backend.outils.ecriture_groupee import FICHIERS_PAR_APPEL_MAX, OUTIL
from backend.outils.fichiers_bac import OUTIL_LIRE


@pytest.fixture
def contexte(conversation: ResumeConversation, racine_bac: Path) -> ContexteExecution:
    return ContexteExecution(conversation_id=conversation.id, racine_bac=racine_bac)


def _executer(arguments: dict, contexte: ContexteExecution) -> str:
    return asyncio.run(OUTIL.executer(arguments, contexte))


def test_ecrit_tous_les_fichiers(contexte: ContexteExecution) -> None:
    fichiers = [{"chemin": "app/main.py", "contenu": "print(1)\n"}, {"path": "README.md", "content": "# x\n"}]
    sortie = _executer({"fichiers": fichiers}, contexte)
    assert sortie.startswith("2 fichier(s) écrit(s)")
    assert (contexte.racine_bac / "app/main.py").read_text() == "print(1)\n"
    assert (contexte.racine_bac / "README.md").read_text() == "# x\n"


def test_liste_en_chaine_json_acceptee(contexte: ContexteExecution) -> None:
    _executer({"files": json.dumps([{"chemin": "a.txt", "contenu": "a"}])}, contexte)
    assert (contexte.racine_bac / "a.txt").read_text() == "a"


def test_un_chemin_hors_bac_est_refuse_sans_perdre_les_autres(contexte: ContexteExecution) -> None:
    fichiers = [{"chemin": "ok.txt", "contenu": "ok"}, {"chemin": "../evasion.txt", "contenu": "x"}]
    with pytest.raises(EchecOutil) as exc:
        _executer({"fichiers": fichiers}, contexte)
    assert "ok.txt" in str(exc.value) and "../evasion.txt" in str(exc.value)
    assert (contexte.racine_bac / "ok.txt").exists()
    assert not (contexte.racine_bac.parent / "evasion.txt").exists()


def test_liste_vide_ou_trop_longue_refusee(contexte: ContexteExecution) -> None:
    with pytest.raises(EchecOutil):
        _executer({"fichiers": []}, contexte)
    trop = [{"chemin": f"f{i}.txt", "contenu": ""} for i in range(FICHIERS_PAR_APPEL_MAX + 1)]
    with pytest.raises(EchecOutil):
        _executer({"fichiers": trop}, contexte)


def test_annonce_montre_les_chemins_pas_le_contenu() -> None:
    apercu = _apercu_valeur([{"chemin": "a.py", "contenu": "x" * 5000}, {"chemin": "b.py", "contenu": ""}])
    assert apercu == "a.py · b.py"


def test_lecture_d_une_plage_de_lignes(contexte: ContexteExecution) -> None:
    _executer({"fichiers": [{"chemin": "long.py", "contenu": "".join(f"ligne {i}\n" for i in range(1, 51))}]},
              contexte)
    extrait = asyncio.run(OUTIL_LIRE.executer({"chemin": "long.py", "ligne_debut": 10, "ligne_fin": 12}, contexte))
    assert extrait == "[lignes 10-12 sur 50]\nligne 10\nligne 11\nligne 12\n"


def test_une_erreur_de_syntaxe_est_signalee_a_l_ecriture(contexte: ContexteExecution) -> None:
    sortie = _executer({"fichiers": [{"chemin": "casse.py", "contenu": "def f(:\n    pass\n"},
                                     {"chemin": "ok.py", "contenu": "x = 1\n"},
                                     {"chemin": "conf.json", "contenu": "{\"a\": }"}]}, contexte)
    assert "SYNTAX ERROR in casse.py, line 1" in sortie
    assert "INVALID JSON in conf.json" in sortie
    assert "ok.py" in sortie and sortie.count("ERROR") + sortie.count("INVALID") == 2
