"""Pont entre un itérateur bloquant et un flux asynchrone.

llama.cpp s'exécute dans le processus et rend ses tokens de façon bloquante : itérer dessus depuis
la boucle asyncio gèlerait tout le backend pendant la génération. Le travail part donc dans un fil,
et les tokens reviennent par une file *bornée* — la borne est ce qui applique une contre-pression au
moteur quand le client lit moins vite qu'il ne produit, au lieu d'accumuler en mémoire.

Trois bornes explicites, aucune attente infinie : taille de file, délai de publication d'un token,
délai d'inactivité côté consommateur.
"""

from __future__ import annotations

import asyncio
import threading
from typing import Any, AsyncIterator, Callable, Iterator, TypeVar

from loguru import logger

T = TypeVar("T")

TAILLE_FILE = 64
DELAI_PUBLICATION_S = 30.0
# Repli seulement : l'appelant réel (`adaptateur_llama_cpp`) passe le délai configuré du chat, pour
# que ce watchdog ne coupe JAMAIS avant celui de génération. Le repli est aligné à la même valeur
# haute — un préremplissage lourd n'émet aucun token avant plusieurs minutes, 300 s le tuait.
DELAI_INACTIVITE_S = 900.0
DELAI_ARRET_FIL_S = 5.0

_SENTINELLE = object()


# Pas d'attente d'un seul tenant : on repasse voir le drapeau d'arrêt à ce rythme.
PAS_ATTENTE_DEPOT_S = 0.25


def _deposer(
    boucle: asyncio.AbstractEventLoop,
    file: "asyncio.Queue[Any]",
    valeur: Any,
    delai: float,
    arret: threading.Event | None = None,
) -> None:
    """Dépose une valeur depuis un fil, sans jamais ignorer une demande d'arrêt.

    L'attente est FRACTIONNÉE, et c'est tout l'enjeu. Attendue d'un seul tenant, elle immobilisait
    le fil jusqu'au bout du délai dès que le client se déconnectait — trente secondes pendant
    lesquelles le VERROU DU MOTEUR restait pris. Une génération lancée entre-temps dans une autre
    conversation échouait alors sur « une génération est déjà en cours », et le chat paraissait
    charger dans le vide. Mesuré le 2026-08-14 : changer de conversation en cours de génération
    rendait l'application inutilisable jusqu'à expiration du délai.

    Le drapeau d'arrêt est justement levé dans ce cas : le consulter régulièrement suffit à rendre
    le verrou tout de suite.
    """
    futur = asyncio.run_coroutine_threadsafe(file.put(valeur), boucle)
    restant = delai
    while restant > 0:
        if arret is not None and arret.is_set():
            futur.cancel()
            return
        try:
            futur.result(timeout=min(PAS_ATTENTE_DEPOT_S, restant))
            return
        except (TimeoutError, asyncio.TimeoutError):
            restant -= PAS_ATTENTE_DEPOT_S
        except RuntimeError as exc:  # boucle asyncio fermée : plus personne pour recevoir
            logger.warning("Flux moteur : dépôt impossible ({}), le consommateur a disparu", exc)
            return
    futur.cancel()
    logger.warning("Flux moteur : dépôt abandonné après {} s, le consommateur ne lit plus", delai)


def _demarrer_producteur(
    fabrique: Callable[[threading.Event], Iterator[T]],
    boucle: asyncio.AbstractEventLoop,
    file: "asyncio.Queue[Any]",
    arret: threading.Event,
    delai_publication_s: float,
) -> threading.Thread:
    """Lance le fil de production. Il se termine toujours en déposant la sentinelle de fin."""

    def producteur() -> None:
        try:
            for element in fabrique(arret):
                if arret.is_set():
                    break
                _deposer(boucle, file, element, delai_publication_s, arret)
        except BaseException as exc:  # remontée telle quelle au consommateur, qui la relèvera
            logger.error("Flux moteur interrompu : {}", exc)
            _deposer(boucle, file, exc, delai_publication_s, arret)
        finally:
            _deposer(boucle, file, _SENTINELLE, delai_publication_s, arret)

    fil = threading.Thread(target=producteur, daemon=True, name="flux-moteur")
    fil.start()
    return fil


async def flux_depuis_bloquant(
    fabrique: Callable[[threading.Event], Iterator[T]],
    *,
    iterations_max: int,
    taille_file: int = TAILLE_FILE,
    delai_publication_s: float = DELAI_PUBLICATION_S,
    delai_inactivite_s: float = DELAI_INACTIVITE_S,
) -> AsyncIterator[T]:
    """Transforme un itérateur bloquant en flux asynchrone annulable.

    `fabrique` reçoit un drapeau d'arrêt : elle doit cesser de produire dès qu'il est levé, ce qui
    arrive quand le client ferme la connexion. `iterations_max` borne le flux — un moteur qui ne
    s'arrête jamais est un bug, pas une génération longue.
    """
    boucle = asyncio.get_running_loop()
    file: "asyncio.Queue[Any]" = asyncio.Queue(maxsize=taille_file)
    arret = threading.Event()
    fil = _demarrer_producteur(fabrique, boucle, file, arret, delai_publication_s)

    compteur = 0
    try:
        while compteur < iterations_max:
            element = await asyncio.wait_for(file.get(), timeout=delai_inactivite_s)
            if element is _SENTINELLE:
                return
            if isinstance(element, BaseException):
                raise element
            compteur += 1
            yield element
        logger.warning("Flux moteur borné à {} éléments : arrêt forcé", iterations_max)
    finally:
        arret.set()
        fil.join(timeout=DELAI_ARRET_FIL_S)
        if fil.is_alive():
            logger.warning("Fil de génération encore actif après {} s", DELAI_ARRET_FIL_S)
