"""Outil `deleguer_code` — faire écrire UNE fonction pure par Claude Haiku, à l'aveugle, via l'abonnement Claude Code.

Demande de Chris (2026-11-11) : l'agent local peut confier une unité de code à Haiku quand on le lui demande ou
quand il le juge utile, jamais par obligation. Passage OBLIGATOIRE par l'abonnement Claude Code de l'hôte
(`claude -p`, relais `docker/resumeur-hote`), jamais par l'API Anthropic. La spec est anonymisée et contrôlée
avant envoi (`code_aveugle`) ; l'agent intègre et teste lui-même le code rendu.
"""

from __future__ import annotations

import os
import re
import time
from typing import Any

import httpx
from loguru import logger

from backend.outils import code_aveugle
from backend.outils.code_aveugle import Spec
from backend.outils.contrat import ContexteExecution, DescriptionOutil, EchecOutil, Outil

NOM = "deleguer_code"
MODELE = "claude-haiku-5-5"
DELAI_S = 320.0
_BLOC = re.compile(r"```[\w+-]*\n(.*?)```", re.S)

SYSTEME = (
    "You are a code-generation worker in a privacy-preserving pipeline. Specs are deliberately abstract and "
    "names are neutral: that is normal. Never ask for context. Implement exactly the signature and behaviour "
    "described, make the given tests pass, use no external dependency unless allowed. Answer with ONE code "
    "block only, no explanation."
)

DESCRIPTION = DescriptionOutil(
    nom=NOM,
    description=(
        "OPTIONAL. Has Claude Haiku write ONE self-contained pure function from an abstract spec, and returns "
        "the code (it does not write any file). Use it only when the user asks for it, or when a tricky pure "
        "function (algorithm, parsing, calculation) failed twice for you. Never for glue code (routes, UI, "
        "files, config). Haiku sees only the spec: no project, paths, URLs or business words — names declared "
        "in `signature` are renamed automatically and restored in the answer. Then write the code into the "
        "file yourself and run the real tests."
    ),
    parametres={"type": "object", "properties": {
        "langage": {"type": "string", "description": "Language, e.g. `python` or `typescript`."},
        "signature": {"type": "string", "description": "The typed signature, e.g. `def merge(a: list[int]) -> int`."},
        "comportement": {"type": "string", "description": "What it must do, in generic words."},
        "tests": {"type": "array", "items": {"type": "string"},
                  "description": "Input → expected output cases, or assert lines."},
        "contraintes": {"type": "string", "description": "Optional: limits, allowed libraries, complexity."},
    }, "required": ["langage", "signature", "comportement"]},
    alias={"language": "langage", "behavior": "comportement", "behaviour": "comportement",
           "constraints": "contraintes"},
)


def _canaris(contexte: ContexteExecution) -> list[str]:
    return code_aveugle.canaris(contexte.projet)


def _corps(spec: Spec) -> str:
    tests = "\n".join(f"- {t}" for t in spec.tests) or "- (none given)"
    return (f"Language: {spec.langage}\nSignature:\n{spec.signature}\n\nBehaviour:\n{spec.comportement}\n\n"
            f"Tests:\n{tests}\n\nConstraints: {spec.contraintes or 'none'}")


async def _demander(corps: str) -> str:
    """Le texte rendu par Haiku via le relais de l'hôte (abonnement Claude Code)."""
    url, jeton = os.environ.get("RESUMEUR_URL", "").strip(), os.environ.get("RESUMEUR_JETON", "").strip()
    if not url or not jeton:
        raise EchecOutil("Échec : relais Claude Code non configuré (RESUMEUR_URL / RESUMEUR_JETON). "
                         "Écris le code toi-même.")
    try:
        async with httpx.AsyncClient(timeout=DELAI_S) as client:
            reponse = await client.post(f"{url}/coder", json={"systeme": SYSTEME, "corps": corps},
                                        headers={"Authorization": f"Bearer {jeton}"})
    except httpx.HTTPError as exc:
        logger.warning("Relais Claude Code injoignable : {}", exc)
        raise EchecOutil(f"Échec : relais Claude Code injoignable ({exc}). Écris le code toi-même.") from exc
    if reponse.status_code != 200:
        logger.warning("Relais Claude Code en échec ({}) : {}", reponse.status_code, reponse.text[:300])
        raise EchecOutil(f"Échec : Haiku n'a pas répondu ({reponse.status_code}). Écris le code toi-même.")
    return str(reponse.json().get("texte", ""))


def _spec(arguments: dict[str, Any]) -> Spec:
    args = DESCRIPTION.normaliser(arguments)
    tests = args.get("tests") or []
    spec = Spec(langage=str(args.get("langage", "")).strip(), signature=str(args.get("signature", "")).strip(),
                comportement=str(args.get("comportement", "")).strip(),
                tests=[str(t) for t in tests] if isinstance(tests, list) else [str(tests)],
                contraintes=str(args.get("contraintes", "") or "").strip())
    if not spec.langage or not spec.signature or not spec.comportement:
        raise EchecOutil("Échec : `langage`, `signature` et `comportement` sont requis.")
    return spec


async def executer(arguments: dict[str, Any], contexte: ContexteExecution) -> str:
    anonyme, table = code_aveugle.anonymiser(_spec(arguments))
    bloque = code_aveugle.fuites(anonyme, _canaris(contexte))
    if bloque:
        logger.warning("Délégation bloquée avant envoi : {}", bloque)
        raise EchecOutil("Refusé avant envoi : la spec contient " + ", ".join(bloque[:5])
                         + ". Reformule-la en termes génériques (ni projet, ni chemin, ni URL, ni nom métier).")
    corps = _corps(anonyme)
    logger.info("Délégation à {} — charge envoyée :\n{}", MODELE, corps)
    debut = time.monotonic()
    bloc = _BLOC.search(await _demander(corps))
    if not bloc:
        raise EchecOutil("Échec : Haiku n'a pas rendu de bloc de code. Écris le code toi-même.")
    code = code_aveugle.rehydrater(bloc.group(1).rstrip(), table)
    duree = time.monotonic() - debut
    return (f"Code by {MODELE} ({duree:.1f} s), names restored. Not written anywhere: put it in the right file, "
            f"then run the real tests.\n```{anonyme.langage}\n{code}\n```")


OUTIL = Outil(description=DESCRIPTION, executer=executer)

__all__ = ["OUTIL"]
