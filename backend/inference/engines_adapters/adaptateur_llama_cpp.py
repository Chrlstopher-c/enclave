"""Adaptateur llama.cpp — moteur en processus, via llama-cpp-python.

Deux vérifications préalables évitent les deux diagnostics faux les plus coûteux de la v1 :

1. le module est-il présent (sinon : moteur absent, pas fichier illisible) ;
2. le binaire sait-il déléguer au GPU (sinon : moteur compilé sans CUDA — c'est le piège du wheel
   PyPI, CPU-only, où « tout fonctionne » sans que rien ne touche la carte).

Le chargement et la génération sont bloquants : ils partent dans un fil pour ne pas geler la boucle
asyncio, la génération étant en plus sérialisée — une instance `Llama` ne supporte pas deux
générations concurrentes.
"""

from __future__ import annotations

import asyncio
import base64
import ctypes
import gc
import json
import os
import re
import threading
import time
from pathlib import Path
from typing import Any, AsyncIterator, Iterator, Sequence

from loguru import logger

from backend.inference.engines_adapters.base import AdaptateurMoteur, exiger_moteur, exiger_source_lisible
from backend.inference.engines_adapters.contrat import (
    CauseEchec,
    ComptageImages,
    ComptageTokens,
    EtatMoteur,
    ImageURL,
    MessageChat,
    MorceauGeneration,
    MoteurSupporte,
    OptionsGeneration,
    PartieContenu,
    PartieImage,
    PartieImageChemin,
    PartieTexte,
    PlanChargement,
    Sante,
)
from backend.inference.engines_adapters.diagnostic import Diagnostic, EchecChargement, qualifier
from backend.inference.engines_adapters.experts_hote import (
    CollecteurJournal,
    deport_actif,
    verifier_application,
    verifier_support,
)
from backend.inference.engines_adapters.flux import flux_depuis_bloquant
from backend.inference.engines_adapters.journal import NiveauEntree, SessionChargement, journal_chargement
from backend.inference.engines_adapters.vram import MesureVram, lire_vram
from backend.models.storage import fichiers_projecteurs

# Identifiants de types GGML acceptés pour le cache KV. Une valeur hors table est un plan invalide :
# la deviner produirait un cache différent de celui que le planificateur a dimensionné.
#
# CETTE LISTE EST RESTRICTIVE À DESSEIN, et l'élargir a un coût mesuré. Le binaire expose
# trente-trois types ggml, dont `q2_0` et `q1_0` — les caches très basse précision qui rendraient
# tenables des fenêtres de plusieurs centaines de milliers de tokens. Le 2026-08-16, les avoir
# acceptés parce qu'ils EXISTAIENT a tué le backend au chargement :
#
#   ggml-backend.cpp:898: pre-allocated tensor (cache_k_l11 (view)) in a buffer (CUDA0)
#   that cannot run the operation (SET_ROWS)  ->  ggml_abort(), SIGABRT, processus mort
#
# Qu'un type existe dans ggml dit seulement qu'on sait ENCODER des poids avec. Servir un CACHE KV
# demande en plus que le backend sache écrire dedans (`SET_ROWS`), et CUDA ne l'implémente pas pour
# ces types. L'échec est un `abort()` natif qu'aucun `try/except` Python ne rattrape — même classe
# de faute que le projecteur de vision (`_detacher_vision_si_vram_insuffisante`), et même
# conclusion : la seule protection est de ne jamais tenter.
#
# N'ajouter un type ici qu'après l'avoir CHARGÉ et fait générer, pas après l'avoir vu dans `dir()`.
TYPES_KV: dict[str, int] = {"f32": 0, "f16": 1, "q4_0": 2, "q8_0": 8}

DELAI_VERROU_GENERATION_S = 5.0

# Attente maximale du verrou pour un simple comptage. Volontairement courte : le panneau de
# contexte se rafraîchit souvent et une génération tient le verrou pendant toute sa durée. Passé ce
# délai, on rend une absence nommée — bien moins coûteux qu'une requête qui pend pendant des minutes.
DELAI_VERROU_COMPTAGE_S = 2.0

# Budget de la passe « le modèle veut-il un outil ? ». Un appel tient en quelques dizaines de
# tokens ; ce plafond borne le seul moment de la génération qui soit invisible à l'utilisateur.
TOKENS_PROPOSITION_OUTILS = 192

# Variable dont la seule présence dégrade gravement le chargement sous WSL2 (mesuré : VRAM figée à
# 2 Go, plusieurs minutes de chargement). Elle n'est jamais posée ici ; si l'environnement la porte
# sans que le plan l'ait demandée, on le signale plutôt que de charger en silence dans ce mode.
VARIABLE_MEMOIRE_UNIFIEE = "GGML_CUDA_ENABLE_UNIFIED_MEMORY"

# Marge de VRAM libre exigée après chargement pour tenter d'initialiser l'encodeur visuel
# (`_init_mtmd_context`, appelé au premier comptage ou à la première image générée). MESURÉE, pas
# raisonnée (2026-08-15, RTX 3060, Qwen3-VL-8B-Instruct Q4_K_M + mmproj F16 1,1 Gio) : poids du
# projecteur alloués ~1105 Mio, tampon de calcul CUDA de l'encodeur ~4769 Mio — ~5,9 Gio au total
# avant le moindre token d'image. En dessous, `cudaMalloc` échoue et `ggml-backend.cpp` répond par
# un `abort()` natif (SIGABRT) qu'aucun `try/except` Python ne peut intercepter. 6 Gio couvre cette
# mesure avec une marge de sécurité ; un projecteur nettement plus lourd que celui mesuré ici
# resterait sous-couvert — voir `_detacher_vision_si_vram_insuffisante`.
MARGE_VISION_OCTETS = 6 * 1024 * 1024 * 1024


def _encoder_data_uri(chemin: str, type_mime: str) -> str | None:
    """Lit le fichier et produit son data URI — l'encodage a lieu ICI, au tout dernier moment, juste
    avant l'appel au moteur (plan d'exécution, section 2.2.4). Aucun octet ni base64 n'a traversé le
    port ni le domaine `chat` avant ce point.

    Une pièce illisible ne fait pas échouer tout le message : elle est journalisée et écartée, le
    reste du prompt part quand même — c'est la même discipline que le reste de l'adaptateur, où une
    frontière disque a toujours son try/catch.
    """
    try:
        octets = Path(chemin).read_bytes()
    except OSError as exc:
        logger.error("Pièce jointe illisible, écartée du prompt : {} ({})", chemin, exc)
        return None
    return f"data:{type_mime};base64,{base64.b64encode(octets).decode('ascii')}"


def _partie_moteur(partie: PartieContenu) -> PartieContenu | None:
    """Convertit une partie image-chemin en image-data-uri ; les autres parties sont inchangées."""
    if not isinstance(partie, PartieImageChemin):
        return partie
    uri = _encoder_data_uri(partie.chemin, partie.type_mime)
    if uri is None:
        return None
    return PartieImage(image_url=ImageURL(url=uri))


