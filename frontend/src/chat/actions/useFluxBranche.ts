/*
 * Flux SSE d'un rejeu ou d'une modification.
 *
 * Un second flux à côté de celui du composeur, et non une extension de `useGeneration` : celui-ci
 * est piloté depuis un message du fil, pas depuis la zone de saisie, et il doit pouvoir être annulé
 * sans toucher au tour normal. Le backend refuse de toute façon deux tours simultanés
 * (`409 generation_deja_en_cours`) — la concurrence est arbitrée là où l'état vit réellement.
 */

import { useCallback, useEffect, useRef, useState } from 'react';
import { messageErreur } from '../api/client';
import { annulerGeneration } from '../api/conversations-api';
import type { EvenementFlux } from '../api/contrats';
import type { RappelsFlux } from '../api/flux-generation';
import { journal } from '../api/journal';
import type { ActiviteRecue } from '../conversation/useGeneration';

/** Ouverture d'un flux déjà paramétré par l'appelant (route, message ciblé, corps). */
export type Ouverture = (rappels: RappelsFlux, signal: AbortSignal) => Promise<void>;

export interface FluxBranche {
  /** Texte reçu jusqu'ici pour la réponse en cours ; `null` hors génération. */
  brouillon: string | null;
  /** Activité du moteur pendant un rejeu ou une édition (même carte que pour un envoi). */
  activite: ActiviteRecue | null;
  genere: boolean;
  erreur: string | null;
  lancer: (ouvrir: Ouverture) => Promise<void>;
  annuler: () => Promise<void>;
}

interface Pilotage {
  ouvrir: Ouverture;
  controle: AbortController;
  traiter: (evenement: EvenementFlux) => void;
  signaler: (message: string) => void;
}

/** Consomme le flux jusqu'à sa fermeture. Ne rejette jamais : l'échec ressort par `signaler`. */
async function derouler({ ouvrir, controle, traiter, signaler }: Pilotage): Promise<void> {
  try {
    await ouvrir({ onEvenement: traiter }, controle.signal);
  } catch (cause) {
    // Une annulation demandée par l'utilisateur n'est pas un échec : elle ne s'affiche pas.
    if (!controle.signal.aborted) {
      journal.erreur('branche interrompue', cause);
      signaler(messageErreur(cause));
    }
  }
}

function appliquer(
  evenement: EvenementFlux,
  ajouter: (fragment: string) => void,
  signaler: (message: string) => void,
): void {
  if (evenement.type === 'fragment') {
    ajouter(evenement.texte);
    return;
  }
  if (evenement.type === 'erreur') {
    signaler(`${evenement.message} ${evenement.remediation}`.trim());
  }
  // `debut` et `fin` ne sont pas rendus : l'état persisté est relu à la fermeture du flux.
}

/*
 * Le serveur d'abord : il persiste le partiel et marque le message interrompu. Couper le flux en
 * premier laisserait la génération continuer côté moteur, VRAM occupée pour rien.
 */
async function demanderArret(conversationId: string): Promise<void> {
  try {
    await annulerGeneration(conversationId);
  } catch (cause) {
    journal.erreur('annulation de branche refusée par le backend', cause);
  }
}

/**
 * @param onTermine relecture de l'état persisté à la fermeture du flux. Le serveur porte
 * l'identifiant réel du nouveau message, son parent et son débit mesuré : les reconstruire à partir
 * des fragments reviendrait à afficher une estimation.
 */
export function useFluxBranche(
  conversationId: string | null,
  onTermine: () => Promise<void>,
): FluxBranche {
  const [brouillon, setBrouillon] = useState<string | null>(null);
  const [activite, setActivite] = useState<ActiviteRecue | null>(null);
  const [genere, setGenere] = useState<boolean>(false);
  const [erreur, setErreur] = useState<string | null>(null);
  const controleur = useRef<AbortController | null>(null);

  const traiter = useCallback((evenement: EvenementFlux): void => {
    if (evenement.type === 'activite') {
      setActivite({ activite: evenement.activite, recueMs: Date.now() });
      return;
    }
    appliquer(evenement, (fragment) => setBrouillon((texte) => (texte ?? '') + fragment), setErreur);
  }, []);

  const lancer = useCallback(
    async (ouvrir: Ouverture): Promise<void> => {
      if (conversationId === null || genere) {
        return;
      }
      const controle = new AbortController();
      controleur.current = controle;
      setBrouillon('');
      setGenere(true);
      setErreur(null);
      try {
        await derouler({ ouvrir, controle, traiter, signaler: setErreur });
      } finally {
        controleur.current = null;
        setGenere(false);
        setBrouillon(null);
        setActivite(null);
        await onTermine();
      }
    },
    [conversationId, genere, traiter, onTermine],
  );

  const annuler = useCallback(async (): Promise<void> => {
    // Rien à couper : la demande viendrait alors annuler le tour du composeur, qui a son propre
    // chemin d'arrêt. Chaque flux n'arrête que le sien.
    if (conversationId === null || controleur.current === null) {
      return;
    }
    await demanderArret(conversationId);
    controleur.current?.abort();
  }, [conversationId]);

  useEffect((): (() => void) => (): void => controleur.current?.abort(), []);

  return { brouillon, activite, genere, erreur, lancer, annuler };
}
