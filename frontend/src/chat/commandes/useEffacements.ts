/*
 * Effacements (`/clear`) de la conversation affichée : lecture à l'ouverture, annulation.
 *
 * Annuler = DELETE puis RELECTURE de la liste : plusieurs `/clear` s'empilent, et seul le serveur
 * sait lequel redevient le dernier actif sur la branche affichée.
 */

import { useCallback, useEffect, useState } from 'react';
import { messageErreur } from '../api/client';
import { journal } from '../api/journal';
import { annulerEffacement, listerEffacements } from './commandes-api';
import { poserEffacements } from './magasin';

export interface EtatEffacements {
  annuler: (effacementId: string) => Promise<void>;
  enAnnulation: boolean;
  erreur: string | null;
}

function useLectureInitiale(conversationId: string | null, dejaLus: boolean): void {
  useEffect((): (() => void) | undefined => {
    if (conversationId === null || dejaLus) {
      return undefined;
    }
    const controle = new AbortController();
    listerEffacements(conversationId, controle.signal)
      .then((liste): void => poserEffacements(conversationId, liste))
      .catch((cause: unknown): void => {
        if (!controle.signal.aborted) {
          // Liste illisible : on n'en masque rien, le fil reste entier — l'erreur est journalisée.
          journal.avertissement('effacements illisibles, fil affiché en entier', cause);
        }
      });
    return (): void => controle.abort();
  }, [conversationId, dejaLus]);
}

export function useEffacements(conversationId: string | null, dejaLus: boolean): EtatEffacements {
  const [enAnnulation, setEnAnnulation] = useState<boolean>(false);
  const [erreur, setErreur] = useState<string | null>(null);
  useLectureInitiale(conversationId, dejaLus);
  useEffect((): void => setErreur(null), [conversationId]);

  const annuler = useCallback(
    async (effacementId: string): Promise<void> => {
      if (conversationId === null) {
        return;
      }
      setEnAnnulation(true);
      setErreur(null);
      try {
        await annulerEffacement(conversationId, effacementId);
        poserEffacements(conversationId, await listerEffacements(conversationId));
      } catch (cause) {
        journal.erreur('annulation de l’effacement refusée', cause);
        setErreur(messageErreur(cause));
      } finally {
        setEnAnnulation(false);
      }
    },
    [conversationId],
  );
  return { annuler, enAnnulation, erreur };
}
