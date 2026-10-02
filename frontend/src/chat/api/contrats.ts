/*
 * Contrats de données servis par le backend, transcrits en TypeScript.
 *
 * Ces types décrivent ce que le backend ENVOIE, ils ne redéfinissent aucune règle : toute valeur
 * du plan arrive accompagnée de sa justification, et l'interface se contente de la rendre.
 * Sources : `backend/chat/modeles.py`, `backend/inference/planner/{entrees,plan}.py`,
 * `backend/inference/engines_adapters/{contrat,journal,superviseur}.py`.
 *
 * Les champs optionnels côté pydantic sont sérialisés à `null`, jamais absents : ils sont donc
 * typés `| null` et non `?`. Les corps de requête, eux, utilisent `?` — un champ omis y a un sens.
 */

/* ------------------------------------------------------------------ planificateur : entrées */

export type Moteur = 'llama.cpp' | 'vllm';
export type FormatModele = 'gguf' | 'safetensors';
export type TypeCacheKV = 'f16' | 'q8_0' | 'q4_0';
export type PlateformePlan = 'linux_natif' | 'wsl2' | 'windows';

/** Métadonnées LUES dans le modèle — jamais déduites de son nom de fichier. */
export interface MetadonneesModele {
  identifiant: string;
  format: FormatModele;
  architecture: string;
  taille_octets: number;
  nombre_couches: number;
  dimension_embedding: number;
  dimension_ffn: number;
  nombre_tetes_attention: number;
  nombre_tetes_kv: number;
  dimension_tete: number | null;
  contexte_entrainement_max: number;
  taille_vocabulaire: number;
  quantification: string | null;
  est_moe: boolean;

  /*
   * Mélange d'experts. Tout ce bloc est facultatif côté contrat, et c'est exactement ce qui le rend
   * dangereux à oublier : sans lui le planificateur ne REFUSE pas, il retombe silencieusement sur la
   * coupe par couches entières — le mauvais axe pour un MoE. Mesuré le 2026-08-26 sur le 35B-A3B :
   * ces champs étaient produits par le backend, envoyés par l'API, et jetés à l'assemblage ; le plan
   * plaçait 3 couches sur 40 en VRAM là où le déport d'experts les garde toutes.
   *
   * Ne jamais transmettre partiellement : `MetadonneesModele._verifier_mesures_par_bloc` refuse une
   * mesure dont la longueur ne fait pas `nombre_couches`, et une mesure tronquée se lirait comme un
   * modèle plus léger qu'il n'est.
   */
  nombre_experts?: number | null;
  nombre_experts_actifs?: number | null;
  dimension_ffn_expert?: number | null;
  dimension_ffn_expert_partage?: number | null;
  octets_par_bloc?: readonly number[];
  octets_experts_par_bloc?: readonly number[];
  octets_hors_blocs?: number | null;
  intervalle_attention_pleine?: number | null;
  /**
   * État récurrent des blocs hybrides. Le backend en tire un poste de VRAM qui valait ZÉRO avant
   * le 2026-08-26 : 60,72 MiB mesurés sur le 35B, et quatre fois plus tant que llama-server
   * ouvrait ses quatre slots. Absentes = architecture non hybride.
   */
  dimension_interne_ssm?: number | null;
  dimension_etat_ssm?: number | null;
  noyau_convolution_ssm?: number | null;
}

export interface ModeleCharge {
  identifiant: string;
  moteur: Moteur;
  vram_octets: number;
}

/** Profil au format attendu par le planificateur (distinct de celui du domaine `system`). */
export interface ProfilMachinePlan {
  plateforme: PlateformePlan;
  index_gpu: number;
  nom_gpu: string;
  vram_totale_octets: number;
  vram_libre_octets: number;
  ram_libre_octets: number;
  moteurs_disponibles: Moteur[];
  modeles_charges: ModeleCharge[];
  capacite_calcul: [number, number] | null;
}

/** Ce que l'utilisateur demande. Rien n'est garanti : tout est plafonné par la machine. */
export interface PreferencesUtilisateur {
  contexte?: number | null;
  batch?: number | null;
  couches_gpu?: number | null;
  type_cache_kv?: TypeCacheKV;
  moteur?: Moteur | null;
  flash_attention?: boolean;
  autoriser_memoire_unifiee?: boolean;
  ratio_fragmentation?: number;
  /** Actifs par défaut dans ggml (llama.cpp) : seule leur désactivation s'exprime. */
  desactiver_cuda_graphs?: boolean;
}

export interface DemandeDeChargement {
  metadonnees: MetadonneesModele;
  profil: ProfilMachinePlan;
  preferences: PreferencesUtilisateur;
}

/* ------------------------------------------------------------------- planificateur : sortie */

/** Une valeur du plan et la phrase qui l'explique. `plafonnee` distingue la machine de l'humain. */
export interface ValeurJustifiee<T> {
  valeur: T;
  justification: string;
  plafonnee: boolean;
  valeur_demandee: T | null;
}

