/*
 * Miroir TypeScript de `backend/chat/modeles.py`.
 *
 * `tokens_generes` et `tokens_par_seconde` valent `null` quand le moteur ne les rapporte pas :
 * l'interface affiche alors « non mesuré », jamais une estimation. `historique_max_messages`
 * compte des MESSAGES, jamais des tokens — la v1 tronquait sur « 4 caractères = 1 token ».
 */

export type RoleMessage = 'system' | 'user' | 'assistant';

/** Plafond de `max_tokens` côté backend ; il borne aussi la boucle de diffusion. */
export const MAX_TOKENS_PLAFOND = 262_144;

export interface ParametresEchantillonnage {
  readonly temperature: number;
  readonly top_p: number;
  readonly top_k: number;
  readonly min_p: number;
  readonly penalite_repetition: number;
  readonly penalite_presence: number;
  readonly max_tokens: number;
  readonly sequences_arret: readonly string[];
  readonly graine: number | null;
}

export interface ReglagesConversation {
  readonly prompt_systeme: string;
  readonly parametres: ParametresEchantillonnage;
  readonly historique_max_messages: number | null;
}

export interface MessageChat {
  readonly id: string;
  readonly conversation_id: string;
  readonly role: RoleMessage;
  readonly contenu: string;
  readonly tokens_generes: number | null;
  readonly tokens_par_seconde: number | null;
  readonly cree_le: string;
  readonly modele_id: string | null;
  readonly interrompu: boolean;
}

export interface ResumeConversation {
  readonly id: string;
  readonly titre: string;
  readonly modele_id: string | null;
  readonly cree_le: string;
  readonly maj_le: string;
  readonly archivee: boolean;
  readonly nb_messages: number;
}

export interface ConversationDetaillee {
  readonly conversation: ResumeConversation;
  readonly reglages: ReglagesConversation;
  readonly messages: readonly MessageChat[];
}

export interface CreationConversation {
  readonly titre?: string;
  readonly modele_id?: string | null;
  readonly reglages?: Partial<ReglagesConversation>;
}

/** Patch partiel : seuls les champs fournis sont écrits. */
export interface MajConversation {
  readonly titre?: string;
  readonly modele_id?: string | null;
  readonly archivee?: boolean;
}

/** Patch partiel des réglages, fusionné avec l'existant côté backend. */
export interface MajReglages {
  readonly prompt_systeme?: string;
  readonly parametres?: ParametresEchantillonnage;
  readonly historique_max_messages?: number | null;
}

/** `parametres` et `modele_id` surchargent les réglages de la conversation sans les écraser. */
export interface DemandeGeneration {
  readonly contenu: string;
  readonly modele_id?: string | null;
  readonly parametres?: ParametresEchantillonnage | null;
}

export interface EvenementDebut {
  readonly type: 'debut';
  readonly conversation_id: string;
  /** Identifiant du message assistant à venir : l'interface peut l'afficher avant le premier token. */
  readonly message_id: string;
  readonly modele_id: string | null;
}

export interface EvenementFragment {
  readonly type: 'fragment';
  readonly texte: string;
}

export interface EvenementFin {
  readonly type: 'fin';
  readonly message_id: string;
  readonly tokens_generes: number | null;
  readonly tokens_par_seconde: number | null;
  readonly duree_ms: number;
  readonly interrompu: boolean;
}

export interface EvenementErreurChat {
  readonly type: 'erreur';
  readonly code: string;
  readonly message: string;
  readonly remediation: string;
}

export type EvenementFlux = EvenementDebut | EvenementFragment | EvenementFin | EvenementErreurChat;
