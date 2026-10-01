"""Fixtures des tests du domaine `outils` — base et disque isolés par cas, comme `backend.fichiers.tests`.

Le bac à sable écrit dans le magasin `fichiers` : ces tests ont donc besoin du même schéma
(`fichiers_conversation`, porté par `backend.chat.depot`) et d'une conversation réelle à qui
rattacher les fichiers produits.
"""

from __future__ import annotations

import subprocess
import tempfile
from collections.abc import Iterator
from pathlib import Path

import pytest

from backend.chat import annulation
from backend.chat.depot import assurer_schema_chat, creer_conversation
from backend.chat.modeles import ReglagesConversation, ResumeConversation
from backend.core import close_connection, get_settings, init_db
from backend.core.config import reset_settings_cache
from backend.outils import atelier, bac_a_sable


@pytest.fixture
def chemin_donnees(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    """Isole la base et le disque du cas de test, sans créer le schéma."""
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    reset_settings_cache()
    close_connection()
    annulation.reinitialiser()
    yield tmp_path
    close_connection()
    reset_settings_cache()
    annulation.reinitialiser()


@pytest.fixture
def base(chemin_donnees: Path) -> Path:
    """Base vierge, schéma commun ET schéma du chat créés (donc `fichiers_conversation` aussi)."""
    init_db()
    assurer_schema_chat()
    return chemin_donnees


@pytest.fixture
def conversation(base: Path) -> ResumeConversation:
    """Une conversation vide, prête à faire tourner du code dans son bac."""
    return creer_conversation("Essai bac à sable", None, ReglagesConversation())


@pytest.fixture
def racine_bac(conversation: ResumeConversation) -> Path:
    """Bac de cette conversation, dérivé exactement comme `MoteurChat._flux` le construit."""
    return get_settings().atelier_workspace / conversation.id


def _executer_local(argv: list[str], sous_dossier: str, timeout_s: int,
                    racine: str = "workspace") -> atelier.ReponseAtelier:
    """Exécute `argv` en local dans le dossier de travail, à la place de l'atelier distant.

    L'atelier est un conteneur : on ne l'exige pas en test unitaire. On mocke à la FRONTIÈRE (le
    module `atelier`), pas plus bas — l'exécution reste réelle, produit de vrais fichiers, et le
    balayage les rattache comme en production. Le dossier est `atelier_workspace/<sous_dossier>`,
    exactement ce que `bac_a_sable._sous_dossier` renvoie.
    """
    reglages = get_settings()
    base = reglages.projets_racine if racine == "projets" and reglages.projets_racine else reglages.atelier_workspace
    cwd = base / sous_dossier
    cwd.mkdir(parents=True, exist_ok=True)
    try:
        proc = subprocess.run(argv, cwd=cwd, capture_output=True, text=True, timeout=timeout_s)
    except subprocess.TimeoutExpired as exc:
        return atelier.ReponseAtelier(code_retour=-1, sortie=exc.stdout or "",
                                      erreur=(exc.stderr or "") + "\n[tué : délai dépassé]",
                                      duree_s=float(timeout_s), tue=True)
    return atelier.ReponseAtelier(code_retour=proc.returncode, sortie=proc.stdout,
                                  erreur=proc.stderr, duree_s=0.0, tue=False)


@pytest.fixture(autouse=True)
def atelier_local(monkeypatch: pytest.MonkeyPatch) -> None:
    """Redirige les appels de `bac_a_sable` vers un exécuteur LOCAL, sans conteneur atelier.

    Patché sur les références que `bac_a_sable` détient (`_executer_*_atelier`), pas sur le module
    `atelier` lui-même : les tests du client réel (`test_atelier.py`) continuent d'exercer le vrai
    `atelier.executer_commande`, intact.
    """
    def _commande(commande: str, sous_dossier: str, timeout_s: int,
                  racine: str = "workspace") -> atelier.ReponseAtelier:
        return _executer_local(["bash", "-lc", commande], sous_dossier, timeout_s, racine)

    def _python(code: str, sous_dossier: str, timeout_s: int,
                racine: str = "workspace") -> atelier.ReponseAtelier:
        fichier = tempfile.NamedTemporaryFile("w", suffix=".py", delete=False, encoding="utf-8")
        fichier.write(code)
        fichier.close()
        try:
            return _executer_local(["python3", fichier.name], sous_dossier, timeout_s, racine)
        finally:
            Path(fichier.name).unlink(missing_ok=True)

    monkeypatch.setattr(bac_a_sable, "_executer_commande_atelier", _commande)
    monkeypatch.setattr(bac_a_sable, "_executer_python_atelier", _python)
