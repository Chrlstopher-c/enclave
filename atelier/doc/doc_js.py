"""Paquet JS installé dans node_modules : version, liens, exports déclarés (.d.ts) et recherche."""

from __future__ import annotations

import json
import re
import subprocess
import signal
import sys
from pathlib import Path

_EXPORT = re.compile(r"^export\s+(?:declare\s+)?(?:default\s+)?(function|class|const|type|interface|enum)\s+(\w+)(.*)")


def trouver(nom: str) -> Path:
    for dossier in (Path.cwd(), *Path.cwd().parents):
        candidat = dossier / "node_modules" / nom
        if (candidat / "package.json").exists():
            return candidat
    raise SystemExit(f"doc: npm package « {nom} » is not in node_modules here. Install it: pnpm add {nom}")


def decrire(racine: Path) -> None:
    pkg = json.loads((racine / "package.json").read_text())
    print(f"{pkg.get('name')} {pkg.get('version')} — {pkg.get('description', '')}")
    depot = pkg.get("repository")
    for nom, lien in (("Homepage", pkg.get("homepage")), ("Repository", depot.get("url") if isinstance(depot, dict)
                                                          else depot)):
        if lien:
            print(f"  {nom}: {lien}")
    types = pkg.get("types") or pkg.get("typings")
    fichier = racine / types if types else next(iter(sorted(racine.glob("**/index.d.ts"))), None)
    if not fichier or not fichier.exists():
        print("no .d.ts types found: read README.md or search with --find")
        return
    lignes = fichier.read_text(errors="ignore").splitlines()
    exports = [m for l in lignes if (m := _EXPORT.match(l.strip()))]
    if not exports:
        reexports = [l.strip() for l in lignes if l.strip().startswith("export")]
        print(f"{fichier.relative_to(racine)} re-exports (follow the paths, or use --find <name>):")
        print("\n".join(f"  {l[:150]}" for l in reexports[:30]))
        return
    print(f"{len(exports)} exports in {fichier.relative_to(racine)}" + (" (first 45)" if len(exports) > 45 else ""))
    for genre, nom, reste in exports[:45]:
        print(f"  {genre} {nom}{reste[:110]}")


def main(args: list[str]) -> None:
    racine = trouver(args[0].removeprefix("npm:"))
    if "--find" in args and args.index("--find") + 1 < len(args):
        mot = args[args.index("--find") + 1]
        try:
            sortie = subprocess.run(["rg", "-n", "-i", "--no-heading", "-g", "*.d.ts", "-e", mot, str(racine)],
                                    capture_output=True, text=True, timeout=30).stdout.splitlines()
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise SystemExit(f"doc: source search failed: {exc}")
        print("\n".join(l.replace(str(racine) + "/", "")[:180] for l in sortie[:30]) or f"nothing matches « {mot} »")
    else:
        decrire(racine)


if __name__ == "__main__":
    signal.signal(signal.SIGPIPE, signal.SIG_DFL)  # `| head` ferme le tube : sortir sans trace
    main(sys.argv[1:])
