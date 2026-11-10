"""Choix du moteur d'inférence, et exclusivité du GPU.

Deux décisions vivent ici :

1. **Quel moteur** peut charger ce format de poids, compte tenu de ce qui est installé et de ce que
   l'utilisateur demande. Une préférence irréalisable est plafonnée et expliquée, jamais subie.
2. **Ce qu'il faut éjecter** avant de charger. vLLM prééalloue la VRAM et ne la rend qu'à l'arrêt du
   processus : sur 16 Go, aucun modèle ne cohabite avec un autre. Le GPU est traité comme une
   ressource exclusive, quel que soit le moteur.
"""

from __future__ import annotations

from backend.core import MoteurIndisponible
from backend.inference.planner.entrees import (
    FormatModele,
    Moteur,
    MetadonneesModele,
    PreferencesUtilisateur,
    ProfilMachine,
)
from backend.inference.planner.plan import EjectionRequise, ValeurJustifiee

# Un format de poids ne se charge pas dans n'importe quel moteur : llama.cpp lit le GGUF, vLLM lit
# les safetensors. Cette table est une contrainte de format, pas une préférence.
MOTEURS_PAR_FORMAT: dict[FormatModele, tuple[Moteur, ...]] = {
    FormatModele.GGUF: (Moteur.LLAMA_CPP,),
    FormatModele.SAFETENSORS: (Moteur.VLLM,),
}


def choisir_moteur(
    metadonnees: MetadonneesModele,
    profil: ProfilMachine,
    preferences: PreferencesUtilisateur,
) -> tuple[ValeurJustifiee[Moteur], tuple[str, ...]]:
    """Retient le moteur utilisable, en expliquant tout écart avec la demande de l'utilisateur."""
    compatibles = MOTEURS_PAR_FORMAT[metadonnees.format]
    utilisables = tuple(moteur for moteur in compatibles if moteur in profil.moteurs_disponibles)
    if not utilisables:
        raise MoteurIndisponible(
            f"Aucun moteur installé ne sait charger un modèle {metadonnees.format.value}.",
            details={
                "format": metadonnees.format.value,
                "moteurs_compatibles": [moteur.value for moteur in compatibles],
                "moteurs_installes": [moteur.value for moteur in profil.moteurs_disponibles],
            },
        )

    retenu = utilisables[0]
    demande = preferences.moteur
    if demande is None or demande is retenu:
        justification = f"Seul moteur installé capable de lire le format {metadonnees.format.value}."
        return ValeurJustifiee[Moteur](valeur=retenu, justification=justification), ()

    avertissement = (
        f"Moteur {demande.value} demandé mais {'non installé' if demande in compatibles else 'incompatible'} "
        f"avec le format {metadonnees.format.value} : {retenu.value} retenu à la place."
    )
    valeur = ValeurJustifiee[Moteur](
        valeur=retenu,
        justification=avertissement,
        plafonnee=True,
        valeur_demandee=demande,
    )
    return valeur, (avertissement,)


def ejections_requises(profil: ProfilMachine) -> tuple[EjectionRequise, ...]:
    """Modèles à décharger avant ce chargement — c'est-à-dire tous ceux qui occupent le GPU.

    Aucune exception, même entre deux modèles llama.cpp : la VRAM libre mesurée dans le profil est
    celle qui reste *avec* ces modèles chargés. Le budget du plan raisonne sur l'après-éjection.
    """
    return tuple(
        EjectionRequise(
            identifiant=charge.identifiant,
            moteur=charge.moteur,
            vram_liberee_octets=charge.vram_octets,
            raison=(
                f"Le GPU est une ressource exclusive : {charge.moteur.value} conserve sa VRAM "
                "jusqu'à l'arrêt du processus."
            ),
        )
        for charge in profil.modeles_charges
    )


