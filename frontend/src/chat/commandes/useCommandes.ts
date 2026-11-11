/*
 * Catalogue des commandes et exécution d'une commande sur une conversation.
 *
 * L'exécution ne passe PAS par l'envoi de message : une commande n'écrit rien dans le fil, elle
 * agit sur le contexte. `/compact` rend 202 et tourne côté serveur — sa progression arrive par le
 * flux de la conversation, auquel le magasin demande de se raccrocher. `/clear` rend son ancre tout
 * de suite : le fil la masque sans attendre.
 */

import { useCallback, useEffect, useState } from 'react';
import { ErreurApi, messageErreur } from '../api/client';
import { journal } from '../api/journal';
import { chargerCatalogue, executerCommande } from './commandes-api';
import type { DefinitionCommande } from './contrats';
import { ajouterEffacement, demarrerCommande } from './magasin';
import { commandeOptimiste } from './progression';

export type EtatCatalogue = 'chargement' | 'pret' | 'erreur';

export interface Catalogue {
  commandes: readonly DefinitionCommande[];
  etat: EtatCatalogue;
  recharger: () => void;
}

export function useCatalogue(): Catalogue {
  const [commandes, setCommandes] = useState<readonly DefinitionCommande[]>([]);
  const [etat, setEtat] = useState<EtatCatalogue>('chargement');
  const [essai, setEssai] = useState<number>(0);
  useEffect((): (() => void) => {
    let vivant = true;
    chargerCatalogue()
      .then((liste): void => {
        if (vivant) {
          setCommandes(liste);
          setEtat('pret');
        }
      })
      .catch((): void => {
        if (vivant) {
          setEtat('erreur');
        }
      });
    return (): void => {
      vivant = false;
    };
  }, [essai]);
  const recharger = useCallback((): void => {
    setEtat('chargement');
    setEssai((n) => n + 1);
  }, []);
  return { commandes, etat, recharger };
}

/*
 * Le 404/409 du contrat porte `detail` en simple texte, que le transport commun ne sait pas lire
 * (il attend `{code, message, remediation}`) : il ne reste alors que le statut HTTP. On lui rend
 * une phrase qui dit quoi faire, plutôt qu'un « Conflict » nu.
 */
function messageCommande(cause: unknown): string {
  if (cause instanceof ErreurApi && cause.code === '') {
    if (cause.statut === 409) {
      return 'Une réponse ou une commande est déjà en cours ici : réessayez à sa fin.';
    }
    if (cause.statut === 422) {
      return 'Commande refusée : la conversation est vide, ou les arguments ne conviennent pas.';
    }
    if (cause.statut === 404) {
      return 'Commande inconnue du serveur.';
    }
  }
  return messageErreur(cause);
}

export type Executer = (nom: string, args: string) => Promise<string | null>;

/** Rend `null` si la commande est partie, sinon le message d'échec à afficher sous la saisie. */
export function useExecution(conversationId: string | null): Executer {
  return useCallback(
    async (nom: string, args: string): Promise<string | null> => {
      if (conversationId === null) {
        return 'Ouvrez une conversation pour lancer une commande.';
      }
      try {
        const reponse = await executerCommande(conversationId, nom, args);
        if (reponse.effacement !== undefined) {
          ajouterEffacement(conversationId, reponse.effacement);
        } else {
          demarrerCommande(conversationId, commandeOptimiste(reponse.commande_id, reponse.nom, new Date()));
        }
        return null;
      } catch (cause) {
        journal.erreur(`commande /${nom} refusée`, cause);
        return messageCommande(cause);
      }
    },
    [conversationId],
  );
}
