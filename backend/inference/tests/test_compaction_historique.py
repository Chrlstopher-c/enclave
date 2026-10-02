"""Preuve de l'aperçu des appels et de la compaction des blocs d'outils passés.

Deux économies distinctes, décidées le 2026-08-16 après une capture réelle où le bloc « Appel
d'outil » pesait 7 261 caractères et sa sortie 7 406 — pour une page HTML que l'utilisateur pouvait
de toute façon ouvrir en artefact.

- À l'ÉMISSION, l'annonce d'un appel ne montre que les premières lignes de chaque argument. Écrire
  un fichier passe son contenu entier en argument ; l'afficher en entier noyait le bloc.
- À la RELECTURE, les blocs d'outils des tours passés sont réduits avant de repartir au moteur. Le
  contenu d'un outil n'a de valeur pleine que pendant le tour qui l'a demandé ; ensuite, seule son
  existence compte, et le modèle peut relire le fichier à la demande.

Propriété non négociable, vérifiée ici : la compaction ne touche QUE ce qui part au moteur. Le
message enregistré et l'affichage restent entiers — c'est une économie de contexte, pas une perte.
"""

from __future__ import annotations

from backend.inference import (
    BALISE_ENTREE_FERMANTE,
    BALISE_ENTREE_OUVRANTE,
    BALISE_OUTIL_FERMANTE,
    BALISE_OUTIL_OUVRANTE,
    BALISE_SORTIE_FERMANTE,
    BALISE_SORTIE_OUVRANTE,
    LIGNES_APERCU_ARGUMENT,
    LIGNES_BLOC_HISTORIQUE,
    _annonce,
    _compacter_blocs_outils,
    _messages_depuis,
)


class _MessageFactice:
    def __init__(self, role: str, contenu: str) -> None:
        self.role = role
        self.contenu = contenu


def _bloc(corps_sortie: str, corps_entree: str = "lire_fichier(chemin : app.py)") -> str:
    return (
        f"Je regarde le fichier.{BALISE_OUTIL_OUVRANTE}"
        f"{BALISE_ENTREE_OUVRANTE}{corps_entree}{BALISE_ENTREE_FERMANTE}"
        f"{BALISE_SORTIE_OUVRANTE}{corps_sortie}{BALISE_SORTIE_FERMANTE}"
        f"{BALISE_OUTIL_FERMANTE}Voilà ce que j'en pense."
    )


def test_l_annonce_ne_montre_que_les_premieres_lignes_d_un_argument_long() -> None:
    contenu = "\n".join(f"ligne {n}" for n in range(50))

    annonce = _annonce("ecrire_fichier", {"chemin": "app.py", "contenu": contenu})

    assert "chemin : app.py" in annonce
    assert "ligne 0" in annonce
    assert f"ligne {LIGNES_APERCU_ARGUMENT - 1}" in annonce
    assert f"ligne {LIGNES_APERCU_ARGUMENT}" not in annonce, "au-delà de l'aperçu, rien ne passe"
    assert "lignes" in annonce and "caractères" in annonce, "le retrait est annoncé, pas silencieux"


def test_l_annonce_laisse_un_argument_court_intact() -> None:
    """Une économie qui abîmerait les cas normaux n'en serait pas une."""
    assert _annonce("presenter_fichier", {"fichier_id": "app.py"}) == "presenter_fichier(fichier_id : app.py)"


def test_un_bloc_court_n_est_pas_touche() -> None:
    texte = _bloc("trois\npetites\nlignes")
    assert _compacter_blocs_outils(texte) == texte


def test_un_bloc_long_est_reduit_et_le_dit() -> None:
    texte = _bloc("\n".join(f"contenu {n}" for n in range(60)))

    compacte = _compacter_blocs_outils(texte)

    assert "contenu 0" in compacte
    assert f"contenu {LIGNES_BLOC_HISTORIQUE - 1}" in compacte
    assert f"contenu {LIGNES_BLOC_HISTORIQUE}" not in compacte
    assert "lignes retirées de l'historique" in compacte


def test_la_compaction_preserve_le_texte_hors_des_blocs() -> None:
    """Le raisonnement et la réponse du modèle ne sont jamais rognés — seuls les blocs d'outils."""
    compacte = _compacter_blocs_outils(_bloc("\n".join(str(n) for n in range(60))))

    assert compacte.startswith("Je regarde le fichier.")
    assert compacte.endswith("Voilà ce que j'en pense.")
    assert BALISE_SORTIE_OUVRANTE in compacte and BALISE_SORTIE_FERMANTE in compacte


def test_un_message_sans_bloc_d_outil_traverse_inchange() -> None:
    texte = "\n".join(f"une longue réponse, ligne {n}" for n in range(80))
    assert _compacter_blocs_outils(texte) == texte


def test_l_historique_arrive_compacte_au_moteur() -> None:
    """Le point d'assemblage : c'est `_messages_depuis` qui alimente le moteur."""
    long_bloc = _bloc("\n".join(f"contenu {n}" for n in range(60)))

    convertis = _messages_depuis([_MessageFactice("assistant", long_bloc)])

    assert len(convertis) == 1
    # Depuis le 2026-10-02 le bloc entier devient une ligne de prose : le modèle imitait le balisage.
    contenu = str(convertis[0].content)
    assert "contenu 59" not in contenu and "<outil>" not in contenu and "<sortie" not in contenu
    assert "Outils utilisés dans ce tour" in contenu
