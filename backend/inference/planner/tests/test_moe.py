"""Tests du placement d'un mélange d'experts — le défaut mesuré sur Qwen3.6-35B-A3B.

Symptôme d'origine : ~10 Go de VRAM utilisés sur 16 pendant que la RAM déborde, parce que le plan
coupait par couches entières alors que 8 experts sur 256 servent à un token. Deux causes distinctes,
et les deux sont rejouées ici :

1. le cache KV était facturé sur les 40 couches, alors qu'une sur quatre seulement en porte un —
   1,9 Gio de VRAM inventée à 32k, 3,3 Gio à 57k ;
2. le poids d'un bloc était pris pour un tout, alors que sa part dense (18 Mo, lue à chaque token)
   et sa part experts (330 à 364 Mo, lue à 8/256) diffèrent d'un facteur 18.

Comme les autres tests du planificateur, aucun GPU n'est nécessaire : les mesures sont des entrées.
"""

from __future__ import annotations

import pytest

from backend.inference.planner import (
    CauseEchec,
    MetadonneesModele,
    PlanDeChargement,
    PreferencesUtilisateur,
    couches_attention,
    largeur_activation_ffn,
    degrader,
    planifier,
)

from .conftest import GIO, INTERVALLE_ATTENTION_MESURE, demande, profil_5080

# Blocs 0 à 4 mesurés à 364 Mio d'experts contre 330 ensuite : à budget égal, ce sont eux qui
# libèrent le plus de VRAM par bloc touché. Le bloc 0 est conservé, l'index départageant l'égalité.
BLOCS_DEPORTES_ATTENDUS = (1, 2, 3, 4)


def test_moe_sans_feed_forward_length_reste_planifiable(modele_moe: MetadonneesModele) -> None:
    """Défaut bloquant d'origine : `dimension_ffn` exigée rendait ce modèle impossible à planifier.

    L'architecture `qwen35moe` ne déclare pas `{arch}.feed_forward_length`. Le champ vaut donc `None`
    et la largeur d'activation se reconstruit depuis les experts, sans valeur de repli.
    """
    assert modele_moe.dimension_ffn is None

    plan = planifier(demande(modele_moe, preferences=PreferencesUtilisateur(contexte=32768)))

    assert plan.niveau_degradation == 0
    assert plan.budget.vram_requise_octets <= plan.budget.vram_disponible_octets


def test_moe_compte_les_experts_actifs_et_non_un_seul_expert(modele_moe: MetadonneesModele) -> None:
    """Piège de substitution : `expert_feed_forward_length` seule sous-dimensionne le tampon x8."""
    attendu = (
        modele_moe.dimension_ffn_expert * modele_moe.nombre_experts_actifs
        + modele_moe.dimension_ffn_expert_partage
    )

    assert largeur_activation_ffn(modele_moe) == attendu
    assert attendu == 8 * 512 + 512, "8 experts routés simultanément, plus l'expert partagé"


def test_moe_ne_facture_le_cache_kv_que_sur_les_couches_dattention(modele_moe: MetadonneesModele) -> None:
    """Mesure : `full_attention_interval` vaut 4, donc 10 couches sur 40 portent un cache KV."""
    contexte = 32768
    plan = planifier(demande(modele_moe, preferences=PreferencesUtilisateur(contexte=contexte)))

    porteuses = couches_attention(modele_moe, modele_moe.nombre_couches)
    assert porteuses == 10
    # 2 (K et V) x 256 (dimension de clé) x 2 (têtes KV) x 2 octets en f16 = 2048 o/token/couche.
    assert _poste(plan, "Cache KV") == porteuses * contexte * 2048
    assert _poste(plan, "Cache KV") < 0.7 * GIO, "facturé sur 40 couches, ce poste valait 2,5 Gio"


