"""Superviseur d'inférence : un modèle chargé à la fois, sur un GPU traité comme ressource exclusive.

Trois garanties, toutes issues de défauts mesurés :

- **Exclusivité.** vLLM prélloue la VRAM et ne la rend qu'à la mort de son processus ; sur 16 Go,
  charger un modèle sans avoir éjecté le précédent produit un OOM au mieux, une machine figée au
  pire. Tout chargement commence donc par une éjection, dont la libération de VRAM est *vérifiée*.
- **Asynchronisme observable.** Un chargement dure de dix secondes à plusieurs minutes. Il part en
  tâche de fond et son état reste interrogeable : en cours, prêt, ou échoué avec une cause nommée.
- **Traçabilité.** Chaque chargement ouvre une session de journal qui porte le plan appliqué et le
  déroulé, consultable après coup sans relancer l'opération.

Le superviseur ne planifie pas et ne dégrade pas : il applique le plan qu'on lui donne et rend une
cause exploitable. La replanification appartient au planificateur.
"""

from __future__ import annotations

import asyncio
import os
import time
from typing import AsyncIterator, Sequence

from loguru import logger
from pydantic import BaseModel, Field

from backend.core import ChargementEchoue, maintenant
from backend.inference.engines_adapters.adaptateur_llama_cpp import AdaptateurLlamaCpp
from backend.inference.engines_adapters.adaptateur_llama_server import AdaptateurLlamaServer
from backend.inference.engines_adapters.adaptateur_vllm import AdaptateurVllm
from backend.inference.engines_adapters import processus_llama_server
from backend.inference.engines_adapters.base import AdaptateurMoteur
from backend.inference.engines_adapters.contrat import (
    CauseEchec,
    EtatChargement,
    EtatMoteur,
    MessageChat,
    MorceauGeneration,
    MoteurSupporte,
    OccupationContexte,
    OptionsGeneration,
    PlanChargement,
    Sante,
    assembler_occupation,
    decouper_images,
    decouper_segments,
)
from backend.inference.engines_adapters.diagnostic import Diagnostic, EchecChargement, qualifier
from backend.inference.engines_adapters.journal import (
    NiveauEntree,
    SessionChargement,
    journal_chargement,
)
from backend.inference.engines_adapters.vram import MesureVram, attendre_liberation, lire_vram

# Bornes : au-delà, on ne bloque pas l'appelant, on lui répond que l'opération est occupée.
DELAI_ANNULATION_S = 30.0
DELAI_VERROU_S = 60.0


class ChargementEnCours(ChargementEchoue):
    """Une opération de chargement occupe déjà le GPU. Conflit d'état, pas échec de modèle."""

    code = "chargement_en_cours"
    statut_http = 409
    remediation_defaut = "Attendre la fin du chargement en cours, ou le décharger avant d'en démarrer un autre."


class StatutInference(BaseModel):
    """Vue complète et sérialisable de ce que fait le domaine inference à cet instant."""

    etat: EtatChargement = EtatChargement.INACTIF
    moteur: MoteurSupporte | None = None
    modele: str | None = None
    plan: PlanChargement | None = None
    etat_moteur: EtatMoteur | None = None
    cause: CauseEchec | None = None
    message: str = ""
    remediation: str = ""
    session_journal: str | None = None
    depuis: str = Field(default_factory=maintenant)


# Variable d'environnement de secours : `bindings` force l'ancien chemin, `serveur` force le
# nouveau. Vide (le cas normal) laisse la disponibilité du binaire décider.
VARIABLE_CHEMIN_LLAMA = "ECHOHUB_CHEMIN_LLAMA"


def _adaptateur_llama_cpp() -> AdaptateurMoteur:
    """Choisit l'implémentation de llama.cpp : le serveur natif, ou les bindings Python.

    CE N'EST PAS UN AUTRE MOTEUR, et c'est la raison de ce choix ici plutôt que dans le
    planificateur : le plan est identique, les deux chemins appliquent les mêmes couches GPU, les
    mêmes blocs d'experts déportés, le même contexte et le même cache. Faire de `llama-server` une
    troisième valeur de `Moteur` aurait obligé le planificateur, l'écran des capacités et le
    frontend à connaître une distinction qui ne change rien à ce qu'ils décident — et aurait rendu
    les deux chemins incomparables, puisqu'ils n'auraient plus reçu le même plan.

    Le serveur natif est préféré quand son binaire est présent, pour une raison mesurée le
    2026-08-26 sur le 35B-A3B : les bindings réévaluent le prompt ENTIER à chaque tour d'une même
    conversation — l'architecture est hybride, un état récurrent ne se tronque pas, et
    `kv_cache_seq_rm` refuse donc la réutilisation du préfixe. TTFT 5,94 s à chaque message contre
    0,15 s dès le second avec le serveur. `swa_full=True` a été essayé : sans effet.

    Le repli sur les bindings n'est pas une précaution de style : ils restent le seul chemin qui
    expose le tokenizer et le découpage multimodal dans ce processus.
    """
    choix = os.environ.get(VARIABLE_CHEMIN_LLAMA, "").strip().lower()
    if choix == "bindings":
        logger.info("llama.cpp : chemin bindings imposé par {}", VARIABLE_CHEMIN_LLAMA)
        return AdaptateurLlamaCpp()
    if choix == "serveur" or processus_llama_server.binaire_disponible():
        logger.info("llama.cpp : chemin llama-server ({})", processus_llama_server.CHEMIN_BINAIRE)
        return AdaptateurLlamaServer()
    logger.info("llama.cpp : binaire llama-server absent, repli sur les bindings Python.")
    return AdaptateurLlamaCpp()


