/*
 * Miroir TypeScript de `backend/inference/engines_adapters/` — pilotage des moteurs.
 *
 * `CauseEchecMoteur` est le vocabulaire des adaptateurs, distinct de celui du planificateur : la
 * v1 remontait « Failed to load model from file » pour tout, ce qui accusait le fichier alors que
 * la cause était ailleurs. Une cause nommée est ce qui permet de dégrader dans la bonne direction.
 */

import type { Moteur } from './types-plan';

export type EtatChargement = 'inactif' | 'en_cours' | 'pret' | 'echoue';

export type CauseEchecMoteur =
  | 'vram_insuffisante'
  | 'vram_non_liberee'
  | 'ram_insuffisante'
  | 'contexte_trop_grand'
  | 'architecture_inconnue'
  | 'quantification_incompatible'
  | 'fichier_illisible'
  | 'moteur_absent'
  | 'moteur_sans_cuda'
  | 'plan_incomplet'
  | 'delai_depasse'
  | 'annule'
  | 'indeterminee';

export type NiveauEntreeJournal = 'info' | 'avertissement' | 'erreur';


/** Moteurs que le superviseur peut servir : ceux du planificateur, plus Strata (hôte, hors plan). */
export type MoteurServi = Moteur | 'strata';
/** Plan tel que l'adaptateur l'a reçu. Aucun champ n'y est recalculé par le moteur. */
export interface PlanChargementApplique {
  readonly moteur: MoteurServi;
  readonly chemin_modele: string;
  readonly identifiant_modele: string;
  /** `-1` = toutes les couches sur GPU (convention llama.cpp). */
  readonly couches_gpu: number;
  readonly contexte: number;
  readonly batch: number;
  readonly type_kv_cache: string | null;
  readonly flash_attention: boolean | null;
  readonly fraction_vram: number | null;
  readonly mode_eager: boolean;
  readonly variables_env: Readonly<Record<string, string>>;
  /** Lignes produites par le planificateur, transportées telles quelles : affichées, jamais relues. */
  readonly justifications: readonly string[];
}

/** Ce que le moteur sert réellement, et ce que le chargement a coûté. */
export interface EtatMoteurCharge {
  readonly moteur: MoteurServi;
  readonly modele: string;
  readonly pret: boolean;
  readonly contexte: number;
  readonly couches_gpu: number;
  readonly port: number | null;
  readonly duree_chargement_s: number;
  readonly vram_avant_octets: number | null;
  readonly vram_apres_octets: number | null;
  readonly details: Readonly<Record<string, unknown>>;
}

/** État courant du superviseur. Un seul modèle à la fois : le GPU est exclusif sur 16 Go. */
export interface StatutInference {
  readonly etat: EtatChargement;
  readonly moteur: MoteurServi | null;
  readonly modele: string | null;
  readonly plan: PlanChargementApplique | null;
  readonly etat_moteur: EtatMoteurCharge | null;
  readonly cause: CauseEchecMoteur | null;
  readonly message: string;
  readonly remediation: string;
  readonly session_journal: string | null;
  readonly depuis: string;
}

export interface EntreeJournal {
  readonly horodatage: string;
  readonly phase: string;
  readonly niveau: NiveauEntreeJournal;
  readonly message: string;
  readonly details: Readonly<Record<string, unknown>>;
}

/** Une tentative de chargement : plan appliqué, déroulé, issue. */
export interface SessionChargement {
  readonly identifiant: string;
  readonly debut: string;
  readonly fin: string | null;
  readonly duree_s: number | null;
  readonly moteur: string;
  readonly modele: string;
  readonly plan: Readonly<Record<string, unknown>>;
  readonly etat: EtatChargement;
  readonly cause: CauseEchecMoteur | null;
  readonly message: string;
  readonly remediation: string;
  readonly entrees: readonly EntreeJournal[];
}

/**
 * Postes de la fenêtre de contexte. `libre` est un poste à part entière, pas un reste implicite :
 * l'espace restant se lit et se chiffre comme les autres.
 */
export type PosteContexte = 'systeme' | 'utilisateur' | 'images' | 'assistant' | 'raisonnement' | 'libre';

/** Un poste chiffré par le tokenizer du modèle chargé. */
export interface PartContexte {
  readonly poste: PosteContexte;
  readonly tokens: number;
  /** Fraction du contexte total, 0 à 1. Calculée par le backend — jamais recomposée à l'affichage. */
  readonly part: number;
  /** Nombre de fragments cumulés dans ce poste (messages, blocs de raisonnement). */
  readonly segments: number;
}

/**
 * Ce que la conversation occupe dans la fenêtre du modèle chargé.
 *
 * `mesurable: false` n'est pas une erreur : sans modèle chargé il n'existe aucun tokenizer, donc
 * aucune mesure. Les champs chiffrés restent alors `null` et l'interface doit le dire — afficher
 * une barre vide laisserait croire à une fenêtre entièrement libre.
 */
export interface OccupationContexte {
  readonly mesurable: boolean;
  readonly raison: string;
  readonly moteur: MoteurServi | null;
  readonly modele: string | null;
  /** Contexte RÉELLEMENT servi, lu sur le moteur — pas le contexte natif du modèle. */
  readonly contexte_total: number | null;
  /** Contexte demandé par le plan. Un écart avec `contexte_total` est signalé, jamais masqué. */
  readonly contexte_plan: number | null;
  readonly tokens_mesures: number | null;
  readonly tokens_libres: number | null;
  /** Tokens au-delà de la fenêtre : la conversation n'y tient plus. */
  readonly depassement_tokens: number | null;
  readonly postes: readonly PartContexte[];
  /** Ce que le décompte ne couvre pas, dit explicitement plutôt que comblé par une estimation. */
  readonly avertissements: readonly string[];
}

/** Sonde à l'instant t : un moteur mort n'apparaît pas dans l'état mémorisé. */
export interface SanteInference {
  readonly disponible: boolean;
  readonly moteur: MoteurServi | null;
  readonly modele: string | null;
  readonly latence_ms: number | null;
  readonly detail: string;
}

export interface MessageMoteur {
  readonly role: 'system' | 'user' | 'assistant';
  readonly content: string;
}

export interface OptionsGenerationMoteur {
  readonly temperature?: number;
  readonly top_p?: number;
  readonly top_k?: number | null;
  readonly repetition_penalty?: number | null;
  readonly max_tokens?: number | null;
  readonly stop?: readonly string[];
  readonly graine?: number | null;
}

/** Unité du flux direct au moteur. `fin` clôt tout flux qui n'a pas levé d'exception. */
export interface MorceauGeneration {
  readonly type: 'token' | 'fin' | 'erreur';
  readonly contenu: string;
  readonly raison_arret: string | null;
  readonly details: Readonly<Record<string, unknown>>;
}

/**
 * Événement d'erreur émis DANS le flux : le statut HTTP est déjà parti quand la génération
 * commence, c'est la seule façon d'informer le client sans le laisser attendre une fin qui ne
 * viendra pas.
 */
export interface ErreurDansFlux {
  readonly type: 'erreur';
  readonly code?: string;
  readonly message: string;
  readonly remediation?: string;
  readonly details?: Readonly<Record<string, unknown>>;
}

export type EvenementInference = MorceauGeneration | ErreurDansFlux;