export interface PosteMemoire {
  libelle: string;
  octets: number;
  justification: string;
}

export interface BudgetMemoire {
  vram_disponible_octets: number;
  postes: PosteMemoire[];
  ram_requise_octets: number;
  ram_disponible_octets: number;
}

export interface VariableEnvironnement {
  nom: string;
  valeur: string;
  justification: string;
}

/** Variable délibérément NON posée : une absence décidée vaut d'être affichée comme un réglage. */
export interface VariableRefusee {
  nom: string;
  raison: string;
}

export interface EjectionRequise {
  identifiant: string;
  moteur: Moteur;
  vram_liberee_octets: number;
  raison: string;
}

export interface PlanDeChargement {
  identifiant_modele: string;
  niveau_degradation: number;
  moteur: ValeurJustifiee<Moteur>;
  couches_gpu: ValeurJustifiee<number>;
  couches_totales: number;
  contexte: ValeurJustifiee<number>;
  batch: ValeurJustifiee<number>;
  type_cache_kv: ValeurJustifiee<TypeCacheKV>;
  flash_attention: ValeurJustifiee<boolean>;
  utilisation_memoire_gpu: ValeurJustifiee<number> | null;
  variables_environnement: VariableEnvironnement[];
  variables_refusees: VariableRefusee[];
  ejections_requises: EjectionRequise[];
  budget: BudgetMemoire;
  avertissements: string[];
}

export interface ReponsePlan {
  plan: PlanDeChargement;
  justifications: string[];
  avertissements: string[];
}

/* ------------------------------------------------------------------------ pilotage moteurs */

export type EtatMoteurChargement = 'inactif' | 'en_cours' | 'pret' | 'echoue';

/** Qualification d'un échec. Elle existe parce que la v1 remontait le même message pour tout. */
export type CauseEchec =
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

export interface EtatMoteur {
  moteur: Moteur;
  modele: string;
  pret: boolean;
  contexte: number;
  couches_gpu: number;
  port: number | null;
  duree_chargement_s: number;
  vram_avant_octets: number | null;
  vram_apres_octets: number | null;
}

export interface StatutInference {
  etat: EtatMoteurChargement;
  moteur: Moteur | null;
  modele: string | null;
  cause: CauseEchec | null;
  message: string;
  remediation: string;
  session_journal: string | null;
  depuis: string;
  etat_moteur: EtatMoteur | null;
}

export type NiveauEntree = 'info' | 'avertissement' | 'erreur';

/** Un fait daté du chargement : c'est la seule progression honnête dont dispose l'interface. */
export interface EntreeJournal {
  horodatage: string;
  phase: string;
  niveau: NiveauEntree;
  message: string;
}

export interface SessionChargement {
  identifiant: string;
  debut: string;
  fin: string | null;
  duree_s: number | null;
  moteur: string;
  modele: string;
  etat: EtatMoteurChargement;
  cause: CauseEchec | null;
  message: string;
  remediation: string;
  entrees: EntreeJournal[];
}

/* --------------------------------------------------------------------------- domaine chat */

export type RoleMessage = 'system' | 'user' | 'assistant';

export interface ParametresEchantillonnage {
  temperature: number;
  top_p: number;
  top_k: number;
  min_p: number;
  penalite_repetition: number;
  penalite_presence: number;
  max_tokens: number;
  sequences_arret: string[];
  graine: number | null;
}

export interface ReglagesConversation {
  prompt_systeme: string;
  parametres: ParametresEchantillonnage;
  historique_max_messages: number | null;
}

/**
 * Balise d'une compaction de contexte. CONTRAT STABLE, décodé à l'identique par le web et par le
 * mobile (`echo-centre` / `EchoHubNoyau`) : les noms de champs sont figés. La compaction ne touche
 * jamais l'historique — elle décrit ce que le MOTEUR relit à la place des tours anciens. La balise
 * s'affiche dans le fil JUSTE AVANT le message assistant `message_id`.
 */
export interface InfoCompaction {
  id: string;
  conversation_id: string;
  /** Message assistant au-dessus duquel la balise se rend. */
  message_id: string;
  /** Dernier message d'historique replié dans le résumé ; tout ce qui suit reste envoyé intact. */
  coupe_message_id: string;
  nb_messages_resumes: number;
  tokens_avant: number;
  tokens_apres: number;
  contexte_total: number;
  resume: string;
  cree_le: string;
}

export interface MessageChat {
  id: string;
  conversation_id: string;
  role: RoleMessage;
  contenu: string;
  tokens_generes: number | null;
  tokens_par_seconde: number | null;
  cree_le: string;
  modele_id: string | null;
  interrompu: boolean;
  /**
   * Parent dans l'arbre de la conversation ; `null` désigne une racine. Deux messages partageant un
   * parent sont deux VARIANTES du même tour (rejeu, édition) et aucune n'écrase l'autre : c'est ce
   * qui permet d'éditer sans détruire ce qui s'est réellement passé.
   */
  parent_id: string | null;
  /**
   * Balise de compaction, présente uniquement sur le message assistant dont la génération l'a
   * déclenchée. `null` partout ailleurs. Le fil la rend au-dessus de ce message.
   */
  compaction: InfoCompaction | null;
}

