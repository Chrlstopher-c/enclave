/*
 * Lecture PURE de la saisie : est-ce une commande, laquelle, avec quels arguments ?
 *
 * Règles (référence : Claude Code, Slack) :
 * - une commande commence au tout premier caractère par « / » ; un « / » ailleurs n'est que du texte ;
 * - « //texte » échappe : le message part tel quel, avec un seul « / » (« /texte ») ;
 * - la palette ne s'ouvre que pendant la frappe du NOM (aucun blanc encore) : dès l'espace qui
 *   ouvre les arguments, on sait de quelle commande il s'agit et la liste n'a plus rien à proposer.
 */

import type { DefinitionCommande } from './contrats';

export type AnalyseSaisie =
  | { type: 'texte' }
  | { type: 'litteral'; contenu: string }
  | { type: 'commande'; nom: string; arguments: string; definition: DefinitionCommande | null };

const COMMANDE = /^\/(\S*)(?:\s+([\s\S]*))?$/;

export function analyserSaisie(texte: string, catalogue: readonly DefinitionCommande[]): AnalyseSaisie {
  if (!texte.startsWith('/')) {
    return { type: 'texte' };
  }
  if (texte.startsWith('//')) {
    return { type: 'litteral', contenu: texte.slice(1) };
  }
  const trouve = COMMANDE.exec(texte.trimEnd());
  const nom = (trouve?.[1] ?? '').toLowerCase();
  const args = (trouve?.[2] ?? '').trim();
  return { type: 'commande', nom, arguments: args, definition: catalogue.find((c) => c.nom === nom) ?? null };
}

/** Nom en cours de frappe (« comp » pour « /comp »), ou `null` si la palette n'a rien à proposer. */
export function nomEnFrappe(texte: string): string | null {
  if (!texte.startsWith('/') || texte.startsWith('//') || /\s/.test(texte)) {
    return null;
  }
  return texte.slice(1).toLowerCase();
}

/** Les commandes qui commencent par le préfixe d'abord, puis celles qui le contiennent. */
export function filtrerCommandes(
  catalogue: readonly DefinitionCommande[],
  prefixe: string,
): DefinitionCommande[] {
  const debut = catalogue.filter((c) => c.nom.startsWith(prefixe));
  const milieu = catalogue.filter((c) => !c.nom.startsWith(prefixe) && c.nom.includes(prefixe));
  return [...debut, ...milieu];
}

/** Texte posé dans la saisie quand on choisit une commande : l'espace invite aux arguments. */
export function completion(definition: DefinitionCommande): string {
  return definition.arguments ? `/${definition.nom} ` : `/${definition.nom}`;
}

/** Vrai si la saisie est déjà exactement la commande choisie : Entrée l'exécute au lieu de compléter. */
export function estComplete(texte: string, definition: DefinitionCommande): boolean {
  return texte.trim().toLowerCase() === `/${definition.nom}`;
}

/** Refus connu d'avance (évite un aller-retour 422) ; `null` si la commande peut partir. */
export function refusArguments(analyse: AnalyseSaisie): string | null {
  if (analyse.type !== 'commande' || analyse.definition === null) {
    return null;
  }
  if (!analyse.definition.arguments && analyse.arguments !== '') {
    return `/${analyse.definition.nom} ne prend pas d’argument : retirez « ${analyse.arguments} ».`;
  }
  return null;
}
