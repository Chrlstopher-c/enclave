"""Lots L5 et L6 du plan d'exécution — coût en tokens d'une image, mesuré, et repli sans vision.

Deux disciplines prouvées ici, chacune par un test qui échoue si on la retire :

- **L5 (2.3)** : `compter_multimodal` ne rend jamais un zéro déguisé en mesure. Sans modèle, sans
  projecteur, ou sur une erreur du moteur, la réponse est `possible=False` avec sa raison. Le poste
  `IMAGES` de `assembler_occupation` n'apparaît que si une mesure a réellement eu lieu.
  `_tokeniser_une_image` est prouvé contre un faux `mtmd_cpp` reproduisant la surface ctypes réelle
  (`mtmd_input_text`, `mtmd_tokenize`, `mtmd_input_chunk_get_n_tokens`...) — jamais une formule sur
  la résolution de l'image.
- **L6 (2.4)** : sans gestionnaire multimodal, une image devient une ligne factuelle DANS le
  message utilisateur — jamais un refus, jamais un texte d'interface.

Les coroutines sont pilotées par `asyncio.run`, comme le reste du dépôt : `asyncio_mode` n'est
configuré nulle part (cf. `test_contexte_execution_outil.py`).
"""

from __future__ import annotations

import backend.inference.engines_adapters.images_moteur as images_moteur

import asyncio
import ctypes
from pathlib import Path
from typing import Any

from backend.inference.engines_adapters import adaptateur_llama_cpp as module_llama_cpp
from backend.inference.engines_adapters.base import AdaptateurMoteur
from backend.inference.engines_adapters.contrat import (
    MessageChat,
    MoteurSupporte,
    PartieImageChemin,
    PartieTexte,
    PosteContexte,
    SegmentContexte,
    assembler_occupation,
    decouper_images,
)

# --------------------------------------------------------------- decouper_images


def test_decouper_images_rassemble_les_images_de_plusieurs_messages() -> None:
    messages = [
        MessageChat(
            role="user",
            content=[PartieTexte(text="a"), PartieImageChemin(chemin="/tmp/1.png", type_mime="image/png")],
        ),
        MessageChat(role="user", content="texte seul"),
        MessageChat(role="user", content=[PartieImageChemin(chemin="/tmp/2.png", type_mime="image/png")]),
    ]
    images = decouper_images(messages)
    assert [image.chemin for image in images] == ["/tmp/1.png", "/tmp/2.png"]


def test_decouper_images_sans_aucune_image_rend_une_liste_vide() -> None:
    assert decouper_images([MessageChat(role="user", content="Bonjour")]) == []


# --------------------------------------------------------------- assembler_occupation : poste IMAGES


def test_assembler_occupation_sans_image_n_a_pas_de_poste_images() -> None:
    segments = [SegmentContexte(poste=PosteContexte.UTILISATEUR, texte="Bonjour")]
    occupation = assembler_occupation(segments, [3], contexte_total=100)
    assert all(poste.poste != PosteContexte.IMAGES for poste in occupation.postes)


def test_assembler_occupation_avec_images_ajoute_leur_poste() -> None:
    segments = [SegmentContexte(poste=PosteContexte.UTILISATEUR, texte="Que vois-tu ?")]
    occupation = assembler_occupation(
        segments, [4], contexte_total=1000, tokens_images=256, nombre_images=1
    )
    poste_images = next(poste for poste in occupation.postes if poste.poste == PosteContexte.IMAGES)
    assert poste_images.tokens == 256
    assert poste_images.segments == 1
    assert occupation.tokens_mesures == 260


# --------------------------------------------------------------- AdaptateurMoteur : défaut « impossible »


class _AdaptateurSansMesureMultimodale(AdaptateurMoteur):
    """Vérifie le défaut hérité de `AdaptateurMoteur.compter_multimodal` — jamais un zéro."""

    moteur = MoteurSupporte.VLLM

    async def charger(self, plan: Any, session: Any = None) -> Any:
        raise NotImplementedError

    async def decharger(self) -> None:
        return None

    def generer(self, messages: Any, options: Any, outils: Any = None) -> Any:
        raise NotImplementedError

    async def sante(self) -> Any:
        raise NotImplementedError

    @property
    def etat(self) -> Any:
        return None


