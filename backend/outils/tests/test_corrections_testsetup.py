"""Corrections tirées de « TestSetup » (11/11/2026) : accents, adresses devinées, consignes du socle."""

from __future__ import annotations

from backend.outils import indice_api, socle
from backend.outils.fichiers_bac import _remplacer
from backend.outils.fragment_approche import localiser_sans_accents

FICHIER = '# Catégories européennes simplifiées.\nCATÉGORIES = {0: "Bon"}\n'


def test_un_fragment_sans_accents_est_retrouve_et_remplace() -> None:
    nouveau, note = _remplacer(FICHIER, "# Categories europeennes simplifiees.", "# Catégories (EPA).")
    assert nouveau.startswith("# Catégories (EPA).\nCATÉGORIES")
    assert "accents" in note


def test_le_texte_exact_reste_prioritaire() -> None:
    nouveau, note = _remplacer(FICHIER, '{0: "Bon"}', '{0: "Bien"}')
    assert '{0: "Bien"}' in nouveau and note == ""


def test_un_repli_ambigu_est_refuse() -> None:
    assert localiser_sans_accents("é e", "e") is None


def test_un_fragment_absent_echoue_toujours() -> None:
    try:
        _remplacer(FICHIER, "rien de tel", "x")
    except Exception as exc:  # noqa: BLE001 — EchecOutil attendu
        assert "n'apparaît pas" in str(exc)
    else:
        raise AssertionError("aurait dû échouer")


def test_une_adresse_refusee_par_curl_renvoie_vers_la_doc() -> None:
    commande = 'curl -s "https://api.open-meteo.com/v1/air-quality?latitude=48.85"'
    assert indice_api.indice(commande, '{"error":true,"reason":"Not Found"}') == indice_api.INDICE


def test_une_reponse_normale_ne_declenche_rien() -> None:
    assert indice_api.indice('curl -s "https://exemple.org/api"', '{"pm2_5": [12.1]}') is None
    assert indice_api.indice("grep -rn 'not found' src/", "src/a.py: not found") is None


def test_le_socle_dit_tester_tot_reflechir_court_et_lire_la_doc() -> None:
    texte = socle._AVEC_OUTILS
    assert "TEST EARLY" in texte and "THINK SHORT" in texte and "documentation FIRST" in texte


def test_contenu_objet_ecrit_en_json(tmp_path) -> None:
    import asyncio
    import json as _json

    from backend.outils import fichiers_bac
    from backend.outils.contrat import ContexteExecution

    contexte = ContexteExecution(conversation_id="c", racine_bac=tmp_path, projet="p")
    asyncio.run(fichiers_bac._ecrire({"chemin": "package.json", "contenu": {"name": "x", "v": [1]}}, contexte))
    assert _json.loads((tmp_path / "package.json").read_text()) == {"name": "x", "v": [1]}
