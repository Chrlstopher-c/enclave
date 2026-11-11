"""Images d'un message, prêtes pour un moteur OpenAI-compatible : encodées au dernier moment, ou repliées.

Partagé par les adaptateurs llama.cpp et vLLM : un moteur avec vision reçoit des parties `image_url` (data URI) ;
un moteur sans vision reçoit une ligne factuelle à la place de chaque image, jamais un format qu'il rejetterait.
"""

from __future__ import annotations

import base64
from pathlib import Path
from typing import Any, Sequence

from loguru import logger

from backend.inference.engines_adapters.contrat import (
    ImageURL,
    MessageChat,
    PartieContenu,
    PartieImage,
    PartieImageChemin,
    PartieTexte,
)


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
        return message.model_dump(exclude_none=True)
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
        return message.model_dump(exclude_none=True)
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


def messages_pour_moteur(messages: Sequence[MessageChat], vision_disponible: bool) -> list[dict[str, Any]]:
    """Nom public de `_messages_pour_moteur`, pour les autres adaptateurs."""
    return _messages_pour_moteur(messages, vision_disponible)
