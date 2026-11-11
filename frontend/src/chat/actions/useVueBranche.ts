/*
 * Vue de branche : le chemin actif tel que le serveur l'a établi, et les variantes de chacun de ses
 * messages.
 *
 * C'est une LECTURE, jamais un calcul. Le frontend n'a ni l'arbre complet, ni la règle de choix de
 * la feuille : reconstituer le chemin ici produirait une seconde vérité qui divergerait au premier
 * rejeu. On relit chaque fois que l'arbre a pu bouger, et on ne relit qu'alors.
 *
 * Toute vue posée est filtrée sur le `conversation_id` qu'elle porte elle-même (ref `attendue`) :
 * sans ce filtre, une lecture lente revenant après un changement de conversation attribuerait ses
 * messages à la mauvaise — le pire défaut possible sur un fil, et l'un des plus durs à reproduire.
 */

import { useCallback, useEffect, useRef, useState } from 'react';
import { messageErreur } from '../api/client';
import { lireBranche } from '../api/branches-api';
import type { EtatBranche, MessageChat } from '../api/contrats';
import { journal } from '../api/journal';
import { fusionnerParId, memeContenu } from '../conversation/fusion-par-id';

/*
 * Constante partagée et non un `{}` reconstruit à chaque rendu : cette valeur part dans un contexte
 * React, et une identité neuve à chaque rendu invaliderait la mémoïsation en aval — donc ferait
 * re-rendre tout le fil à chaque token reçu.
 */
const AUCUNE_VARIANTE: Record<string, string[]> = {};

export interface VueBranche {
  /** Chemin actif, ou `null` tant qu'aucune réponse n'est arrivée — l'appelant garde alors sa liste. */
  chemin: MessageChat[] | null;
  variantes: Record<string, string[]>;
  erreur: string | null;
  recharger: () => Promise<void>;
  /** Pose une vue déjà obtenue (réponse de `POST /branche`) — évite une seconde lecture. */
  poser: (etat: EtatBranche) => void;
}

function charger(
  conversationId: string,
  signal: AbortSignal,
  poser: (vue: EtatBranche) => void,
  signaler: (erreur: string) => void,
): void {
  // Promesse volontairement non attendue : un effet React ne peut pas être asynchrone. L'échec est
  // traité dans le `.catch` ci-dessous, il n'est donc ni perdu ni propagé.
  void lireBranche(conversationId, signal)
    .then(poser)
    .catch((cause: unknown): void => {
      // Une lecture annulée par un changement de conversation n'est pas un échec à afficher.
      if (signal.aborted) {
        return;
      }
      journal.erreur('vue de branche illisible', cause);
      signaler(messageErreur(cause));
    });
}

/* Relecture fusionnée : une vue identique garde son objet, et les messages inchangés gardent le leur. */
function fusionnerVue(courant: EtatBranche | null, vue: EtatBranche): EtatBranche {
  if (courant === null || courant.conversation_id !== vue.conversation_id) {
    return vue;
  }
  if (memeContenu(courant, vue)) {
    return courant;
  }
  return {
    ...vue,
    messages: fusionnerParId(courant.messages, vue.messages),
    variantes: memeContenu(courant.variantes, vue.variantes) ? courant.variantes : vue.variantes,
  };
}

async function relire(
  conversationId: string | null,
  poser: (vue: EtatBranche) => void,
  signaler: (erreur: string) => void,
): Promise<void> {
  if (conversationId === null) {
    return;
  }
  try {
    poser(await lireBranche(conversationId));
  } catch (cause) {
    journal.erreur('vue de branche illisible', cause);
    signaler(messageErreur(cause));
  }
}

export function useVueBranche(conversationId: string | null): VueBranche {
  const [etat, setEtat] = useState<EtatBranche | null>(null);
  const [erreur, setErreur] = useState<string | null>(null);
  const attendue = useRef<string | null>(conversationId);

  const poser = useCallback((vue: EtatBranche): void => {
    if (attendue.current === vue.conversation_id) {
      setEtat((courant) => fusionnerVue(courant, vue));
      setErreur(null);
    }
  }, []);

  useEffect((): (() => void) | undefined => {
    attendue.current = conversationId;
    setEtat(null);
    setErreur(null);
    if (conversationId === null) {
      return undefined;
    }
    const controle = new AbortController();
    charger(conversationId, controle.signal, poser, setErreur);
    return (): void => controle.abort();
  }, [conversationId, poser]);

  const recharger = useCallback(
    (): Promise<void> => relire(conversationId, poser, setErreur),
    [conversationId, poser],
  );

  const variantes = etat?.variantes ?? AUCUNE_VARIANTE;
  return { chemin: etat?.messages ?? null, variantes, erreur, recharger, poser };
}

/**
 * Relit la vue à la FIN d'un tour mené ailleurs (composeur), jamais à chaque battement de rendu.
 *
 * Un tour normal s'accroche à la feuille active : après une bascule de branche, seule cette
 * relecture au front descendant rend la nouvelle feuille visible. Déclencher sur l'état plutôt que
 * sur la transition provoquerait une requête par rendu pendant toute la génération.
 */
export function useRelectureEnFinDeTour(
  genereAilleurs: boolean,
  recharger: () => Promise<void>,
): void {
  const precedent = useRef<boolean>(genereAilleurs);
  useEffect((): void => {
    const finDeTour = precedent.current && !genereAilleurs;
    precedent.current = genereAilleurs;
    if (finDeTour) {
      // `recharger` capture ses propres échecs et les expose par `erreur` : rien à propager ici.
      void recharger();
    }
  }, [genereAilleurs, recharger]);
}