def _message_pour_moteur(message: MessageChat) -> dict[str, Any]:
    """Un message prêt pour `create_chat_completion` : images encodées, jamais avant."""
    if isinstance(message.content, str):
        return message.model_dump()
    parties = [_partie_moteur(partie) for partie in message.content]
    return {"role": message.role, "content": [partie.model_dump() for partie in parties if partie is not None]}


# Bornes des marqueurs JPEG SOFn (« Start Of Frame ») porteurs des dimensions. Les autres marqueurs
# de la famille SOF (progressive, arithmétique...) partagent le même agencement de segment ; ceux
# listés ici couvrent l'écrasante majorité des JPEG produits par un navigateur ou un appareil photo.
_MARQUEURS_JPEG_SOF = frozenset({0xC0, 0xC1, 0xC2, 0xC3})
_MARQUEURS_JPEG_SANS_LONGUEUR = frozenset({0x01, 0xD8}) | frozenset(range(0xD0, 0xD8))


def _dimensions_jpeg(octets: bytes) -> tuple[int, int] | None:
    """Largeur/hauteur JPEG lues dans le segment SOF — jamais devinées, `None` si introuvables."""
    indice = 2
    borne = len(octets)
    # Borne explicite : un JPEG valide ne peut pas contenir plus de segments que d'octets / 4.
    for _ in range(borne // 4 + 1):
        if indice + 4 > borne or octets[indice] != 0xFF:
            return None
        marqueur = octets[indice + 1]
        if marqueur in _MARQUEURS_JPEG_SOF:
            hauteur = int.from_bytes(octets[indice + 5 : indice + 7], "big")
            largeur = int.from_bytes(octets[indice + 7 : indice + 9], "big")
            return largeur, hauteur
        if marqueur in _MARQUEURS_JPEG_SANS_LONGUEUR:
            indice += 2
            continue
        taille_segment = int.from_bytes(octets[indice + 2 : indice + 4], "big")
        indice += 2 + taille_segment
    return None


def _dimensions_image(octets: bytes) -> tuple[int, int] | None:
    """Largeur/hauteur lues dans l'en-tête du fichier — PNG et JPEG seulement.

    Aucune formule, aucune estimation : soit l'en-tête connu est présent et on le lit, soit `None`
    et la ligne factuelle du repli (2.4) omet les dimensions plutôt que d'en inventer. GIF, WebP et
    SVG (formats acceptés par le magasin de fichiers, `backend/fichiers/politique.py`) ne sont pas
    couverts ici : le poids et le nom suffisent à la donnée factuelle transmise au modèle.
    """
    if octets[:8] == b"\x89PNG\r\n\x1a\n" and len(octets) >= 24:
        largeur = int.from_bytes(octets[16:20], "big")
        hauteur = int.from_bytes(octets[20:24], "big")
        return largeur, hauteur
    if octets[:2] == b"\xff\xd8":
        return _dimensions_jpeg(octets)
    return None


def _ligne_image_repliee(partie: PartieImageChemin) -> str:
    """Ligne factuelle qui remplace une image dans le texte, quand le moteur n'a pas de vision.

    Seul repli autorisé par le plan (2.4) : une DONNÉE transmise au modèle DANS le message
    utilisateur, jamais un refus rendu à l'utilisateur. Le modèle sait qu'une image existe, avec
    son nom, ses dimensions si lisibles, son poids — et répond ce qu'il veut de cette information.
    """
    nom = partie.nom_affiche or Path(partie.chemin).name
    try:
        octets = Path(partie.chemin).read_bytes()
    except OSError as exc:
        logger.warning("Image jointe illisible pour le repli sans vision : {} ({})", partie.chemin, exc)
        return f"[image jointe : {nom}]"
    taille_ko = len(octets) // 1024
    dimensions = _dimensions_image(octets)
    if dimensions is None:
        return f"[image jointe : {nom}, {taille_ko} Ko]"
    largeur, hauteur = dimensions
    return f"[image jointe : {nom}, {largeur}×{hauteur}, {taille_ko} Ko]"


def _message_pour_moteur_sans_vision(message: MessageChat) -> dict[str, Any]:
    """Repli du plan (2.4) : les parties image deviennent une ligne factuelle DANS le texte.

    Le moteur chargé n'a pas de gestionnaire multimodal ; `content` doit donc rester une chaîne
    simple, celle que son gabarit sait lire. Aucune image n'est perdue silencieusement : chaque
    partie devient une ligne, journalisée, et le texte original reste intact autour d'elle.
    """
    if isinstance(message.content, str):
        return message.model_dump()
    morceaux: list[str] = []
    images_repliees = 0
    for partie in message.content:
        if isinstance(partie, PartieTexte):
            morceaux.append(partie.text)
        elif isinstance(partie, PartieImageChemin):
            morceaux.append(_ligne_image_repliee(partie))
            images_repliees += 1
        # `PartieImage` (déjà encodée en data URI) n'a rien à faire ici : l'encodage n'a lieu que
        # dans le chemin AVEC vision (`_message_pour_moteur`), jamais avant ce repli.
    if images_repliees:
        logger.info(
            "Repli sans vision : {} image(s) remplacée(s) par une ligne factuelle dans le message "
            "(aucun projecteur multimodal chargé).",
            images_repliees,
        )
    return {"role": message.role, "content": "\n".join(morceaux)}


def _vision_disponible(llm: Any) -> bool:
    """Le moteur chargé a-t-il un gestionnaire multimodal ? — seul juge du chemin à emprunter.

    `Llama` stocke le `chat_handler` reçu au chargement (`_parametres`, `chat_handler=`) tel quel :
    sa seule présence dit que `_handler_vision` a trouvé et construit un projecteur. Rien n'est
    déduit du nom du modèle ni de sa capacité déclarée — l'objet réellement chargé fait foi.
    """
    return getattr(llm, "chat_handler", None) is not None


def _messages_pour_moteur(messages: Sequence[MessageChat], vision_disponible: bool = True) -> list[dict[str, Any]]:
    """Sérialise les messages pour le moteur — SEUL endroit qui encode une image en data URI.

    `vision_disponible` bascule entre les deux chemins du plan (2.2 et 2.4) : avec un gestionnaire
    multimodal, chaque image devient une partie `image_url`. Sans lui, c'est le repli — l'image
    devient une ligne de texte factuelle DANS le message. Défaut à `True` pour ne pas changer le
    comportement des appelants qui ignorent délibérément la question (aucun en dehors des tests) ;
    les deux appels réels du moteur (génération, proposition d'outils) passent la valeur mesurée.
    """
    if vision_disponible:
        return [_message_pour_moteur(message) for message in messages]
    return [_message_pour_moteur_sans_vision(message) for message in messages]


class AdaptateurLlamaCpp(AdaptateurMoteur):
    """Pilote une instance `Llama` unique, chargée dans le processus du backend."""

    moteur = MoteurSupporte.LLAMA_CPP

    def __init__(self) -> None:
        self._llm: Any | None = None
        self._etat: EtatMoteur | None = None
        self._contexte: int = 0
        # Verrou de fil (pas asyncio) : il protège l'objet C, manipulé depuis les fils de génération.
        self._verrou_generation = threading.Lock()

    @property
    def etat(self) -> EtatMoteur | None:
        return self._etat

    async def charger(self, plan: PlanChargement, session: SessionChargement | None = None) -> EtatMoteur:
        exiger_moteur(plan, self.moteur)
        chemin = exiger_source_lisible(plan)
        module = self._importer(session)
        self._verifier_offload_gpu(module, plan, session)
        self._appliquer_environnement(plan, session)

        parametres = self._parametres(plan, chemin, session)
        vram_avant = lire_vram()
        # `model_path` est déjà dans `plan.nom_affiche` (bruyant, redondant) ; `chat_handler` est
        # l'objet `MTMDChatHandler` construit par `_handler_vision` (ctypes, non sérialisable) —
        # ni l'un ni l'autre n'a sa place dans un journal destiné à être rendu en JSON par la route
        # `/inference/journal`. Sa présence est notée comme un fait booléen, pas comme l'objet.
        parametres_serialisables = {
            c: v for c, v in parametres.items() if c not in ("model_path", "chat_handler")
        }
        journal_chargement.noter(
            session, "llama.cpp", f"Chargement de {plan.nom_affiche}",
            details={"parametres": parametres_serialisables,
                     "vision_chargee": "chat_handler" in parametres,
                     "experts_deportes": plan.experts_deportes,
                     "vram_libre_mo": vram_avant.libre_mo if vram_avant else None},
        )

        debut = time.perf_counter()
        self._llm = await self._charger_instance(module, parametres, plan, session)
        duree = time.perf_counter() - debut
        vram_apres = lire_vram()
        self._contexte = plan.contexte
        self._etat = EtatMoteur(
            moteur=self.moteur, modele=plan.nom_affiche, pret=True,
            contexte=plan.contexte, couches_gpu=plan.couches_gpu, duree_chargement_s=round(duree, 2),
            vram_avant_octets=vram_avant.utilisee_octets if vram_avant else None,
            vram_apres_octets=vram_apres.utilisee_octets if vram_apres else None,
        )
        journal_chargement.noter(
            session, "llama.cpp", f"Modèle prêt en {duree:.1f} s",
            details={"vram_utilisee_mo": vram_apres.utilisee_mo if vram_apres else None},
        )
        self._detacher_vision_si_vram_insuffisante(vram_apres, session)
        return self._etat

    def _detacher_vision_si_vram_insuffisante(
        self, vram_apres: MesureVram | None, session: SessionChargement | None
    ) -> None:
        """Retire le `chat_handler` si la VRAM restante ne peut pas porter l'encodeur visuel.

        Plantage natif réel, reproduit et diagnostiqué le 2026-08-15 : `_init_mtmd_context` (appelé
        au premier comptage ou à la première génération avec image, JAMAIS au chargement — c'est
        volontairement paresseux) alloue les poids du projecteur PUIS un tampon de calcul CUDA pour
        l'encodeur visuel. Sur cette machine (RTX 3060, Qwen3-VL-8B-Instruct + son mmproj F16), ces
        deux allocations pèsent ensemble ~5,9 Gio, MESURÉS (`alloc_tensor_range` sur ~1105 Mio de
        poids, puis `reserve_compute_meta` sur ~4769 Mio de tampon). Un plan qui remplit la VRAM au
        plus juste pour le modèle principal (cas courant : le planificateur maximise les couches GPU
        et n'a aucune raison de connaître le coût d'un projecteur qu'il n'a pas choisi) ne laisse pas
        cette marge. `cudaMalloc` échoue alors sur l'allocation des poids du projecteur, et
        `ggml-backend.cpp` répond par `GGML_ASSERT(buffer)` — un `abort()` natif, SIGABRT, qui tue le
        processus entier. Aucune exception Python ne peut l'intercepter : la seule protection possible
        est de ne JAMAIS tenter cette allocation quand la marge n'y est pas.

        Le modèle reste chargé et utilisable : seul le tour de vision est retiré, exactement comme si
        aucun projecteur n'avait été trouvé (repli déjà éprouvé, section 2.4). Le chargement du modèle
        principal, lui, n'est jamais remis en cause par cette vérification.
        """
        if self._llm is None or getattr(self._llm, "chat_handler", None) is None:
            return
        if vram_apres is None:
            return  # pas de mesure : rien à comparer, on laisse la vision tentée (comportement antérieur)
        if vram_apres.libre_octets >= MARGE_VISION_OCTETS:
            return
        self._llm.chat_handler = None
        journal_chargement.noter(
            session, "llama.cpp",
            f"Projecteur de vision détaché : VRAM libre ({vram_apres.libre_mo} Mo) sous la marge "
            f"mesurée pour l'encodeur visuel ({MARGE_VISION_OCTETS // (1024 * 1024)} Mo). Une "
            "initialisation aurait planté le processus (SIGABRT natif, non rattrapable) au premier "
            "comptage ou à la première image envoyée. Le modèle reste chargé, le repli sans vision "
            "(2.4) s'applique désormais aux deux : mesure et génération.",
            niveau=NiveauEntree.AVERTISSEMENT,
        )

    async def _charger_instance(self, module: Any, parametres: dict[str, Any], plan: PlanChargement,
                                session: SessionChargement | None) -> Any:
        """Instancie le modèle, en rappelant d'abord en mémoire hôte les experts que le plan désigne."""
        if not plan.experts_deportes:
            return await self._instancier(module, parametres, session)
        return await self._instancier_avec_deport(module, parametres, plan, session)

    async def _instancier_avec_deport(self, module: Any, parametres: dict[str, Any], plan: PlanChargement,
                                      session: SessionChargement | None) -> Any:
        """Charge en plaçant les tenseurs d'experts des blocs du plan en mémoire hôte.

        Le déport n'est jamais réputé appliqué : `Llama.__init__` avale les paramètres inconnus sans
        erreur, donc l'absence d'exception ne prouve rien. Seul le journal de llama.cpp fait foi, et
        un déport non constaté fait échouer le chargement — servir un modèle qui a en réalité tout
        mis en VRAM reviendrait à saturer la carte en silence.
        """
        support = verifier_support(module)
        if not support.disponible or support.buffer_type_hote is None:
            raise self._echec_deport(support.raison, session, {"blocs": plan.experts_deportes})
        indices = tuple(plan.experts_deportes)
        with deport_actif(module, indices, support.buffer_type_hote) as collecteur:
            instance = await self._instancier(module, parametres, session)
        # Le mode verbeux n'était demandé que pour disposer du journal de chargement ; le laisser
        # ferait imprimer les temps de chaque génération sur la sortie d'erreur.
        self._taire(instance)
        applique, message = verifier_application(collecteur, indices)
        self._noter_deport(collecteur, message, applique, session)
        if not applique:
            await _fermer(instance)
            raise self._echec_deport(message, session, {"blocs_demandes": list(indices)})
        return instance

    def _noter_deport(self, collecteur: CollecteurJournal, message: str, applique: bool,
                      session: SessionChargement | None) -> None:
        """Consigne le résultat du déport ET les tailles de tampons que llama.cpp vient d'imprimer.

        Ces lignes sont la seule mesure disponible des tampons de calcul réels : le planificateur les
        provisionne aujourd'hui par le calcul, elles permettront de le confronter à la mesure.
        """
        journal_chargement.noter(
            session, "llama.cpp", message,
            niveau=NiveauEntree.INFO if applique else NiveauEntree.ERREUR,
            details={"blocs_confirmes": sorted(collecteur.blocs_surcharges),
                     "tampons_mesures": collecteur.lignes_tampons},
        )

    def _echec_deport(self, raison: str, session: SessionChargement | None,
                      indices: dict[str, Any]) -> EchecChargement:
        """Échec nommé : le planificateur doit abandonner la stratégie, pas la redimensionner."""
        journal_chargement.noter(session, "llama.cpp", raison, niveau=NiveauEntree.ERREUR, details=indices)
        return EchecChargement(
            Diagnostic(
                cause=CauseEchec.DEPORT_EXPERTS_INDISPONIBLE,
                message=raison,
                remediation="Le plan sera dégradé vers une répartition par couches entières.",
                indices=indices,
            )
        )

    def _taire(self, instance: Any) -> None:
        """Repasse l'instance en mode silencieux après un chargement journalisé."""
        try:
            instance.verbose = False
        except AttributeError as exc:  # version sans attribut public : sans conséquence
            logger.debug("Mode verbeux non réinitialisable sur cette version : {}", exc)

    async def _instancier(self, module: Any, parametres: dict[str, Any], session: SessionChargement | None) -> Any:
        """Construit l'instance dans un fil. Toute exception est qualifiée, jamais remontée nue.

        Une annulation pendant ce chargement ne l'interrompt pas — llama.cpp charge en C, sans point
        d'annulation. Le fil finit son travail ; l'instance produite n'étant référencée nulle part,
        elle est collectée et sa VRAM rendue peu après.
        """
        try:
            return await asyncio.to_thread(lambda: module.Llama(**parametres))
        except Exception as exc:
            # `source_verifiee` : la lisibilité du GGUF a déjà été contrôlée, le fichier est hors de cause.
            diagnostic = qualifier(str(exc), source_verifiee=True, exception=exc)
            journal_chargement.noter(
                session, "llama.cpp", f"Échec : {diagnostic.message}",
                niveau=NiveauEntree.ERREUR, details={"cause": diagnostic.cause.value},
            )
            raise EchecChargement(diagnostic, details={"moteur": self.moteur.value}) from exc

    def _importer(self, session: SessionChargement | None) -> Any:
        try:
            import llama_cpp
        except ImportError as exc:
            journal_chargement.noter(
                session, "llama.cpp", "Module llama_cpp introuvable", niveau=NiveauEntree.ERREUR,
            )
            raise EchecChargement(
                Diagnostic(
                    cause=CauseEchec.MOTEUR_ABSENT,
                    message="llama-cpp-python n'est pas installé dans l'environnement du backend.",
                    remediation="Installer le moteur depuis l'écran Système avant de charger un modèle.",
                    indices={"import": str(exc)},
                )
            ) from exc
        return llama_cpp

    def _verifier_offload_gpu(self, module: Any, plan: PlanChargement, session: SessionChargement | None) -> None:
        """Un plan qui délègue au GPU exige un binaire compilé avec CUDA — sinon l'échec est muet."""
        if plan.couches_gpu == 0:
            return
        sonde = getattr(module, "llama_supports_gpu_offload", None)
        if sonde is None:
            journal_chargement.noter(
                session, "llama.cpp", "Version trop ancienne pour déclarer son support GPU : non vérifié",
                niveau=NiveauEntree.AVERTISSEMENT,
            )
            return
        try:
            supporte = bool(sonde())
        except Exception as exc:
            logger.warning("Sonde de support GPU llama.cpp inutilisable : {}", exc)
            return
        if not supporte:
            raise EchecChargement(
                Diagnostic(
                    cause=CauseEchec.MOTEUR_SANS_CUDA,
                    message="llama-cpp-python est installé sans support CUDA : aucune couche ne peut aller au GPU.",
                    remediation="Réinstaller avec --no-binary et CMAKE_ARGS=-DGGML_CUDA=on : "
                                "le wheel PyPI par défaut est CPU-only.",
                    indices={"couches_gpu_demandees": plan.couches_gpu},
                )
            )

    def _appliquer_environnement(self, plan: PlanChargement, session: SessionChargement | None) -> None:
        """Pose les variables du plan. Le moteur étant en processus, elles restent pour sa durée de vie."""
        for cle, valeur in plan.variables_env.items():
            os.environ[cle] = valeur
        if VARIABLE_MEMOIRE_UNIFIEE in os.environ and VARIABLE_MEMOIRE_UNIFIEE not in plan.variables_env:
            journal_chargement.noter(
                session, "llama.cpp",
                f"{VARIABLE_MEMOIRE_UNIFIEE} présente dans l'environnement sans être au plan : "
                "sous WSL2 elle fige la VRAM et rend le modèle inutilisable.",
                niveau=NiveauEntree.AVERTISSEMENT,
            )

    def _parametres(
        self, plan: PlanChargement, chemin: Path, session: SessionChargement | None = None
    ) -> dict[str, Any]:
        """Traduit le plan en arguments `Llama`. Aucune valeur n'est inventée ici.

        Le déport d'experts ne passe par AUCUN argument : il n'en existe pas, et `**kwargs` avalerait
        silencieusement un nom inventé (cf. `experts_hote`). Seul `verbose` change de valeur, parce
        que le journal de chargement est le seul canal qui prouve que le déport a eu lieu — sans lui,
        llama-cpp-python relève le seuil de ses journaux et la vérification devient impossible.
        """
        parametres: dict[str, Any] = {
            "model_path": str(chemin),
            "n_ctx": plan.contexte,
            "n_batch": plan.batch,
            "n_gpu_layers": plan.couches_gpu,
            "verbose": bool(plan.experts_deportes),
        }
        if plan.flash_attention is not None:
            parametres["flash_attn"] = plan.flash_attention
        if plan.type_kv_cache is not None:
            identifiant = TYPES_KV.get(plan.type_kv_cache.lower())
            if identifiant is None:
                raise EchecChargement(
                    Diagnostic(
                        cause=CauseEchec.PLAN_INCOMPLET,
                        message=f"Type de cache KV inconnu : {plan.type_kv_cache}.",
                        remediation=f"Valeurs acceptées : {', '.join(sorted(TYPES_KV))}.",
                    )
                )
            parametres["type_k"] = identifiant
            parametres["type_v"] = identifiant
        handler = self._handler_vision(chemin, session)
        if handler is not None:
            parametres["chat_handler"] = handler
        return parametres

    def _handler_vision(self, chemin: Path, session: SessionChargement | None) -> Any | None:
        """Gestionnaire multimodal si un projecteur existe dans le dossier du modèle, sinon `None`.

        Un projecteur absent n'empêche JAMAIS le chargement du modèle — on charge sans, et on
        continue (plan d'exécution, sections 2.2 et 2.4) : la détection ne fait que CHOISIR quoi
        charger, elle n'autorise ni ne refuse jamais l'envoi d'une image. Toute erreur de détection
        ou de construction est journalisée et dégradée de la même façon, jamais remontée en échec de
        chargement.
        """
        try:
            projecteurs = fichiers_projecteurs(chemin.parent)
        except Exception as exc:  # noqa: BLE001 — la détection est un plus, jamais une condition
            logger.warning("Détection du projecteur de vision impossible ({}) : chargement sans vision.", exc)
            return None
        if not projecteurs:
            return None
        projecteur = projecteurs[0]
        try:
            from llama_cpp.llama_chat_format import MTMDChatHandler

            handler = MTMDChatHandler(clip_model_path=str(projecteur))
        except Exception as exc:  # noqa: BLE001 — même règle : jamais bloquant pour le chargement
            logger.warning("Projecteur de vision {} non chargé ({}) : chargement sans vision.", projecteur, exc)
            journal_chargement.noter(
                session, "llama.cpp", f"Projecteur de vision non chargé : {exc}",
                niveau=NiveauEntree.AVERTISSEMENT,
            )
            return None
        logger.info("Projecteur de vision chargé : {}", projecteur)
        journal_chargement.noter(session, "llama.cpp", f"Projecteur de vision chargé : {projecteur.name}")
        return handler

    async def decharger(self) -> None:
        """Libère l'instance et force un cycle GC : la VRAM part avec l'objet C, pas avant."""
        if self._llm is None:
            self._etat = None
            return
        instance, self._llm, self._etat = self._llm, None, None
        await _fermer(instance)
        logger.info("llama.cpp déchargé")

    async def sante(self) -> Sante:
        if self._llm is None or self._etat is None:
            return Sante(disponible=False, moteur=self.moteur, detail="Aucun modèle chargé.")
        debut = time.perf_counter()
        try:
            contexte = await asyncio.to_thread(self._llm.n_ctx)
        except Exception as exc:
            logger.error("Sonde llama.cpp en échec : {}", exc)
            return Sante(disponible=False, moteur=self.moteur, modele=self._etat.modele, detail=str(exc))
        latence = (time.perf_counter() - debut) * 1000
        return Sante(
            disponible=True, moteur=self.moteur, modele=self._etat.modele,
            latence_ms=round(latence, 2), detail=f"contexte servi : {contexte}",
        )

    async def compter_tokens(self, textes: Sequence[str]) -> ComptageTokens:
        """Compte par le tokenizer du modèle chargé — le seul qui sache ce que ce modèle coûte.

        Aucun modèle chargé signifie aucun tokenizer, donc aucune mesure possible : on le dit au
        lieu de rendre des zéros. Le travail part dans un fil comme le reste de l'adaptateur, la
        tokenisation étant un appel bloquant vers le C.
        """
        if self._llm is None:
            return ComptageTokens(
                possible=False,
                raison="Aucun modèle chargé dans llama.cpp : pas de tokenizer, donc pas de comptage.",
            )
        try:
            return await asyncio.to_thread(self._compter_sous_verrou, list(textes))
        except Exception as exc:
            logger.error("Comptage de tokens llama.cpp en échec : {}", exc)
            return ComptageTokens(possible=False, raison=f"Le tokenizer a refusé le texte : {exc}")

    def _compter_sous_verrou(self, textes: list[str]) -> ComptageTokens:
        """Tokenise le lot entier sous UNE prise du verrou de génération.

        Le verrou est celui qui sérialise les générations : l'objet `Llama` est un objet C qu'on ne
        touche jamais pendant qu'un autre fil le fait avancer. Un lot plutôt qu'un texte par prise,
        pour ne pas s'intercaler N fois entre deux tours d'une génération.
        """
        if not self._verrou_generation.acquire(timeout=DELAI_VERROU_COMPTAGE_S):
            return ComptageTokens(
                possible=False,
                raison="Une génération occupe le moteur : le comptage reprendra à la fin du flux.",
            )
        try:
            llm = self._llm
            if llm is None:  # déchargé pendant l'attente du verrou
                return ComptageTokens(possible=False, raison="Modèle déchargé pendant l'attente du verrou.")
            return ComptageTokens(
                possible=True,
                tokens_par_texte=[_compter_un(llm, texte) for texte in textes],
                contexte_moteur=int(llm.n_ctx()),
            )
        finally:
            self._verrou_generation.release()

    async def compter_multimodal(self, images: Sequence[PartieImageChemin]) -> ComptageImages:
        """Coût en tokens de chaque image, mesuré par le même découpage qui la placera dans le prompt.

        Sans projecteur chargé, aucun contexte mtmd n'existe : la mesure est impossible, nommée —
        jamais un zéro (plan d'exécution, 2.3). Le travail part dans un fil comme le reste de
        l'adaptateur : `mtmd_tokenize` décode l'image (`stb_image`) et l'encode au travers du clip,
        un appel bloquant vers le C.
        """
        if self._llm is None:
            return ComptageImages(
                possible=False,
                raison="Aucun modèle chargé dans llama.cpp : pas de contexte multimodal, donc pas de comptage.",
            )
        handler = getattr(self._llm, "chat_handler", None)
        if handler is None or not hasattr(handler, "_mtmd_cpp"):
            return ComptageImages(
                possible=False,
                raison="Aucun projecteur de vision chargé avec ce modèle : le coût d'une image n'est pas mesurable.",
            )
        try:
            return await asyncio.to_thread(self._compter_multimodal_sous_verrou, handler, list(images))
        except Exception as exc:
            logger.error("Comptage multimodal llama.cpp en échec : {}", exc)
            return ComptageImages(possible=False, raison=f"Le découpage multimodal a refusé l'image : {exc}")

    def _compter_multimodal_sous_verrou(self, handler: Any, images: list[PartieImageChemin]) -> ComptageImages:
        """Tokenise chaque image séparément, sous UNE prise du verrou de génération.

        Une image à la fois plutôt qu'un lot dans un seul `mtmd_tokenize` : c'est ce qui rend
        `tokens_par_image` directement comparable au découpage par segment du texte — le coût
        PROPRE de chacune, pas un total mélangé à celui de ses voisines.
        """
        if not self._verrou_generation.acquire(timeout=DELAI_VERROU_COMPTAGE_S):
            return ComptageImages(
                possible=False,
                raison="Une génération occupe le moteur : le comptage reprendra à la fin du flux.",
            )
        try:
            llm = self._llm
            if llm is None:  # déchargé pendant l'attente du verrou
                return ComptageImages(possible=False, raison="Modèle déchargé pendant l'attente du verrou.")
            try:
                handler._init_mtmd_context(llm)  # idempotent : déjà fait dès la première génération
            except Exception as exc:
                return ComptageImages(possible=False, raison=f"Contexte multimodal indisponible : {exc}")
            mtmd_cpp = handler._mtmd_cpp
            tokens_par_image: list[int] = []
            for image in images:
                # Même remise à zéro que `MTMDChatHandler.__call__` juste avant son propre
                # `mtmd_tokenize` (`llama_chat_format.py`, autour de la ligne 3511) : la mesure
                # emprunte le même état de départ que la génération, jamais un contexte KV hérité
                # d'un appel précédent.
                llm.reset()
                llm._ctx.kv_cache_clear()
                resultat = _tokeniser_une_image(mtmd_cpp, handler, image)
                if isinstance(resultat, str):  # raison d'échec
                    return ComptageImages(possible=False, raison=resultat)
                tokens_par_image.append(resultat)
            return ComptageImages(possible=True, tokens_par_image=tokens_par_image)
        finally:
            self._verrou_generation.release()

    async def proposer_outils(
        self,
        messages: Sequence[MessageChat],
        options: OptionsGeneration,
        outils: Sequence[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Demande au modèle s'il veut appeler un outil, et rend les appels demandés.

        Étape NON streamée, et elle ne peut pas l'être : un appel d'outil n'existe qu'une fois
        l'argument JSON complet, il n'y a rien à afficher au fil des tokens. Le flux visible ne
        commence qu'après, quand le modèle rédige sa réponse avec les résultats en main.

        Le format d'appel n'est pas imposé par nous : les gabarits des GGUF chargés ici déclarent
        tous `tools` et `tool_call` (vérifié le 2026-08-14 sur les six modèles présents), et c'est
        le gabarit du modèle qui met en forme la demande. Nous ne faisons que la lire.

        Rend une liste vide dès que quoi que ce soit sort de l'ordinaire : un modèle qui ne veut
        pas d'outil, un moteur déchargé, une réponse de forme inattendue. Aucun de ces cas n'est
        une erreur — la génération normale suit.
        """
        if self._llm is None or not outils:
            return []
        return await asyncio.to_thread(self._proposer_bloquant, messages, options, outils)

    def _proposer_bloquant(
        self,
        messages: Sequence[MessageChat],
        options: OptionsGeneration,
        outils: Sequence[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        # Le verrou est celui des générations : sans cette prise, deux fils toucheraient le même
        # objet C. Un moteur occupé n'est pas une erreur — la génération qui suit attendra son
        # tour —, mais l'abandon doit rester visible, sinon le modèle génère sans outil et
        # l'utilisateur ne voit qu'une réponse inventée sans savoir pourquoi.
        if not self._verrou_generation.acquire(timeout=DELAI_VERROU_GENERATION_S):
            logger.warning(
                "Proposition d'outils abandonnée après {} s : le moteur est occupé par une autre génération.",
                DELAI_VERROU_GENERATION_S,
            )
            return []
        try:
            llm = self._llm
            if llm is None:
                return []
            # Le plafond de la conversation est REMPLACÉ, il n'est pas hérité. Cette passe n'est
            # pas streamée : tout ce qu'elle produit se fait en silence, écran figé côté
            # utilisateur. Avec le max_tokens d'une vraie réponse (1024 et plus), un modèle qui
            # ne veut pas d'outil rédige ici une réponse complète que personne ne lira, puis la
            # génération visible recommence tout — deux fois le temps, dont la moitié invisible.
            # Mesuré le 2026-08-15 sur un 27B partiellement en RAM : chargement apparemment
            # infini au second message, alors que le 0,5B passait sans qu'on voie rien.
            #
            # Un appel d'outil tient en quelques dizaines de tokens. Un modèle qui n'en a pas
            # émis dans ce budget n'en émettra pas : on arrête et on génère normalement.
            arguments = _arguments_echantillonnage(options)
            arguments["max_tokens"] = TOKENS_PROPOSITION_OUTILS
            reponse = llm.create_chat_completion(
                messages=_messages_pour_moteur(messages, _vision_disponible(llm)),
                tools=list(outils),
                tool_choice="auto",
                stream=False,
                **arguments,
            )
        except Exception as exc:  # noqa: BLE001 — un modèle qui gère mal `tools` ne doit rien casser
            logger.warning("Proposition d'outils impossible ({}) : génération sans outil.", exc)
            return []
        finally:
            self._verrou_generation.release()
        if not isinstance(reponse, dict):
            logger.warning("Proposition d'outils : réponse de forme inattendue ({}).", type(reponse).__name__)
            return []
        choix = (reponse.get("choices") or [{}])[0]
        message = choix.get("message") or {}
        appels = [appel for appel in (message.get("tool_calls") or []) if isinstance(appel, dict)]
        # Tracé dans les deux cas : « le modèle n'a demandé aucun outil » et « le harnais n'a pas
        # tourné » produisent la même réponse à l'écran, et seuls les journaux peuvent les séparer.
        if appels:
            logger.info("Le modèle demande {} appel(s) d'outil.", len(appels))
            return appels
        texte = str(message.get("content") or "")
        textuels = _appels_dans_le_texte(texte)
        if textuels:
            logger.info("Le modèle demande {} appel(s) d'outil, en texte.", len(textuels))
            return textuels
        logger.info("Le modèle n'a demandé aucun outil (début de réponse : {!r}).", texte[:160])
        return []

    def generer(
        self,
        messages: Sequence[MessageChat],
        options: OptionsGeneration,
        outils: Sequence[dict[str, Any]] | None = None,
    ) -> AsyncIterator[MorceauGeneration]:
        """Flux de tokens. `outils` est déclaré au modèle DANS ce même appel, jamais dans un autre.

        Un second appel préalable pour demander « veux-tu un outil ? » construirait un prompt
        différent de celui de la génération, et invaliderait le cache de prompt de llama.cpp : sur
        un modèle de 27 milliards de paramètres partiellement en RAM, cela revient à payer DEUX
        évaluations complètes du prompt avant le premier token affiché. Mesuré le 2026-08-15 :
        plusieurs dizaines de secondes d'écran figé, imperceptibles sur un modèle de 0,5 milliard.
        """
        if self._llm is None:
            raise EchecChargement(
                Diagnostic(
                    cause=CauseEchec.MOTEUR_ABSENT,
                    message="Aucun modèle chargé dans llama.cpp.",
                    remediation="Charger un modèle avant de générer.",
                )
            )
        plafond = options.max_tokens or self._contexte
        # Le watchdog d'inactivité du flux moteur lit le MÊME délai que celui du chat : il ne doit
        # jamais couper avant lui, sous peine de tuer un préremplissage lourd avant le premier token.
        from backend.core import get_settings

        return flux_depuis_bloquant(
            lambda arret: self._iterer(messages, options, arret, outils),
            iterations_max=plafond + 1,  # +1 : le morceau de fin n'est pas un token
            delai_inactivite_s=get_settings().delai_inactivite_generation_s,
        )

    def _iterer(
        self,
        messages: Sequence[MessageChat],
        options: OptionsGeneration,
        arret: threading.Event,
        outils: Sequence[dict[str, Any]] | None = None,
    ) -> Iterator[MorceauGeneration]:
        """Boucle bloquante exécutée dans un fil, sous verrou : une génération à la fois."""
        if not self._verrou_generation.acquire(timeout=DELAI_VERROU_GENERATION_S):
            raise RuntimeError("Une génération est déjà en cours sur ce modèle.")
        try:
            extra: dict[str, Any] = {"tools": list(outils), "tool_choice": "auto"} if outils else {}
            flux = self._llm.create_chat_completion(  # type: ignore[union-attr]
                **extra,
                messages=_messages_pour_moteur(messages, _vision_disponible(self._llm)),
                stream=True,
                **_arguments_echantillonnage(options),
            )
            raison: str | None = None
            for morceau in flux:
                if arret.is_set():
                    raison = "annule"
                    break
                choix = (morceau.get("choices") or [{}])[0]
                raison = choix.get("finish_reason") or raison
                contenu = (choix.get("delta") or {}).get("content") or ""
                if contenu:
                    yield MorceauGeneration(type="token", contenu=contenu)
            yield MorceauGeneration(type="fin", raison_arret=raison)
        finally:
            self._verrou_generation.release()


"""Appels d'outils émis EN TEXTE, dans `content`, au lieu du champ `tool_calls`.

Mesuré le 2026-08-15 : les gabarits Qwen produisent la balise `<tool_call>` autour d'un objet JSON,
et llama-cpp-python ne remplit `tool_calls` que pour les formats qu'il sait analyser lui-même
(functionary, chatml-function-calling). Avec le gabarit natif du GGUF — celui qu'on veut garder,
puisque c'est lui qui connaît le modèle — l'appel arrive donc en texte brut et se retrouve affiché
à l'utilisateur au lieu d'être exécuté.

Le JSON relevé porte des accolades doublées (`{{"name": …}}`), artefact du gabarit lui-même. On
retente donc une fois après les avoir réduites : refuser un appel pour une accolade en trop
reviendrait à casser l'outil sur un détail de mise en forme que le modèle ne contrôle pas.
"""
# La balise fermante est FACULTATIVE, et c'est la seule tolérance qui compte ici : un modèle
# dégradé (quantification basse) ou une génération arrêtée net laisse un `<tool_call>` ouvert, et
# l'exiger faisait perdre l'appel ENTIER — pas dégrader, perdre. L'alternance est en dernier
# recours : le moteur d'expressions essaie `</tool_call>` d'abord à chaque position, `\Z` ne sert
# que s'il n'existe pas. Un appel bien formé se lit donc exactement comme avant.
_MOTIF_APPEL_TEXTE = re.compile(
    r"<tool_call>\s*(?P<charge>.+?)\s*(?:</tool_call>|\Z)", re.DOTALL | re.IGNORECASE
)


def _fermetures_manquantes(charge: str) -> str:
    """Complète un objet JSON laissé ouvert : guillemet, accolades, crochets — dans cet ordre.

    Cas MESURÉ le 2026-08-16 : le gabarit ouvre `{{"name": …, "arguments": {…` — trois accolades
    ouvrantes — et n'en referme que deux. La réduction des accolades doublées ne suffit donc pas, le
    JSON reste déséquilibré et l'appel est perdu ENTIER. Même forme quand la fenêtre de contexte
    coupe la génération en plein argument : le début de l'appel est parfaitement lisible, seule la
    fin manque.

    Le comptage ignore ce qui est à l'intérieur d'une chaîne, sans quoi une accolade écrite dans le
    contenu d'un fichier — cas courant, on écrit du code — fausserait tout le calcul.
    """
    dans_chaine = False
    echappe = False
    pile: list[str] = []
    for caractere in charge:
        if echappe:
            echappe = False
            continue
        if caractere == "\\":
            echappe = True
        elif caractere == '"':
            dans_chaine = not dans_chaine
        elif dans_chaine:
            continue
        elif caractere in "{[":
            pile.append("}" if caractere == "{" else "]")
        elif caractere in "}]" and pile:
            pile.pop()
    return ('"' if dans_chaine else "") + "".join(reversed(pile))


def _charger_json_tolerant(charge: str) -> dict[str, Any] | None:
    """Objet JSON d'un appel, réparé si besoin — un appel perdu coûte tout le tour du modèle.

    Les trois tentatives vont de la plus fidèle à la plus permissive : tel quel, puis accolades
    doublées réduites, puis fermetures manquantes ajoutées. Aucune n'invente de valeur : elles ne
    font que refermer ce que le modèle a ouvert. Un appel dont le NOM manque reste refusé plus haut.
    """
    reduit = charge.replace("{{", "{").replace("}}", "}")
    candidats = (charge, reduit, charge + _fermetures_manquantes(charge), reduit + _fermetures_manquantes(reduit))
    for candidat in candidats:
        try:
            valeur = json.loads(candidat)
        except json.JSONDecodeError:
            continue
        if isinstance(valeur, dict):
            if candidat is not charge:
                logger.info("Appel d'outil réparé avant lecture (JSON incomplet ou accolades doublées).")
            return valeur
    logger.warning("Appel d'outil en texte illisible : {!r}", charge[:200])
    return None


# Second dialecte, CONSTATÉ le 2026-08-15 sur les dérivés Qwen3.6 chargés ici : l'appel n'est pas
# du JSON mais du balisage, `<function=nom><parameter=cle>valeur</parameter></function>`. C'est la
# convention des gabarits de la famille Qwen3-Coder. Les deux formes cohabitent selon le modèle, et
# aucune n'est devinable à l'avance : on lit celle qui arrive.
# Fermantes facultatives, même raison que pour `<tool_call>`. Pour un paramètre, la borne de repli
# n'est pas seulement la fin du texte : c'est aussi le paramètre suivant ou la fin de la fonction,
# sans quoi une valeur non fermée avalerait tous les arguments qui la suivent — un `code` qui
# engloutit le reste de l'appel est pire qu'un argument manquant, parce qu'il s'exécute.
_MOTIF_FONCTION_BALISEE = re.compile(
    r"<function=(?P<nom>[\w.-]+)>(?P<corps>.*?)(?:</function>|\Z)", re.DOTALL
)
_MOTIF_PARAMETRE = re.compile(
    r"<parameter=(?P<cle>[\w.-]+)>(?P<valeur>.*?)(?:</parameter>|(?=<parameter=)|(?=</function>)|\Z)",
    re.DOTALL,
)


def _appels_balises(texte: str) -> list[dict[str, Any]]:
    """Appels au format balisé. Les valeurs sont rendues telles quelles, seulement détourées."""
    appels: list[dict[str, Any]] = []
    for fonction in _MOTIF_FONCTION_BALISEE.finditer(texte):
        parametres = _MOTIF_PARAMETRE.finditer(fonction.group("corps"))
        arguments = {p.group("cle"): p.group("valeur").strip() for p in parametres}
        appels.append({"type": "function", "function": {"name": fonction.group("nom"), "arguments": arguments}})
    return appels


def _appels_dans_le_texte(texte: str) -> list[dict[str, Any]]:
    """Appels trouvés dans le texte, ramenés à la forme `tool_calls` du reste de la chaîne.

    Deux dialectes sont acceptés parce que les deux ont été observés sur cette machine : JSON dans
    `<tool_call>`, et balisage `<function=…>`. Le second est cherché aussi hors de `<tool_call>` —
    certains gabarits l'émettent seul.
    """
    appels: list[dict[str, Any]] = []
    for trouve in _MOTIF_APPEL_TEXTE.finditer(texte):
        charge = trouve.group("charge")
        balises = _appels_balises(charge)
        if balises:
            appels.extend(balises)
            continue
        objet = _charger_json_tolerant(charge)
        nom = str(objet.get("name", "")) if objet else ""
        if nom:
            appels.append({"type": "function", "function": {"name": nom, "arguments": objet.get("arguments", {})}})
    if not appels:
        appels.extend(_appels_balises(texte))
    return appels


async def _fermer(instance: Any) -> None:
    """Libère une instance `Llama` et force un cycle GC : la VRAM part avec l'objet C, pas avant.

    Sert aussi bien au déchargement normal qu'à l'abandon d'une instance chargée dont le déport
    d'experts n'a pas pu être confirmé — dans ce second cas, la garder occuperait toute la carte.
    """
    try:
        fermer = getattr(instance, "close", None)
        if callable(fermer):
            await asyncio.to_thread(fermer)
    except Exception as exc:
        logger.warning("Fermeture llama.cpp imparfaite : {}", exc)
    finally:
        del instance
        gc.collect()


def _tokeniser_une_image(mtmd_cpp: Any, handler: Any, image: PartieImageChemin) -> int | str:
    """Coût réel d'UNE image en tokens — ou une raison d'échec (`str`), jamais un zéro deviné.

    Reproduit exactement l'entrée que `MTMDChatHandler.__call__` construit avant de générer
    (`llama_chat_format.py`, section `MTMDChatHandler`) : le marqueur média par défaut comme seul
    texte, la même image en bitmap, la même fonction `mtmd_tokenize` qui la découpera au moment de
    répondre. `mtmd_input_chunk_get_n_tokens` est sommé sur CHAQUE chunk rendu — texte du marqueur
    compris, pour ne rien soustraire à la main — plutôt que déduit d'une formule sur la résolution
    (plan d'exécution, 2.3 : c'est exactement l'interdiction que cette fonction respecte).

    Rend un `int` (0 admis : c'est une mesure, pas une absence) sur succès, une `str` (la raison)
    sur échec — le type de retour porte la distinction plutôt qu'une exception pour un cas attendu.
    """
    try:
        octets = Path(image.chemin).read_bytes()
    except OSError as exc:
        return f"Image illisible ({image.chemin}) : {exc}"
    try:
        bitmap = handler._create_bitmap_from_bytes(octets)
    except Exception as exc:
        return f"Le moteur n'a pas pu décoder l'image ({image.chemin}) : {exc}"
    chunks = mtmd_cpp.mtmd_input_chunks_init()
    try:
        if chunks is None:
            return "Le moteur n'a pas pu allouer de découpage pour l'image."
        entree = mtmd_cpp.mtmd_input_text()
        entree.text = mtmd_cpp.mtmd_default_marker()
        entree.add_special = False
        entree.parse_special = True
        tableau_bitmaps = (mtmd_cpp.mtmd_bitmap_p_ctypes * 1)(bitmap)
        resultat = mtmd_cpp.mtmd_tokenize(handler.mtmd_ctx, chunks, ctypes.byref(entree), tableau_bitmaps, 1)
        if resultat != 0:
            return f"La tokenisation de l'image a échoué (code {resultat})."
        total = 0
        for indice in range(mtmd_cpp.mtmd_input_chunks_size(chunks)):
            chunk = mtmd_cpp.mtmd_input_chunks_get(chunks, indice)
            if chunk is not None:
                total += mtmd_cpp.mtmd_input_chunk_get_n_tokens(chunk)
        return total
    finally:
        mtmd_cpp.mtmd_input_chunks_free(chunks)
        mtmd_cpp.mtmd_bitmap_free(bitmap)


def _compter_un(llm: Any, texte: str) -> int:
    """Longueur en tokens d'un texte, mesurée par le vocabulaire du modèle chargé.

    Trois choix imposés par la signature réelle de `Llama.tokenize(text: bytes, add_bos: bool =
    True, special: bool = False)`, vérifiée dans les sources du paquet et non supposée :

    - `encode("utf-8")` : la méthode prend des octets, pas une chaîne ;
    - `add_bos=False` : le BOS est unique pour tout le prompt assemblé, pas un par fragment ;
      le laisser à son défaut gonflerait le total d'un token par message ;
    - `special=True` : c'est ainsi que llama.cpp tokenise le prompt final. Un marqueur écrit
      littéralement dans un message (`<|im_start|>`) compte donc exactement comme le modèle le
      comptera, au lieu d'être découpé en caractères.

    Un texte vide ne franchit pas la frontière C : zéro token est ici une certitude, pas une
    absence de mesure.
    """
    if not texte:
        return 0
    return len(llm.tokenize(texte.encode("utf-8"), add_bos=False, special=True))


def _arguments_echantillonnage(options: OptionsGeneration) -> dict[str, Any]:
    """Ne transmet que les réglages explicitement demandés : le reste reste au défaut du moteur."""
    arguments: dict[str, Any] = {"temperature": options.temperature, "top_p": options.top_p}
    if options.top_k is not None:
        arguments["top_k"] = options.top_k
    if options.repetition_penalty is not None:
        arguments["repeat_penalty"] = options.repetition_penalty
    if options.presence_penalty is not None:
        arguments["presence_penalty"] = options.presence_penalty
    if options.min_p is not None:
        arguments["min_p"] = options.min_p
    if options.max_tokens is not None:
        arguments["max_tokens"] = options.max_tokens
    if options.stop:
        arguments["stop"] = list(options.stop)
    if options.graine is not None:
        arguments["seed"] = options.graine
    return arguments
