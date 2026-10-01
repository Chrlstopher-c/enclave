"""Contrat de message multimodal — cinq décisions du plan d'exécution (section 2.2).

Ce que ce fichier prouve, dans l'ordre :

- l'union `content: str | list[PartieContenu]` garde `str` valide, donc l'existant n'est pas cassé ;
- `texte_de` est la SEULE fonction qui inspecte `content` : elle concatène le texte, ignore l'image,
  quelle que soit sa forme (chemin non encodé, ou data URI déjà résolu) ;
- `decouper_segments` ne voit plus jamais `content` directement — passer par `texte_de` doit rendre
  le même découpage qu'avant sur un message texte, et ignorer l'image sur un message multimodal ;
- l'adaptateur llama.cpp encode en data URI au tout dernier moment, jamais avant ;
- un projecteur de vision absent ou qui échoue à se construire n'empêche jamais le chargement.
"""

from __future__ import annotations

import asyncio
import base64
import importlib.util
from pathlib import Path
from typing import Any

import pytest

from backend.inference.engines_adapters import adaptateur_llama_cpp as module_llama_cpp
from backend.inference.engines_adapters.contrat import (
    ImageURL,
    MessageChat,
    PartieImage,
    PartieImageChemin,
    PartieTexte,
    PosteContexte,
    decouper_segments,
    texte_de,
)


# --------------------------------------------------------------- texte_de : forme simple (str)


# La CI n'installe pas llama-cpp-python (compilation trop longue) : ces cas construisent un vrai handler.
_AVEC_LLAMA_CPP = pytest.mark.skipif(importlib.util.find_spec("llama_cpp") is None,
                                     reason="llama-cpp-python absent")


def test_texte_de_sur_un_contenu_simple_le_rend_tel_quel() -> None:
    message = MessageChat(role="user", content="Bonjour")
    assert texte_de(message) == "Bonjour"


def test_texte_de_sur_un_contenu_vide_rend_une_chaine_vide() -> None:
    message = MessageChat(role="user", content="")
    assert texte_de(message) == ""


# ------------------------------------------------------------ texte_de : forme multipartie


def test_texte_de_concatene_les_parties_texte_et_ignore_les_images() -> None:
    message = MessageChat(
        role="user",
        content=[
            PartieTexte(text="Regarde cette image : "),
            PartieImageChemin(chemin="/tmp/x.png", type_mime="image/png"),
            PartieTexte(text=" qu'en penses-tu ?"),
        ],
    )
    assert texte_de(message) == "Regarde cette image :  qu'en penses-tu ?"


def test_texte_de_sur_une_seule_image_sans_texte_rend_une_chaine_vide() -> None:
    message = MessageChat(role="user", content=[PartieImageChemin(chemin="/tmp/x.png", type_mime="image/png")])
    assert texte_de(message) == ""


def test_texte_de_ignore_aussi_une_image_deja_encodee_en_data_uri() -> None:
    message = MessageChat(
        role="user",
        content=[PartieImage(image_url=ImageURL(url="data:image/png;base64,AAAA"))],
    )
    assert texte_de(message) == ""


# -------------------------------------------------------- decouper_segments passe par texte_de
#
# Preuve DANS LES DEUX SENS que `decouper_segments` n'inspecte plus `content` directement : le test
# suivant échoue si `decouper_segments` redevient `message.content` (qui lèverait `TypeError` sur une
# liste passée à `SegmentContexte(texte=...)`, ou concaténerait la représentation Python des objets).


def test_decouper_segments_sur_message_texte_reste_inchange() -> None:
    segments = decouper_segments("", [MessageChat(role="user", content="Bonjour")])
    assert len(segments) == 1
    assert segments[0].poste == PosteContexte.UTILISATEUR
    assert segments[0].texte == "Bonjour"


def test_decouper_segments_sur_message_multimodal_ne_voit_que_le_texte() -> None:
    message = MessageChat(
        role="user",
        content=[
            PartieTexte(text="Que vois-tu ?"),
            PartieImageChemin(chemin="/tmp/photo.jpg", type_mime="image/jpeg"),
        ],
    )
    segments = decouper_segments("", [message])
    assert len(segments) == 1
    assert segments[0].texte == "Que vois-tu ?"


def test_decouper_segments_sur_image_seule_ne_produit_aucun_segment() -> None:
    """Un message purement image ne doit pas planter — ni produire un segment vide fantôme."""
    message = MessageChat(role="user", content=[PartieImageChemin(chemin="/tmp/x.png", type_mime="image/png")])
    segments = decouper_segments("", [message])
    assert segments == []


# --------------------------------------------------------- adaptateur : encodage data URI final


def test_encoder_data_uri_produit_un_data_uri_valide(tmp_path: Path) -> None:
    fichier = tmp_path / "carre.png"
    octets = b"\x89PNG\r\n\x1a\nfaux-contenu-png"
    fichier.write_bytes(octets)

    uri = module_llama_cpp._encoder_data_uri(str(fichier), "image/png")

    assert uri is not None
    assert uri.startswith("data:image/png;base64,")
    encode = uri.split(",", 1)[1]
    assert base64.b64decode(encode) == octets


