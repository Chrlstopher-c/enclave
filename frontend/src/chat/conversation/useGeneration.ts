/*
 * Génération en streaming : ouverture du flux, accumulation du texte reçu, annulation.
 *
 * Séparé de la persistance parce que ce sont deux durées de vie différentes : l'historique survit
 * à la page, le flux ne survit pas au démontage — il est explicitement coupé.
 *
 * INVARIANT — un flux appartient à UNE conversation. Son texte, son erreur et sa relecture
 * d'historique portent l'identifiant de celle qui l'a ouvert, et ne sont appliqués que si c'est
 * encore celle qu'on regarde. L'état rendu n'est pas « le brouillon » mais « le brouillon de X » :
 * ce hook est monté une seule fois pour l'écran et ne se remonte pas quand la sélection change, un
 * état anonyme s'affichait donc sous n'importe quelle conversation, y verrouillait le composeur et
 * y écrivait l'historique d'une autre.
 *
 * CHOIX — changer de conversation ANNULE la génération franchement, au lieu de la poursuivre en
 * arrière-plan. Le GPU est exclusif : laisser un moteur produire pour une conversation que personne
 * ne regarde immobilise la VRAM d'une réponse que personne n'attend. Rien n'est perdu pour autant,
 * le backend persiste le partiel et marque le message `interrompu` : la réponse tronquée se relit
 * en rouvrant la conversation. Poursuivre imposerait au contraire de garder un brouillon par
 * conversation puis de l'afficher à la réouverture — un texte que l'utilisateur n'a pas vu se
 * construire, reconstruit hors de la source de vérité qu'est l'historique persisté.
 */

import { useCallback, useEffect, useRef, useState } from 'react';
import type { Dispatch, MutableRefObject, SetStateAction } from 'react';
import { messageErreur } from '../api/client';
import type { EvenementFlux, InfoCompaction } from '../api/contrats';
import { annulerGeneration } from '../api/conversations-api';
import { ouvrirFluxGeneration, type RappelsFlux } from '../api/flux-generation';
import { journal } from '../api/journal';

/*
 * Plafond d'attente de l'annulation côté serveur. `postJson` n'a pas de délai propre : sans cette
 * borne, un backend qui ne répond pas laisserait la connexion SSE ouverte indéfiniment, donc le
 * moteur en train de produire. Passé ce délai on rompt localement, quitte à ce que le serveur
 * l'apprenne par la fermeture de la connexion.
 */
// 20 s : le serveur répond une fois le partiel ENREGISTRÉ (il attend jusqu'à 15 s, `DELAI_ARRET_S`).
// À 3 s, la relecture partait avant l'écriture et l'écran se vidait jusqu'au rafraîchissement.
const DELAI_ANNULATION_MS = 20_000;

export interface EtatGeneration {
  /** Texte reçu jusqu'ici pour la réponse en cours ; `null` hors génération. */
  brouillon: string | null;
  genere: boolean;
  erreur: string | null;
  /** Balise de compaction émise pour la réponse en cours ; `null` tant qu'aucune n'a eu lieu. */
  compactionEnCours: InfoCompaction | null;
  envoyer: (contenu: string, fichierIds?: string[]) => Promise<void>;
  annuler: () => Promise<void>;
}

/** État produit par un flux, indissociable de la conversation qui l'a ouvert. */
interface FluxCourant {
  readonly proprietaire: string;
  readonly brouillon: string | null;
  readonly actif: boolean;
  readonly erreur: string | null;
  readonly compaction: InfoCompaction | null;
}

/** Flux réellement ouvert : son propriétaire et sa poignée d'annulation, jamais l'un sans l'autre. */
interface FluxEnVol {
  readonly proprietaire: string;
  readonly controle: AbortController;
}

type Transformation = (courant: FluxCourant) => FluxCourant;
type MajFlux = (id: string, transformer: Transformation) => void;
type Fin = (id: string, controle: AbortController) => Promise<void>;

function avecFragment(texte: string): Transformation {
  return (courant): FluxCourant => ({ ...courant, brouillon: (courant.brouillon ?? '') + texte });
}

function avecErreur(message: string): Transformation {
  return (courant): FluxCourant => ({ ...courant, erreur: message });
}

function avecCompaction(compaction: InfoCompaction): Transformation {
  return (courant): FluxCourant => ({ ...courant, compaction });
}

function termine(courant: FluxCourant): FluxCourant {
  // La balise du direct disparaît à la clôture : la version persistée revient portée par le message
  // relu (`message.compaction`), au même endroit. Deux balises pour un seul événement dérouteraient.
  return { ...courant, brouillon: null, actif: false, compaction: null };
}

/**
 * Coupe un flux : le serveur d'abord — il persiste le partiel et marque le message interrompu —
 * puis la connexion. Rompre en premier laisserait le moteur produire dans le vide. L'attente du
 * serveur est bornée, et `abort()` est idempotent : la connexion est coupée une fois, au plus tôt.
 */
async function couperFlux(id: string, controle: AbortController): Promise<void> {
  const minuterie = window.setTimeout((): void => controle.abort(), DELAI_ANNULATION_MS);
  try {
    await annulerGeneration(id);
  } catch (cause) {
    journal.erreur('annulation refusée par le backend', cause);
  } finally {
    window.clearTimeout(minuterie);
    controle.abort();
  }
}

/** Un événement n'atteint que l'état de SA conversation : `majFlux` en est le seul gardien. */
function appliquer(majFlux: MajFlux, id: string, evenement: EvenementFlux): void {
  if (evenement.type === 'fragment') {
    majFlux(id, avecFragment(evenement.texte));
    return;
  }
  if (evenement.type === 'compaction') {
    majFlux(id, avecCompaction(evenement.compaction));
    return;
  }
  if (evenement.type === 'erreur') {
    const message = `${evenement.message} ${evenement.remediation}`.trim();
    majFlux(id, avecErreur(message));
  }
  // `debut` et `fin` ne sont pas rendus : l'état persisté est relu à la fermeture du flux.
}

