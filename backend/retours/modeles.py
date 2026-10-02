"""Structures du domaine `retours` : le verdict porté sur une réponse et ce qu'on en garde."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

Verdict = Literal["positif", "negatif", "correction", "meilleure", "pire"]
# « meilleure » / « pire » : choix entre variantes du même tour (même parent), un seul de chaque par tour.
VERDICTS_COMPARATIFS = ("meilleure", "pire")
# Raisons qu'aucun contrôle automatique ne peut établir. CTA absent, longueur, mots interdits et recopie
# du brief ne figurent PAS ici : ils sont mesurés à l'export, pas étiquetés à la main.
Raison = Literal["accroche_faible", "ton", "fait_invente", "cliche_ia", "francais", "generique", "hors_brief",
                 "structure"]


class DemandeRetour(BaseModel):
    """Ce que l'interface envoie : le reste (brief, prompt système, modèle) est relu côté serveur."""

    model_config = ConfigDict(extra="forbid")

    conversation_id: str
    message_id: str
    verdict: Verdict
    correction: str | None = Field(default=None, max_length=50_000)
    raisons: list[Raison] = Field(default_factory=list, max_length=8)

    @model_validator(mode="after")
    def _correction_coherente(self) -> DemandeRetour:
        if self.verdict == "correction" and not (self.correction or "").strip():
            raise ValueError("une correction exige le texte corrigé")
        return self


class TourHistorique(BaseModel):
    role: str
    contenu: str


class Retour(BaseModel):
    """Un retour complet, autonome : de quoi rejouer l'exemple sans relire la conversation."""

    message_id: str
    conversation_id: str
    parent_id: str | None
    modele_id: str | None
    prompt_systeme: str
    temperature: float | None
    historique: list[TourHistorique]
    # 0 = première génération sur le brief (qualité du texte) ; >= 1 = itération demandée en conversation
    # (« plus court », « change le hook ») : une autre compétence, exportée dans un jeu séparé.
    tour: int = 0
    reponse: str
    verdict: Verdict
    correction: str | None
    raisons: list[Raison] = Field(default_factory=list)
    cree_le: str


class ResumeRetours(BaseModel):
    total: int
    positifs: int
    negatifs: int
    corrections: int
    comparaisons: int
    par_message: dict[str, Verdict]
    raisons_par_message: dict[str, list[Raison]]
