/*
 * État des commandes, PAR CONVERSATION, partagé entre la saisie, le fil et le flux.
 *
 * Un magasin externe (`useSyncExternalStore`) plutôt qu'un état remonté : la saisie lance la
 * commande, le flux de génération (`useGeneration`) reçoit sa progression, le fil l'affiche — trois
 * branches de l'arbre qui ne partagent aucun parent dans ce domaine. Chaque entrée est indexée par
 * l'identifiant de conversation : un événement de A n'écrit jamais dans l'état de B.
 */

import { useSyncExternalStore } from 'react';
import type { InfoCompaction } from '../api/contrats';
import type { EtatCommande, InfoEffacement } from './contrats';

export interface CommandeRecue {
  readonly commande: EtatCommande;
  readonly recueMs: number;
}

export interface EtatCommandes {
  /** Commande longue en cours ou échouée ; `null` sinon (une réussite s'efface d'elle-même). */
  readonly commande: CommandeRecue | null;
  /** Balise produite par la dernière `/compact`, rendue avant que le fil ne soit relu. */
  readonly compaction: InfoCompaction | null;
  /** `null` tant que la liste n'a pas été lue : rien n'est masqué sur une supposition. */
  readonly effacements: readonly InfoEffacement[] | null;
  /** Incrémenté pour demander au flux de se raccrocher (une commande vient de partir). */
  readonly jeton: number;
  /** Raccrochages relancés pour la commande courante : borne contre une boucle. */
  readonly relances: number;
}

const VIDE: EtatCommandes = { commande: null, compaction: null, effacements: null, jeton: 0, relances: 0 };
const RELANCES_MAX = 5;
const RELANCES_SANS_FLUX = 2;
const DELAI_RELANCE_MS = 1000;

const etats = new Map<string, EtatCommandes>();
const abonnes = new Set<() => void>();

function lire(id: string): EtatCommandes {
  return etats.get(id) ?? VIDE;
}

function modifier(id: string, transformer: (etat: EtatCommandes) => EtatCommandes): void {
  const avant = lire(id);
  const apres = transformer(avant);
  if (apres !== avant) {
    etats.set(id, apres);
    abonnes.forEach((rappel) => rappel());
  }
}

function abonner(rappel: () => void): () => void {
  abonnes.add(rappel);
  return (): void => {
    abonnes.delete(rappel);
  };
}

export function useEtatCommandes(conversationId: string | null): EtatCommandes {
  return useSyncExternalStore(abonner, () => (conversationId === null ? VIDE : lire(conversationId)));
}

export function commandeEnCours(etat: EtatCommandes): boolean {
  return etat.commande !== null && etat.commande.commande.etat === 'en_cours';
}

/** Après le 202 : affiche la carte tout de suite et demande au flux de s'y raccrocher. */
export function demarrerCommande(id: string, commande: EtatCommande): void {
  modifier(id, (etat) => ({
    ...etat, commande: { commande, recueMs: Date.now() }, jeton: etat.jeton + 1, relances: 0,
  }));
}

/* Une réussite retire la carte : la balise de compaction prend le relais au même endroit. */
export function recevoirCommande(id: string, commande: EtatCommande): void {
  modifier(id, (etat) => ({
    ...etat, commande: commande.etat === 'termine' ? null : { commande, recueMs: Date.now() },
  }));
}

export function recevoirCompaction(id: string, compaction: InfoCompaction): void {
  modifier(id, (etat) => (commandeEnCours(etat) ? { ...etat, compaction } : etat));
}

export function ecarterCommande(id: string): void {
  modifier(id, (etat) => (etat.commande === null ? etat : { ...etat, commande: null }));
}

/*
 * Fin d'un flux de raccrochage alors que la commande paraît encore « en cours » :
 * - flux rejoint puis fermé → connexion perdue en route, on se raccroche à nouveau (borné) ;
 * - aucun flux (204) → soit la diffusion n'est pas encore ouverte (on retente deux fois), soit la
 *   commande s'est terminée avant qu'on arrive : l'état optimiste est alors retiré.
 */
export function finDeFlux(id: string, rejoint: boolean): void {
  const etat = lire(id);
  if (!commandeEnCours(etat)) {
    return;
  }
  if (etat.relances >= (rejoint ? RELANCES_MAX : RELANCES_SANS_FLUX)) {
    ecarterCommande(id);
    return;
  }
  window.setTimeout((): void => {
    modifier(id, (courant) => (commandeEnCours(courant)
      ? { ...courant, jeton: courant.jeton + 1, relances: courant.relances + 1 }
      : courant));
  }, DELAI_RELANCE_MS);
}

export function poserEffacements(id: string, effacements: readonly InfoEffacement[]): void {
  modifier(id, (etat) => ({ ...etat, effacements }));
}

export function ajouterEffacement(id: string, effacement: InfoEffacement): void {
  modifier(id, (etat) => ({ ...etat, effacements: [...(etat.effacements ?? []), effacement] }));
}
