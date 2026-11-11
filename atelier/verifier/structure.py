"""Organisation du projet : documents obligatoires, venv, dossiers par couche technique, plus gros fichiers."""

from __future__ import annotations

from pathlib import Path

from projet import fichiers_sources, relatif
from rapport import Rapport

DOCUMENTS = ("README.md", "STATE.md", "TODO.md", "ARCHITECTURE.md", "ARBORESCENCE.md", ".env.example",
             "start.sh", "stop.sh", "restart.sh")
COUCHES = {"controllers", "services", "models", "helpers", "utils", "managers", "views"}


def verifier(base: Path) -> Rapport:
    rapport = Rapport(f"PROJECT {base}")
    manquants = [d for d in DOCUMENTS if not (base / d).exists()]
    if manquants:
        rapport.alerte(f"missing project files: {', '.join(manquants)}")
    else:
        rapport.ok("project files present")
    sources = fichiers_sources(base)
    if any(f.suffix == ".py" for f in sources):
        if (base / ".venv").exists() or (base / "venv").exists():
            rapport.ok("python venv present")
        else:
            rapport.alerte("python code but no .venv (python3 -m venv .venv)")
        if not any((base / f).exists() for f in ("requirements.txt", "pyproject.toml")):
            rapport.alerte("no requirements.txt / pyproject.toml")
    if (base / "package.json").exists() and (base / "package-lock.json").exists():
        rapport.alerte("package-lock.json found: this project uses pnpm, not npm")
    couches = sorted({p.name for f in sources for p in f.relative_to(base).parents if p.name in COUCHES})
    if couches:
        rapport.alerte(f"folders by technical layer ({', '.join(couches)}): group by feature/domain instead")
    tailles = sorted(((len(f.read_text(errors="ignore").splitlines()), f) for f in sources
                      if f.suffix not in {".json"}), reverse=True)
    trop = [f"{relatif(f, base)}: {n} lines" for n, f in tailles if n > 500]
    if trop:
        rapport.echec(f"{len(trop)} file(s) over 500 lines", trop)
    rapport.ok(f"{len(sources)} source files; biggest: "
               + ", ".join(f"{relatif(f, base)} ({n})" for n, f in tailles[:3]))
    return rapport
