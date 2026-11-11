/*
 * Conversation courante : historique persisté, réglages, et branchement de la génération.
 *
 * Le message de l'utilisateur est ajouté localement dès l'envoi pour que le fil réagisse
 * immédiatement, puis l'historique complet est relu à la fin du flux : le backend reste la source
 * de vérité, l'optimisme local ne vit que le temps d'une génération.
 */

import { useCallback, useEffect, useRef, useState } from 'react';
import { messageErreur } from '../api/client';
import type {
  ConversationDetaillee,
  InfoCompaction,
  MajReglages,
  MessageChat,
  ReglagesConversation,
  TacheAgent,
} from '../api/contrats';
import { ecrireReglages, lireConversation, listerMessages } from '../api/conversations-api';
import { journal } from '../api/journal';
import { useRetourPremierPlan, PERIODE_RESYNC_MS } from '../../shared/hooks/useRetourPremierPlan';
import { fusionnerParId } from './fusion-par-id';
import { useGeneration, type ActiviteRecue } from './useGeneration';

export interface EtatConversation {
  detail: ConversationDetaillee | null;
  messages: MessageChat[];
  brouillon: string | null;
  genere: boolean;
  erreur: string | null;
  /** Débit mesuré de la dernière réponse complète — une mesure, pas une prévision. */
  debitObserve: number | null;
  /** Balise de compaction du tour en cours, à rendre au-dessus du brouillon ; `null` sinon. */
  compactionEnCours: InfoCompaction | null;
  /** Activité du moteur en direct (débit, phase, outil en cours) ; `null` hors génération. */
  activite: ActiviteRecue | null;
  /** Dernier plan de tâches de l'agent vu dans cette conversation ; survit à la fin du tour. */
  taches: TacheAgent[] | null;
  envoyer: (contenu: string, fichierIds?: string[]) => Promise<void>;
  annuler: () => Promise<void>;
  enregistrerReglages: (patch: MajReglages) => Promise<void>;
  /** Réglages confirmés ailleurs (panneau de chargement, modale) : la vérité affichée suit. */
  appliquerReglages: (reglages: ReglagesConversation) => void;
}

interface Socle {
  detail: ConversationDetaillee | null;
  messages: MessageChat[];
  erreur: string | null;
  setDetail: (detail: ConversationDetaillee) => void;
  setMessages: (messages: MessageChat[]) => void;
  /** Relecture de l'historique : fusion par identifiant, sans recréer les messages inchangés. */
  fusionnerMessages: (recus: MessageChat[]) => void;
  setErreur: (erreur: string | null) => void;
}

function dernierDebit(messages: MessageChat[]): number | null {
  for (let index = messages.length - 1; index >= 0; index -= 1) {
    const debit = messages[index]?.tokens_par_seconde ?? null;
    if (debit !== null && debit > 0) {
      return debit;
    }
  }
  return null;
}

function messageLocal(conversationId: string, contenu: string): MessageChat {
  return {
    id: `local-${Date.now()}`,
    conversation_id: conversationId,
    role: 'user',
    contenu,
    tokens_generes: null,
    tokens_par_seconde: null,
    cree_le: new Date().toISOString(),
    modele_id: null,
    interrompu: false,
    // Le parent réel est décidé par le backend, qui seul connaît la branche active. Un message
    // optimiste affiché avant la réponse ne peut que l'ignorer : `null` dit « pas encore rattaché »,
    // et la version persistée qui revient porte le vrai parent.
    parent_id: null,
    // Un message optimiste ne déclenche aucune compaction : la balise vient du backend, jamais d'ici.
    compaction: null,
  };
}

/** Charge la conversation et son historique, et les remet à zéro quand la sélection change. */
function useSocle(conversationId: string | null): Socle {
  const [detail, setDetail] = useState<ConversationDetaillee | null>(null);
  const [messages, setMessages] = useState<MessageChat[]>([]);
  const [erreur, setErreur] = useState<string | null>(null);

  useEffect((): (() => void) | undefined => {
    setDetail(null);
    setMessages([]);
    if (conversationId === null) {
      return undefined;
    }
    const controle = new AbortController();
    lireConversation(conversationId, controle.signal)
      .then((charge): void => {
        setDetail(charge);
        setMessages(charge.messages);
        setErreur(null);
      })
      .catch((cause: unknown): void => {
        if (controle.signal.aborted) {
          return;
        }
        journal.erreur('conversation illisible', cause);
        setErreur(messageErreur(cause));
      });
    return (): void => controle.abort();
  }, [conversationId]);

  const fusionnerMessages = useCallback((recus: MessageChat[]): void => {
    setMessages((courants) => fusionnerParId(courants, recus));
  }, []);

  return { detail, messages, erreur, setDetail, setMessages, setErreur, fusionnerMessages };
}

/**
 * Relecture de l'historique persisté, bornée à la conversation RÉELLEMENT affichée quand la
 * réponse arrive : une lecture partie pour A et revenue après un changement écraserait le fil de B.
 * La comparaison passe par une référence et non par la valeur capturée dans la closure — cette
 * closure est justement celle de A, elle validerait sa propre écriture.
 */
