"""Budget de navigateur et écriture de code par le shell en mode hybride."""

from pathlib import Path

import pytest

from backend.inference import budget_navigateur
from backend.outils import mode_hybride
from backend.outils.contrat import ContexteExecution


def test_reconnait_le_navigateur() -> None:
    assert budget_navigateur.est_navigateur("mcp_appeler", {"serveur": "playwright", "outil": "browser_navigate"})
    assert budget_navigateur.est_navigateur("mcp_appeler", '{"server": "playwright"}')
    assert not budget_navigateur.est_navigateur("mcp_appeler", {"serveur": "autre"})
    assert budget_navigateur.est_changement("confier_a_haiku") and not budget_navigateur.est_changement("lire_fichier")


def test_heredoc_refuse_en_mode_hybride(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("RESUMEUR_URL", "http://relais")
    monkeypatch.setenv("RESUMEUR_JETON", "x")
    ctx = ContexteExecution(conversation_id="c", racine_bac=tmp_path, projet="p")
    gros = "cat > index.html <<'EOF'\n" + "<p>x</p>\n" * 80 + "EOF"
    assert mode_hybride.refuse_commande(ctx, gros)
    assert mode_hybride.refuse_commande(ctx, "node --test test/ 2>&1 | tail -30") is None
    assert mode_hybride.refuse_commande(ctx, "echo ok > out.txt") is None
