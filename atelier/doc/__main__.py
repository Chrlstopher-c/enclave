"""doc — la documentation d'un module INSTALLÉ, lue sur place, en sortie courte.

    doc httpx                      version, liens officiels, classes et fonctions publiques
    doc httpx.AsyncClient          signature, docstring, méthodes publiques
    doc httpx.AsyncClient.get      signature et docstring complète
    doc httpx --find timeout       définitions du code source qui contiennent ce mot
    doc npm:zod                    paquet JS de node_modules : version, liens, exports (.d.ts)
    doc npm:zod --find parse

Utilise le Python du projet (.venv trouvé en remontant depuis le dossier courant), sinon python3.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ICI = Path(__file__).resolve().parent


def python_du_projet() -> str:
    for dossier in (Path.cwd(), *Path.cwd().parents):
        for venv in (".venv", "venv"):
            candidat = dossier / venv / "bin" / "python"
            if candidat.exists():
                return str(candidat)
    return "python3"


def main(args: list[str]) -> int:
    if not args or args[0] in {"-h", "--help"}:
        print(__doc__)
        return 0 if args else 2
    if args[0].startswith("npm:"):
        script, interprete = ICI / "doc_js.py", sys.executable
    else:
        script, interprete = ICI / "doc_python.py", python_du_projet()
    try:
        return subprocess.run([interprete, str(script), *args], timeout=60).returncode
    except subprocess.TimeoutExpired:
        print("doc: timeout after 60s (the module may hang on import)")
        return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
