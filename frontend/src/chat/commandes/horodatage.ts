/*
 * Temporalité lisible du fil (demande de Chris, 2026-11-11) : quand un message a été écrit, combien
 * de temps la réponse a pris. Fonctions PURES, `maintenant` injectable pour les tests.
 */

import { formaterDuree } from './progression';

const HEURE = new Intl.DateTimeFormat('fr-FR', { hour: '2-digit', minute: '2-digit' });
const JOUR = new Intl.DateTimeFormat('fr-FR', { day: 'numeric', month: 'short' });
const JOUR_ANNEE = new Intl.DateTimeFormat('fr-FR', { day: 'numeric', month: 'short', year: 'numeric' });

function memeJour(a: Date, b: Date): boolean {
  return a.toDateString() === b.toDateString();
}

/** « aujourd'hui 14:32 », « hier 09:10 », « 12 nov. 14:32 », « 3 janv. 2025 14:32 ». */
export function horodatageLisible(iso: string, maintenant: Date = new Date()): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) {
    return '';
  }
  const heure = HEURE.format(date);
  if (memeJour(date, maintenant)) {
    return `aujourd’hui ${heure}`;
  }
  const veille = new Date(maintenant);
  veille.setDate(veille.getDate() - 1);
  if (memeJour(date, veille)) {
    return `hier ${heure}`;
  }
  const format = date.getFullYear() === maintenant.getFullYear() ? JOUR : JOUR_ANNEE;
  return `${format.format(date)} ${heure}`;
}

/*
 * Durée d'écriture de la réponse, tirée des deux mesures que le backend persiste (jetons écrits et
 * débit). Elle exclut la relecture du contexte avant le premier jeton : d'où le « ≈ », assumé.
 */
export function dureeGeneration(tokens: number | null, tokensParSeconde: number | null): string | null {
  if (tokens === null || tokensParSeconde === null || tokens <= 0 || tokensParSeconde <= 0) {
    return null;
  }
  return `≈ ${formaterDuree((tokens / tokensParSeconde) * 1000)}`;
}

/** « au travail depuis 1 min 07 s » ; `null` sans horodatage de début (ancien backend). */
export function depuisDebut(debut: string | null | undefined, maintenant: number): string | null {
  if (debut == null) {
    return null;
  }
  const depart = Date.parse(debut);
  return Number.isNaN(depart) ? null : formaterDuree(maintenant - depart);
}
