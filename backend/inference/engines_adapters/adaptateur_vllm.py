"""Adaptateur vLLM — serveur OpenAI-compatible piloté comme sous-processus sur un port dédié.

vLLM prélloue la VRAM et ne la rend qu'à l'arrêt du processus : sur 16 Go, aucune cohabitation
n'est possible avec un modèle llama.cpp chargé. L'exclusivité est donc imposée par le superviseur,
et cet adaptateur garantit seulement que son processus meurt complètement quand on le lui demande.

L'attente de démarrage est un sondage réel de `/health`, borné, qui surveille aussi la mort du
sous-processus. En cas d'échec, c'est le journal du sous-processus qui est qualifié : la cause y est
écrite en clair, alors que l'exception côté client ne dit que « connexion refusée ».
"""

from __future__ import annotations

import asyncio
import json
import subprocess
import time
from pathlib import Path
from typing import IO, Any, AsyncIterator, Sequence

import httpx
from loguru import logger

from backend.inference.engines_adapters import processus_vllm
from backend.inference.engines_adapters.base import AdaptateurMoteur, exiger_moteur, exiger_source_lisible
from backend.inference.engines_adapters.contrat import (
    CauseEchec,
    EtatMoteur,
    MessageChat,
    MorceauGeneration,
    MoteurSupporte,
    OptionsGeneration,
    PlanChargement,
    Sante,
)
from backend.inference.engines_adapters.diagnostic import Diagnostic, EchecChargement, qualifier
from backend.inference.engines_adapters.journal import NiveauEntree, SessionChargement, journal_chargement
from backend.inference.engines_adapters.vram import MesureVram, lire_vram

DELAI_GENERATION_S = 600.0
DELAI_SONDE_S = 5.0
PREFIXE_SSE = "data: "
MARQUEUR_FIN_SSE = "[DONE]"


