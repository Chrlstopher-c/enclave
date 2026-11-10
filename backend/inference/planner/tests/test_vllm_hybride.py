"""Ornith 9B W4A16 sur une RTX 3060 : le plan vLLM doit tenir ce que vLLM a réellement chargé.

Mesuré le 2026-11-10, bureau occupant ~1,5 Gio : 64K de contexte, cache fp8, graphes CUDA, fraction
0,78, 1,53 Gio de cache KV disponibles, 46 tok/s. Le planificateur proposait 22K en mode eager
(réserve de graphes de ~3 Go, tampons et fragmentation façon llama.cpp).
"""

from __future__ import annotations

from backend.inference.planner import planifier
from backend.inference.planner.entrees import DemandeDeChargement

_MIO = 1024**2
METADONNEES = {'architecture': 'qwen3_5_text',
     'taille_octets': 7841081344,
     'nombre_couches': 32,
     'dimension_embedding': 4096,
     'dimension_ffn': 12288,
     'nombre_tetes_attention': 16,
     'nombre_tetes_kv': 4,
     'dimension_tete': 256,
     'contexte_entrainement_max': 262144,
     'taille_vocabulaire': 248320,
     'quantification': 'auto-round_4bit',
     'intervalle_attention_pleine': 4,
     'dimension_interne_ssm': 4096,
     'dimension_etat_ssm': 128,
     'noyau_convolution_ssm': 4,
     'octets_par_bloc': [113530240, 113530240, 113530240, 108971008, 113530240, 113530240, 113530240, 108971008,
                         113530240, 113530240, 113530240, 108971008, 113530240, 113530240, 113530240, 108971008,
                         113530240, 113530240, 113530240, 108971008, 113530240, 113530240, 113530240, 108971008,
                         113530240, 113530240, 113530240, 108971008, 113530240, 113530240, 113530240, 108971008],
     'octets_hors_blocs': 4244587520,
     'identifiant': 'ornith-9b-w4a16',
     'format': 'safetensors',
     'est_moe': False}


def _plan(contexte: int, type_kv: str = "q8_0", sans_graphes: bool = False):  # noqa: ANN202 - plan pydantic
    return planifier(DemandeDeChargement.model_validate({
        "metadonnees": METADONNEES,
        "profil": {"plateforme": "linux_natif", "index_gpu": 0, "nom_gpu": "RTX 3060",
                   "vram_totale_octets": 12288 * _MIO, "vram_libre_octets": (12288 - 1500) * _MIO,
                   "ram_libre_octets": 26 * 1024**3, "moteurs_disponibles": ["llama.cpp", "vllm"],
                   "modeles_charges": [], "capacite_calcul": [8, 6]},
        "preferences": {"contexte": contexte, "moteur": "vllm", "type_cache_kv": type_kv,
                        "desactiver_cuda_graphs": sans_graphes},
    }))


def test_64k_en_cache_compresse_tient_avec_les_graphes() -> None:
    plan = _plan(65536)
    assert plan.contexte.valeur == 65536 and not plan.mode_eager
    assert plan.utilisation_memoire_gpu is not None and plan.utilisation_memoire_gpu.valeur <= 0.78
    assert any(poste.libelle == "Graphes CUDA" for poste in plan.budget.postes)


def test_graphes_desactives_par_l_utilisateur_donnent_le_mode_eager() -> None:
    plan = _plan(65536, sans_graphes=True)
    assert plan.mode_eager and all(poste.libelle != "Graphes CUDA" for poste in plan.budget.postes)


def test_le_cache_f16_coute_le_double_et_raccourcit_le_contexte() -> None:
    assert _plan(65536, "f16").contexte.valeur < 65536
