"""Le balisage du harnais ne doit jamais revenir au modèle — ni être imité par lui dans l'interface.

Mesuré le 2026-10-02 (projet `spoofer`, captures de Chris) : l'historique renvoyait au modèle les blocs
`<outil><entree>…</entree><sortie>…</sortie></outil>` et les `<etape-fin/>` de ses tours passés. Il les
a recopiés — avec des fautes (`<etape_fin/>`, `</etree>`, `</otel>`) — et a INVENTÉ des résultats
(« Code de retour 600 (timeout) », message que le harnais n'émet pas), que l'interface affichait comme
de vraies cartes d'outil. Tout format laissé dans le contexte finit imité (cf. `_sans_appels_outils`).

Deux remèdes, chacun d'un côté :
- vers le MODÈLE (`pour_le_modele`) : chaque bloc d'outil devient une ligne de prose sans chevron
  (outils utilisés, échecs), les marqueurs d'étape et toute balise imitée disparaissent ;
- vers l'ÉCRAN (`sans_balises_imitees`) : une balise du harnais écrite PAR le modèle est neutralisée
  (« ‹ » au lieu de « < ») avant diffusion — elle ne peut plus passer pour une vraie carte.
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import AsyncIterator
from typing import Any

# Noms des balises du harnais ET des déformations observées : le modèle ne doit pouvoir écrire aucune.
_NOMS = r"(?:outil|entree|etree|entrée|sortie|etape[-_]?fin|otel)"
_BALISE_IMITEE = re.compile(rf"<(/?){_NOMS}\b", re.IGNORECASE)
_BALISE_COMPLETE = re.compile(rf"</?{_NOMS}\b[^>]*>", re.IGNORECASE)
_BLOC = re.compile(
    r"<outil>\s*<entree>(?P<entree>.*?)</entree>\s*(?P<ouvrante><sortie[^>]*>)(?P<sortie>.*?)</sortie>\s*</outil>",
    re.DOTALL,
)
_BLOC_INACHEVE = re.compile(r"<outil>.*\Z", re.DOTALL)
# Une balise peut arriver coupée entre deux morceaux du flux : on retient la fin d'un morceau tant
# qu'elle pourrait encore en être le début.
_RETENUE_MAX = 16


def _recapitulatif(blocs: list[tuple[str, bool]]) -> str:
    if not blocs:
        return ""
    comptes = Counter(nom for nom, _ in blocs)
    echecs = Counter(nom for nom, echec in blocs if echec)
    parties = [f"{nom} ×{n}" + (f" dont {echecs[nom]} en échec" if echecs[nom] else "") for nom, n in comptes.items()]
    return ("\n\n(Outils utilisés dans ce tour : " + ", ".join(parties)
            + ". Leurs sorties ne sont plus dans le contexte : relancer ou relire si besoin.)")


def pour_le_modele(texte: str) -> str:
    """Texte d'un tour passé tel que le modèle doit le relire : sa prose, sans aucun balisage."""
    blocs: list[tuple[str, bool]] = []

    def retirer(trouve: re.Match[str]) -> str:
        nom = trouve.group("entree").split("(", 1)[0].strip() or "outil"
        blocs.append((nom, "echec" in trouve.group("ouvrante")))
        return ""

    propre = _BLOC.sub(retirer, texte)
    propre = _BLOC_INACHEVE.sub("", propre)
    propre = _BALISE_COMPLETE.sub("\n", propre)
    propre = re.sub(r"[ \t]*\n[\s]*", "\n", propre).strip()
    return propre + _recapitulatif(blocs)


def neutraliser(texte: str) -> str:
    """Une balise du harnais écrite par le modèle devient inoffensive à l'affichage."""
    return _BALISE_IMITEE.sub(lambda m: f"‹{m.group(1)}{m.group(0)[1 + len(m.group(1)):]}", texte)


def _coupure(tampon: str) -> int:
    """Index à partir duquel retenir le tampon : un « < » final qui peut encore ouvrir une balise."""
    debut = tampon.rfind("<", max(0, len(tampon) - _RETENUE_MAX))
    if debut == -1 or ">" in tampon[debut:]:
        return len(tampon)
    return debut


async def sans_balises_imitees(flux: AsyncIterator[dict[str, Any]]) -> AsyncIterator[dict[str, Any]]:
    """Le flux du modèle, balises du harnais imitées neutralisées ; le reste passe tel quel."""
    tampon = ""
    async for morceau in flux:
        fragment = morceau.get("texte")
        if not isinstance(fragment, str):
            yield morceau
            continue
        tampon += fragment
        coupe = _coupure(tampon)
        pret, tampon = neutraliser(tampon[:coupe]), tampon[coupe:]
        if pret:
            yield {**morceau, "texte": pret}
    if tampon:
        yield {"texte": neutraliser(tampon)}


__all__ = ["neutraliser", "pour_le_modele", "sans_balises_imitees"]