# VRAM laissée au bureau EN PLUS de ce qu'il occupe au moment de la mesure. Le navigateur, Discord et
# Claude Desktop (Electron) allouent de la VRAM au fil de l'usage : un plan qui prenait tout le libre
# mesuré les privait de cette marge, et ils plantaient (NV_ERR_NO_MEMORY, Chrome en SIGILL, Claude
# Desktop fermé deux fois en dix minutes le 2026-11-10 avec vLLM à 82 % de la carte).
RESERVE_BUREAU_OCTETS = 1536 * 1024**2


def vram_apres_ejection(profil: ProfilMachine) -> tuple[int, tuple[EjectionRequise, ...]]:
    """VRAM sur laquelle le plan peut compter : le libre mesuré plus ce que les éjections rendront.

    `☠` LE PLAFOND N'EST PAS LA VRAM TOTALE, et l'avoir cru a rendu le modèle inchargeable depuis
    l'interface pendant toute une session.

    Une carte n'héberge pas que des modèles. Sur la machine mesurée le 2026-08-26, le compositeur,
    le shell, le fond animé et le navigateur occupent 1 453 Mio en permanence — et AUCUNE éjection
    de modèle ne les rendra. Plafonner à `vram_totale` revient donc à promettre au planificateur une
    VRAM qui n'existera jamais.

    L'effet est brutal parce qu'il porte sur le déport d'experts, qui est un curseur : à
    12 288 Mio annoncés, le planificateur ne déportait que 2 groupes d'experts — le plan réclamait
    11 479 Mio pour 10 454 réellement libres, et le GPU refusait l'allocation. À la valeur honnête,
    il en déporte 7 et le chargement passe. Aucun message n'aurait pu faire soupçonner un plafond :
    l'erreur remontée était « VRAM insuffisante », ce qui était vrai et ne désignait pas la cause.

    Ce qui n'est pas éjectable se déduit sans supposer quoi que ce soit : c'est l'occupation
    mesurée, moins ce que les éjections rendront. Le plan ne peut pas compter dessus.
    """
    ejections = ejections_requises(profil)
    liberee = sum(ejection.vram_liberee_octets for ejection in ejections)
    occupe = max(0, profil.vram_totale_octets - profil.vram_libre_octets)
    # Une éjection ne peut pas rendre plus que ce qui est pris : un client qui rapporte la taille du
    # FICHIER plutôt que la VRAM réelle d'un modèle ne doit pas pouvoir gonfler le budget.
    liberee = min(liberee, occupe)
    plafond = profil.vram_totale_octets - (occupe - liberee)
    disponible = min(plafond, profil.vram_libre_octets + liberee)
    return max(0, disponible - RESERVE_BUREAU_OCTETS), ejections


def flash_attention_active(
    profil: ProfilMachine,
    preferences: PreferencesUtilisateur,
    moteur: Moteur,
) -> ValeurJustifiee[bool]:
    """Flash attention : demandée par l'utilisateur, autorisée par la capacité de calcul du GPU.

    Les noyaux flash attention de ggml exigent au minimum une capacité 7.5 (Turing). En dessous, la
    matrice de scores est matérialisée et le budget doit la provisionner.
    """
    if moteur is not Moteur.LLAMA_CPP:
        return ValeurJustifiee[bool](
            valeur=True,
            justification="vLLM utilise ses propres noyaux d'attention, le réglage ne s'applique pas.",
        )
    if not preferences.flash_attention:
        return ValeurJustifiee[bool](valeur=False, justification="Désactivée par préférence utilisateur.")
    capacite = profil.capacite_calcul
    if capacite is not None and capacite < (7, 5):
        return ValeurJustifiee[bool](
            valeur=False,
            justification=f"Capacité de calcul {capacite[0]}.{capacite[1]} inférieure à 7.5 : noyaux indisponibles.",
            plafonnee=True,
            valeur_demandee=True,
        )
    return ValeurJustifiee[bool](
        valeur=True,
        justification="Évite de matérialiser la matrice de scores : le contexte long cesse de dominer les tampons.",
    )