def test_encoder_data_uri_sur_fichier_absent_rend_none_sans_lever(tmp_path: Path) -> None:
    absent = tmp_path / "n_existe_pas.png"
    assert module_llama_cpp._encoder_data_uri(str(absent), "image/png") is None


def test_messages_pour_moteur_laisse_un_contenu_texte_inchange() -> None:
    messages = [MessageChat(role="user", content="Bonjour")]
    rendu = module_llama_cpp._messages_pour_moteur(messages)
    assert rendu == [{"role": "user", "content": "Bonjour"}]


def test_messages_pour_moteur_encode_image_chemin_en_data_uri_au_dernier_moment(tmp_path: Path) -> None:
    """Le chemin ne devient un data URI QU'À CET APPEL — jamais avant, dans le port ni le domaine chat."""
    fichier = tmp_path / "photo.png"
    fichier.write_bytes(b"\x89PNG\r\n\x1a\nabc")
    message = MessageChat(
        role="user",
        content=[PartieTexte(text="Regarde"), PartieImageChemin(chemin=str(fichier), type_mime="image/png")],
    )

    rendu = module_llama_cpp._messages_pour_moteur([message])

    parties = rendu[0]["content"]
    assert parties[0] == {"type": "text", "text": "Regarde"}
    assert parties[1]["type"] == "image_url"
    assert parties[1]["image_url"]["url"].startswith("data:image/png;base64,")


def test_messages_pour_moteur_ecarte_une_image_illisible_sans_faire_echouer_le_message(tmp_path: Path) -> None:
    absent = tmp_path / "absent.png"
    message = MessageChat(
        role="user",
        content=[PartieTexte(text="Regarde"), PartieImageChemin(chemin=str(absent), type_mime="image/png")],
    )
    rendu = module_llama_cpp._messages_pour_moteur([message])
    assert rendu[0]["content"] == [{"type": "text", "text": "Regarde"}]


# ------------------------------------------------------- projecteur de vision : jamais bloquant


class _AdaptateurTest(module_llama_cpp.AdaptateurLlamaCpp):
    """Sous-classe vide : `_handler_vision` est une méthode d'instance, il faut une instance."""


