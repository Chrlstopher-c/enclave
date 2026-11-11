/*
 * Lecture PURE de la progression d'une commande ou d'une compaction en direct : libellés, durées,
 * étapes. Aucune valeur n'est inventée — le temps écoulé est la durée MESURÉE par le serveur plus
 * le temps passé depuis sa réception, et une étape n'avance que si le serveur l'a dit.
 */

import type { Tone } from '../../shared/design';
import type { ActiviteMoteur } from '../api/contrats';
import type { CleEtapeCompaction, EtapeCommande, EtatCommande, MoteurCommande, Resumeur } from './contrats';

/* Sans nouvelle du serveur au-delà, on le DIT : il bat au moins chaque seconde pendant le résumé. */
export const SILENCE_MS = 4000;

export const ETAPES_COMPACTION: readonly { cle: CleEtapeCompaction; libelle: string }[] = [
  { cle: 'preparation', libelle: 'Préparation' },
  { cle: 'resume', libelle: 'Résumé' },
  { cle: 'enregistrement', libelle: 'Enregistrement' },
];

const NOMBRE = new Intl.NumberFormat('fr-FR');

export function formaterDuree(ms: number): string {
  const secondes = Math.max(0, Math.floor(ms / 1000));
  if (secondes < 60) {
    return `${secondes} s`;
  }
  const minutes = Math.floor(secondes / 60);
  if (minutes < 60) {
    return `${minutes} min ${String(secondes % 60).padStart(2, '0')} s`;
  }
  return `${Math.floor(minutes / 60)} h ${String(minutes % 60).padStart(2, '0')} min`;
}

/** Durée mesurée par le serveur, prolongée du temps écoulé depuis sa réception tant que ça tourne. */
export function dureeEcoulee(dureeMs: number, recueMs: number, maintenant: number, enCours: boolean): number {
  return enCours ? dureeMs + Math.max(0, maintenant - recueMs) : dureeMs;
}

export function libelleResumeur(resumeur: Resumeur | null): string | null {
  if (resumeur === 'claude-haiku') {
    return 'Claude Haiku';
  }
  return resumeur === 'local' ? 'modèle local' : null;
}

export function jetonsEcrits(tokens: number | null): string | null {
  return tokens !== null && tokens > 0 ? `${NOMBRE.format(tokens)} jetons écrits` : null;
}

export function debit(tokensParSeconde: number | null): string | null {
  return tokensParSeconde !== null && tokensParSeconde > 0
    ? `${tokensParSeconde.toFixed(1).replace('.', ',')} tok/s`
    : null;
}

const MOTEUR: Record<MoteurCommande['etat'], { libelle: string; tone: Tone }> = {
  pret: { libelle: 'Moteur prêt', tone: 'ok' },
  en_cours: { libelle: 'Moteur en chargement', tone: 'accent' },
  inactif: { libelle: 'Aucun modèle chargé', tone: 'neutral' },
  erreur: { libelle: 'Moteur en erreur', tone: 'critical' },
};

export function etatMoteur(moteur: MoteurCommande): { libelle: string; tone: Tone } {
  return MOTEUR[moteur.etat];
}

/** Étapes d'une compaction qui n'envoie que sa clé courante (`activite.compaction.etape`). */
export function etapesDepuisCle(cle: CleEtapeCompaction): EtapeCommande[] {
  const position = ETAPES_COMPACTION.findIndex((etape) => etape.cle === cle);
  return ETAPES_COMPACTION.map((etape, index) => ({
    ...etape,
    etat: index < position ? 'fait' : index === position ? 'en_cours' : 'a_faire',
  }));
}

/** État affiché entre le 202 et le premier événement : la vérité serveur le remplace aussitôt. */
export function commandeOptimiste(id: string, nom: string, maintenant: Date): EtatCommande {
  return {
    id, nom, etat: 'en_cours', etape: 'preparation', etapes: etapesDepuisCle('preparation'),
    detail: '', resumeur: null, tokens: null, tokens_par_seconde: null, moteur: null,
    debut: maintenant.toISOString(), duree_ms: 0, erreur: null,
  };
}

export const NOMS_COMMANDES: Record<string, string> = {
  compact: 'Compaction du contexte',
  clear: 'Effacement du contexte',
};

export function titreCommande(commande: EtatCommande): string {
  const nom = NOMS_COMMANDES[commande.nom] ?? `/${commande.nom}`;
  if (commande.etat === 'echec') {
    return `${nom} : échec`;
  }
  return commande.etat === 'termine' ? `${nom} : terminée` : nom;
}

/* ------------------------------------------------------------- activité pendant une génération */

export type Mesure = 'debit' | 'lecture' | 'compaction' | 'silence';

export interface RepereActivite {
  libelle: string;
  tone: Tone;
  mesure: Mesure;
  /** Le compteur de jetons ÉCRITS n'a de sens que quand le moteur écrit. */
  montrerJetons: boolean;
  /** Une ligne d'outil pendant une relecture ou une compaction se lirait « exécute » : contradiction. */
  montrerOutil: boolean;
}

const PHASES: Record<ActiviteMoteur['phase'], { libelle: string; tone: Tone }> = {
  reflexion: { libelle: 'Réflexion', tone: 'neutral' },
  texte: { libelle: 'Rédaction', tone: 'accent' },
  outil: { libelle: 'Écrit un appel', tone: 'accent' },
  execution: { libelle: 'Exécute', tone: 'caution' },
  lecture: { libelle: 'Relit le contexte', tone: 'neutral' },
  compaction: { libelle: 'Compacte le contexte', tone: 'accent' },
};

/*
 * Une compaction annoncée (`activite.compaction`) l'emporte sur la phase : le serveur peut la
 * publier sans changer la phase, et l'écran ne doit pas afficher « Exécute » pendant un résumé.
 */
export function repereActivite(activite: ActiviteMoteur, silencieux: boolean): RepereActivite {
  const phase = activite.compaction != null ? 'compaction' : activite.phase;
  const calme = phase === 'lecture' || phase === 'compaction';
  if (silencieux && phase !== 'execution' && phase !== 'lecture') {
    return { libelle: 'Aucune nouvelle du moteur', tone: 'caution', mesure: 'silence', montrerJetons: false,
      montrerOutil: !calme };
  }
  const mesure: Mesure = phase === 'lecture' || phase === 'compaction' ? phase : 'debit';
  return { ...PHASES[phase], mesure, montrerJetons: !calme && activite.tokens > 0, montrerOutil: !calme };
}
