/*
 * Lecture du flux SSE de génération.
 *
 * `fetch` + `ReadableStream` plutôt que `EventSource` pour deux raisons : `EventSource` ne sait pas
 * émettre un POST (le corps porte le message et les paramètres), et il ne s'annule pas proprement —
 * or l'annulation en cours de génération est une exigence de l'écran.
 *
 * Le backend émet à la fois `event:` et un champ `type` dans la charge JSON ; on parse le JSON, ce
 * qui rend la lecture indépendante du nom d'événement.
 */

import type { DemandeEdition, DemandeGeneration, DemandeRejeu, EvenementFlux } from './contrats';
import { ErreurApi, lireErreur } from './client';
import { journal } from './journal';

/*
 * Borne dure du nombre de lectures du flux. Le backend plafonne `max_tokens` à 262 144 et émet un
 * fragment par token : au-delà d'un million de lectures, le flux ne se comporte plus comme un flux
 * de génération et on préfère rompre plutôt que boucler indéfiniment.
 */
const LECTURES_MAX = 1_000_000;

const SEPARATEUR_TRAME = '\n\n';
const PREFIXE_DONNEES = 'data:';

export interface RappelsFlux {
  onEvenement: (evenement: EvenementFlux) => void;
}

function extraireCharge(trame: string): string | null {
  for (const ligne of trame.split('\n')) {
    if (ligne.startsWith(PREFIXE_DONNEES)) {
      return ligne.slice(PREFIXE_DONNEES.length).trim();
    }
  }
  return null;
}

function traiterTrame(trame: string, rappels: RappelsFlux): void {
  const charge = extraireCharge(trame);
  if (charge === null || charge === '') {
    return;
  }
  try {
    // Même justification que dans `client.ts` : le contrat est décrit par `contrats.ts`.
    rappels.onEvenement(JSON.parse(charge) as EvenementFlux);
  } catch (cause) {
    journal.avertissement('trame SSE illisible, ignorée', cause);
  }
}

/** Consomme les trames complètes du tampon et rend le reliquat incomplet. */
function consommerTrames(tampon: string, rappels: RappelsFlux): string {
  const morceaux = tampon.split(SEPARATEUR_TRAME);
  const reliquat = morceaux.pop() ?? '';
  for (const trame of morceaux) {
    traiterTrame(trame, rappels);
  }
  return reliquat;
}

async function drainer(corps: ReadableStream<Uint8Array>, rappels: RappelsFlux): Promise<void> {
  const lecteur = corps.getReader();
  const decodeur = new TextDecoder();
  let tampon = '';
  try {
    for (let lecture = 0; lecture < LECTURES_MAX; lecture += 1) {
      const { done, value } = await lecteur.read();
      if (done) {
        consommerTrames(`${tampon}${SEPARATEUR_TRAME}`, rappels);
        return;
      }
      tampon = consommerTrames(tampon + decodeur.decode(value, { stream: true }), rappels);
    }
    journal.avertissement('flux de génération interrompu : borne de lectures atteinte');
  } finally {
    lecteur.releaseLock();
  }
}

/**
 * Ouvre un flux de génération et rend la main quand il se ferme. L'annulation passe par `signal` ;
 * l'échec d'ouverture reste une `ErreurApi` (le statut HTTP est encore disponible à ce moment),
 * alors qu'un échec ultérieur arrive sous forme d'événement `erreur` dans le flux lui-même.
 *
 * L'erreur d'ouverture est LUE dans le corps de la réponse : les refus de branche (`404
 * message_introuvable`, `422 branche_invalide`, `409 generation_deja_en_cours`) portent chacun une
 * remédiation distincte, et les remplacer par un message générique reviendrait à jeter la seule
 * information dont l'utilisateur a besoin pour corriger son geste.
 */
async function ouvrirFlux(
  chemin: string,
  corps: unknown,
  rappels: RappelsFlux,
  signal: AbortSignal,
): Promise<void> {
  const reponse = await fetch(`/api/chat/conversations/${chemin}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Accept: 'text/event-stream' },
    body: JSON.stringify(corps),
    signal,
  });
  if (!reponse.ok) {
    const erreur = await lireErreur(reponse);
    journal.erreur(`ouverture du flux refusée (${reponse.status} ${erreur.code})`, erreur.message);
    throw erreur;
  }
  if (reponse.body === null) {
    journal.erreur('flux accepté mais sans corps lisible');
    throw new ErreurApi(
      reponse.status,
      'flux_sans_corps',
      'La génération a démarré sans flux lisible.',
      'Recharger la page ; si le défaut persiste, consulter le journal du backend.',
    );
  }
  await drainer(reponse.body, rappels);
}

/**
 * Se raccroche à la génération EN COURS d'une conversation (retour d'une autre conversation ou d'un
 * autre écran) : le serveur rejoue le déjà-produit puis diffuse la suite. Rend `false` s'il n'y a
 * aucune génération en cours (204), `true` une fois le flux rejoint et terminé.
 */
export async function rejoindreFluxGeneration(
  conversationId: string,
  rappels: RappelsFlux,
  signal: AbortSignal,
): Promise<boolean> {
  const reponse = await fetch(`/api/chat/conversations/${conversationId}/flux`, {
    headers: { Accept: 'text/event-stream' },
    signal,
  });
  if (reponse.status === 204) {
    return false;
  }
  if (!reponse.ok || reponse.body === null) {
    const erreur = await lireErreur(reponse);
    journal.erreur(`raccrochage au flux refusé (${reponse.status} ${erreur.code})`, erreur.message);
    throw erreur;
  }
  await drainer(reponse.body, rappels);
  return true;
}

/** Tour normal : le message part au bout du chemin actif. */
export function ouvrirFluxGeneration(
  conversationId: string,
  demande: DemandeGeneration,
  rappels: RappelsFlux,
  signal: AbortSignal,
): Promise<void> {
  return ouvrirFlux(`${conversationId}/generer`, demande, rappels, signal);
}

/**
 * Rejeu : une réponse SŒUR est produite sous le même parent, l'ancienne reste intacte et reste
 * atteignable par les flèches de variantes. Le flux démarre immédiatement — il n'existe pas de mode
 * « créer la branche sans générer ».
 */
export function ouvrirFluxRejeu(
  conversationId: string,
  messageId: string,
  demande: DemandeRejeu,
  rappels: RappelsFlux,
  signal: AbortSignal,
): Promise<void> {
  return ouvrirFlux(`${conversationId}/messages/${messageId}/rejouer`, demande, rappels, signal);
}

/** Édition d'un message utilisateur : le nouveau texte ouvre une branche sœur, puis génère. */
export function ouvrirFluxEdition(
  conversationId: string,
  messageId: string,
  demande: DemandeEdition,
  rappels: RappelsFlux,
  signal: AbortSignal,
): Promise<void> {
  return ouvrirFlux(`${conversationId}/messages/${messageId}/editer`, demande, rappels, signal);
}
