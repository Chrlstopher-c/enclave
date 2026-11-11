/*
 * Masquage PUR du fil après un `/clear`.
 *
 * Le fil cache tout jusqu'à l'ancre du DERNIER effacement actif (incluse) — si cette ancre est sur
 * le chemin affiché. Une ancre absente (autre branche, liste pas encore relue) est sautée au profit
 * de la précédente : on ne masque jamais sur la foi d'un identifiant qu'on ne voit pas.
 */

import type { MessageChat } from '../api/contrats';
import type { InfoEffacement } from './contrats';

export interface VueEffacee {
  visibles: MessageChat[];
  effacement: InfoEffacement | null;
  masques: number;
}

export function masquerEfface(
  messages: readonly MessageChat[],
  effacements: readonly InfoEffacement[],
): VueEffacee {
  for (let index = effacements.length - 1; index >= 0; index -= 1) {
    const effacement = effacements[index];
    if (effacement === undefined) {
      continue;
    }
    const ancre = messages.findIndex((message) => message.id === effacement.ancre_message_id);
    if (ancre >= 0) {
      return { visibles: messages.slice(ancre + 1), effacement, masques: ancre + 1 };
    }
  }
  return { visibles: [...messages], effacement: null, masques: 0 };
}

const HEURE = new Intl.DateTimeFormat('fr-FR', { hour: '2-digit', minute: '2-digit' });
const JOUR = new Intl.DateTimeFormat('fr-FR', { day: 'numeric', month: 'short' });

/** « 14:32 » le jour même, « 12 nov. 14:32 » ensuite. `maintenant` injectable pour les tests. */
export function heureEffacement(iso: string, maintenant: Date = new Date()): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) {
    return '';
  }
  const memeJour = date.toDateString() === maintenant.toDateString();
  return memeJour ? HEURE.format(date) : `${JOUR.format(date)} ${HEURE.format(date)}`;
}