function useMajFlux(setFlux: Dispatch<SetStateAction<FluxCourant | null>>): MajFlux {
  return useCallback<MajFlux>(
    (id, transformer): void => {
      // Garde d'appartenance. Un fragment de A arrivé après un changement de conversation trouve
      // ici un état qui appartient à B, et n'écrit rien.
      setFlux((courant) => (courant !== null && courant.proprietaire === id ? transformer(courant) : courant));
    },
    [setFlux],
  );
}

/**
 * @param onTermine relecture de l'historique persisté à la fermeture du flux. Le backend porte
 * l'identifiant réel du message, son débit mesuré et son éventuelle interruption : les reconstruire
 * à partir des fragments reviendrait à afficher une estimation.
 */
function useFin(
  enVol: MutableRefObject<FluxEnVol | null>,
  majFlux: MajFlux,
  onTermine: (conversationId: string) => Promise<void>,
): Fin {
  return useCallback<Fin>(
    async (id, controle): Promise<void> => {
      // Le flux en vol n'est plus celui qui se termine : la conversation a changé et `couper` a
      // déjà tout remis à zéro. Ni l'état ni l'historique de A ne doivent toucher l'écran de B.
      if (enVol.current === null || enVol.current.controle !== controle) {
        return;
      }
      enVol.current = null;
      majFlux(id, termine);
      await onTermine(id);
    },
    [enVol, majFlux, onTermine],
  );
}

function useEnvoi(
  conversationId: string | null,
  enVol: MutableRefObject<FluxEnVol | null>,
  setFlux: Dispatch<SetStateAction<FluxCourant | null>>,
  majFlux: MajFlux,
  terminer: Fin,
): (contenu: string, fichierIds?: string[]) => Promise<void> {
  return useCallback(
    async (contenu: string, fichierIds?: string[]): Promise<void> => {
      // Le verrou porte sur le flux réellement ouvert, pas sur un booléen partagé par l'écran :
      // c'est ce qui permet d'écrire dans B pendant que la génération de A se termine.
      if (conversationId === null || enVol.current !== null) {
        return;
      }
      const id = conversationId;
      const controle = new AbortController();
      enVol.current = { proprietaire: id, controle };
      setFlux({ proprietaire: id, brouillon: '', actif: true, erreur: null, compaction: null });
      const rappels: RappelsFlux = { onEvenement: (evenement): void => appliquer(majFlux, id, evenement) };
      try {
        await ouvrirFluxGeneration(id, { contenu, fichier_ids: fichierIds }, rappels, controle.signal);
      } catch (cause) {
        if (!controle.signal.aborted) {
          journal.erreur('génération interrompue', cause);
          majFlux(id, avecErreur(messageErreur(cause)));
        }
      } finally {
        await terminer(id, controle);
      }
    },
    [conversationId, enVol, setFlux, majFlux, terminer],
  );
}

function useAnnulation(enVol: MutableRefObject<FluxEnVol | null>): () => Promise<void> {
  return useCallback(async (): Promise<void> => {
    const courant = enVol.current;
    if (courant === null) {
      return;
    }
    // On vise le propriétaire du flux et non la conversation affichée : demander l'arrêt de celle
    // qu'on regarde renverrait `annulee: false` et laisserait l'autre produire.
    await couperFlux(courant.proprietaire, courant.controle);
  }, [enVol]);
}

function useCoupure(
  enVol: MutableRefObject<FluxEnVol | null>,
  setFlux: Dispatch<SetStateAction<FluxCourant | null>>,
): () => void {
  return useCallback((): void => {
    const courant = enVol.current;
    enVol.current = null;
    setFlux(null);
    if (courant === null) {
      return;
    }
    // Un nettoyage React est synchrone : impossible d'attendre le serveur ici. `couperFlux`
    // journalise ses propres échecs et ne rejette pas — la promesse est abandonnée en connaissance
    // de cause, et sa borne de délai garantit que la connexion finit coupée.
    void couperFlux(courant.proprietaire, courant.controle);
  }, [enVol, setFlux]);
}

export function useGeneration(
  conversationId: string | null,
  onTermine: (conversationId: string) => Promise<void>,
): EtatGeneration {
  const [flux, setFlux] = useState<FluxCourant | null>(null);
  const enVol = useRef<FluxEnVol | null>(null);
  const majFlux = useMajFlux(setFlux);
  const terminer = useFin(enVol, majFlux, onTermine);
  const envoyer = useEnvoi(conversationId, enVol, setFlux, majFlux, terminer);
  const annuler = useAnnulation(enVol);
  const couper = useCoupure(enVol, setFlux);

  // `conversationId` n'est pas lu dans l'effet : il en est le déclencheur. Son changement — comme
  // le démontage de l'écran — exécute le nettoyage, qui annule le flux et remet l'état à zéro.
  useEffect((): (() => void) => couper, [conversationId, couper]);

  // Le rattachement est refait au rendu, et pas seulement au nettoyage : un nettoyage d'effet
  // s'exécute APRÈS la peinture, la conversation entrante aurait donc affiché le brouillon de la
  // précédente le temps d'une image.
  const affiche = flux !== null && flux.proprietaire === conversationId ? flux : null;

  return {
    brouillon: affiche?.brouillon ?? null,
    genere: affiche?.actif ?? false,
    erreur: affiche?.erreur ?? null,
    compactionEnCours: affiche?.compaction ?? null,
    envoyer,
    annuler,
  };
}
