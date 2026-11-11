/*
 * Retour au premier plan : la page revient visible (onglet, verrouillage du téléphone, bfcache,
 * réseau retrouvé). Pendant la veille, une connexion streaming meurt sans erreur ni événement : le
 * seul moyen de la revérifier est de prévenir l'écran au retour, puis à intervalle tant qu'il est visible.
 *
 * Le rappel est lu depuis une référence : les écouteurs sont installés une seule fois, et un rappel
 * recréé à chaque rendu ne réinstalle rien.
 */

import { useEffect, useRef } from 'react';

/** Cadence de la relecture légère (titres, ordre, fil) quand la page est visible. */
export const PERIODE_RESYNC_MS = 15_000;

export type RaisonRetour = 'retour' | 'battement';

const EVENEMENTS_RETOUR: readonly string[] = ['visibilitychange', 'focus', 'online', 'pageshow'];

function estVisible(): boolean {
  return document.visibilityState === 'visible';
}

/**
 * `rappel('retour')` au retour sur la page ; `rappel('battement')` toutes les `periodeMs` tant que
 * la page est visible. Rien n'est appelé page cachée.
 */
export function useRetourPremierPlan(rappel: (raison: RaisonRetour) => void, periodeMs: number): void {
  const courant = useRef(rappel);
  useEffect((): void => {
    courant.current = rappel;
  }, [rappel]);

  useEffect((): (() => void) => {
    const sur = (raison: RaisonRetour) => (): void => {
      if (estVisible()) courant.current(raison);
    };
    const auRetour = sur('retour');
    const minuterie = window.setInterval(sur('battement'), periodeMs);
    EVENEMENTS_RETOUR.forEach((nom) => {
      const cible: Window | Document = nom === 'visibilitychange' ? document : window;
      cible.addEventListener(nom, auRetour);
    });
    return (): void => {
      window.clearInterval(minuterie);
      EVENEMENTS_RETOUR.forEach((nom) => {
        const cible: Window | Document = nom === 'visibilitychange' ? document : window;
        cible.removeEventListener(nom, auRetour);
      });
    };
  }, [periodeMs]);
}
