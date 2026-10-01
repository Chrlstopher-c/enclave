"""Preuves du domaine `projets` : racine confinée, instantanés git réels, restauration annulable.

L'atelier est remplacé à sa frontière (`executer_commande`) par une exécution bash locale dans
`<racine>/<projet>` : git tourne pour de vrai, seuls le conteneur et le réseau disparaissent.
"""

from __future__ import annotations

import subprocess
from collections.abc import Iterator
from pathlib import Path

import pytest

from backend.core.config import reset_settings_cache
from backend.outils import atelier
from backend.projets import contenu, instantanes, racine
from backend.projets.racine import ProjetInvalide


@pytest.fixture
def racine_projets(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    base = tmp_path / "projets"
    monkeypatch.setenv("ECHOHUB_PROJETS_RACINE", str(base))
    reset_settings_cache()

    def _local(commande: str, sous_dossier: str, timeout_s: int, racine_: str = "workspace") -> atelier.ReponseAtelier:
        assert racine_ == "projets"
        proc = subprocess.run(["bash", "-c", commande], cwd=base / sous_dossier, capture_output=True,
                              text=True, timeout=timeout_s)
        return atelier.ReponseAtelier(code_retour=proc.returncode, sortie=proc.stdout, erreur=proc.stderr,
                                      duree_s=0.0, tue=False)

    monkeypatch.setattr(instantanes, "executer_commande", _local)
    yield base
    reset_settings_cache()


def test_sans_racine_le_catalogue_est_inactif(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ECHOHUB_PROJETS_RACINE", raising=False)
    reset_settings_cache()
    assert racine.catalogue().actif is False


def test_creer_puis_lister(racine_projets: Path) -> None:
    racine.creer("mon-app")
    catalogue = racine.catalogue()
    assert catalogue.actif and [p.nom for p in catalogue.projets] == ["mon-app"]
    assert racine.chemin_projet("mon-app") == (racine_projets / "mon-app").resolve()


@pytest.mark.parametrize("nom", ["../evasion", "a/b", ".cache", "", "Majuscule"])
def test_noms_refuses(racine_projets: Path, nom: str) -> None:
    with pytest.raises(ProjetInvalide):
        racine.chemin_projet(nom)


def test_lien_symbolique_hors_racine_refuse(racine_projets: Path, tmp_path: Path) -> None:
    (tmp_path / "dehors").mkdir()
    racine_projets.mkdir(parents=True, exist_ok=True)
    (racine_projets / "piege").symlink_to(tmp_path / "dehors")
    with pytest.raises(ProjetInvalide):
        racine.chemin_projet("piege")


def test_instantane_puis_restauration(racine_projets: Path) -> None:
    racine.creer("app")
    dossier = racine_projets / "app"
    (dossier / "main.py").write_text("v1\n")
    (dossier / "node_modules").mkdir()
    (dossier / "node_modules" / "lourd.js").write_text("x")
    premier = instantanes.prendre("app", "avant le tour 1")
    assert premier is not None
    assert instantanes.prendre("app", "rien n'a changé") is None

    (dossier / "main.py").write_text("v2 cassée\n")
    (dossier / "nouveau.py").write_text("ajout du modèle\n")
    filet = instantanes.restaurer("app", premier)

    assert (dossier / "main.py").read_text() == "v1\n"
    assert not (dossier / "nouveau.py").exists()
    assert (dossier / "node_modules" / "lourd.js").exists(), "les dépendances ne sont pas versionnées"
    assert filet is not None and filet in {i.sha for i in instantanes.lister("app")}

    instantanes.restaurer("app", filet)
    assert (dossier / "main.py").read_text() == "v2 cassée\n", "une restauration s'annule"


def test_sha_invalide_refuse(racine_projets: Path) -> None:
    racine.creer("app")
    with pytest.raises(ProjetInvalide):
        instantanes.restaurer("app", "HEAD; rm -rf /")


def test_arbre_ignore_les_dependances_et_lire_reste_confine(racine_projets: Path) -> None:
    racine.creer("app")
    base = racine_projets / "app"
    (base / "src").mkdir()
    (base / "src" / "main.py").write_text("print(1)\n")
    (base / "node_modules" / "x").mkdir(parents=True)
    (base / "node_modules" / "x" / "index.js").write_text("")
    assert [f.chemin for f in contenu.arbre("app").fichiers] == ["src/main.py"]
    assert contenu.lire("app", "src/main.py").contenu == "print(1)\n"
    for chemin in ("../../etc/passwd", "/etc/passwd", ".echohub/x"):
        with pytest.raises(ProjetInvalide):
            contenu.lire("app", chemin)


def test_modifications_depuis_le_dernier_instantane(racine_projets: Path) -> None:
    racine.creer("app")
    base = racine_projets / "app"
    assert instantanes.modifications("app").reference is None
    (base / "a.py").write_text("un\n")
    (base / "b.py").write_text("b\n")
    instantanes.prendre("app", "avant le tour")
    (base / "a.py").write_text("un\ndeux\n")
    (base / "b.py").unlink()
    (base / "c.py").write_text("c\n")
    etat = instantanes.modifications("app")
    assert etat.reference is not None and etat.reference.message == "avant le tour"
    par_chemin = {m.chemin: m for m in etat.fichiers}
    assert {c: m.etat for c, m in par_chemin.items()} == {"a.py": "M", "b.py": "D", "c.py": "A"}
    assert par_chemin["a.py"].ajouts == 1 and par_chemin["a.py"].suppressions == 0
    assert "+deux" in instantanes.diff("app", "a.py").diff
    with pytest.raises(ProjetInvalide):
        instantanes.diff("app", "--output=/tmp/x")
