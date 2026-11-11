"""Code à l'aveugle — une spec de fonction rendue anonyme avant de partir chez Claude Haiku, et le code rendu
re-nommé au retour.

Idée de Chris (2026-11-11, « Pipeline Blind Coder ») : le modèle local garde le projet ; Haiku ne reçoit qu'une
spec atomique (signature, comportement, tests), sans nom de projet, chemin, URL ni identifiant parlant.
Tout ici est déterministe, jamais confié à un modèle :
- `anonymiser` : chaque identifiant DÉCLARÉ dans la signature devient neutre (`fn_1`, `v_1`, `T1`), partout
  dans la spec ; la table de correspondance reste sur la machine ;
- `fuites` : la garde avant envoi (URL, chemin, courriel, IP, secret, nom du projet, canaris) ;
- `rehydrater` : la table inverse appliquée au code rendu.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from loguru import logger

from backend.agent import racine

_IDENT = re.compile(r"\b[A-Za-z_][A-Za-z0-9_]*\b")
# Mots du langage et types de base : jamais renommés (le code rendu ne compilerait plus).
_RESERVES = frozenset("""
def async await return lambda class self cls None True False and or not in is if else for while with yield pass
int float str bool bytes list dict set tuple object Any Optional Union Callable Iterable Iterator Sequence Mapping
function const let var export import from default new this void null undefined true false typeof keyof readonly
number string boolean bigint symbol any unknown never Array ReadonlyArray Record Promise Map Set Date Partial
interface type extends implements public private protected static fn pub mut impl struct enum i32 i64 u8 u32
u64 f32 f64 usize String Vec Option Result Box str char byte rune func go chan error int32 int64 float64
""".split())
_FUITES = (
    ("URL", re.compile(r"\b(?:https?|wss?|ftp)://\S+")),
    ("courriel", re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b")),
    ("chemin", re.compile(r"(?<![\w.])(?:~|/)[\w.-]+/[\w./-]+")),
    ("adresse IP", re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")),
    ("secret", re.compile(r"\b(?:sk-|ghp_|xox[bp]-|AKIA)[\w-]{8,}|\b[A-Fa-f0-9]{32,}\b")),
)


@dataclass
class Spec:
    """Une unité de code à écrire : une fonction pure, testable seule."""

    langage: str
    signature: str
    comportement: str
    tests: list[str] = field(default_factory=list)
    contraintes: str = ""

    def textes(self) -> list[str]:
        return [self.langage, self.signature, self.comportement, *self.tests, self.contraintes]


def _neutre(nom: str, rangs: dict[str, int], signature: str) -> str:
    if nom[0].isupper():
        genre = "T"
    elif re.search(rf"\b(?:def|function|fn|func)\s+{re.escape(nom)}\b|\b{re.escape(nom)}\s*\(", signature):
        genre = "fn_"
    else:
        genre = "v_"
    rangs[genre] = rangs.get(genre, 0) + 1
    return f"{genre}{rangs[genre]}"


def _remplacer(texte: str, table: dict[str, str]) -> str:
    if not table:
        return texte
    motif = re.compile(r"\b(" + "|".join(re.escape(n) for n in sorted(table, key=len, reverse=True)) + r")\b")
    return motif.sub(lambda m: table[m.group(1)], texte)


def anonymiser(spec: Spec) -> tuple[Spec, dict[str, str]]:
    """La spec aux identifiants neutres, et la table neutre → réel (qui ne quitte jamais la machine)."""
    rangs: dict[str, int] = {}
    reel_vers_neutre: dict[str, str] = {}
    for nom in _IDENT.findall(spec.signature):
        if len(nom) > 2 and nom not in _RESERVES and nom not in reel_vers_neutre:
            reel_vers_neutre[nom] = _neutre(nom, rangs, spec.signature)
    anonyme = Spec(
        langage=spec.langage,
        signature=_remplacer(spec.signature, reel_vers_neutre),
        comportement=_remplacer(spec.comportement, reel_vers_neutre),
        tests=[_remplacer(t, reel_vers_neutre) for t in spec.tests],
        contraintes=_remplacer(spec.contraintes, reel_vers_neutre),
    )
    return anonyme, {neutre: reel for reel, neutre in reel_vers_neutre.items()}


def rehydrater(code: str, table: dict[str, str]) -> str:
    """Le code rendu, avec ses noms réels."""
    return _remplacer(code, table)


def fuites(spec: Spec, canaris: list[str]) -> list[str]:
    """Ce qui ne doit pas partir : chaque trouvaille bloque l'envoi."""
    return fuites_texte("\n".join(spec.textes()), canaris)


def fuites_texte(texte: str, canaris: list[str]) -> list[str]:
    """La même garde sur un texte libre (tâche confiée, fichier renvoyé)."""
    trouve = [f"{genre} « {m.group(0)[:60]} »" for genre, motif in _FUITES for m in motif.finditer(texte)]
    bas = texte.lower()
    trouve += [f"terme sensible « {c} »" for c in canaris if len(c) > 2 and c.lower() in bas]
    return trouve


def canaris(projet: str | None) -> list[str]:
    """Termes qui ne partent jamais : le nom du projet, et la liste de Chris (`~agent/canaris.txt`)."""
    termes = [projet] if projet else []
    try:
        fichier = racine() / "canaris.txt"
        if fichier.is_file():
            termes += [ligne.strip() for ligne in fichier.read_text().splitlines() if ligne.strip()]
    except OSError as exc:
        logger.warning("Canaris illisibles ({}) : seul le nom du projet est gardé.", exc)
    return termes