function useRelectureMessages(
  conversationId: string | null,
  fusionner: (recus: MessageChat[]) => void,
  setErreur: (erreur: string | null) => void,
): (id: string) => Promise<void> {
  const idAffiche = useRef<string | null>(conversationId);
  useEffect((): void => {
    idAffiche.current = conversationId;
  }, [conversationId]);

  return useCallback(
    async (id: string): Promise<void> => {
      try {
        const messages = await listerMessages(id);
        if (id !== idAffiche.current) {
          return;
        }
        fusionner(messages);
      } catch (cause) {
        journal.erreur('historique illisible', cause);
        setErreur(messageErreur(cause));
      }
    },
    [fusionner, setErreur],
  );
}

/*
 * Relecture périodique et au retour, HORS génération seulement : pendant un tour, l'historique relu
 * ne contient pas encore le message optimiste et le ferait disparaître.
 */
function useResyncMessages(
  conversationId: string | null,
  genere: boolean,
  relire: (id: string) => Promise<void>,
): void {
  const genereRef = useRef<boolean>(genere);
  useEffect((): void => {
    genereRef.current = genere;
  }, [genere]);
  useRetourPremierPlan(
    useCallback((): void => {
      if (conversationId !== null && !genereRef.current) {
        void relire(conversationId);
      }
    }, [conversationId, relire]),
    PERIODE_RESYNC_MS,
  );
}

/** Le plan reste affiché après le tour qui l'a posé ; il repart de zéro en changeant de conversation. */
function useDernieresTaches(conversationId: string | null, recues: TacheAgent[] | null): TacheAgent[] | null {
  const [taches, setTaches] = useState<TacheAgent[] | null>(null);
  useEffect((): void => {
    setTaches(null);
  }, [conversationId]);
  useEffect((): void => {
    if (recues !== null && recues.length > 0) {
      setTaches(recues);
    }
  }, [recues]);
  return taches;
}

export function useConversation(conversationId: string | null): EtatConversation {
  const socle = useSocle(conversationId);
  const { fusionnerMessages, setErreur } = socle;
  const rafraichirMessages = useRelectureMessages(conversationId, fusionnerMessages, setErreur);

  const generation = useGeneration(conversationId, rafraichirMessages);
  useResyncMessages(conversationId, generation.genere, rafraichirMessages);
  const taches = useDernieresTaches(conversationId, generation.activite?.activite.taches ?? null);
  const enregistrerReglages = useEnregistrementReglages(conversationId, socle);
  const appliquerReglages = useAppliquerReglages(socle);

  const envoyer = useEnvoi(conversationId, socle, generation.envoyer);

  return {
    detail: socle.detail,
    messages: socle.messages,
    brouillon: generation.brouillon,
    genere: generation.genere,
    erreur: generation.erreur ?? socle.erreur,
    debitObserve: dernierDebit(socle.messages),
    compactionEnCours: generation.compactionEnCours,
    activite: generation.activite,
    taches,
    envoyer,
    annuler: generation.annuler,
    enregistrerReglages,
    appliquerReglages,
  };
}

function useAppliquerReglages(socle: Socle): (reglages: ReglagesConversation) => void {
  const { detail, setDetail } = socle;
  return useCallback(
    (reglages: ReglagesConversation): void => {
      if (detail !== null) {
        setDetail({ ...detail, reglages });
      }
    },
    [detail, setDetail],
  );
}

/*
 * Envoi d'un message. Les commandes (`/compact`, `/clear`) n'arrivent jamais ici : la saisie les
 * exécute elle-même (`chat/commandes`), et « //texte » y est déjà ramené à « /texte ».
 * Dépendance sur `lancerGeneration`, stable, et non sur l'objet d'état reconstruit à chaque fragment
 * reçu : sinon l'identité de `envoyer` change des dizaines de fois par seconde pendant une génération.
 */
function useEnvoi(
  conversationId: string | null,
  socle: Socle,
  lancerGeneration: (contenu: string, fichierIds?: string[]) => Promise<void>,
): (contenu: string, fichierIds?: string[]) => Promise<void> {
  const { messages, setMessages } = socle;
  return useCallback(
    async (contenu: string, fichierIds?: string[]): Promise<void> => {
      if (conversationId === null) {
        return;
      }
      setMessages([...messages, messageLocal(conversationId, contenu)]);
      await lancerGeneration(contenu, fichierIds);
    },
    [conversationId, messages, setMessages, lancerGeneration],
  );
}

function useEnregistrementReglages(
  conversationId: string | null,
  socle: Socle,
): (patch: MajReglages) => Promise<void> {
  const { detail, setDetail, setErreur } = socle;
  return useCallback(
    async (patch: MajReglages): Promise<void> => {
      if (conversationId === null || detail === null) {
        return;
      }
      try {
        const reglages: ReglagesConversation = await ecrireReglages(conversationId, patch);
        setDetail({ ...detail, reglages });
      } catch (cause) {
        journal.erreur('enregistrement des réglages refusé', cause);
        setErreur(messageErreur(cause));
      }
    },
    [conversationId, detail, setDetail, setErreur],
  );
}
