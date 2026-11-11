/*
 * Assemblage des actions de message pour un fil : vue de branche, aperçu local, second flux SSE.
 *
 * Un seul endroit décide de ce qui s'affiche. `messages` vaut `null` tant que le serveur n'a pas
 * répondu — l'écran garde alors sa propre liste au lieu d'afficher un fil vide, et il n'invente
 * jamais un chemin de repli.
 */

import { useCallback, useEffect, useMemo, useState } from 'react';
import type { ActiviteRecue } from '../conversation/useGeneration';
import type { MessageChat } from '../api/contrats';
import { useRetourPremierPlan, PERIODE_RESYNC_MS } from '../../shared/hooks/useRetourPremierPlan';
import { appliquerBifurcation, messageOptimiste, type Bifurcation } from './apercu';
import type { ActionsMessages } from './fournisseur';
import { useFluxBranche } from './useFluxBranche';
import { useGestesBranche, type Gestes } from './useGestesBranche';
import { useRelectureEnFinDeTour, useVueBranche } from './useVueBranche';

export interface EtatActionsFil {
  /** Chemin à afficher, aperçu compris ; `null` ⇒ l'appelant garde la liste qu'il a déjà. */
  messages: MessageChat[] | null;
  /** Réponse en cours de réception pour un rejeu ou une édition ; `null` hors de ces cas. */
  brouillon: string | null;
  activite: ActiviteRecue | null;
  genere: boolean;
  erreur: string | null;
  actions: ActionsMessages;
  /** À appeler quand le composeur envoie : sans cela l'envoi resterait invisible sur ce chemin. */
  noterEnvoi: (contenu: string) => void;
  annuler: () => Promise<void>;
}

interface Apercu {
  bifurcation: Bifurcation | null;
  envoi: MessageChat | null;
  poserBifurcation: (bifurcation: Bifurcation) => void;
  noterEnvoi: (contenu: string) => void;
  effacer: () => void;
}

/*
 * L'aperçu ne vit que le temps d'un aller-retour : dès que la vue de branche est relue, il est
 * effacé et la mesure du serveur reprend la main. C'est ce qui garantit qu'aucun message affiché ne
 * survit à sa réfutation par le serveur.
 */
function useApercu(conversationId: string | null): Apercu {
  const [bifurcation, setBifurcation] = useState<Bifurcation | null>(null);
  const [envoi, setEnvoi] = useState<MessageChat | null>(null);

  const noterEnvoi = useCallback(
    (contenu: string): void => {
      if (conversationId !== null) {
        setEnvoi(messageOptimiste(conversationId, contenu));
      }
    },
    [conversationId],
  );

  const effacer = useCallback((): void => {
    setBifurcation(null);
    setEnvoi(null);
  }, []);

  // Changer de conversation périme tout aperçu : il ne décrit plus rien d'affiché.
  useEffect((): void => effacer(), [conversationId, effacer]);

  return { bifurcation, envoi, poserBifurcation: setBifurcation, noterEnvoi, effacer };
}

function useCheminAffiche(
  chemin: MessageChat[] | null,
  bifurcation: Bifurcation | null,
  envoi: MessageChat | null,
): MessageChat[] | null {
  return useMemo((): MessageChat[] | null => {
    if (chemin === null) {
      return null;
    }
    const base = bifurcation === null ? chemin : appliquerBifurcation(chemin, bifurcation);
    return envoi === null ? base : [...base, envoi];
  }, [chemin, bifurcation, envoi]);
}

/* Surface exposée aux messages. Recomposée seulement quand l'un de ses trois ingrédients change. */
function useSurfaceActions(
  variantes: Record<string, string[]>,
  occupe: boolean,
  gestes: Gestes,
): ActionsMessages {
  return useMemo(
    (): ActionsMessages => ({
      variantes,
      occupe,
      messageEnEdition: gestes.messageEnEdition,
      demarrerEdition: gestes.demarrerEdition,
      annulerEdition: gestes.annulerEdition,
      confirmerEdition: gestes.confirmerEdition,
      rejouer: gestes.rejouer,
      activerVariante: gestes.activerVariante,
    }),
    [variantes, occupe, gestes],
  );
}

/**
 * @param genereAilleurs génération menée par le composeur. Elle occupe le moteur — les gestes de
 * branche sont refusés pendant ce temps — et sa fin est le seul moment où la feuille active a pu
 * changer sans que ce module l'ait demandé.
 */
export function useActionsFil(
  conversationId: string | null,
  genereAilleurs: boolean,
): EtatActionsFil {
  const { chemin, variantes, erreur: erreurVue, recharger, poser } = useVueBranche(conversationId);
  const { bifurcation, envoi, poserBifurcation, noterEnvoi, effacer } = useApercu(conversationId);

  // Relire D'ABORD, effacer l'aperçu ENSUITE : l'ordre inverse laisserait passer un rendu où le
  // chemin est encore l'ancien et la coupure déjà levée — l'ancienne réponse réapparaîtrait le
  // temps d'une image, juste avant d'être remplacée.
  const terminer = useCallback(async (): Promise<void> => {
    await recharger();
    effacer();
  }, [effacer, recharger]);

  const flux = useFluxBranche(conversationId, terminer);
  useRelectureEnFinDeTour(genereAilleurs, terminer);

  const occupe = genereAilleurs || flux.genere;
  // Le fil se relit au retour sur la page et à intervalle, sauf pendant un tour (chemin optimiste).
  useRetourPremierPlan(
    useCallback((): void => {
      if (!occupe) {
        void recharger();
      }
    }, [occupe, recharger]),
    PERIODE_RESYNC_MS,
  );
  const gestes = useGestesBranche({
    conversationId,
    occupe,
    poserBifurcation,
    poserVue: poser,
    lancer: flux.lancer,
  });

  const messages = useCheminAffiche(chemin, bifurcation, envoi);
  const actions = useSurfaceActions(variantes, occupe, gestes);

  return {
    messages,
    brouillon: flux.brouillon,
    activite: flux.activite,
    genere: flux.genere,
    erreur: flux.erreur ?? gestes.erreur ?? erreurVue,
    actions,
    noterEnvoi,
    annuler: flux.annuler,
  };
}
