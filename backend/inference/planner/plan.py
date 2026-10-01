"""Sortie du planificateur : le plan de chargement et ses justifications.

Un plan n'est pas un sac de paramètres : **chaque valeur porte la raison qui l'a produite**, en
français, lisible telle quelle par l'utilisateur. C'est la valeur que l'interface affiche — elle ne
recalcule jamais rien, elle rend ce plan.

Le plan est immuable. Dégrader ne modifie pas un plan : on en produit un nouveau, comparable à
l'ancien via `est_plus_conservateur_que`. C'est ce garde-fou qui rend structurellement impossible
l'escalade de la v1 (contexte 55k → 131k après échec).
"""

from __future__ import annotations

from typing import Generic, TypeVar

from pydantic import BaseModel, ConfigDict, Field

from backend.inference.planner.entrees import Moteur, TypeCacheKV

T = TypeVar("T")

# Coût mémoire d'un élément de cache KV, en octets. Ce ne sont pas des valeurs choisies : ce sont
# les formats de bloc GGML. Un bloc q8_0 encode 32 valeurs sur 32 octets + 1 échelle f16 = 34 o ;
# un bloc q4_0 encode 32 valeurs sur 16 octets + 1 échelle f16 = 18 o.
#
# Aucune entrée pour des types plus compressés : `TypeCacheKV` n'en expose pas, et pour cause —
# `q2_0` tue le processus au chargement (voir son docstring). Une table qui les chiffrerait ferait
# croire le planificateur capable de dimensionner un cache que le moteur ne sait pas servir.
OCTETS_PAR_ELEMENT_KV: dict[TypeCacheKV, float] = {
    TypeCacheKV.F16: 2.0,
    TypeCacheKV.Q8_0: 34.0 / 32.0,
    TypeCacheKV.Q4_0: 18.0 / 32.0,
}


class ValeurJustifiee(BaseModel, Generic[T]):
    """Une valeur du plan et la phrase qui l'explique.

    `plafonnee` distingue « la machine a imposé cette valeur » de « l'utilisateur l'a choisie ».
    Cette distinction est ce qui manquait à la v1 : elle rabotait les paramètres sans le dire, et
    l'utilisateur croyait tourner avec ce qu'il avait demandé.
    """

    model_config = ConfigDict(frozen=True)

    valeur: T
    justification: str
    plafonnee: bool = False
    valeur_demandee: T | None = None


class PosteMemoire(BaseModel):
    """Une ligne du budget mémoire : à quoi servent ces octets, et d'où sort le chiffre."""

    model_config = ConfigDict(frozen=True)

    libelle: str
    octets: int = Field(ge=0)
    justification: str


class BudgetMemoire(BaseModel):
    """Décomposition complète de la VRAM engagée par le plan.

    La somme des postes est bornée par `vram_disponible_octets`, qui vaut la VRAM libre mesurée
    **plus** celle que libéreront les éjections exigées par le plan.
    """

    model_config = ConfigDict(frozen=True)

    vram_disponible_octets: int = Field(ge=0)
    postes: tuple[PosteMemoire, ...] = ()
    ram_requise_octets: int = Field(default=0, ge=0)
    ram_disponible_octets: int = Field(default=0, ge=0)

    @property
    def vram_requise_octets(self) -> int:
        return sum(poste.octets for poste in self.postes)

    @property
    def vram_restante_octets(self) -> int:
        return self.vram_disponible_octets - self.vram_requise_octets


class VariableEnvironnement(BaseModel):
    """Variable d'environnement que le lanceur de moteur doit poser, et pourquoi."""

    model_config = ConfigDict(frozen=True)

    nom: str
    valeur: str
    justification: str


class VariableRefusee(BaseModel):
    """Variable délibérément NON posée. Une absence décidée vaut d'être affichée comme un réglage.

    Cas de référence : `GGML_CUDA_ENABLE_UNIFIED_MEMORY` sous WSL2.
    """

    model_config = ConfigDict(frozen=True)

    nom: str
    raison: str


class EjectionRequise(BaseModel):
    """Modèle à décharger avant d'exécuter ce plan, avec la VRAM que cela rendra."""

    model_config = ConfigDict(frozen=True)

    identifiant: str
    moteur: Moteur
    vram_liberee_octets: int = Field(ge=0)
    raison: str