class SuperviseurInference:
    """Point d'entrée unique du pilotage des moteurs. Une seule instance par processus."""

    def __init__(self) -> None:
        self._adaptateurs: dict[MoteurSupporte, AdaptateurMoteur] = {
            MoteurSupporte.LLAMA_CPP: _adaptateur_llama_cpp(),
            MoteurSupporte.VLLM: AdaptateurVllm(),
        }
        self._actif: AdaptateurMoteur | None = None
        self._statut = StatutInference()
        self._verrou = asyncio.Lock()
        self._tache: asyncio.Task[None] | None = None
        # Ligne de base de VRAM mesurée avant le tout premier chargement : cible de la vérification
        # de libération. La VRAM au repos n'est jamais nulle (bureau Windows, autres processus).
        self._reference_vram: MesureVram | None = None

    # ------------------------------------------------------------------ état

    def statut(self) -> StatutInference:
        return self._statut

    def journal(self, limite: int = 10) -> list[SessionChargement]:
        return journal_chargement.sessions(limite)

    async def sante(self) -> Sante:
        if self._actif is None:
            return Sante(disponible=False, detail="Aucun moteur actif.")
        return await self._actif.sante()

    # -------------------------------------------------------------- chargement

    async def demarrer_chargement(self, plan: PlanChargement) -> StatutInference:
        """Lance le chargement en tâche de fond et rend l'état immédiatement observable."""
        if self._statut.etat is EtatChargement.EN_COURS:
            raise ChargementEnCours(
                f"Un chargement est déjà en cours ({self._statut.modele}).",
                details={"modele_en_cours": self._statut.modele},
            )
        session = journal_chargement.ouvrir(plan)
        self._statut = StatutInference(
            etat=EtatChargement.EN_COURS,
            moteur=plan.moteur,
            modele=plan.nom_affiche,
            plan=plan,
            session_journal=session.identifiant,
        )
        self._tache = asyncio.create_task(self._executer(plan, session), name=f"chargement-{plan.nom_affiche}")
        return self._statut

    async def _executer(self, plan: PlanChargement, session: SessionChargement) -> None:
        """Corps de la tâche de fond. Ne lève jamais : toute issue est traduite en statut."""
        debut = time.perf_counter()
        try:
            async with self._verrou:
                await self._liberer(session)
                adaptateur = self._adaptateurs[plan.moteur]
                etat_moteur = await adaptateur.charger(plan, session)
                self._actif = adaptateur
            self._conclure_succes(plan, session, etat_moteur, time.perf_counter() - debut)
        except asyncio.CancelledError:
            # `adaptateur.charger()` peut avoir déjà lancé un sous-processus (llama-server) quand
            # l'annulation frappe pendant l'attente de sa santé : l'exception traverse `_demarrer`
            # sans jamais atteindre son propre nettoyage, et le Popen reste référencé dans
            # l'adaptateur sans qu'aucun `poll()` supplémentaire ne le récolte — un zombie mesuré
            # le 2026-08-28 (PID 337338, PPID du backend, jamais réclamé). `decharger()` est
            # idempotent : appelé alors que rien n'a démarré, il ne fait rien.
            await self._adaptateurs[plan.moteur].decharger()
            self._conclure_echec(plan, session, _diagnostic_annulation(), time.perf_counter() - debut)
            raise
        except EchecChargement as exc:
            self._conclure_echec(plan, session, exc.diagnostic, time.perf_counter() - debut)
        except Exception as exc:  # signature inconnue : qualifiée puis journalisée, jamais avalée
            logger.exception("Chargement de {} interrompu par une erreur non qualifiée", plan.nom_affiche)
            diagnostic = qualifier(str(exc), source_verifiee=True, exception=exc)
            self._conclure_echec(plan, session, diagnostic, time.perf_counter() - debut)

    def _conclure_succes(
        self,
        plan: PlanChargement,
        session: SessionChargement,
        etat_moteur: EtatMoteur,
        duree: float,
    ) -> None:
        journal_chargement.cloturer(session, EtatChargement.PRET, duree_s=round(duree, 2))
        self._statut = StatutInference(
            etat=EtatChargement.PRET,
            moteur=plan.moteur,
            modele=plan.nom_affiche,
            plan=plan,
            etat_moteur=etat_moteur,
            session_journal=session.identifiant,
        )
        logger.success("Modèle {} prêt sur {} en {:.1f} s", plan.nom_affiche, plan.moteur.value, duree)

    def _conclure_echec(
        self,
        plan: PlanChargement,
        session: SessionChargement,
        diagnostic: Diagnostic,
        duree: float,
    ) -> None:
        journal_chargement.cloturer(
            session, EtatChargement.ECHOUE,
            cause=diagnostic.cause, message=diagnostic.message,
            remediation=diagnostic.remediation, duree_s=round(duree, 2),
        )
        self._statut = StatutInference(
            etat=EtatChargement.ECHOUE,
            moteur=plan.moteur,
            modele=plan.nom_affiche,
            plan=plan,
            cause=diagnostic.cause,
            message=diagnostic.message,
            remediation=diagnostic.remediation,
            session_journal=session.identifiant,
        )
        logger.error("Chargement de {} échoué [{}] : {}", plan.nom_affiche, diagnostic.cause.value, diagnostic.message)

    async def attendre(self, delai_s: float) -> StatutInference:
        """Attend la fin du chargement en cours, dans une fenêtre bornée. Utile aux appels synchrones."""
        tache = self._tache
        if tache is None or tache.done():
            return self._statut
        try:
            await asyncio.wait_for(asyncio.shield(tache), timeout=delai_s)
        except asyncio.TimeoutError:
            logger.info("Attente de chargement écoulée après {} s, le chargement continue", delai_s)
        except asyncio.CancelledError:
            logger.info("Chargement annulé pendant l'attente")
        return self._statut

    # ------------------------------------------------------------ déchargement

    async def decharger(self) -> StatutInference:
        """Éjecte le modèle courant, en annulant d'abord un chargement en cours."""
        await self._annuler_tache()
        try:
            await asyncio.wait_for(self._verrou.acquire(), timeout=DELAI_VERROU_S)
        except asyncio.TimeoutError as exc:
            raise ChargementEnCours(
                "Le moteur ne rend pas la main : déchargement impossible pour l'instant.",
                details={"delai_s": DELAI_VERROU_S},
            ) from exc
        try:
            await self._liberer(journal_chargement.derniere())
            self._statut = StatutInference(etat=EtatChargement.INACTIF)
        finally:
            self._verrou.release()
        return self._statut

    async def _annuler_tache(self) -> None:
        """Annule le chargement en cours. Un chargement llama.cpp déjà dans son fil ne s'interrompt
        pas : l'annulation prend effet à son retour, d'où l'attente bornée plutôt qu'infinie."""
        tache = self._tache
        if tache is None or tache.done():
            return
        tache.cancel()
        try:
            await asyncio.wait_for(asyncio.shield(tache), timeout=DELAI_ANNULATION_S)
        except (asyncio.TimeoutError, asyncio.CancelledError):
            logger.warning("Chargement non terminé {} s après annulation", DELAI_ANNULATION_S)

    async def _liberer(self, session: SessionChargement | None) -> None:
        """Décharge le moteur actif et VÉRIFIE la restitution de la VRAM avant d'autoriser la suite."""
        if self._reference_vram is None and self._actif is None:
            self._reference_vram = lire_vram()
        if self._actif is None:
            return

        precedent = self._actif
        self._actif = None
        journal_chargement.noter(session, "ejection", f"Déchargement de {precedent.moteur.value}")
        await precedent.decharger()

        resultat = await attendre_liberation(self._reference_vram)
        journal_chargement.noter(
            session, "ejection",
            "VRAM rendue" if resultat.verifiee else resultat.message or "VRAM non vérifiable",
            niveau=NiveauEntree.INFO if resultat.verifiee or not resultat.mesurable else NiveauEntree.ERREUR,
            details={"tentatives": resultat.tentatives,
                     "vram_utilisee_mo": resultat.mesure_finale.utilisee_mo if resultat.mesure_finale else None},
        )
        if resultat.mesurable and not resultat.verifiee:
            raise EchecChargement(
                Diagnostic(
                    cause=CauseEchec.VRAM_NON_LIBEREE,
                    message=resultat.message,
                    remediation="Un processus moteur survit au déchargement : redémarrer le backend libérera la carte.",
                    indices={"tentatives": resultat.tentatives},
                )
            )

    # --------------------------------------------------------- fenêtre de contexte

    async def compter_contexte(
        self,
        prompt_systeme: str,
        messages: Sequence[MessageChat],
    ) -> OccupationContexte:
        """Décompose ce que cette conversation occupe dans la fenêtre du modèle chargé.

        Passe par le moteur actif, donc par le verrou qui protège déjà la génération : un comptage
        ne s'exécute jamais pendant qu'un flux avance. Sans modèle prêt il n'existe aucun tokenizer
        et donc aucune mesure — la réponse le dit, elle ne rend pas une fenêtre vide.
        """
        if self._actif is None or self._statut.etat is not EtatChargement.PRET:
            return self._contexte_non_mesurable(
                f"Aucun modèle prêt (état : {self._statut.etat.value}) : aucun tokenizer à interroger."
            )
        segments = decouper_segments(prompt_systeme, messages)
        comptage = await self._actif.compter_tokens([segment.texte for segment in segments])
        etat_moteur = self._statut.etat_moteur
        contexte_plan = etat_moteur.contexte if etat_moteur is not None else None
        if not comptage.possible or comptage.contexte_moteur is None:
            return self._contexte_non_mesurable(comptage.raison, contexte_plan)

        # Les images suivent la même discipline que le texte : une conversation qui en porte et
        # dont le coût ne peut pas être mesuré rend TOUTE l'occupation non mesurable, plutôt que
        # d'afficher un total qui sous-compterait silencieusement ce qu'elle occupe réellement.
        images = decouper_images(messages)
        tokens_images: int | None = None
        if images:
            comptage_images = await self._actif.compter_multimodal(images)
            if not comptage_images.possible:
                return self._contexte_non_mesurable(comptage_images.raison, contexte_plan)
            tokens_images = sum(comptage_images.tokens_par_image)

        return assembler_occupation(
            segments,
            comptage.tokens_par_texte,
            contexte_total=comptage.contexte_moteur,
            contexte_plan=contexte_plan,
            moteur=self._statut.moteur,
            modele=self._statut.modele,
            tokens_images=tokens_images,
            nombre_images=len(images),
        )

    def _contexte_non_mesurable(self, raison: str, contexte_plan: int | None = None) -> OccupationContexte:
        """Absence de mesure, nommée. Aucun champ chiffré : un zéro passerait pour une fenêtre libre."""
        return OccupationContexte(
            mesurable=False,
            raison=raison,
            moteur=self._statut.moteur,
            modele=self._statut.modele,
            contexte_plan=contexte_plan,
        )

    # -------------------------------------------------------------- génération

    def accepte_pre_remplissage(self) -> bool:
        """Le moteur actif continue-t-il un tour d'assistant laissé ouvert ? (llama-server : oui.)"""
        return isinstance(self._actif, AdaptateurLlamaServer)

    def generer(
        self,
        messages: Sequence[MessageChat],
        options: OptionsGeneration,
        outils: Sequence[dict[str, object]] | None = None,
    ) -> AsyncIterator[MorceauGeneration]:
        """Flux de tokens du modèle chargé. Refuse tant qu'aucun modèle n'est prêt."""
        if self._actif is None or self._statut.etat is not EtatChargement.PRET:
            raise EchecChargement(
                Diagnostic(
                    cause=CauseEchec.MOTEUR_ABSENT,
                    message=f"Aucun modèle prêt (état : {self._statut.etat.value}).",
                    remediation="Charger un modèle avant de générer.",
                )
            )
        return self._actif.generer(messages, options, outils)

    async def proposer_outils(
        self,
        messages: Sequence[MessageChat],
        options: OptionsGeneration,
        outils: Sequence[dict[str, object]],
    ) -> list[dict[str, object]]:
        """Appels d'outils demandés par le modèle, avant la rédaction de sa réponse.

        Ne lève jamais quand aucun modèle n'est prêt, contrairement à `generer` : c'est une étape
        préparatoire facultative, et la génération qui suit portera l'erreur si elle doit être
        portée. Deux messages d'échec pour un seul problème n'aideraient personne.
        """
        if self._actif is None or self._statut.etat is not EtatChargement.PRET:
            return []
        return await self._actif.proposer_outils(messages, options, outils)


def _diagnostic_annulation() -> Diagnostic:
    return Diagnostic(
        cause=CauseEchec.ANNULE,
        message="Chargement annulé avant la fin.",
        remediation="Relancer le chargement si l'annulation n'était pas voulue.",
    )


# Instance unique du processus : le GPU est une ressource unique, son pilote l'est aussi.
superviseur = SuperviseurInference()