def test_handler_vision_sans_projecteur_rend_none(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(module_llama_cpp, "fichiers_projecteurs", lambda dossier: [])
    adaptateur = _AdaptateurTest()
    assert adaptateur._handler_vision(tmp_path / "modele.gguf", None) is None


@_AVEC_LLAMA_CPP
def test_handler_vision_avec_projecteur_construit_le_handler(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    projecteur = tmp_path / "mmproj-test.gguf"
    projecteur.write_bytes(b"faux-gguf")
    monkeypatch.setattr(module_llama_cpp, "fichiers_projecteurs", lambda dossier: [projecteur])

    construits: list[str] = []

    class HandlerFactice:
        def __init__(self, clip_model_path: str) -> None:
            construits.append(clip_model_path)

    monkeypatch.setattr("llama_cpp.llama_chat_format.MTMDChatHandler", HandlerFactice)

    adaptateur = _AdaptateurTest()
    handler = adaptateur._handler_vision(tmp_path / "modele.gguf", None)

    assert handler is not None
    assert construits == [str(projecteur)]


@_AVEC_LLAMA_CPP
def test_handler_vision_qui_leve_a_la_construction_rend_none_sans_bloquer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Un projecteur présent mais invalide ne doit JAMAIS empêcher le chargement du modèle."""
    projecteur = tmp_path / "mmproj-corrompu.gguf"
    projecteur.write_bytes(b"pas un vrai gguf")
    monkeypatch.setattr(module_llama_cpp, "fichiers_projecteurs", lambda dossier: [projecteur])

    def _leve(clip_model_path: str) -> None:
        raise ValueError("Clip model path does not exist")

    monkeypatch.setattr("llama_cpp.llama_chat_format.MTMDChatHandler", _leve)

    adaptateur = _AdaptateurTest()
    assert adaptateur._handler_vision(tmp_path / "modele.gguf", None) is None


# ------------------------------------------ journal de chargement : reste servable avec vision


@_AVEC_LLAMA_CPP
def test_journal_de_chargement_avec_vision_reste_serialisable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Reproduit le plantage réel de la route `/inference/journal` (500,
    `PydanticSerializationError: Unable to serialize unknown type: MTMDChatHandler`) : un
    chargement avec projecteur de vision inscrivait l'objet handler lui-même — pas une donnée sur
    lui — dans les `details` de l'entrée de journal. Assemblage complet via `charger()`, la méthode
    qui a réellement produit le plantage, pas une réimplémentation de sa logique."""
    from backend.inference.engines_adapters.contrat import MoteurSupporte, PlanChargement
    from backend.inference.engines_adapters.journal import JournalChargement

    modele = tmp_path / "modele.gguf"
    modele.write_bytes(b"GGUF" + b"\x00" * 8)  # en-tête suffisant pour `preverifier_source`
    projecteur = tmp_path / "mmproj-test.gguf"
    projecteur.write_bytes(b"faux-mmproj")
    monkeypatch.setattr(module_llama_cpp, "fichiers_projecteurs", lambda dossier: [projecteur])

    class HandlerFactice:
        def __init__(self, clip_model_path: str) -> None:
            self.clip_model_path = clip_model_path

    monkeypatch.setattr("llama_cpp.llama_chat_format.MTMDChatHandler", HandlerFactice)

    class LlamaFactice:
        def __init__(self, **kwargs: object) -> None:
            self.kwargs = kwargs

    class ModuleFactice:
        Llama = LlamaFactice

    monkeypatch.setattr(module_llama_cpp.AdaptateurLlamaCpp, "_importer", lambda self, session: ModuleFactice)

    plan = PlanChargement(
        moteur=MoteurSupporte.LLAMA_CPP, chemin_modele=str(modele),
        identifiant_modele="test/vision::modele.gguf", couches_gpu=0, contexte=2048, batch=512,
    )
    journal = JournalChargement()
    session = journal.ouvrir(plan)
    adaptateur = module_llama_cpp.AdaptateurLlamaCpp()

    asyncio.run(adaptateur.charger(plan, session))

    entree = next(e for e in session.entrees if "Chargement de" in e.message)
    assert "chat_handler" not in entree.details["parametres"]
    assert entree.details["vision_chargee"] is True

    # Ce que la route fait réellement (`response_model=list[SessionChargement]`) : FastAPI
    # sérialise via pydantic-core. Un objet non prévu par le schéma y lève
    # `PydanticSerializationError` — exactement le 500 observé en conteneur.
    session.model_dump_json()


def test_vision_detachee_quand_vram_libre_sous_la_marge(monkeypatch: pytest.MonkeyPatch) -> None:
    """Reproduit la cause du plantage natif réel (SIGABRT, `GGML_ASSERT(buffer)` dans
    `ggml-backend.cpp`, sur `cudaMalloc` en échec au premier `_init_mtmd_context`) : une VRAM libre
    sous la marge mesurée pour l'encodeur visuel doit détacher `chat_handler` plutôt que de laisser
    la prochaine mesure ou génération tenter l'allocation qui abat le processus."""
    from backend.inference.engines_adapters.vram import MesureVram

    class HandlerFactice:
        pass

    class LlamaFactice:
        def __init__(self) -> None:
            self.chat_handler = HandlerFactice()

    adaptateur = module_llama_cpp.AdaptateurLlamaCpp()
    adaptateur._llm = LlamaFactice()

    vram_juste_sous_la_marge = MesureVram(
        index=0, total_octets=12 * 1024**3,
        utilisee_octets=12 * 1024**3 - (module_llama_cpp.MARGE_VISION_OCTETS - 1),
        libre_octets=module_llama_cpp.MARGE_VISION_OCTETS - 1,
    )
    adaptateur._detacher_vision_si_vram_insuffisante(vram_juste_sous_la_marge, None)

    assert adaptateur._llm.chat_handler is None


def test_vision_reste_attachee_quand_vram_libre_couvre_la_marge() -> None:
    """Validation dans l'autre sens : au-dessus de la marge, le handler n'est jamais touché."""
    from backend.inference.engines_adapters.vram import MesureVram

    class HandlerFactice:
        pass

    class LlamaFactice:
        def __init__(self) -> None:
            self.chat_handler = HandlerFactice()

    adaptateur = module_llama_cpp.AdaptateurLlamaCpp()
    adaptateur._llm = LlamaFactice()
    handler_avant = adaptateur._llm.chat_handler

    vram_au_dessus_de_la_marge = MesureVram(
        index=0, total_octets=12 * 1024**3,
        utilisee_octets=12 * 1024**3 - (module_llama_cpp.MARGE_VISION_OCTETS + 1024**3),
        libre_octets=module_llama_cpp.MARGE_VISION_OCTETS + 1024**3,
    )
    adaptateur._detacher_vision_si_vram_insuffisante(vram_au_dessus_de_la_marge, None)

    assert adaptateur._llm.chat_handler is handler_avant


def test_parametres_sans_projecteur_ne_porte_pas_de_chat_handler(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Preuve d'assemblage : `_parametres` — le seul endroit qui construit les paramètres du moteur —
    ne bloque jamais le chargement en l'absence de projecteur."""
    from backend.inference.engines_adapters.contrat import MoteurSupporte, PlanChargement

    monkeypatch.setattr(module_llama_cpp, "fichiers_projecteurs", lambda dossier: [])
    plan = PlanChargement(
        moteur=MoteurSupporte.LLAMA_CPP, chemin_modele=str(tmp_path / "modele.gguf"),
        couches_gpu=0, contexte=2048, batch=512,
    )
    adaptateur = _AdaptateurTest()
    parametres = adaptateur._parametres(plan, tmp_path / "modele.gguf")
    assert "chat_handler" not in parametres