class PlanDeChargement(BaseModel):
    """Réponse complète à « comment charger ce modèle sur cette machine, maintenant ? »."""

    model_config = ConfigDict(frozen=True)

    identifiant_modele: str
    niveau_degradation: int = Field(default=0, ge=0)

    moteur: ValeurJustifiee[Moteur]
    couches_gpu: ValeurJustifiee[int]
    couches_totales: int = Field(gt=0)

    # Second axe de placement, indispensable sur un MoE : les blocs dont les tenseurs d'experts sont
    # rappelés en mémoire hôte alors que la couche, elle, reste sur le GPU. Quand il est renseigné,
    # `couches_gpu` cesse de décrire seul le placement — il vaut le nombre total de blocs et c'est
    # cette liste qui porte la dégradation. `None` = axe sans objet (modèle dense, vLLM, stratégie
    # écartée) ; tuple vide = MoE dont tous les groupes d'experts tiennent en VRAM.
    experts_deportes: ValeurJustifiee[tuple[int, ...]] | None = None

    contexte: ValeurJustifiee[int]
    batch: ValeurJustifiee[int]
    type_cache_kv: ValeurJustifiee[TypeCacheKV]
    flash_attention: ValeurJustifiee[bool]

    # Renseigné pour vLLM uniquement : ce moteur ne raisonne pas en couches mais en fraction de
    # VRAM préallouée. Calculé à partir du besoin réel, jamais par paliers successifs.
    utilisation_memoire_gpu: ValeurJustifiee[float] | None = None

    variables_environnement: tuple[VariableEnvironnement, ...] = ()
    variables_refusees: tuple[VariableRefusee, ...] = ()
    ejections_requises: tuple[EjectionRequise, ...] = ()
    budget: BudgetMemoire
    avertissements: tuple[str, ...] = ()

    @property
    def environnement(self) -> dict[str, str]:
        """Environnement prêt à être passé au processus du moteur."""
        return {variable.nom: variable.valeur for variable in self.variables_environnement}

    @property
    def couches_cpu(self) -> int:
        return self.couches_totales - self.couches_gpu.valeur

    @property
    def blocs_experts_gpu(self) -> int:
        """Blocs dont les tenseurs d'experts résident en VRAM — l'axe comparable entre stratégies.

        Sans déport, une couche sur GPU y emporte ses experts : la grandeur vaut alors `couches_gpu`.
        C'est ce qui permet de comparer un plan « toutes couches, 4 groupes d'experts en RAM » à un
        plan « 29 couches sur 40 » sans que le changement d'axe ne passe pour une escalade.
        """
        if self.experts_deportes is None:
            return self.couches_gpu.valeur
        return self.couches_gpu.valeur - len(self.experts_deportes.valeur)

    def justifications(self) -> tuple[str, ...]:
        """Lignes explicatives, dans l'ordre d'affichage attendu par l'interface."""
        champs: tuple[tuple[str, ValeurJustifiee[object]], ...] = (
            ("Moteur", self.moteur),
            ("Couches sur GPU", self.couches_gpu),
            ("Contexte", self.contexte),
            ("Batch", self.batch),
            ("Cache KV", self.type_cache_kv),
            ("Flash attention", self.flash_attention),
        )
        lignes = [f"{libelle} : {valeur.valeur} — {valeur.justification}" for libelle, valeur in champs]
        if self.experts_deportes is not None:
            lignes.insert(
                2,
                f"Experts en mémoire hôte : {len(self.experts_deportes.valeur)} groupes "
                f"— {self.experts_deportes.justification}",
            )
        for variable in self.variables_environnement:
            lignes.append(f"{variable.nom}={variable.valeur} — {variable.justification}")
        for refusee in self.variables_refusees:
            lignes.append(f"{refusee.nom} : non posée — {refusee.raison}")
        return tuple(lignes)

    def _criteres_conservatisme(self) -> tuple[int, int, int, int, float, float]:
        """Grandeurs comparables entre deux plans. Toutes « plus petit = plus conservateur »."""
        return (
            self.couches_gpu.valeur,
            self.blocs_experts_gpu,
            self.contexte.valeur,
            self.batch.valeur,
            OCTETS_PAR_ELEMENT_KV[self.type_cache_kv.valeur],
            self.utilisation_memoire_gpu.valeur if self.utilisation_memoire_gpu else 0.0,
        )

    def est_plus_conservateur_que(self, autre: PlanDeChargement) -> bool:
        """Vrai si ce plan demande strictement moins de ressources que `autre`, sur tous les axes.

        « Strictement » au sens : aucun critère ne remonte, au moins un descend. Un plan qui
        échangerait moins de couches contre plus de contexte serait refusé — c'est exactement le
        genre de compensation qui a produit l'escalade de la v1.
        """
        miens = self._criteres_conservatisme()
        siens = autre._criteres_conservatisme()
        return all(m <= s for m, s in zip(miens, siens)) and any(m < s for m, s in zip(miens, siens))
