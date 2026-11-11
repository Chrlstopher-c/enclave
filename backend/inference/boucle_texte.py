"""Boucle de texte — le modèle répète le même passage à l'infini dans UN seul tour.

Le radotage entre tours (`harnais.radote`) ne voit rien ici : le tour ne finit jamais, il remplit la
fenêtre en récitant le même paragraphe. Constaté sur « ServerBuilding » (11/11/2026) : un raisonnement
de ~400 caractères recopié des dizaines de fois. Le flux est donc surveillé pendant qu'il arrive, et
coupé dès qu'un bloc se répète plusieurs fois d'affilée à l'identique.

Un contenu de fichier légitimement répétitif (lignes de tableau, gabarits) ne doit pas être pris pour
une boucle : la détection exige un bloc long, répété plusieurs fois, et ignore l'intérieur d'un appel
d'outil en cours d'écriture.
"""

from __future__ import annotations

PERIODE_MIN = 80
PERIODE_MAX = 1500
# Le bloc doit apparaître au moins autant de fois de suite pour être une boucle.
REPETITIONS_MIN = 4
# Coupures tolérées dans une même génération avant de rendre la main.
COUPURES_MAX = 3

_OUVERTURES_APPEL = ("<tool_call>", "<function=")
_FERMETURES_APPEL = ("</tool_call>", "</function>")

CONSIGNE_BOUCLE_TEXTE = (
    "HARNESS: your last message was cut because you repeated the same passage over and over:\n"
    "«{bloc}»\n"
    "Thinking it over again will not settle it. Stop reasoning in circles and CHECK the fact you are "
    "unsure about with a tool call now (read the log, run the test, print the value), then continue."
)


def _dans_appel_ouvert(texte: str) -> bool:
    """Vrai si un appel d'outil est ouvert et pas encore refermé : son contenu est un fichier."""
    ouverture = max(texte.rfind(marque) for marque in _OUVERTURES_APPEL)
    fermeture = max(texte.rfind(marque) for marque in _FERMETURES_APPEL)
    return ouverture > fermeture


def bloc_repete(texte: str) -> str | None:
    """Le bloc qui se répète en fin de texte, ou `None`.

    Une fin de texte est périodique de période p si chaque caractère égale celui situé p plus tôt,
    sur (REPETITIONS_MIN - 1) × p caractères : peu importe où le bloc commence.
    """
    if _dans_appel_ouvert(texte):
        return None
    longueur = len(texte)
    for periode in range(PERIODE_MIN, min(PERIODE_MAX, longueur // REPETITIONS_MIN) + 1):
        etendue = periode * (REPETITIONS_MIN - 1)
        if texte[-etendue:] == texte[-etendue - periode:-periode]:
            bloc = texte[-periode:]
            if bloc.strip():
                return bloc
    return None


def tronquer(texte: str, bloc: str) -> str:
    """Le texte arrêté après UNE copie du passage : on remonte au début de la zone périodique."""
    periode = len(bloc)
    debut = len(texte) - periode - 1
    while debut >= 0 and texte[debut] == texte[debut + periode]:
        debut -= 1
    return texte[: debut + 1 + periode]


def consigne(bloc: str) -> str:
    """Consigne au modèle, qui cite le passage répété (raccourci) pour qu'il le reconnaisse."""
    extrait = " ".join(bloc.split())
    return CONSIGNE_BOUCLE_TEXTE.format(bloc=extrait[:300] + ("…" if len(extrait) > 300 else ""))