def test_compter_multimodal_par_defaut_rend_impossible_jamais_zero() -> None:
    adaptateur = _AdaptateurSansMesureMultimodale()
    image = PartieImageChemin(chemin="/tmp/x.png", type_mime="image/png")
    resultat = asyncio.run(adaptateur.compter_multimodal([image]))
    assert resultat.possible is False
    assert resultat.tokens_par_image == []
    assert "vllm" in resultat.raison


# --------------------------------------------------------------- AdaptateurLlamaCpp.compter_multimodal


class _AdaptateurTest(module_llama_cpp.AdaptateurLlamaCpp):
    """Sous-classe vide : les méthodes visées sont des méthodes d'instance."""


class _FauxLlm:
    def __init__(self, chat_handler: Any) -> None:
        self.chat_handler = chat_handler


def test_compter_multimodal_sans_modele_charge_rend_impossible() -> None:
    adaptateur = _AdaptateurTest()
    image = PartieImageChemin(chemin="/tmp/x.png", type_mime="image/png")
    resultat = asyncio.run(adaptateur.compter_multimodal([image]))
    assert resultat.possible is False
    assert resultat.tokens_par_image == []
    assert "Aucun modèle chargé" in resultat.raison


def test_compter_multimodal_sans_projecteur_rend_impossible() -> None:
    adaptateur = _AdaptateurTest()
    adaptateur._llm = _FauxLlm(chat_handler=None)  # type: ignore[assignment]
    image = PartieImageChemin(chemin="/tmp/x.png", type_mime="image/png")
    resultat = asyncio.run(adaptateur.compter_multimodal([image]))
    assert resultat.possible is False
    assert resultat.tokens_par_image == []
    assert "Aucun projecteur" in resultat.raison


# --------------------------------------------------------------- _tokeniser_une_image : le cœur de la mesure
#
# Reproduit la surface ctypes de `mtmd_cpp` réellement utilisée (mêmes noms de fonctions, mêmes
# types), sans dépendre de `libmtmd.so` : ce que ces tests prouvent est la LOGIQUE (somme des
# chunks, propagation d'un échec nommé), pas le calcul du clip — celui-là n'est vérifiable qu'en
# conteneur, avec un vrai projecteur chargé (preuves du rapport de lot).


class _EntreeTexteFactice(ctypes.Structure):
    _fields_ = [("text", ctypes.c_char_p), ("add_special", ctypes.c_bool), ("parse_special", ctypes.c_bool)]


class _MtmdCppFactice:
    mtmd_bitmap_p_ctypes = ctypes.c_void_p
    mtmd_input_text = _EntreeTexteFactice

    def __init__(self, tokens_par_chunk: list[int], echec_tokenize: bool = False) -> None:
        self._tokens_par_chunk = tokens_par_chunk
        self._echec_tokenize = echec_tokenize
        self.chunks_liberes = 0
        self.bitmaps_liberes = 0

    def mtmd_default_marker(self) -> bytes:
        return b"<marker>"

    def mtmd_input_chunks_init(self) -> list[int]:
        return list(self._tokens_par_chunk)

    def mtmd_tokenize(self, ctx: Any, chunks: Any, entree_ptr: Any, bitmaps: Any, n_bitmaps: int) -> int:
        return 1 if self._echec_tokenize else 0

    def mtmd_input_chunks_size(self, chunks: list[int]) -> int:
        return len(chunks)

    def mtmd_input_chunks_get(self, chunks: list[int], indice: int) -> int:
        return chunks[indice]

    def mtmd_input_chunk_get_n_tokens(self, chunk: int) -> int:
        return chunk

    def mtmd_input_chunks_free(self, chunks: object) -> None:
        self.chunks_liberes += 1

    def mtmd_bitmap_free(self, bitmap: object) -> None:
        self.bitmaps_liberes += 1


