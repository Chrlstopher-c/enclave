"""Construit un retour à partir de la conversation : brief, prompt système et réponse sont relus ici.

L'interface n'envoie que le verdict ; relire côté serveur garantit que l'exemple enregistré est
exactement ce que le modèle a vu et produit, pas ce que le navigateur en affichait.
"""

from __future__ import annotations

from backend import chat
from backend.core import EchoHubError
from backend.retours import depot
from backend.retours.modeles import VERDICTS_COMPARATIFS, DemandeRetour, ResumeRetours, Retour, TourHistorique


class RetourInvalide(EchoHubError):
    """Le message visé ne peut pas recevoir de retour (pas une réponse du modèle)."""

    code = "retour_invalide"
    statut_http = 422
    remediation_defaut = "Noter uniquement une réponse du modèle."


def noter(demande: DemandeRetour) -> Retour:
    chemin = chat.chemin_jusqua(demande.conversation_id, demande.message_id)
    if not chemin or chemin[-1].role != "assistant":
        raise RetourInvalide(f"Le message {demande.message_id} n'est pas une réponse du modèle.")
    reponse = chemin[-1]
    reglages = chat.lire_reglages(demande.conversation_id)
    historique = [TourHistorique(role=m.role, contenu=m.contenu) for m in chemin[:-1] if m.role != "system"]
    retour = Retour(
        message_id=reponse.id,
        conversation_id=demande.conversation_id,
        parent_id=reponse.parent_id,
        modele_id=reponse.modele_id,
        prompt_systeme=reglages.prompt_systeme,
        temperature=reglages.parametres.temperature,
        historique=historique,
        tour=sum(t.role == "assistant" for t in historique),
        reponse=reponse.contenu,
        verdict=demande.verdict,
        correction=demande.correction if demande.verdict == "correction" else None,
        raisons=demande.raisons,
        source=demande.source,
        cree_le="",
    )
    if demande.verdict in VERDICTS_COMPARATIFS:
        depot.retirer_chez_les_freres(reponse.parent_id, demande.verdict, reponse.id, demande.source)
    return depot.enregistrer(retour)


def resumer(conversation_id: str | None = None) -> ResumeRetours:
    retours = depot.lister(conversation_id)
    chris = [r for r in retours if r.source == "chris"]
    return ResumeRetours(
        total=len(retours),
        positifs=sum(r.verdict == "positif" for r in retours),
        negatifs=sum(r.verdict == "negatif" for r in retours),
        corrections=sum(r.verdict == "correction" for r in retours),
        comparaisons=sum(r.verdict in VERDICTS_COMPARATIFS for r in retours),
        par_source={s: sum(r.source == s for r in retours) for s in ("chris", "claude")},
        par_message={r.message_id: r.verdict for r in chris},
        raisons_par_message={r.message_id: r.raisons for r in chris if r.raisons},
        claude_par_message={r.message_id: r.verdict for r in retours if r.source == "claude"},
    )
