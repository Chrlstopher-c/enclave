"""Introspection d'un module Python installé, lancée avec le Python du projet par `doc`."""

from __future__ import annotations

import difflib
import importlib
import importlib.metadata as meta
import inspect
import re
import subprocess
import signal
import sys
from pathlib import Path
from types import ModuleType

MAX_MEMBRES, MAX_DOC = 45, 40
_ADRESSES = re.compile(r" object at 0x[0-9a-f]+>")


def premiere_ligne(objet: object) -> str:
    doc = inspect.getdoc(objet) or ""
    return doc.strip().splitlines()[0][:110] if doc.strip() else ""


def signature(objet: object) -> str:
    try:
        return _ADRESSES.sub(">", str(inspect.signature(objet)))  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return "(…)"


def resoudre(chemin: str) -> tuple[object, ModuleType]:
    """Importe la plus longue partie du chemin qui est un module, puis descend par attributs."""
    morceaux = chemin.split(".")
    for coupe in range(len(morceaux), 0, -1):
        try:
            module = importlib.import_module(".".join(morceaux[:coupe]))
        except ModuleNotFoundError as exc:
            if coupe == 1:
                raise SystemExit(f"doc: module « {morceaux[0]} » is not installed for {sys.executable} ({exc}).\n"
                                 f"Install it: {sys.executable} -m pip install -q {morceaux[0]}  "
                                 "(the pip name can differ from the import name: search PyPI if it fails)")
            continue
        except Exception as exc:  # noqa: BLE001 — l'import du paquet lui-même plante : c'est l'info utile
            raise SystemExit(f"doc: importing « {'.'.join(morceaux[:coupe])} » raised {type(exc).__name__}: {exc}")
        objet: object = module
        for nom in morceaux[coupe:]:
            if not hasattr(objet, nom):
                noms = dir(objet)
                proches = difflib.get_close_matches(nom, noms, n=6, cutoff=0.6)
                proches += [n for n in noms if nom.lower() in n.lower() and n not in proches][:6]
                raise SystemExit(f"doc: « {nom} » not found in {getattr(objet, '__name__', objet)}. "
                                 f"Close names: {', '.join(proches) or 'none'} — try `doc {morceaux[0]} --find {nom}`")
            objet = getattr(objet, nom)
        return objet, module
    raise SystemExit(f"doc: cannot resolve {chemin}")


def entete_paquet(nom: str) -> None:
    try:
        dist = meta.distribution(meta.packages_distributions().get(nom, [nom])[0])
    except (meta.PackageNotFoundError, IndexError):
        return
    print(f"{dist.metadata['Name']} {dist.version} — {dist.metadata.get('Summary') or ''}")
    liens = dist.metadata.get_all("Project-URL") or []
    if dist.metadata.get("Home-page"):
        liens.insert(0, f"Homepage, {dist.metadata['Home-page']}")
    for lien in liens[:6]:
        print(f"  {lien.replace(', ', ': ', 1)}")


def membres(objet: object, prefixe: str) -> None:
    noms = [n for n in (getattr(objet, "__all__", None) or dir(objet)) if not n.startswith("_")]
    lignes = []
    for nom in noms:
        valeur = getattr(objet, nom, None)
        if inspect.ismodule(valeur) or valeur is None:
            continue
        genre = "class" if inspect.isclass(valeur) else "def" if callable(valeur) else "attr"
        sig = signature(valeur) if genre == "def" else ""
        lignes.append(f"  {genre} {prefixe}{nom}{sig[:90]}  — {premiere_ligne(valeur)}"[:200])
    print(f"{len(lignes)} public members" + (f" (first {MAX_MEMBRES})" if len(lignes) > MAX_MEMBRES else "") + ":")
    print("\n".join(lignes[:MAX_MEMBRES]))


def decrire(chemin: str) -> None:
    objet, module = resoudre(chemin)
    if inspect.ismodule(objet):
        entete_paquet(chemin.split(".")[0])
        print(f"module {chemin}  ({getattr(objet, '__file__', '?')})")
        print(premiere_ligne(objet))
        membres(objet, "")
        return
    print(f"{'class' if inspect.isclass(objet) else 'def'} {chemin}{signature(objet)}")
    print(f"  defined in {inspect.getsourcefile(objet) if not inspect.isbuiltin(objet) else 'builtin'}"
          if _a_source(objet) else "")
    doc = (inspect.getdoc(objet) or "(no docstring)").splitlines()
    print("\n".join(doc[:MAX_DOC]) + (f"\n… {len(doc) - MAX_DOC} more docstring lines" if len(doc) > MAX_DOC else ""))
    if inspect.isclass(objet):
        membres(objet, ".")


def _a_source(objet: object) -> bool:
    try:
        return inspect.getsourcefile(objet) is not None  # type: ignore[arg-type]
    except TypeError:
        return False


def chercher(paquet: str, mot: str) -> None:
    module = resoudre(paquet.split(".")[0])[1]
    racine = Path(module.__file__ or ".").parent
    motif = rf"^\s*(async\s+)?(def|class)\s+\w*{re.escape(mot)}\w*|^\s*{re.escape(mot)}\s*[:=]"
    try:
        sortie = subprocess.run(["rg", "-n", "-i", "--no-heading", "-t", "py", "-e", motif, str(racine)],
                                capture_output=True, text=True, timeout=30).stdout.splitlines()
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise SystemExit(f"doc: source search failed: {exc}")
    print(f"{len(sortie)} definition(s) matching « {mot} » in {racine}" + (" (first 30)" if len(sortie) > 30 else ""))
    print("\n".join(l.replace(str(racine) + "/", "")[:180] for l in sortie[:30]))
    if sortie:
        print("Read one: sed -n 'START,ENDp' <file>  or  doc <module.path.Name>")


def main(args: list[str]) -> None:
    sys.path.insert(0, str(Path.cwd()))
    if "--find" in args:
        i = args.index("--find")
        chercher(args[0], args[i + 1] if i + 1 < len(args) else "")
    else:
        decrire(args[0])


if __name__ == "__main__":
    signal.signal(signal.SIGPIPE, signal.SIG_DFL)  # `| head` ferme le tube : sortir sans trace
    main(sys.argv[1:])
