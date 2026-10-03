"""Strata : le moteur écrit pour Qwen3.8-Flash-Next, servi sur l'HÔTE et piloté par HTTP.

Pourquoi un moteur à part : mesuré le 2026-10-02 sur ce modèle (SC117 IQ2_XS, 68 Go), llama.cpp
rend 6,6 tok/s et lit le prompt à 5 tok/s — un contexte d'agent de 16 k tokens coûtait ~50 min
avant le premier mot. Strata (cache d'experts en VRAM choisi par profil, tête MTP, préremplissage
par blocs de 8 k) est fait pour ce modèle sur une carte de 12 Go.

Pourquoi sur l'hôte : son moteur est compilé pour l'hôte (Arch, CUDA 13) et l'image est en Ubuntu
22.04 / CUDA 12 — la même impasse que llama-server (cf. docker-compose.yml). Son serveur tourne en
permanence, À VIDE (`--lazy`, lancé par docker/strata-hote.sh) : charger = POST /v1/load,
décharger = POST /v1/unload. La VRAM n'est tenue que lorsque le superviseur l'a décidé.

Le flux SSE est celui de llama-server (même dialecte OpenAI, `reasoning_content` compris) : seuls
l'adresse, la clé, le cycle de vie et le décompte de tokens changent.
"""

from __future__ import annotations

import functools
import json
import os
import time
from typing import Any, ClassVar, Sequence

import httpx
from loguru import logger
from pydantic import BaseModel

from backend.inference.engines_adapters.adaptateur_llama_server import AdaptateurLlamaServer
from backend.inference.engines_adapters.base import exiger_moteur
from backend.inference.engines_adapters.contrat import (
    CauseEchec,
    ComptageTokens,
    EtatMoteur,
    MoteurSupporte,
    PlanChargement,
    Sante,
)
from backend.inference.engines_adapters.diagnostic import Diagnostic, EchecChargement
from backend.inference.engines_adapters.journal import SessionChargement, journal_chargement
from backend.inference.engines_adapters.vram import lire_vram

# Vide = Strata non configuré (mode natif, tests) : aucun appel réseau, sonde « injoignable ».
URL_STRATA = os.environ.get("STRATA_URL", "").rstrip("/")
JETON_STRATA = os.environ.get("STRATA_JETON", "")
# Dossier `tokenizer` du pack : pas un tokenizer.json Hugging Face, mais vocab.json + merges.txt
# (BPE GPT-2 octet par octet) et le motif de prétokenisation dans le tokenizer.json de Strata.
CHEMIN_TOKENIZER = os.environ.get("STRATA_TOKENIZER", "/data/strata/tokenizer")
# Premier chargement : 35-55 Go lus depuis le SSD et une part verrouillée pour la carte (mesuré par
# Strata : 1 à 3 min, davantage à froid). Les suivants profitent du cache de pages.
DELAI_CHARGEMENT_S = 1200.0
DELAI_SONDE_S = 5.0
_REMEDIATION = ("Démarrer le serveur Strata sur l'hôte : ./start.sh --docker le lance, ou "
                "docker/strata-hote.sh demarrer ; son journal est logs/strata.log.")


