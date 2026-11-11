/*
 * Génération en streaming : ouverture du flux, accumulation du texte reçu, annulation, raccrochage.
 *
 * Séparé de la persistance parce que ce sont deux durées de vie différentes : l'historique survit
 * à la page, le flux ne survit pas au démontage — il est explicitement coupé.
 *
 * INVARIANT — un flux appartient à UNE conversation. Son texte, son erreur et sa relecture
 * d'historique portent l'identifiant de celle qui l'a ouvert, et ne sont appliqués que si c'est
 * encore celle qu'on regarde. L'état rendu n'est pas « le brouillon » mais « le brouillon de X » :
 * ce hook est monté une seule fois pour l'écran et ne se remonte pas quand la sélection change.
 *
 * INVARIANT — fin d'un flux = réponse du serveur, jamais la fermeture d'une connexion. Une connexion
 * peut mourir pendant la veille ou sur un réseau coupé sans erreur : `suivreJusquAuBout` se raccroche
 * alors jusqu'au 204. `enVol` porte le suivi qui fait foi ; tout raccrochage remplace un suivi muet.
 *
 * CHOIX — changer de conversation ANNULE la génération franchement, au lieu de la poursuivre en
 * arrière-plan (GPU exclusif). Le backend persiste le partiel et marque le message `interrompu`.
 */

import { useCallback, useEffect, useRef, useState } from 'react';
import type { Dispatch, MutableRefObject, SetStateAction } from 'react';
import { ErreurApi, messageErreur } from '../api/client';
import type { ActiviteMoteur, EvenementFlux, InfoCompaction } from '../api/contrats';
import { annulerGeneration } from '../api/conversations-api';
import { ouvrirFluxGeneration, type RappelsFlux } from '../api/flux-generation';
import { journal } from '../api/journal';
import { finDeFlux, recevoirCommande, recevoirCompaction, useEtatCommandes } from '../commandes';
import { useRetourPremierPlan, type RaisonRetour } from '../../shared/hooks/useRetourPremierPlan';
import {
  creerSuivi,
  marquerOctet,
  nouvelleTentative,
  PERIODE_SURVEILLANCE_MS,
  relancerSiMuet,
  type SuiviFlux,
} from './suivi-flux-regles';
import { suivreJusquAuBout } from './suivi-flux';

/*
 * Plafond d'attente de l'annulation côté serveur. Passé ce délai on rompt localement, quitte à ce
 * que le serveur l'apprenne par la fermeture de la connexion.
 */
// 20 s : le serveur répond une fois le partiel ENREGISTRÉ (il attend jusqu'à 15 s, `DELAI_ARRET_S`).
const DELAI_ANNULATION_MS = 20_000;

export interface EtatGeneration {
  /** Texte reçu jusqu'ici pour la réponse en cours ; `null` hors génération. */
  brouillon: string | null;
  genere: boolean;
  erreur: string | null;
  /** Balise de compaction émise pour la réponse en cours ; `null` tant qu'aucune n'a eu lieu. */
  compactionEnCours: InfoCompaction | null;
  /** Dernière activité reçue du moteur et son heure de réception (ms) ; `null` hors génération. */
  activite: ActiviteRecue | null;
  envoyer: (contenu: string, fichierIds?: string[]) => Promise<void>;
  annuler: () => Promise<void>;
}

/** État produit par un flux, indissociable de la conversation qui l'a ouvert. */
export interface ActiviteRecue {
  readonly activite: ActiviteMoteur;
  readonly recueMs: number;
}

interface FluxCourant {
  readonly proprietaire: string;
  readonly activite?: ActiviteRecue | null;
  readonly brouillon: string | null;
  readonly actif: boolean;
  readonly erreur: string | null;
  readonly compaction: InfoCompaction | null;
}