class _HandlerFactice:
    def __init__(self, mtmd_cpp: _MtmdCppFactice, echec_bitmap: bool = False) -> None:
        self._mtmd_cpp = mtmd_cpp
        self.mtmd_ctx = object()
        self._echec_bitmap = echec_bitmap

    def _create_bitmap_from_bytes(self, octets: bytes) -> int:
        # Un entier plutôt qu'un `object()` : `mtmd_bitmap_p_ctypes` est `c_void_p`, et ctypes
        # n'accepte pour le convertir qu'une adresse (int) ou `None` — jamais un objet Python quelconque.
        if self._echec_bitmap:
            raise ValueError("bitmap refusé")
        return 0x1234


def test_tokeniser_une_image_somme_les_chunks_rendus(tmp_path: Path) -> None:
    fichier = tmp_path / "photo.png"
    fichier.write_bytes(b"\x89PNG\r\n\x1a\nabc")
    mtmd_cpp = _MtmdCppFactice(tokens_par_chunk=[0, 143])
    handler = _HandlerFactice(mtmd_cpp)

    resultat = module_llama_cpp._tokeniser_une_image(
        mtmd_cpp, handler, PartieImageChemin(chemin=str(fichier), type_mime="image/png")
    )

    assert resultat == 143
    assert mtmd_cpp.chunks_liberes == 1
    assert mtmd_cpp.bitmaps_liberes == 1


def test_tokeniser_une_image_deux_fois_rend_le_meme_nombre(tmp_path: Path) -> None:
    """Preuve unitaire de la garantie exigée en conteneur : déterministe, pas un tirage."""
    fichier = tmp_path / "photo.png"
    fichier.write_bytes(b"\x89PNG\r\n\x1a\nabc")
    mtmd_cpp = _MtmdCppFactice(tokens_par_chunk=[64])
    handler = _HandlerFactice(mtmd_cpp)
    image = PartieImageChemin(chemin=str(fichier), type_mime="image/png")

    premier = module_llama_cpp._tokeniser_une_image(mtmd_cpp, handler, image)
    second = module_llama_cpp._tokeniser_une_image(mtmd_cpp, handler, image)

    assert premier == second == 64


def test_tokeniser_une_image_sur_echec_de_tokenize_rend_une_raison(tmp_path: Path) -> None:
    fichier = tmp_path / "photo.png"
    fichier.write_bytes(b"\x89PNG\r\n\x1a\nabc")
    mtmd_cpp = _MtmdCppFactice(tokens_par_chunk=[10], echec_tokenize=True)
    handler = _HandlerFactice(mtmd_cpp)

    resultat = module_llama_cpp._tokeniser_une_image(
        mtmd_cpp, handler, PartieImageChemin(chemin=str(fichier), type_mime="image/png")
    )

    assert isinstance(resultat, str)
    assert "échoué" in resultat


def test_tokeniser_une_image_sur_fichier_illisible_rend_une_raison(tmp_path: Path) -> None:
    mtmd_cpp = _MtmdCppFactice(tokens_par_chunk=[10])
    handler = _HandlerFactice(mtmd_cpp)
    absent = tmp_path / "absent.png"

    resultat = module_llama_cpp._tokeniser_une_image(
        mtmd_cpp, handler, PartieImageChemin(chemin=str(absent), type_mime="image/png")
    )

    assert isinstance(resultat, str)
    assert "illisible" in resultat


def test_tokeniser_une_image_sur_echec_de_bitmap_rend_une_raison(tmp_path: Path) -> None:
    fichier = tmp_path / "photo.png"
    fichier.write_bytes(b"\x89PNG\r\n\x1a\nabc")
    mtmd_cpp = _MtmdCppFactice(tokens_par_chunk=[10])
    handler = _HandlerFactice(mtmd_cpp, echec_bitmap=True)

    resultat = module_llama_cpp._tokeniser_une_image(
        mtmd_cpp, handler, PartieImageChemin(chemin=str(fichier), type_mime="image/png")
    )

    assert isinstance(resultat, str)
    assert "décoder" in resultat