class AdaptateurVllm(AdaptateurMoteur):
    """Pilote un serveur vLLM local, un modèle à la fois."""

    moteur = MoteurSupporte.VLLM

    def __init__(self) -> None:
        self._processus: subprocess.Popen[bytes] | None = None
        self._journal_fichier: IO[bytes] | None = None
        self._etat: EtatMoteur | None = None

    @property
    def etat(self) -> EtatMoteur | None:
        return self._etat

    async def charger(self, plan: PlanChargement, session: SessionChargement | None = None) -> EtatMoteur:
        exiger_moteur(plan, self.moteur)
        exiger_source_lisible(plan)
        await processus_vllm.nettoyer_orphelin()

        interpreteur = processus_vllm.resoudre_interpreteur()
        commande = processus_vllm.construire_commande(plan, interpreteur)
        chemin_journal = processus_vllm.chemin_journal()
        vram_avant = lire_vram()
        journal_chargement.noter(
            session, "vllm", f"Démarrage du serveur pour {plan.nom_affiche}",
            details={"commande": commande[1:], "journal": str(chemin_journal),
                     "vram_libre_mo": vram_avant.libre_mo if vram_avant else None},
        )

        debut = time.perf_counter()
        self._journal_fichier = self._ouvrir_journal(chemin_journal)
        self._processus = processus_vllm.demarrer(commande, plan.variables_env, self._journal_fichier)
        processus_vllm.retenir_pid(self._processus.pid)

        try:
            pret, raison = await processus_vllm.attendre_sante(self._processus)
        except asyncio.CancelledError:
            # Une annulation pendant le démarrage laisserait un serveur vivant et sa VRAM prise :
            # le sous-processus doit mourir avant que l'annulation ne remonte.
            journal_chargement.noter(
                session, "vllm", "Annulation pendant le démarrage : arrêt du sous-processus",
                niveau=NiveauEntree.AVERTISSEMENT,
            )
            await self.decharger()
            raise
        if not pret:
            await self._echouer(plan, chemin_journal, raison, session)
        return self._enregistrer_etat(plan, time.perf_counter() - debut, vram_avant, session)

    def _ouvrir_journal(self, chemin: Path) -> IO[bytes]:
        """Journal remis à zéro à chaque démarrage : un fichier qui couvre le run en cours est lisible."""
        try:
            return open(chemin, "wb")
        except OSError as exc:
            logger.error("Journal vLLM {} inutilisable : {}", chemin, exc)
            raise EchecChargement(
                Diagnostic(
                    cause=CauseEchec.MOTEUR_ABSENT,
                    message=f"Impossible d'écrire le journal du moteur vLLM : {exc}",
                    remediation="Vérifier les droits du répertoire de logs et le montage du volume de données.",
                )
            ) from exc

    async def _echouer(
        self,
        plan: PlanChargement,
        chemin_journal: Path,
        raison: str,
        session: SessionChargement | None,
    ) -> None:
        """Qualifie l'échec à partir du journal du sous-processus, puis nettoie. Lève toujours."""
        texte = self._lire_journal(chemin_journal)
        diagnostic = qualifier(f"{raison}\n{texte}", source_verifiee=True)
        if diagnostic.cause is CauseEchec.INDETERMINEE and "aucune réponse" in raison:
            diagnostic = Diagnostic(
                cause=CauseEchec.DELAI_DEPASSE,
                message=f"Le serveur vLLM n'a pas répondu dans la fenêtre de démarrage : {raison}.",
                remediation="Consulter le journal du moteur : le chargement est bloqué, pas seulement lent.",
                indices=diagnostic.indices,
            )
        journal_chargement.noter(
            session, "vllm", f"Échec : {diagnostic.message}",
            niveau=NiveauEntree.ERREUR,
            details={"cause": diagnostic.cause.value, "raison": raison},
        )
        await self.decharger()
        raise EchecChargement(diagnostic, details={"moteur": self.moteur.value, "modele": plan.nom_affiche})

    def _lire_journal(self, chemin: Path) -> str:
        try:
            if self._journal_fichier is not None:
                self._journal_fichier.flush()
            return chemin.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            logger.warning("Journal vLLM illisible : {}", exc)
            return ""

    def _enregistrer_etat(
        self,
        plan: PlanChargement,
        duree: float,
        vram_avant: MesureVram | None,
        session: SessionChargement | None,
    ) -> EtatMoteur:
        vram_apres = lire_vram()
        self._etat = EtatMoteur(
            moteur=self.moteur, modele=plan.nom_affiche, pret=True,
            contexte=plan.contexte, couches_gpu=plan.couches_gpu,
            port=processus_vllm.port_vllm(), duree_chargement_s=round(duree, 2),
            vram_avant_octets=vram_avant.utilisee_octets if vram_avant else None,
            vram_apres_octets=vram_apres.utilisee_octets if vram_apres else None,
            details={"pid": self._processus.pid if self._processus else None},
        )
        journal_chargement.noter(
            session, "vllm", f"Serveur prêt en {duree:.1f} s",
            details={"vram_utilisee_mo": vram_apres.utilisee_mo if vram_apres else None},
        )
        return self._etat

    async def decharger(self) -> None:
        """Tue l'arbre de processus : c'est la seule façon de récupérer la VRAM préallouée."""
        await processus_vllm.arreter(self._processus)
        self._processus = None
        self._etat = None
        if self._journal_fichier is not None:
            try:
                self._journal_fichier.close()
            except OSError as exc:
                logger.warning("Fermeture du journal vLLM imparfaite : {}", exc)
            finally:
                self._journal_fichier = None

    async def sante(self) -> Sante:
        if self._processus is None or self._etat is None:
            return Sante(disponible=False, moteur=self.moteur, detail="Aucun serveur vLLM démarré.")
        code_sortie = self._processus.poll()
        if code_sortie is not None:
            return Sante(
                disponible=False, moteur=self.moteur, modele=self._etat.modele,
                detail=f"Le sous-processus vLLM s'est arrêté (code {code_sortie}).",
            )
        debut = time.perf_counter()
        try:
            async with httpx.AsyncClient(timeout=DELAI_SONDE_S) as client:
                reponse = await client.get(f"{processus_vllm.url_base()}/health")
            disponible = reponse.status_code == 200
            detail = "" if disponible else f"/health a répondu {reponse.status_code}"
        except httpx.HTTPError as exc:
            logger.warning("Sonde vLLM en échec : {}", exc)
            return Sante(disponible=False, moteur=self.moteur, modele=self._etat.modele, detail=str(exc))
        return Sante(
            disponible=disponible, moteur=self.moteur, modele=self._etat.modele,
            latence_ms=round((time.perf_counter() - debut) * 1000, 2), detail=detail,
        )

    def generer(
        self,
        messages: Sequence[MessageChat],
        options: OptionsGeneration,
    ) -> AsyncIterator[MorceauGeneration]:
        if self._etat is None:
            raise EchecChargement(
                Diagnostic(
                    cause=CauseEchec.MOTEUR_ABSENT,
                    message="Aucun modèle servi par vLLM.",
                    remediation="Charger un modèle avant de générer.",
                )
            )
        return self._flux(messages, options)

    async def _flux(
        self,
        messages: Sequence[MessageChat],
        options: OptionsGeneration,
    ) -> AsyncIterator[MorceauGeneration]:
        """Relaie le flux SSE de vLLM, borné par le contexte servi : un flux sans fin est un bug."""
        charge_utile = self._charge_utile(messages, options)
        plafond = options.max_tokens or (self._etat.contexte if self._etat else 0)
        emis = 0
        raison: str | None = None
        async with httpx.AsyncClient(timeout=DELAI_GENERATION_S) as client:
            async with client.stream(
                "POST", f"{processus_vllm.url_base()}/v1/chat/completions", json=charge_utile
            ) as reponse:
                await self._verifier_reponse(reponse)
                async for ligne in reponse.aiter_lines():
                    morceau = _decoder_evenement(ligne)
                    if morceau is None:
                        continue
                    if morceau.type == "fin":
                        raison = morceau.raison_arret or raison
                        break
                    raison = morceau.raison_arret or raison
                    if morceau.contenu:
                        emis += 1
                        yield morceau
                    if emis >= plafond > 0:
                        logger.warning("Flux vLLM borné à {} tokens : arrêt", plafond)
                        break
        yield MorceauGeneration(type="fin", raison_arret=raison)

    async def _verifier_reponse(self, reponse: httpx.Response) -> None:
        """Un 4xx/5xx de vLLM porte la vraie cause dans son corps : le lire avant de lever."""
        if reponse.status_code < 400:
            return
        corps = (await reponse.aread()).decode(errors="replace")
        logger.error("vLLM {} sur /v1/chat/completions : {}", reponse.status_code, corps[:500])
        diagnostic = qualifier(corps, source_verifiee=True)
        raise EchecChargement(diagnostic, details={"statut": reponse.status_code})

    def _charge_utile(self, messages: Sequence[MessageChat], options: OptionsGeneration) -> dict[str, Any]:
        charge: dict[str, Any] = {
            "model": self._etat.modele if self._etat else "",
            "messages": [message.model_dump() for message in messages],
            "temperature": options.temperature,
            "top_p": options.top_p,
            "stream": True,
        }
        if options.top_k is not None:
            charge["top_k"] = options.top_k
        if options.repetition_penalty is not None:
            charge["repetition_penalty"] = options.repetition_penalty
        if options.max_tokens is not None:
            charge["max_tokens"] = options.max_tokens
        if options.stop:
            charge["stop"] = list(options.stop)
        if options.graine is not None:
            charge["seed"] = options.graine
        return charge


def _decoder_evenement(ligne: str) -> MorceauGeneration | None:
    """Traduit une ligne SSE en morceau. Retourne None pour tout ce qui n'est pas un événement."""
    if not ligne or not ligne.startswith(PREFIXE_SSE):
        return None
    charge = ligne[len(PREFIXE_SSE):].strip()
    if charge == MARQUEUR_FIN_SSE:
        return MorceauGeneration(type="fin")
    try:
        evenement = json.loads(charge)
    except json.JSONDecodeError:
        logger.warning("Événement SSE vLLM illisible, ignoré : {}", charge[:120])
        return None
    choix = (evenement.get("choices") or [{}])[0]
    contenu = (choix.get("delta") or {}).get("content") or ""
    return MorceauGeneration(type="token", contenu=contenu, raison_arret=choix.get("finish_reason"))
