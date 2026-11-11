"""Collecte des constats d'un fichier et rendu compact (OK / FAIL / WARN)."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Rapport:
    titre: str
    lignes: list[str] = field(default_factory=list)
    erreurs: int = 0
    alertes: int = 0

    def ok(self, quoi: str) -> None:
        self.lignes.append(f"  OK   {quoi}")

    def echec(self, quoi: str, details: list[str] | None = None) -> None:
        self.erreurs += 1
        self._ajouter("FAIL", quoi, details)

    def alerte(self, quoi: str, details: list[str] | None = None) -> None:
        self.alertes += 1
        self._ajouter("WARN", quoi, details)

    def _ajouter(self, marque: str, quoi: str, details: list[str] | None) -> None:
        self.lignes.append(f"  {marque} {quoi}")
        details = details or []
        self.lignes += [f"       {d}" for d in details[:12]]
        if len(details) > 12:
            self.lignes.append(f"       … {len(details) - 12} more")

    def texte(self) -> str:
        return "\n".join([self.titre, *self.lignes])