# --------------------------------------------------------------- L6 : repli sans vision


def test_messages_pour_moteur_sans_vision_remplace_image_par_une_ligne_factuelle(tmp_path: Path) -> None:
    fichier = tmp_path / "capture.png"
    entete = b"\x89PNG\r\n\x1a\n" + b"\x00" * 8 + (100).to_bytes(4, "big") + (50).to_bytes(4, "big")
    fichier.write_bytes(entete + b"reste")
    message = MessageChat(
        role="user",
        content=[
            PartieTexte(text="Regarde ceci"),
            PartieImageChemin(chemin=str(fichier), type_mime="image/png", nom_affiche="capture.png"),
        ],
    )

    rendu = images_moteur._messages_pour_moteur([message], vision_disponible=False)

    assert rendu == [
        {"role": "user", "content": "Regarde ceci\n[image jointe : capture.png, 100×50, 0 Ko]"}
    ]


def test_messages_pour_moteur_sans_vision_ne_produit_jamais_de_message_de_refus(tmp_path: Path) -> None:
    """La ligne factuelle n'est ni un refus ni un aveu d'incapacité côté application (plan, 2.4)."""
    fichier = tmp_path / "x.png"
    fichier.write_bytes(b"\x89PNG\r\n\x1a\nabc")
    message = MessageChat(role="user", content=[PartieImageChemin(chemin=str(fichier), type_mime="image/png")])

    rendu = images_moteur._messages_pour_moteur([message], vision_disponible=False)

    contenu = rendu[0]["content"].lower()
    for interdit in ("ne prend pas en charge", "non supporté", "unsupported", "désolé", "je ne peux pas"):
        assert interdit not in contenu


def test_messages_pour_moteur_sans_vision_laisse_un_message_texte_inchange() -> None:
    rendu = images_moteur._messages_pour_moteur(
        [MessageChat(role="user", content="Bonjour")], vision_disponible=False
    )
    assert rendu == [{"role": "user", "content": "Bonjour"}]


def test_messages_pour_moteur_avec_vision_encode_toujours_en_image_url(tmp_path: Path) -> None:
    """Contrôle négatif : le défaut (vision disponible) n'est PAS touché par le repli."""
    fichier = tmp_path / "photo.png"
    fichier.write_bytes(b"\x89PNG\r\n\x1a\nabc")
    message = MessageChat(role="user", content=[PartieImageChemin(chemin=str(fichier), type_mime="image/png")])

    rendu = images_moteur._messages_pour_moteur([message], vision_disponible=True)

    assert rendu[0]["content"][0]["type"] == "image_url"


def test_vision_disponible_lit_le_chat_handler_de_l_instance_llama() -> None:
    class _AvecHandler:
        chat_handler = object()

    class _SansHandler:
        chat_handler = None

    assert module_llama_cpp._vision_disponible(_AvecHandler()) is True
    assert module_llama_cpp._vision_disponible(_SansHandler()) is False


# --------------------------------------------------------------- dimensions lues, jamais devinées


def test_dimensions_image_lit_un_en_tete_png() -> None:
    octets = b"\x89PNG\r\n\x1a\n" + b"\x00" * 8 + (800).to_bytes(4, "big") + (600).to_bytes(4, "big") + b"reste"
    assert images_moteur._dimensions_image(octets) == (800, 600)


def test_dimensions_image_lit_un_en_tete_jpeg() -> None:
    segment_sof0 = (
        b"\xff\xc0" + (17).to_bytes(2, "big") + bytes([8])
        + (300).to_bytes(2, "big") + (400).to_bytes(2, "big") + b"\x00" * 10
    )
    octets = b"\xff\xd8" + segment_sof0
    assert images_moteur._dimensions_image(octets) == (400, 300)


def test_dimensions_image_sur_format_non_reconnu_rend_none() -> None:
    assert images_moteur._dimensions_image(b"GIF89a" + b"\x00" * 20) is None
