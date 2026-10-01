"""Preuves des garde-fous de commandes : ce qui passe (le travail normal) et ce qui est refusé."""

from __future__ import annotations

import pytest

from backend.outils.garde_fous import CommandeRefusee, verifier_code_python, verifier_commande

RACINE = "/projets/mon-app"

AUTORISEES = [
    "bun create vite web --template react-ts && cd web && bun install",
    "cd web && bun run build && cd .. && ls",
    "rm -rf dist node_modules/.cache",
    "rm -rf /tmp/essai",
    "apt-get update && apt-get install -y sqlite3",
    "pip install fastapi uvicorn && python3 -m pytest -q",
    "git init && git add -A && git commit -m 'init'",
    "curl -s http://localhost:5173/ | head -5",
    "ls /usr/bin | grep node",
    f"cat {RACINE}/package.json",
    "echo 'a;b' > notes.txt",
    "kill 4242",
]

REFUSEES = [
    "rm -rf /",
    "rm -rf ..",
    "rm -rf .",
    "rm -rf *",
    "cd / && rm -rf usr",
    "cd .. && rm -rf autre-projet",
    "ls ../autre-projet",
    "cat /projets/autre/secret.env",
    "cp -r . /workspace/1234",
    "rm -rf .echohub",
    "git push origin main",
    "npm publish",
    "pkill python",
    "kill -9 1",
    "shutdown -h now",
    "mkfs.ext4 /dev/sda1",
    "dd if=/dev/zero of=/dev/sda",
    "ssh user@example.com",
    "chmod -R 777 /",
    ":(){ :|:& };:",
    "docker ps",
]


@pytest.mark.parametrize("commande", AUTORISEES)
def test_le_travail_normal_passe(commande: str) -> None:
    verifier_commande(commande, RACINE)


@pytest.mark.parametrize("commande", REFUSEES)
def test_les_accidents_sont_refuses(commande: str) -> None:
    with pytest.raises(CommandeRefusee):
        verifier_commande(commande, RACINE)


def test_conversation_sans_projet_ne_voit_pas_les_projets() -> None:
    with pytest.raises(CommandeRefusee):
        verifier_commande("ls /projets", "/workspace/conv-1")


def test_python_confine() -> None:
    verifier_code_python("open('app.py').read()", RACINE)
    verifier_code_python(f"open('{RACINE}/x.txt', 'w')", RACINE)
    with pytest.raises(CommandeRefusee):
        verifier_code_python("import shutil; shutil.rmtree('/projets/autre')", RACINE)
    with pytest.raises(CommandeRefusee):
        verifier_code_python("import os; os.listdir('.echohub')", RACINE)
