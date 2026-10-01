/*
 * Projet confié à la conversation active : liaison, catalogue, instantanés, et les gestes associés.
 *
 * La liaison est lue à chaque changement de conversation ; le catalogue et les instantanés ne sont
 * chargés qu'à l'ouverture de la modale (`rafraichir`) — inutile d'interroger l'atelier à chaque tour.
 * Toute action rend une erreur lisible dans `erreur`, jamais un état affiché que le serveur a refusé.
 */

import { useCallback, useEffect, useState } from 'react';
import { messageErreur } from '../api/client';
import { journal } from '../api/journal';
import {
  creerProjet,
  lierProjet,
  lireProjetConversation,
  listerInstantanes,
  listerProjets,
  restaurerInstantane,
  type CatalogueProjets,
  type Instantane,
} from './api-projet';

export interface EtatProjetConversation {
  readonly projet: string | null;
  readonly catalogue: CatalogueProjets | null;
  readonly instantanes: readonly Instantane[];
  readonly occupe: boolean;
  readonly erreur: string | null;
  readonly rafraichir: () => void;
  readonly confier: (nom: string | null) => void;
  readonly creerEtConfier: (nom: string) => void;
  readonly restaurer: (sha: string) => void;
}

function useLiaison(conversationId: string | null): [string | null, (projet: string | null) => void] {
  const [projet, setProjet] = useState<string | null>(null);
  useEffect((): (() => void) | undefined => {
    setProjet(null);
    if (conversationId === null) {
      return undefined;
    }
    const controleur = new AbortController();
    lireProjetConversation(conversationId, controleur.signal)
      .then(setProjet)
      .catch((cause: unknown): void => {
        if (!controleur.signal.aborted) {
          journal.avertissement('projet de la conversation non servi', cause);
        }
      });
    return (): void => controleur.abort();
  }, [conversationId]);
  return [projet, setProjet];
}

interface Execution {
  readonly occupe: boolean;
  readonly erreur: string | null;
  readonly executer: (action: () => Promise<void>) => void;
}

/* Une action à la fois, son erreur lisible : jamais un état affiché que le serveur a refusé. */
function useExecution(): Execution {
  const [occupe, setOccupe] = useState<boolean>(false);
  const [erreur, setErreur] = useState<string | null>(null);
  const executer = useCallback((action: () => Promise<void>): void => {
    setOccupe(true);
    setErreur(null);
    action()
      .catch((cause: unknown): void => {
        journal.erreur('action de projet refusée', cause);
        setErreur(messageErreur(cause));
      })
      .finally((): void => setOccupe(false));
  }, []);
  return { occupe, erreur, executer };
}

/* Confier (ou créer puis confier) un projet, puis recharger catalogue et instantanés du projet lié. */
function useLier(
  conversationId: string | null,
  executer: Execution['executer'],
  charger: (nom: string | null) => Promise<void>,
  setProjet: (projet: string | null) => void,
): (nom: string | null, creer: boolean) => void {
  return useCallback(
    (nom: string | null, creer: boolean): void => {
      if (conversationId === null) {
        return;
      }
      executer(async (): Promise<void> => {
        if (creer && nom !== null) {
          await creerProjet(nom);
        }
        const lie = await lierProjet(conversationId, nom);
        setProjet(lie);
        await charger(lie);
      });
    },
    [conversationId, executer, charger, setProjet],
  );
}

export function useProjetConversation(conversationId: string | null): EtatProjetConversation {
  const [projet, setProjet] = useLiaison(conversationId);
  const [catalogue, setCatalogue] = useState<CatalogueProjets | null>(null);
  const [instantanes, setInstantanes] = useState<readonly Instantane[]>([]);
  const { occupe, erreur, executer } = useExecution();

  const charger = useCallback(async (nom: string | null): Promise<void> => {
    setCatalogue(await listerProjets());
    setInstantanes(nom === null ? [] : await listerInstantanes(nom));
  }, []);

  const lier = useLier(conversationId, executer, charger, setProjet);

  const restaurer = useCallback(
    (sha: string): void => {
      if (projet !== null) {
        executer(async (): Promise<void> => {
          await restaurerInstantane(projet, sha);
          setInstantanes(await listerInstantanes(projet));
        });
      }
    },
    [projet, executer],
  );

  return {
    projet, catalogue, instantanes, occupe, erreur, restaurer,
    rafraichir: useCallback((): void => executer(() => charger(projet)), [executer, charger, projet]),
    confier: useCallback((nom: string | null): void => lier(nom, false), [lier]),
    creerEtConfier: useCallback((nom: string): void => lier(nom, true), [lier]),
  };
}