def test_moe_garde_toutes_les_couches_sur_gpu_et_deporte_des_experts(
    modele_moe: MetadonneesModele, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Le plan attendu : 40 blocs sur GPU, seuls des groupes d'experts rappelés en mémoire hôte.

    Sans réserve de bureau : les blocs attendus ont été mesurés sur le budget brut de la carte.
    """
    monkeypatch.setattr("backend.inference.planner.moteur.RESERVE_BUREAU_OCTETS", 0)
    plan = planifier(demande(modele_moe, preferences=PreferencesUtilisateur(contexte=32768)))

    assert plan.couches_gpu.valeur == plan.couches_totales
    assert plan.couches_cpu == 0, "aucune couche d'attention ni de dense ne doit quitter le GPU"
    assert plan.experts_deportes is not None
    assert plan.experts_deportes.valeur == BLOCS_DEPORTES_ATTENDUS
    assert plan.blocs_experts_gpu == 36
    assert plan.budget.vram_requise_octets <= plan.budget.vram_disponible_octets
    assert plan.budget.ram_requise_octets <= plan.budget.ram_disponible_octets


def test_moe_deporte_les_groupes_dexperts_les_plus_lourds(modele_moe: MetadonneesModele) -> None:
    """Le ratio trafic/VRAM libérée étant identique partout, les plus gros minimisent le nombre de blocs."""
    plan = planifier(demande(modele_moe, preferences=PreferencesUtilisateur(contexte=32768)))
    assert plan.experts_deportes is not None

    poids = modele_moe.octets_experts_par_bloc
    deportes = plan.experts_deportes.valeur
    residents = [index for index in range(modele_moe.nombre_couches) if index not in deportes]
    assert min(poids[index] for index in deportes) >= max(poids[index] for index in residents)
    assert plan.budget.ram_requise_octets == sum(poids[index] for index in deportes)


def test_moe_separe_le_poids_dense_du_poids_des_experts(modele_moe: MetadonneesModele) -> None:
    """Les deux parts sont chiffrées à part : c'est leur confusion qui produisait la coupe par couches."""
    plan = planifier(demande(modele_moe, preferences=PreferencesUtilisateur(contexte=32768)))

    dense = _poste(plan, "Poids dense des blocs sur GPU")
    experts = _poste(plan, "Poids des experts sur GPU")
    assert dense < 1 * GIO, "0,721 Gio mesurés pour les 40 blocs, hors experts"
    assert experts > 10 * dense, "les experts pèsent 90,9 % du fichier"
    assert _poste(plan, "Tenseurs hors blocs") > 0


def test_moe_justifie_le_deport_dans_le_plan(modele_moe: MetadonneesModele) -> None:
    """Une décision de placement non justifiée est invisible pour l'utilisateur : elle doit s'afficher."""
    plan = planifier(demande(modele_moe, preferences=PreferencesUtilisateur(contexte=32768)))

    lignes = plan.justifications()
    deport = [ligne for ligne in lignes if "mémoire hôte" in ligne]
    assert deport, "le déport d'experts doit apparaître dans les justifications affichées"
    assert "experts" in deport[0]
    assert any("blocs restent sur le GPU" in ligne for ligne in lignes)


def test_moe_sans_mesure_dexperts_retombe_sur_la_coupe_par_couches(
    modele_moe_sans_mesure: MetadonneesModele,
) -> None:
    """Sans poids d'experts relevé, aucun déport ne se décide : on ne répartit pas à l'estime."""
    plan = planifier(demande(modele_moe_sans_mesure, preferences=PreferencesUtilisateur(contexte=32768)))

    assert plan.experts_deportes is None
    assert plan.couches_gpu.valeur < plan.couches_totales
    assert plan.budget.vram_requise_octets <= plan.budget.vram_disponible_octets


def test_moe_degradation_ne_remet_jamais_dexperts_en_vram(modele_moe: MetadonneesModele) -> None:
    """Verrou anti-escalade sur le second axe : compresser le cache libère de la VRAM, pas des experts."""
    entree = demande(modele_moe, preferences=PreferencesUtilisateur(contexte=32768))
    plan = planifier(entree)
    precedents = [plan]

    for _ in range(8):
        try:
            plan = degrader(entree, plan, CauseEchec.MEMOIRE_GPU_INSUFFISANTE)
        except Exception:  # noqa: BLE001 - fin d'échelle, testée ailleurs
            break
        dernier = precedents[-1]
        assert plan.blocs_experts_gpu <= dernier.blocs_experts_gpu
        assert plan.couches_gpu.valeur <= dernier.couches_gpu.valeur
        assert plan.est_plus_conservateur_que(dernier) is True
        precedents.append(plan)

    assert len(precedents) > 1, "au moins une dégradation doit être possible depuis le plan nominal"


def test_moe_moteur_incapable_de_deporter_bascule_sur_la_coupe_par_couches(
    modele_moe: MetadonneesModele,
) -> None:
    """Le moteur a refusé le déport : la stratégie est abandonnée, pas redimensionnée.

    C'est la seule cause qui disqualifie l'axe de placement lui-même. Le plan suivant coupe par
    couches, et reste strictement plus conservateur — sinon un modèle deviendrait inchargeable.
    """
    entree = demande(modele_moe, preferences=PreferencesUtilisateur(contexte=32768))
    initial = planifier(entree)
    assert initial.experts_deportes is not None

    suivant = degrader(entree, initial, CauseEchec.DEPORT_EXPERTS_INDISPONIBLE)

    assert suivant.experts_deportes is None
    assert suivant.couches_gpu.valeur < suivant.couches_totales
    assert suivant.est_plus_conservateur_que(initial) is True
    assert suivant.budget.ram_requise_octets <= suivant.budget.ram_disponible_octets


def test_moe_preference_de_couches_plus_basse_ecarte_le_deport(modele_moe: MetadonneesModele) -> None:
    """Demander explicitement moins de couches reste un droit : le déport ne passe pas outre."""
    preferences = PreferencesUtilisateur(contexte=32768, couches_gpu=20)
    plan = planifier(demande(modele_moe, preferences=preferences))

    assert plan.experts_deportes is None
    assert plan.couches_gpu.valeur == 20


def test_moe_signale_letat_recurrent_non_provisionne(modele_moe: MetadonneesModele) -> None:
    """Ce qui n'est pas mesuré ne s'invente pas — mais son absence se dit dans le plan."""
    plan = planifier(demande(modele_moe, preferences=PreferencesUtilisateur(contexte=32768)))

    assert any("ssm" in avertissement for avertissement in plan.avertissements)
    assert any(str(INTERVALLE_ATTENTION_MESURE) in a for a in plan.avertissements)


def test_moe_contexte_long_deporte_davantage_dexperts(modele_moe: MetadonneesModele) -> None:
    """Le contexte se paie en groupes d'experts déportés, pas en couches d'attention sacrifiées."""
    court = planifier(demande(modele_moe, preferences=PreferencesUtilisateur(contexte=8192)))
    long = planifier(demande(modele_moe, preferences=PreferencesUtilisateur(contexte=57344)))

    assert court.experts_deportes is not None and long.experts_deportes is not None
    assert len(long.experts_deportes.valeur) > len(court.experts_deportes.valeur)
    assert long.couches_gpu.valeur == court.couches_gpu.valeur == long.couches_totales


def test_moe_vram_reduite_deporte_plus_sans_sacrifier_dattention(modele_moe: MetadonneesModele) -> None:
    """Sur une carte deux fois plus courte, c'est le nombre de groupes déportés qui absorbe le manque.

    C'est le gain de granularité recherché : 330 Mio par groupe d'experts au lieu de 368 Mio par
    couche entière, et surtout sans jamais renvoyer au CPU une couche d'attention ou du dense.
    """
    entree = demande(
        modele_moe,
        profil_5080(vram_libre_gio=8.0, ram_libre_gio=24.0),
        PreferencesUtilisateur(contexte=32768),
    )
    plan = planifier(entree)
    reference = planifier(demande(modele_moe, preferences=PreferencesUtilisateur(contexte=32768)))

    assert plan.budget.vram_requise_octets <= plan.budget.vram_disponible_octets
    assert plan.budget.ram_requise_octets <= plan.budget.ram_disponible_octets
    assert plan.couches_gpu.valeur == plan.couches_totales
    assert plan.experts_deportes is not None and reference.experts_deportes is not None
    assert len(plan.experts_deportes.valeur) > len(reference.experts_deportes.valeur)


def _poste(plan: PlanDeChargement, libelle: str) -> int:
    """Octets d'un poste du budget, par son libellé."""
    return next(poste.octets for poste in plan.budget.postes if poste.libelle == libelle)
