"""verifier — contrôle en une commande ce que l'agent vient d'écrire.

    verifier fichier.py [autre.ts …]   ces fichiers
    verifier                            les fichiers modifiés selon git (sinon : aide)
    verifier --projet                   l'organisation du projet + tous ses fichiers modifiés
    verifier --tout                     tous les fichiers sources du projet (60 au plus)

Par fichier : syntaxe, lint, normes de taille, branchement au projet, fonctions inutilisées, tests liés.
Code de sortie 1 s'il reste un FAIL.
"""

from __future__ import annotations

import signal
import sys
from pathlib import Path

import controles
import integration
import normes
import structure
import tests_lies
from projet import fichiers_modifies, fichiers_sources, racine, relatif
from rapport import Rapport

MAX_FICHIERS = 60


def verifier_fichier(fichier: Path, base: Path, avec_tests: bool) -> Rapport:
    rapport = Rapport(relatif(fichier, base))
    try:
        texte = fichier.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        rapport.echec(f"unreadable: {exc}")
        return rapport
    if controles.syntaxe(fichier, texte, base, rapport):
        controles.lint(fichier, base, rapport)
    normes.verifier(fichier, texte, rapport)
    integration.branchement(fichier, texte, base, rapport)
    integration.symboles_inutilises(fichier, texte, base, rapport)
    if avec_tests:
        tests_lies.lancer_tests(fichier, base, rapport)
    return rapport


def _cibles(args: list[str], base: Path) -> list[Path] | None:
    chemins = [Path(a).resolve() for a in args if not a.startswith("--")]
    if chemins:
        absents = [str(c) for c in chemins if not c.is_file()]
        if absents:
            print("not found: " + ", ".join(absents))
            return None
        return chemins
    if "--tout" in args:
        return fichiers_sources(base)[:MAX_FICHIERS]
    return fichiers_modifies(base)[:MAX_FICHIERS]


def main(args: list[str]) -> int:
    if "-h" in args or "--help" in args:
        print(__doc__)
        return 0
    premier = next((Path(a) for a in args if not a.startswith("--")), Path.cwd())
    base = racine(premier.resolve() if premier.is_dir() else premier.resolve().parent)
    rapports: list[Rapport] = [structure.verifier(base)] if "--projet" in args else []
    cibles = _cibles(args, base)
    if cibles is None:
        return 2
    if not cibles and not rapports:
        print("nothing to check: give file paths, or --projet / --tout\n" + __doc__)
        return 2
    rapports += [verifier_fichier(f, base, "--sans-tests" not in args) for f in cibles]
    ts = controles.typescript(base, [f for f in cibles if f.suffix in {".ts", ".tsx"}])
    if ts:
        bilan_ts = Rapport("typescript (tsc --noEmit)")
        bilan_ts.echec(f"{len(ts)} type error(s)", ts)
        rapports.append(bilan_ts)
    print("\n\n".join(r.texte() for r in rapports))
    erreurs, alertes = sum(r.erreurs for r in rapports), sum(r.alertes for r in rapports)
    print(f"\nSUMMARY: {len(cibles)} file(s), {erreurs} FAIL, {alertes} WARN"
          + ("" if erreurs else " — no blocking problem"))
    return 1 if erreurs else 0


if __name__ == "__main__":
    signal.signal(signal.SIGPIPE, signal.SIG_DFL)  # `| head` ferme le tube : sortir sans trace
    sys.exit(main(sys.argv[1:]))
