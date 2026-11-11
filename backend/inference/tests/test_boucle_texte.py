"""Un tour qui récite le même passage en boucle est coupé, et le modèle est sommé de vérifier.

Cas réel : « ServerBuilding », 11/11/2026 — un raisonnement de ~400 caractères recopié jusqu'à
remplir la fenêtre, sans qu'aucun garde-fou ne l'arrête.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Sequence
from typing import Any

import backend.inference as domaine_inference
from backend.chat.modeles import ParametresEchantillonnage
from backend.chat.port_inference import MessageInference, RequeteGeneration
from backend.inference import MoteurChat, boucle_texte
from backend.inference.engines_adapters.contrat import MessageChat, MorceauGeneration, OptionsGeneration

PASSAGE = (
    "Attendez — 12ea2b19c9a0 est apparu dans l'ancien serveur (avant l'arrêt). Le nouveau serveur a "
    "redémarré. Donc le test live que j'ai fait a tourné sur le NOUVEAU serveur 3575. "
)


def test_un_passage_repete_est_reconnu() -> None:
    assert boucle_texte.bloc_repete("Introduction. " + PASSAGE * 5) is not None


def test_un_texte_ordinaire_n_est_pas_une_boucle() -> None:
    texte = " ".join(f"Étape {i} : je vérifie le fichier numéro {i}." for i in range(200))
    assert boucle_texte.bloc_repete(texte) is None


def test_trois_copies_ne_suffisent_pas() -> None:
    assert boucle_texte.bloc_repete("Début. " + PASSAGE * 3) is None


def test_un_fichier_repetitif_en_cours_d_ecriture_n_est_pas_coupe() -> None:
    ligne = "<div class='carte'><h2>Titre</h2><p>Un paragraphe de contenu assez long ici.</p></div>\n"
    assert boucle_texte.bloc_repete("<tool_call>{\"contenu\": \"" + ligne * 10) is None


def test_la_troncature_garde_une_seule_copie() -> None:
    texte = "Début. " + PASSAGE * 6
    bloc = boucle_texte.bloc_repete(texte)
    assert bloc is not None
    assert boucle_texte.tronquer(texte, bloc).count("Attendez") == 1


class _SuperviseurQuiBoucle:
    def __init__(self) -> None:
        self.tours = 0
        self.emis = 0
        self.ferme = False
        self.appels: list[list[MessageChat]] = []

    def generer(
        self, messages: Sequence[MessageChat], options: OptionsGeneration,
        outils: Sequence[dict[str, Any]] | None = None,
    ) -> AsyncIterator[MorceauGeneration]:
        self.tours += 1
        self.appels.append(list(messages))
        return self._boucle() if self.tours == 1 else self._fin()

    async def _boucle(self) -> AsyncIterator[MorceauGeneration]:
        try:
            for _ in range(3000):
                for mot in PASSAGE.split(" "):
                    self.emis += 1
                    yield MorceauGeneration(type="token", contenu=mot + " ")
            yield MorceauGeneration(type="fin", raison_arret="stop")
        finally:
            self.ferme = True

    async def _fin(self) -> AsyncIterator[MorceauGeneration]:
        yield MorceauGeneration(type="token", contenu="Je vérifie le journal.")
        yield MorceauGeneration(type="fin", raison_arret="stop")


def _jouer(monkeypatch: Any) -> _SuperviseurQuiBoucle:
    superviseur = _SuperviseurQuiBoucle()
    monkeypatch.setattr(domaine_inference, "superviseur", superviseur)

    async def lire() -> None:
        async for _ in MoteurChat().generer(RequeteGeneration(
            messages=[MessageInference(role="user", contenu="débogue le serveur")],
            parametres=ParametresEchantillonnage(), conversation_id="boucle-texte",
        )):
            pass

    asyncio.run(lire())
    return superviseur


def test_le_tour_en_boucle_est_coupe_tot_et_le_moteur_arrete(monkeypatch: Any) -> None:
    superviseur = _jouer(monkeypatch)
    assert superviseur.ferme, "le flux du moteur est fermé, pas laissé tourner"
    assert superviseur.emis < 500, f"coupé tôt ({superviseur.emis} jetons)"


def test_le_modele_repart_avec_une_seule_copie_et_la_consigne(monkeypatch: Any) -> None:
    superviseur = _jouer(monkeypatch)
    *_, assistant, consigne = superviseur.appels[1]
    assert str(consigne.content).startswith("HARNESS: your last message was cut")
    assert str(assistant.content).count("Attendez") == 1
