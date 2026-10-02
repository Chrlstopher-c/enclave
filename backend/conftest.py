"""Isolation des tests vis-à-vis du `.env` du poste de dev.

`Settings` lit `.env` dans le dossier courant. Lancés depuis la racine du dépôt, les tests héritaient
donc des chemins réels de la machine (ATELIER_WORKSPACE, ECHOHUB_PROJETS_RACINE…) et écrivaient hors
de leur dossier temporaire — ou échouaient selon la configuration de qui les lançait.
"""

from __future__ import annotations

import os
import tempfile

from backend.core.config import Settings, reset_settings_cache

# La maison de l'agent est régénérée à chaque socle (AWARENESS.md) : jamais celle du poste en test.
os.environ.setdefault("ECHOHUB_AGENT_DIR", tempfile.mkdtemp(prefix="echohub-agent-tests-"))

Settings.model_config["env_file"] = None
reset_settings_cache()