type EnVol = MutableRefObject<SuiviFlux | null>;
type Transformation = (courant: FluxCourant) => FluxCourant;
type MajFlux = (id: string, transformer: Transformation) => void;
type Fin = (id: string, suivi: SuiviFlux) => Promise<void>;
type PoseFlux = Dispatch<SetStateAction<FluxCourant | null>>;

function fraisFlux(id: string): FluxCourant {
  return { proprietaire: id, brouillon: '', actif: true, erreur: null, compaction: null };
}

function avecFragment(texte: string): Transformation {
  return (courant): FluxCourant => ({ ...courant, brouillon: (courant.brouillon ?? '') + texte });
}

function avecActivite(activite: ActiviteMoteur): Transformation {
  return (courant): FluxCourant => ({ ...courant, activite: { activite, recueMs: Date.now() } });
}

function avecErreur(message: string): Transformation {
  return (courant): FluxCourant => ({ ...courant, erreur: message });
}

function avecCompaction(compaction: InfoCompaction): Transformation {
  return (courant): FluxCourant => ({ ...courant, compaction });
}

function termine(courant: FluxCourant): FluxCourant {
  // La balise du direct disparaît à la clôture : la version persistée revient portée par le message relu.
  return { ...courant, brouillon: null, actif: false, compaction: null, activite: null };
}

/**
 * Coupe un flux : le serveur d'abord — il persiste le partiel et marque le message interrompu —
 * puis la connexion. Rompre en premier laisserait le moteur produire dans le vide.
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
  } else if (evenement.type === 'activite') {
    majFlux(id, avecActivite(evenement.activite));
  } else if (evenement.type === 'compaction') {
    majFlux(id, avecCompaction(evenement.compaction));
    // Sans génération (commande `/compact`), seul le magasin des commandes la retient pour le fil.
    recevoirCompaction(id, evenement.compaction);
  } else if (evenement.type === 'commande') {
    recevoirCommande(id, evenement.commande);
  } else if (evenement.type === 'erreur') {
    majFlux(id, avecErreur(`${evenement.message} ${evenement.remediation}`.trim()));
  }
  // `debut` est traité à part (`rappelsDuSuivi`) ; `fin` n'est pas rendu.
}

function useMajFlux(setFlux: PoseFlux): MajFlux {
  return useCallback<MajFlux>(
    (id, transformer): void => {
      // Garde d'appartenance : un événement de A arrivé après un changement de conversation n'écrit rien.
      setFlux((courant) => (courant !== null && courant.proprietaire === id ? transformer(courant) : courant));
    },
    [setFlux],
  );
}

/** Libère le suivi s'il est encore celui qui fait foi, puis coupe sa connexion. Sans cela un suivi
 * abandonné garderait le verrou et bloquerait tout raccrochage ultérieur. */
function liberer(enVol: EnVol, suivi: SuiviFlux): void {
  if (enVol.current === suivi) {
    enVol.current = null;
  }
  suivi.controle.abort();
}

/** Les rappels d'un suivi : un `debut` (en tête de tout flux, y compris un rejeu) repart de zéro. */
function rappelsDuSuivi(
  id: string,
  suivi: SuiviFlux,
  enVol: EnVol,
  setFlux: PoseFlux,
  majFlux: MajFlux,
): RappelsFlux {
  return {
    onEvenement: (evenement): void => {
      if (evenement.type === 'debut') {
        if (enVol.current === suivi) {
          setFlux(fraisFlux(id));
        }
        return;
      }
      appliquer(majFlux, id, evenement);
    },
    onOctet: (): void => marquerOctet(suivi, Date.now()),
  };
}

function useFin(enVol: EnVol, majFlux: MajFlux, onTermine: (conversationId: string) => Promise<void>): Fin {
  return useCallback<Fin>(
    async (id, suivi): Promise<void> => {
      // Le suivi n'est plus celui qui fait foi : la conversation a changé, `couper` a tout remis à zéro.
      if (enVol.current !== suivi) {
        return;
      }
      enVol.current = null;
      majFlux(id, termine);
      await onTermine(id);
    },
    [enVol, majFlux, onTermine],
  );
}

