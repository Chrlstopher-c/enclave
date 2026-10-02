"""Le balisage du harnais ne revient pas au modèle, et celui qu'il imite est neutralisé à l'écran."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from typing import Any

from backend.inference.hygiene_historique import neutraliser, pour_le_modele, sans_balises_imitees

TOUR = ('Je regarde.<outil><entree>executer_commande(commande : ls)</entree><sortie etat="echec">'
        'Code de retour 2</sortie></outil><etape-fin/>Puis je lis.<outil><entree>lire_fichier(chemin : a.py)'
        '</entree><sortie>print(1)</sortie></outil><etape-fin/>Fini.')


def test_le_modele_relit_sa_prose_et_un_recapitulatif_sans_balise() -> None:
    texte = pour_le_modele(TOUR)
    assert "<" not in texte
    assert texte.startswith("Je regarde.\nPuis je lis.\nFini.")
    assert "executer_commande ×1 dont 1 en échec" in texte and "lire_fichier ×1" in texte
    assert "print(1)" not in texte


def test_balises_imitees_et_bloc_inacheve_retires() -> None:
    assert pour_le_modele("ok</etree><sortie etat=\"echec\">faux</sortie></etape_fin/>") == "ok\nfaux"
    assert pour_le_modele("avant<outil><entree>executer_commande(") == "avant"


def test_neutralisation_a_l_affichage_y_compris_balise_coupee() -> None:
    assert neutraliser("<etape_fin/> </etree>") == "‹etape_fin/> ‹/etree>"
    assert neutraliser("<tool_call>{}</tool_call> a < b") == "<tool_call>{}</tool_call> a < b"

    async def flux() -> AsyncIterator[dict[str, Any]]:
        for texte in ("texte <so", "rtie>faux</sor", "tie> fin"):
            yield {"texte": texte}

    async def lire() -> str:
        return "".join([m["texte"] async for m in sans_balises_imitees(flux())])

    assert asyncio.run(lire()) == "texte ‹sortie>faux‹/sortie> fin"
