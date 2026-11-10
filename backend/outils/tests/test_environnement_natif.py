"""L'agent démarre en sachant où il est, et `/tmp` marche comme partout ailleurs.

Captures de Chris du 2026-11-10 : six appels pour découvrir son dossier ; `/tmp/explore.py` refusé.
"""

from __future__ import annotations

import asyncio
import base64
from pathlib import Path
from typing import Any

import pytest

import backend.outils.fichiers_tmp as fichiers_tmp
from backend.outils.bac_a_sable import ResultatExecution
from backend.outils.contrat import ContexteExecution
from backend.outils.environnement import bloc_environnement
from backend.outils.garde_fous import CommandeRefusee, verifier_commande
from backend.outils.registre import executer


def test_le_bloc_dit_ou_est_l_agent_et_ce_qu_il_a(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "app.py").write_text("x")
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "README.md").write_text("x")
    bloc = bloc_environnement(tmp_path, "tui-test")
    assert "/projets/tui-test" in bloc and "src/\n  app.py\nREADME.md" in bloc and "node_modules" not in bloc


def test_le_refus_dit_ou_l_agent_se_trouve() -> None:
    with pytest.raises(CommandeRefusee, match="already in /projets/tui-test"):
        verifier_commande("ls /projets", "/projets/tui-test")


def test_tmp_passe_par_l_atelier(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    disque: dict[str, bytes] = {}

    def atelier(code: str, racine: Any) -> ResultatExecution:
        chemin = code.split("p=")[1].split("\n")[0].strip("'")
        if "b64decode" in code:
            disque[chemin] = base64.b64decode(code.split("b64decode(")[-1].split(")")[0].strip("'"))
            sortie = ""
        else:
            sortie = base64.b64encode(disque[chemin]).decode()
        return ResultatExecution(sortie=sortie, erreur="", code_retour=0, duree_s=0, tue_par_filet_securite=False)

    monkeypatch.setattr(fichiers_tmp, "executer_code_confine", atelier)
    contexte = ContexteExecution(conversation_id="c", racine_bac=tmp_path)

    async def jouer() -> list[Any]:
        return [await executer("ecrire_fichier",
                               {"chemin": "/tmp/explore.py", "contenu": "print(1)\n"}, contexte),
                await executer("modifier_fichier", {"chemin": "/tmp/explore.py", "ancien": "1", "nouveau": "2"},
                               contexte),
                await executer("lire_fichier", {"chemin": "/tmp/explore.py"}, contexte)]

    ecrit, modifie, lu = asyncio.run(jouer())
    assert ecrit.succes and modifie.succes and lu.succes, (ecrit.texte, modifie.texte, lu.texte)
    assert "print(2)" in lu.texte and not (tmp_path / "tmp").exists()