/** Un refus HTTP (409, 422, 404…) est une réponse du serveur : elle s'affiche, elle ne se rattrape pas. */
function estRefus(cause: unknown): boolean {
  return cause instanceof ErreurApi && cause.statut >= 400;
}

async function lancerEnvoi(
  id: string,
  suivi: SuiviFlux,
  rappels: RappelsFlux,
  envoyer: (signal: AbortSignal) => Promise<void>,
  majFlux: MajFlux,
  terminer: Fin,
): Promise<void> {
  try {
    await envoyer(nouvelleTentative(suivi, Date.now()).signal);
  } catch (cause) {
    if (estRefus(cause)) {
      journal.erreur('génération refusée', cause);
      majFlux(id, avecErreur(messageErreur(cause)));
      await terminer(id, suivi);
      return;
    }
    if (!suivi.controle.signal.aborted) {
      journal.avertissement('connexion d’envoi coupée, raccrochage', cause);
    }
  }
  await suivreJusquAuBout(suivi, rappels);
  await terminer(id, suivi);
}

function useEnvoi(
  conversationId: string | null,
  enVol: EnVol,
  setFlux: PoseFlux,
  majFlux: MajFlux,
  terminer: Fin,
): (contenu: string, fichierIds?: string[]) => Promise<void> {
  return useCallback(
    async (contenu: string, fichierIds?: string[]): Promise<void> => {
      // Le verrou porte sur le suivi réellement ouvert, pas sur un booléen partagé par l'écran.
      if (conversationId === null || enVol.current !== null) {
        return;
      }
      const id = conversationId;
      const suivi = creerSuivi(id, Date.now());
      enVol.current = suivi;
      setFlux(fraisFlux(id));
      const rappels = rappelsDuSuivi(id, suivi, enVol, setFlux, majFlux);
      await lancerEnvoi(
        id,
        suivi,
        rappels,
        (signal) => ouvrirFluxGeneration(id, { contenu, fichier_ids: fichierIds }, rappels, signal),
        majFlux,
        terminer,
      );
    },
    [conversationId, enVol, setFlux, majFlux, terminer],
  );
}

function useAnnulation(enVol: EnVol): () => Promise<void> {
  return useCallback(async (): Promise<void> => {
    const suivi = enVol.current;
    if (suivi === null) {
      return;
    }
    // On vise le propriétaire du flux et non la conversation affichée : demander l'arrêt de celle
    // qu'on regarde renverrait `annulee: false` et laisserait l'autre produire.
    await couperFlux(suivi.proprietaire, suivi.controle);
  }, [enVol]);
}

function useCoupure(enVol: EnVol, setFlux: PoseFlux): () => void {
  return useCallback((): void => {
    const suivi = enVol.current;
    enVol.current = null;
    setFlux(null);
    // Quitter la conversation ne doit PAS arrêter la génération côté serveur : on ferme seulement la
    // connexion locale, le retour sur la conversation s'y raccroche (`ouvrirRaccrochage`).
    suivi?.controle.abort();
  }, [enVol, setFlux]);
}

/**
 * Attache un suivi de raccrochage si la conversation n'en a pas déjà un. Le flux rejoint peut être
 * celui d'une génération (`debut` en tête) ou celui d'une commande (`commande` seuls).
 */
function ouvrirRaccrochage(
  id: string,
  enVol: EnVol,
  setFlux: PoseFlux,
  majFlux: MajFlux,
  terminer: Fin,
): SuiviFlux | null {
  if (enVol.current?.proprietaire === id) {
    return null;
  }
  // Un suivi d'une autre conversation ne doit plus rien écrire : on le coupe avant de le remplacer.
  enVol.current?.controle.abort();
  const suivi = creerSuivi(id, Date.now());
  enVol.current = suivi;
  const rappels = rappelsDuSuivi(id, suivi, enVol, setFlux, majFlux);
  void suivreRaccrochage(id, suivi, rappels, enVol, terminer);
  return suivi;
}

