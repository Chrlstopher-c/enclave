/*
 * Contenu vivant du projet confié à la conversation : arborescence, fichiers modifiés depuis le
 * dernier instantané, et le fichier (ou son diff) sélectionné.
 *
 * Relu toutes les quelques secondes tant que le panneau est ouvert : c'est pendant que l'agent
 * travaille qu'on veut voir ses fichiers apparaître, pas seulement à la fin de son tour. Changer de
 * projet remonte le panneau (`key`), ce qui remet cet état à zéro.
 */

import { useCallback, useEffect, useState } from 'react';
import { messageErreur } from '../api/client';
import {
  lireArbre,
  lireDiff,
  lireFichierProjet,
  lireModifications,
  type ArbreProjet,
  type ContenuFichier,
  type DiffFichier,
  type ModificationsProjet,
} from './api-projet';

export const INTERVALLE_RAFRAICHISSEMENT_MS = 4_000;

export type ModeVue = 'fichier' | 'diff';

export interface Selection {
  readonly chemin: string;
  readonly mode: ModeVue;
}

export type VueSelection =
  | { readonly mode: 'fichier'; readonly fichier: ContenuFichier }
  | { readonly mode: 'diff'; readonly diff: DiffFichier };

export interface EtatFichiersProjet {
  readonly arbre: ArbreProjet | null;
  readonly modifications: ModificationsProjet | null;
  readonly selection: Selection | null;
  readonly vue: VueSelection | null;
  readonly erreur: string | null;
  readonly selectionner: (selection: Selection | null) => void;
  readonly rafraichir: () => void;
}

async function chargerVue(projet: string, selection: Selection, signal: AbortSignal): Promise<VueSelection> {
  if (selection.mode === 'diff') {
    return { mode: 'diff', diff: await lireDiff(projet, selection.chemin, signal) };
  }
  return { mode: 'fichier', fichier: await lireFichierProjet(projet, selection.chemin, signal) };
}

interface ContenuProjet {
  readonly arbre: ArbreProjet;
  readonly modifications: ModificationsProjet;
}

interface Ecrivains {
  readonly contenu: (contenu: ContenuProjet) => void;
  readonly vue: (vue: VueSelection) => void;
  readonly erreur: (erreur: string | null) => void;
}

/** Une relecture complète : arbre, modifications et sélection. Les erreurs d'un abandon sont tues. */
function relire(projet: string, selection: Selection | null, signal: AbortSignal, ecrire: Ecrivains): void {
  const echec = (cause: unknown): void => {
    if (!signal.aborted) {
      ecrire.erreur(messageErreur(cause));
    }
  };
  Promise.all([lireArbre(projet, signal), lireModifications(projet, signal)])
    .then(([arbre, modifications]): void => {
      ecrire.contenu({ arbre, modifications });
      ecrire.erreur(null);
    })
    .catch(echec);
  if (selection !== null) {
    chargerVue(projet, selection, signal).then(ecrire.vue).catch(echec);
  }
}

export function useFichiersProjet(projet: string | null, ouvert: boolean): EtatFichiersProjet {
  const [contenu, setContenu] = useState<ContenuProjet | null>(null);
  const [selection, setSelection] = useState<Selection | null>(null);
  const [vue, setVue] = useState<VueSelection | null>(null);
  const [erreur, setErreur] = useState<string | null>(null);
  const [tick, setTick] = useState<number>(0);

  useEffect((): (() => void) | undefined => {
    if (projet === null || !ouvert) {
      return undefined;
    }
    const controleur = new AbortController();
    relire(projet, selection, controleur.signal,
      { contenu: setContenu, vue: setVue, erreur: setErreur });
    const minuterie = window.setTimeout((): void => setTick((t) => t + 1), INTERVALLE_RAFRAICHISSEMENT_MS);
    return (): void => {
      controleur.abort();
      window.clearTimeout(minuterie);
    };
  }, [projet, ouvert, selection, tick]);

  const selectionner = useCallback((suivante: Selection | null): void => {
    setVue(null);
    setSelection(suivante);
  }, []);
  const rafraichir = useCallback((): void => setTick((t) => t + 1), []);

  const arbre = contenu?.arbre ?? null;
  const modifications = contenu?.modifications ?? null;
  return { arbre, modifications, selection, vue, erreur, selectionner, rafraichir };
}
