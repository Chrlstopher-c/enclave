/*
 * Contrats des commandes du chat (`/compact`, `/clear`), transcrits du backend.
 *
 * Même règle que `api/contrats.ts` : un champ optionnel côté pydantic arrive à `null`, jamais
 * absent. Séparés de ce fichier parce que la commande est un domaine à part entière (saisie,
 * progression, effacement), et parce que `api/contrats.ts` touche sa limite de taille.
 */

/** Entrée de `GET /chat/commandes` : de quoi remplir la palette, rien de plus. */
export interface DefinitionCommande {
  nom: string;
  usage: string;
  description: string;
  /** Vrai si la commande accepte un texte après son nom (`/compact garde les endpoints`). */
  arguments: boolean;
}

/** Corps de `POST /chat/conversations/{id}/commandes`. */
export interface DemandeCommande {
  nom: string;
  arguments: string;
}

/** Un `/clear` : l'ancre est le dernier message masqué, le contexte repart juste après lui. */
export interface InfoEffacement {
  id: string;
  ancre_message_id: string;
  cree_le: string;
}

/** Réponse du POST : `effacement` n'existe que pour `/clear` (200), pas pour `/compact` (202). */
export interface ReponseCommande {
  commande_id: string;
  nom: string;
  effacement?: InfoEffacement;
}

export type CleEtapeCompaction = 'preparation' | 'resume' | 'enregistrement';
export type EtatEtape = 'fait' | 'en_cours' | 'a_faire';
export type Resumeur = 'claude-haiku' | 'local';

export interface EtapeCommande {
  cle: CleEtapeCompaction;
  libelle: string;
  etat: EtatEtape;
}

export interface MoteurCommande {
  etat: 'pret' | 'en_cours' | 'inactif' | 'erreur';
  modele: string;
}

/** Dernier état connu d'une commande longue — un ÉTAT rejoué au raccrochage, pas un historique. */
export interface EtatCommande {
  id: string;
  nom: string;
  etat: 'en_cours' | 'termine' | 'echec';
  etape: CleEtapeCompaction;
  etapes: EtapeCommande[];
  detail: string;
  resumeur: Resumeur | null;
  /** Jetons ÉCRITS par le résumeur ; `null` avec le relais Haiku, qui ne diffuse pas. */
  tokens: number | null;
  tokens_par_seconde: number | null;
  moteur: MoteurCommande | null;
  debut: string;
  duree_ms: number;
  erreur: string | null;
}

export interface EvenementCommande {
  type: 'commande';
  commande: EtatCommande;
}

/** Compaction menée PENDANT une génération (`activite.compaction`), mêmes sens qu'au-dessus. */
export interface CompactionEnDirect {
  etape: CleEtapeCompaction;
  detail: string;
  resumeur: Resumeur | null;
  tokens: number | null;
  tokens_par_seconde: number | null;
  duree_ms: number;
}