async function suivreRaccrochage(
  id: string,
  suivi: SuiviFlux,
  rappels: RappelsFlux,
  enVol: EnVol,
  terminer: Fin,
): Promise<void> {
  const ouverts = await suivreJusquAuBout(suivi, rappels);
  if (ouverts > 0) {
    await terminer(id, suivi);
  } else if (enVol.current === suivi) {
    enVol.current = null;
  }
  if (!suivi.controle.signal.aborted) {
    finDeFlux(id, ouverts > 0);
  }
}

/**
 * Relance de la vérification à chaque retour sur la page : raccroche si rien n'est suivi, et coupe
 * une connexion muette pour que le suivi se raccroche. Le battement périodique ne fait que la coupure.
 */
function surveiller(
  id: string | null,
  raison: RaisonRetour,
  enVol: EnVol,
  setFlux: PoseFlux,
  majFlux: MajFlux,
  terminer: Fin,
): void {
  if (id === null) {
    return;
  }
  if (raison === 'retour') {
    ouvrirRaccrochage(id, enVol, setFlux, majFlux, terminer);
  }
  relancerSiMuet(enVol.current, Date.now());
}

function useRaccrochage(
  conversationId: string | null,
  enVol: EnVol,
  setFlux: PoseFlux,
  majFlux: MajFlux,
  terminer: Fin,
): void {
  useEffect((): (() => void) | undefined => {
    if (conversationId === null) {
      return undefined;
    }
    const suivi = ouvrirRaccrochage(conversationId, enVol, setFlux, majFlux, terminer);
    return suivi === null ? undefined : (): void => liberer(enVol, suivi);
  }, [conversationId, enVol, setFlux, majFlux, terminer]);

  const { jeton } = useEtatCommandes(conversationId);
  useEffect((): void => {
    if (conversationId !== null && jeton > 0) {
      ouvrirRaccrochage(conversationId, enVol, setFlux, majFlux, terminer);
    }
    // `conversationId` volontairement absent : seul un nouveau jeton demande une relance.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [jeton]);
}

export function useGeneration(
  conversationId: string | null,
  onTermine: (conversationId: string) => Promise<void>,
): EtatGeneration {
  const [flux, setFlux] = useState<FluxCourant | null>(null);
  const enVol = useRef<SuiviFlux | null>(null);
  const majFlux = useMajFlux(setFlux);
  const terminer = useFin(enVol, majFlux, onTermine);
  const envoyer = useEnvoi(conversationId, enVol, setFlux, majFlux, terminer);
  const annuler = useAnnulation(enVol);
  const couper = useCoupure(enVol, setFlux);

  // Changer de conversation — comme le démontage de l'écran — exécute ce nettoyage : flux coupé, état à zéro.
  useEffect((): (() => void) => couper, [conversationId, couper]);
  useRaccrochage(conversationId, enVol, setFlux, majFlux, terminer);

  const surveillance = useCallback(
    (raison: RaisonRetour): void => surveiller(conversationId, raison, enVol, setFlux, majFlux, terminer),
    [conversationId, enVol, setFlux, majFlux, terminer],
  );
  useRetourPremierPlan(surveillance, PERIODE_SURVEILLANCE_MS);

  // Le rattachement est refait au rendu : un nettoyage d'effet s'exécute APRÈS la peinture.
  const affiche = flux !== null && flux.proprietaire === conversationId ? flux : null;

  return {
    brouillon: affiche?.brouillon ?? null,
    genere: affiche?.actif ?? false,
    erreur: affiche?.erreur ?? null,
    compactionEnCours: affiche?.compaction ?? null,
    activite: affiche?.activite ?? null,
    envoyer,
    annuler,
  };
}