class AdaptateurStrata(AdaptateurLlamaServer):
    """Pilote un serveur Strata déjà lancé sur l'hôte : charge, décharge, relaie le flux."""

    moteur: ClassVar[MoteurSupporte] = MoteurSupporte.STRATA

    def _url_base(self) -> str:
        return URL_STRATA

    def _client(self, delai_s: float) -> httpx.AsyncClient:
        entetes = {"Authorization": f"Bearer {JETON_STRATA}"} if JETON_STRATA else {}
        return httpx.AsyncClient(timeout=delai_s, headers=entetes)

    async def charger(self, plan: PlanChargement, session: SessionChargement | None = None) -> EtatMoteur:
        """POST /v1/load (synchrone côté Strata), puis /health pour lire ce qui est servi."""
        exiger_moteur(plan, self.moteur)
        if not URL_STRATA:
            raise EchecChargement(Diagnostic(cause=CauseEchec.MOTEUR_ABSENT, message="STRATA_URL non défini.",
                                             remediation=_REMEDIATION))
        journal_chargement.noter(session, "strata", f"Chargement de {plan.nom_affiche} sur {URL_STRATA}")
        vram_avant = lire_vram()
        depart = time.monotonic()
        try:
            async with self._client(DELAI_CHARGEMENT_S) as client:
                reponse = await client.post(f"{URL_STRATA}/v1/load", json={})
                _exiger_succes(reponse, "/v1/load")
                sante = (await client.get(f"{URL_STRATA}/health")).json()
        except httpx.HTTPError as exc:
            logger.error("Strata injoignable sur {} : {}", URL_STRATA, exc)
            raise EchecChargement(Diagnostic(
                cause=CauseEchec.MOTEUR_ABSENT, message=f"Serveur Strata injoignable ({URL_STRATA}) : {exc}",
                remediation=_REMEDIATION,
            )) from exc
        if not sante.get("loaded"):
            raise EchecChargement(Diagnostic(
                cause=CauseEchec.INDETERMINEE, message="Strata a répondu au chargement sans charger le modèle.",
                remediation="Lire logs/strata.log et le journal du moteur (strata-<modèle>.log) sur l'hôte.",
            ))
        duree = time.monotonic() - depart
        self._etat = _etat_servi(sante, plan, duree, vram_avant)
        journal_chargement.noter(session, "strata", f"Prêt en {duree:.1f} s — contexte {self._etat.contexte}.")
        return self._etat

    async def decharger(self) -> None:
        """POST /v1/unload, TOUJOURS : un Strata resté chargé par un backend précédent est libéré aussi.

        Idempotent ; un serveur absent n'est pas une erreur (rien ne tient la VRAM)."""
        self._etat = None
        if not URL_STRATA:
            return
        try:
            async with self._client(DELAI_CHARGEMENT_S) as client:
                reponse = await client.post(f"{URL_STRATA}/v1/unload", json={})
            if reponse.status_code != 200:
                logger.warning("Strata /v1/unload a répondu {} : {}", reponse.status_code, reponse.text[:300])
        except httpx.HTTPError as exc:
            logger.debug("Strata absent au déchargement ({}) : rien à libérer.", exc)

    async def sante(self) -> Sante:
        if self._etat is None:
            return Sante(disponible=False, detail="Aucun modèle servi par Strata.")
        depart = time.monotonic()
        try:
            async with self._client(DELAI_SONDE_S) as client:
                corps = (await client.get(f"{URL_STRATA}/health")).json()
        except (httpx.HTTPError, ValueError) as exc:
            return Sante(disponible=False, moteur=self.moteur, modele=self._etat.modele,
                         detail=f"Strata injoignable : {exc}")
        charge = bool(corps.get("loaded"))
        return Sante(disponible=charge, moteur=self.moteur, modele=self._etat.modele,
                     latence_ms=round((time.monotonic() - depart) * 1000, 1),
                     detail="" if charge else "Strata a déchargé le modèle.")

    async def compter_tokens(self, textes: Sequence[str]) -> ComptageTokens:
        """Le tokenizer du pack, lu localement : Strata n'expose pas de /tokenize.

        Sans ce décompte l'autocompaction ne se déclencherait jamais (cf. la version llama-server)."""
        if self._etat is None:
            return ComptageTokens(possible=False, raison="Aucun modèle servi par Strata.")
        tokenizer = _tokenizer()
        if tokenizer is None:
            return ComptageTokens(possible=False, raison=f"Tokenizer Strata illisible : {CHEMIN_TOKENIZER}")
        comptes = [len(tokenizer.encode(t, add_special_tokens=False).ids) if t else 0 for t in textes]
        return ComptageTokens(possible=True, tokens_par_texte=comptes, contexte_moteur=self._etat.contexte)


