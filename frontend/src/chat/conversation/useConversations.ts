/*
 * Liste des conversations. Volontairement séparée du détail : ouvrir une conversation ne doit pas
 * recharger la liste, et créer une conversation ne doit pas recharger l'historique de la courante.
 *
 * Les archivées vivent dans un second tableau, chargé À LA DEMANDE et jamais au montage : le
 * backend les sert par une liste distincte (`?archivees=true`), et l'écran ne les montre que si on
 * les demande — payer cette requête à chaque session pour une section repliée serait du réseau
 * dépensé pour rien. `null` signifie « jamais chargées », à distinguer de « aucune ».
 *
 * Chaque action est une fonction de module qui reçoit les poseurs d'état : le hook ne fait que
 * les lier — c'est ce qui garde chaque geste lisible et testable seul.
 */

import { useCallback, useEffect, useState } from 'react';
import type { Dispatch, SetStateAction } from 'react';
import { messageErreur } from '../api/client';
import type { ResumeConversation } from '../api/contrats';
import {
  creerConversation,
  listerConversations,
  renommerConversation,
  supprimerConversation,
} from '../api/conversations-api';
import { archiverConversation, listerConversationsArchivees } from './api-archivage';
import { journal } from '../api/journal';
import { useRetourPremierPlan, PERIODE_RESYNC_MS } from '../../shared/hooks/useRetourPremierPlan';
import { fusionnerParId } from './fusion-par-id';

const TITRE_PAR_DEFAUT = 'Nouvelle conversation';

export interface EtatConversations {
  conversations: ResumeConversation[];
  /** `null` tant que la section n'a jamais été ouverte. */
  archivees: ResumeConversation[] | null;
  erreur: string | null;
  rafraichir: () => Promise<void>;
  creer: (modeleId: string | null) => Promise<ResumeConversation | null>;
  supprimer: (id: string) => Promise<void>;
  renommer: (id: string, titre: string) => Promise<void>;
  archiver: (id: string, archivee: boolean) => Promise<void>;
  chargerArchivees: () => Promise<void>;
}

interface Listes {
  actives: ResumeConversation[];
  archivees: ResumeConversation[] | null;
}

type PoseListes = Dispatch<SetStateAction<Listes>>;
type PoseErreur = (erreur: string | null) => void;

/** La plus récemment modifiée en tête — le même ordre que celui servi par le backend. */
function ordonner(liste: ResumeConversation[]): ResumeConversation[] {
  return [...liste].sort((a, b) => b.maj_le.localeCompare(a.maj_le));
}

/* Déplace la conversation confirmée par le backend d'une liste vers l'autre. Si les archivées
 * n'ont jamais été chargées, elles le restent : la prochaine ouverture de la section fera foi. */
function deplacer(listes: Listes, maj: ResumeConversation): Listes {
  const sansElle = {
    actives: listes.actives.filter((c) => c.id !== maj.id),
    archivees: listes.archivees?.filter((c) => c.id !== maj.id) ?? null,
  };
  if (maj.archivee) {
    return { ...sansElle, archivees: sansElle.archivees === null ? null : ordonner([...sansElle.archivees, maj]) };
  }
  return { ...sansElle, actives: ordonner([...sansElle.actives, maj]) };
}

async function creerEtInserer(
  poser: PoseListes,
  poserErreur: PoseErreur,
  modeleId: string | null,
): Promise<ResumeConversation | null> {
  try {
    const creee = await creerConversation(TITRE_PAR_DEFAUT, modeleId);
    poser((courantes) => ({ ...courantes, actives: [creee, ...courantes.actives] }));
    return creee;
  } catch (cause) {
    journal.erreur('création de conversation refusée', cause);
    poserErreur(messageErreur(cause));
    return null;
  }
}

async function supprimerPartout(poser: PoseListes, poserErreur: PoseErreur, id: string): Promise<void> {
  try {
    await supprimerConversation(id);
    poser((courantes) => ({
      actives: courantes.actives.filter((c) => c.id !== id),
      archivees: courantes.archivees?.filter((c) => c.id !== id) ?? null,
    }));
  } catch (cause) {
    journal.erreur('suppression de conversation refusée', cause);
    poserErreur(messageErreur(cause));
  }
}

/* Le titre confirmé par le backend remplace l'ancien : on n'affiche jamais un renommage que
 * la persistance aurait refusé. */
async function renommerPartout(
  poser: PoseListes,
  poserErreur: PoseErreur,
  id: string,
  titre: string,
): Promise<void> {
  try {
    const maj = await renommerConversation(id, titre);
    poser((courantes) => ({
      actives: courantes.actives.map((c) => (c.id === id ? maj : c)),
      archivees: courantes.archivees?.map((c) => (c.id === id ? maj : c)) ?? null,
    }));
  } catch (cause) {
    journal.erreur('renommage de conversation refusé', cause);
    poserErreur(messageErreur(cause));
  }
}

async function archiverEtDeplacer(
  poser: PoseListes,
  poserErreur: PoseErreur,
  id: string,
  archivee: boolean,
): Promise<void> {
  try {
    const maj = await archiverConversation(id, archivee);
    poser((courantes) => deplacer(courantes, maj));
  } catch (cause) {
    journal.erreur('archivage de conversation refusé', cause);
    poserErreur(messageErreur(cause));
  }
}

async function chargerLesArchivees(poser: PoseListes, poserErreur: PoseErreur): Promise<void> {
  try {
    const archivees = await listerConversationsArchivees();
    poser((courantes) => ({ ...courantes, archivees }));
  } catch (cause) {
    journal.erreur('liste des conversations archivées indisponible', cause);
    poserErreur(messageErreur(cause));
  }
}

async function rafraichirListe(poser: PoseListes, poserErreur: PoseErreur): Promise<void> {
  try {
    const actives = await listerConversations();
    poser((courantes) => ({ ...courantes, actives: fusionnerParId(courantes.actives, actives) }));
    poserErreur(null);
  } catch (cause) {
    journal.erreur('liste des conversations indisponible', cause);
    poserErreur(messageErreur(cause));
  }
}

export function useConversations(): EtatConversations {
  const [listes, setListes] = useState<Listes>({ actives: [], archivees: null });
  const [erreur, setErreur] = useState<string | null>(null);

  const rafraichir = useCallback((): Promise<void> => rafraichirListe(setListes, setErreur), []);

  useEffect((): void => {
    void rafraichir();
  }, [rafraichir]);

  // Au retour sur la page et à intervalle : titres, ordre et activité suivent sans rechargement.
  useRetourPremierPlan(
    useCallback((): void => {
      void rafraichir();
    }, [rafraichir]),
    PERIODE_RESYNC_MS,
  );

  return {
    conversations: listes.actives,
    archivees: listes.archivees,
    erreur,
    rafraichir,
    creer: useCallback((modeleId) => creerEtInserer(setListes, setErreur, modeleId), []),
    supprimer: useCallback((id) => supprimerPartout(setListes, setErreur, id), []),
    renommer: useCallback((id, titre) => renommerPartout(setListes, setErreur, id, titre), []),
    archiver: useCallback((id, archivee) => archiverEtDeplacer(setListes, setErreur, id, archivee), []),
    chargerArchivees: useCallback(() => chargerLesArchivees(setListes, setErreur), []),
  };
}
