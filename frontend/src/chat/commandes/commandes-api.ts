/*
 * Appels HTTP des commandes du chat. Une fonction par route ; la logique d'écran vit dans les hooks.
 *
 * Le catalogue est mis en cache pour la durée de la page : il ne change qu'avec le backend, et la
 * palette doit s'ouvrir à la frappe du « / » sans aller-retour. Un échec vide le cache, la frappe
 * suivante retente.
 */

import { deleteJson, getJson, postJson } from '../api/client';
import { journal } from '../api/journal';
import type { DefinitionCommande, InfoEffacement, ReponseCommande } from './contrats';

const RACINE = '/chat/conversations';

let catalogue: Promise<DefinitionCommande[]> | null = null;

export function chargerCatalogue(): Promise<DefinitionCommande[]> {
  if (catalogue === null) {
    catalogue = getJson<DefinitionCommande[]>('/chat/commandes').catch((cause: unknown) => {
      journal.erreur('catalogue des commandes illisible', cause);
      catalogue = null;
      throw cause;
    });
  }
  return catalogue;
}

export function executerCommande(conversationId: string, nom: string, args: string): Promise<ReponseCommande> {
  return postJson<ReponseCommande>(`${RACINE}/${conversationId}/commandes`, { nom, arguments: args });
}

export function listerEffacements(conversationId: string, signal?: AbortSignal): Promise<InfoEffacement[]> {
  return getJson<InfoEffacement[]>(`${RACINE}/${conversationId}/effacements`, signal);
}

/*
 * 204 sans corps : `requete` lit toujours du JSON, on tolère donc l'échec de lecture d'une réponse
 * vide plutôt que de dupliquer le transport. Un vrai refus (404, 409) lève avant la lecture.
 */
export async function annulerEffacement(conversationId: string, effacementId: string): Promise<void> {
  try {
    await deleteJson<unknown>(`${RACINE}/${conversationId}/effacements/${effacementId}`);
  } catch (cause) {
    if (cause instanceof SyntaxError) {
      return;
    }
    throw cause;
  }
}