export interface ResumeConversation {
  id: string;
  titre: string;
  modele_id: string | null;
  cree_le: string;
  maj_le: string;
  archivee: boolean;
  nb_messages: number;
}

export interface ConversationDetaillee {
  conversation: ResumeConversation;
  reglages: ReglagesConversation;
  /** CHEMIN ACTIF de l'arbre, pas l'historique complet — identique sur une conversation linéaire. */
  messages: MessageChat[];
  /** Feuille du chemin affiché ; `null` sur une conversation sans aucun message. */
  feuille_active: string | null;
  /** Voir `EtatBranche.variantes`. Vide tant qu'aucune branche n'existe. */
  variantes: Record<string, string[]>;
}

/* ------------------------------------------------------------------------ branches de dialogue */

/**
 * Vue courante d'une conversation : le chemin affiché et les frères de chacun de ses messages.
 *
 * `variantes[id]` liste les identifiants qui partagent le parent de ce message, LUI COMPRIS, dans
 * l'ordre de création. La position affichée se lit `variantes[id].indexOf(id)` et le total
 * `variantes[id].length` : le frontend ne recalcule aucune filiation, il lit ce que le serveur a
 * établi. Une clé absente signifie « message sans variante », pas « inconnu ».
 */
export interface EtatBranche {
  conversation_id: string;
  feuille_active: string | null;
  messages: MessageChat[];
  variantes: Record<string, string[]>;
}

/*
 * `GET /arbre` (arbre complet, branches abandonnées comprises) n'est volontairement pas transcrit :
 * aucun écran ne le consomme encore. Le type suivra la vue qui en aura besoin — un contrat sans
 * appelant se périme sans que personne ne s'en aperçoive.
 */

/** Corps de `POST /branche` : bascule la vue sur la branche qui contient ce message. */
export interface ActivationBranche {
  message_id: string;
}

/** Corps de `POST /messages/{id}/rejouer`. Les deux champs omis reprennent les réglages du fil. */
export interface DemandeRejeu {
  modele_id?: string | null;
  parametres?: ParametresEchantillonnage | null;
}

/** Corps de `POST /messages/{id}/editer` : le nouveau texte ouvre une branche sœur. */
export interface DemandeEdition extends DemandeRejeu {
  contenu: string;
}

export interface MajReglages {
  prompt_systeme?: string;
  parametres?: ParametresEchantillonnage;
  historique_max_messages?: number | null;
}

export interface DemandeGeneration {
  contenu: string;
  modele_id?: string | null;
  parametres?: ParametresEchantillonnage;
  /** Fichiers déjà déposés dans le magasin (voir `FichierConversation`), à lier à ce message. */
  fichier_ids?: string[];
}

/* --------------------------------------------------------------------- domaine fichiers */

export type OrigineFichier = 'utilisateur' | 'modele';

/** Référence à un fichier de conversation — les octets vivent sur le disque, jamais ici. */
export interface FichierConversation {
  id: string;
  conversation_id: string;
  message_id: string | null;
  origine: OrigineFichier;
  nom_affiche: string;
  chemin_relatif: string;
  type_mime: string;
  taille_octets: number;
  empreinte_sha256: string;
  cree_le: string;
}

/* ------------------------------------------------------------------ événements de génération */

export interface EvenementDebut {
  type: 'debut';
  conversation_id: string;
  message_id: string;
  modele_id: string | null;
  /** Nœud sous lequel la réponse en cours s'accroche — `null` si elle ouvre la conversation. */
  parent_id: string | null;
  /**
   * Message utilisateur créé par ce tour : envoi normal et édition en portent un, un rejeu de
   * réponse n'en crée aucun et vaut `null`. Une absence ici n'est pas un manque d'information :
   * c'est le fait qu'aucun message n'a été écrit.
   */
  message_utilisateur_id: string | null;
}

export interface EvenementFragment {
  type: 'fragment';
  texte: string;
}

export interface EvenementFin {
  type: 'fin';
  message_id: string;
  tokens_generes: number | null;
  tokens_par_seconde: number | null;
  duree_ms: number;
  interrompu: boolean;
}

export interface EvenementErreur {
  type: 'erreur';
  code: string;
  message: string;
  remediation: string;
}

/**
 * Compaction déclenchée AVANT la génération de la réponse en cours. `compaction.message_id` est le
 * message assistant à venir (celui d'`EvenementDebut`) : la balise se pose au-dessus de lui, en
 * direct comme au rechargement. Décodé à l'identique par le mobile.
 */
export interface EvenementCompaction {
  type: 'compaction';
  compaction: InfoCompaction;
}

export type EvenementFlux =
  | EvenementDebut
  | EvenementFragment
  | EvenementCompaction
  | EvenementFin
  | EvenementErreur;
