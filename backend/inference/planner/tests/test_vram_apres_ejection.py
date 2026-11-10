"""Ce que ces tests empêchent : que le planificateur compte le bureau comme éjectable.

Défaut vécu le 2026-08-26 : le modèle est devenu inchargeable DEPUIS L'INTERFACE, à tous les
contextes, pendant toute une session. L'erreur remontée était « VRAM insuffisante » — vraie, et
muette sur la cause.

Deux fautes se cumulaient, chacune suffisante :
  - le plafond était `vram_totale`, ce qui suppose qu'éjecter les modèles rend la carte ENTIÈRE ;
  - le client annonçait comme VRAM du modèle la VRAM totale UTILISÉE (`vram_apres_octets`), bureau
    compris.
Résultat : 12 288 Mio annoncés disponibles sur une carte dont 1 453 étaient pris en permanence par
le compositeur, le shell et le navigateur.

L'effet portait sur le déport d'experts, qui est un curseur continu : trop de VRAM annoncée, trop
peu d'experts déportés, allocation refusée. Rien dans le message d'erreur ne pouvait y mener.
"""

from __future__ import annotations

from backend.inference.planner.entrees import Moteur, ModeleCharge, Plateforme, ProfilMachine
from backend.inference.planner.moteur import RESERVE_BUREAU_OCTETS, vram_apres_ejection

_MIO = 1024 * 1024
_CARTE = 12288 * _MIO


def _profil(vram_libre_mio: int, charges: list[ModeleCharge]) -> ProfilMachine:
    return ProfilMachine(
        plateforme=Plateforme.LINUX_NATIF, vram_totale_octets=_CARTE,
        vram_libre_octets=vram_libre_mio * _MIO, ram_libre_octets=30 * 1024**3,
        moteurs_disponibles=[Moteur.LLAMA_CPP], modeles_charges=charges)


def _modele(vram_mio: int) -> ModeleCharge:
    return ModeleCharge(identifiant="m", moteur=Moteur.LLAMA_CPP, vram_octets=vram_mio * _MIO)


def test_sans_modele_charge_la_vram_disponible_est_la_vram_libre() -> None:
    """Cas simple, et le seul qui marchait déjà : rien à éjecter, rien à déduire."""
    disponible, ejections = vram_apres_ejection(_profil(10454, []))
    assert disponible == 10454 * _MIO - RESERVE_BUREAU_OCTETS
    assert ejections == ()


def test_le_bureau_n_est_jamais_compte_comme_liberable() -> None:
    """LA régression à empêcher.

    Modèle de 9 820 Mio, bureau de 1 453 : éjecter le modèle rend 10 835 Mio, pas les 12 288 de la
    carte. L'ancien `min(vram_totale, …)` rendait 12 288 dès que la somme atteignait le total.
    """
    disponible, _ = vram_apres_ejection(_profil(12288 - 11273, [_modele(9820)]))
    assert disponible == 10835 * _MIO - RESERVE_BUREAU_OCTETS


def test_une_ejection_ne_peut_pas_rendre_plus_que_ce_qui_est_occupe() -> None:
    """Garde-fou contre un client qui annonce la taille du FICHIER au lieu de la VRAM réelle.

    Sans cette borne, une valeur gonflée passait telle quelle dans le budget et produisait un plan
    que le GPU refusait — le pire des cas, puisque l'échec arrive après le déchargement.
    """
    occupe = 11273
    disponible, _ = vram_apres_ejection(_profil(12288 - occupe, [_modele(99000)]))
    assert disponible <= _CARTE
    assert disponible == _CARTE - RESERVE_BUREAU_OCTETS  # tout l'occupé est réputé éjectable, mais rien de plus


def test_plusieurs_modeles_charges_cumulent_leur_liberation() -> None:
    disponible, ejections = vram_apres_ejection(
        _profil(1000, [_modele(4000), _modele(3000)]))
    assert len(ejections) == 2
    assert disponible == 8000 * _MIO - RESERVE_BUREAU_OCTETS