def _exiger_succes(reponse: httpx.Response, route: str) -> None:
    if reponse.status_code == 200:
        return
    logger.error("Strata {} a répondu {} : {}", route, reponse.status_code, reponse.text[:500])
    cause = CauseEchec.VRAM_INSUFFISANTE if "out of memory" in reponse.text.lower() else CauseEchec.INDETERMINEE
    raise EchecChargement(Diagnostic(
        cause=cause, message=f"Strata {route} : {reponse.status_code} {reponse.text[:300]}",
        remediation="Libérer la VRAM (autre modèle, autre programme) ou lire logs/strata.log sur l'hôte.",
    ))


def _etat_servi(sante: dict[str, Any], plan: PlanChargement, duree: float, vram_avant: Any) -> EtatMoteur:
    apres = lire_vram()
    return EtatMoteur(
        moteur=MoteurSupporte.STRATA, modele=plan.nom_affiche, pret=True,
        contexte=int(sante.get("max_context") or plan.contexte), couches_gpu=plan.couches_gpu,
        duree_chargement_s=round(duree, 2),
        vram_avant_octets=vram_avant.utilisee_octets if vram_avant else None,
        vram_apres_octets=apres.utilisee_octets if apres else None,
        details={"serveur": URL_STRATA, "modele_strata": sante.get("model")},
    )


@functools.cache
def _tokenizer() -> Any:
    """Le BPE du pack rebâti avec `tokenizers`, une fois ; `None` (journalisé) s'il est illisible."""
    try:
        from tokenizers import Regex, Tokenizer, models, pre_tokenizers

        with open(f"{CHEMIN_TOKENIZER}/tokenizer.json", encoding="utf-8") as fichier:
            motif = json.load(fichier)["pre_pattern"]
        tokenizer = Tokenizer(models.BPE.from_file(f"{CHEMIN_TOKENIZER}/vocab.json", f"{CHEMIN_TOKENIZER}/merges.txt"))
        tokenizer.pre_tokenizer = pre_tokenizers.Sequence([
            pre_tokenizers.Split(Regex(motif), behavior="isolated"),
            pre_tokenizers.ByteLevel(add_prefix_space=False, use_regex=False),
        ])
        return tokenizer
    except Exception as exc:  # ImportError, fichier absent, JSON invalide : même issue, mesure absente
        logger.warning("Tokenizer Strata illisible ({}) : {}", CHEMIN_TOKENIZER, exc)
        return None


class SondeStrata(BaseModel):
    """Ce que le serveur Strata de l'hôte dit de lui, pour l'écran des modèles."""

    joignable: bool
    charge: bool = False
    modele: str | None = None
    contexte: int | None = None
    detail: str = ""


async def sonder_serveur() -> SondeStrata:
    """GET /health, sans rien charger. Injoignable n'est pas une erreur : Strata est optionnel."""
    if not URL_STRATA:
        return SondeStrata(joignable=False, detail="STRATA_URL non défini : Strata n'est pas configuré.")
    try:
        async with httpx.AsyncClient(timeout=DELAI_SONDE_S) as client:
            corps = (await client.get(f"{URL_STRATA}/health")).json()
    except (httpx.HTTPError, ValueError) as exc:
        logger.debug("Strata injoignable sur {} : {}", URL_STRATA, exc)
        return SondeStrata(joignable=False, detail=_REMEDIATION)
    return SondeStrata(joignable=True, charge=bool(corps.get("loaded")), modele=corps.get("model"),
                       contexte=corps.get("max_context"))


def plan_strata(sonde: SondeStrata) -> PlanChargement:
    """Le plan d'un chargement Strata : rien à décider ici, Strata place lui-même ses experts."""
    return PlanChargement(
        moteur=MoteurSupporte.STRATA, chemin_modele=URL_STRATA,
        identifiant_modele=f"strata/{sonde.modele or 'qwen3.8-flash-next'}",
        couches_gpu=-1, contexte=sonde.contexte or 32768, batch=8192, type_kv_cache="int8",
        justifications=["Moteur Strata (hôte) : cache d'experts en VRAM, MTP, préremplissage par blocs de 8 k."],
    )


__all__ = ["AdaptateurStrata", "JETON_STRATA", "SondeStrata", "URL_STRATA", "plan_strata", "sonder_serveur"]
