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
} from '../api/contrats';
import { ecrireReglages, lireConversation, listerMessages } from '../api/conversations-api';
import { journal } from '../api/journal';
import { useGeneration } from './useGeneration';

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
  envoyer: (contenu: string, fichierIds?: string[]) => Promise<void>;
  annuler: () => Promise<void>;
  enregistrerReglages: (patch: MajReglages) => Promise<void>;
}

interface Socle {
  detail: ConversationDetaillee | null;
  messages: MessageChat[];
  erreur: string | null;
  setDetail: (detail: ConversationDetaillee) => void;
  setMessages: (messages: MessageChat[]) => void;
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

  return { detail, messages, erreur, setDetail, setMessages, setErreur };
}

/**
 * Relecture de l'historique persisté, bornée à la conversation RÉELLEMENT affichée quand la
 * réponse arrive : une lecture partie pour A et revenue après un changement écraserait le fil de B.
 * La comparaison passe par une référence et non par la valeur capturée dans la closure — cette
 * closure est justement celle de A, elle validerait sa propre écriture.
 */
function useRelectureMessages(
  conversationId: string | null,
  setMessages: (messages: MessageChat[]) => void,
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
        setMessages(messages);
      } catch (cause) {
        journal.erreur('historique illisible', cause);
        setErreur(messageErreur(cause));
      }
    },
    [setMessages, setErreur],
  );
}

export function useConversation(conversationId: string | null): EtatConversation {
  const socle = useSocle(conversationId);
  const { setMessages, setErreur } = socle;
  const rafraichirMessages = useRelectureMessages(conversationId, setMessages, setErreur);

  const generation = useGeneration(conversationId, rafraichirMessages);
  const enregistrerReglages = useEnregistrementReglages(conversationId, socle);

  // Dépendance sur `generation.envoyer`, stable, et non sur l'objet d'état reconstruit à chaque
  // fragment reçu : sinon l'identité de `envoyer` change des dizaines de fois par seconde pendant
  // une génération, et toute mise en dépendance ultérieure boucle.
  const { envoyer: lancerGeneration } = generation;
  const envoyer = useCallback(
    async (contenu: string, fichierIds?: string[]): Promise<void> => {
      if (conversationId === null) {
        return;
      }
      setMessages([...socle.messages, messageLocal(conversationId, contenu)]);
      await lancerGeneration(contenu, fichierIds);
    },
    [conversationId, socle.messages, setMessages, lancerGeneration],
  );

  return {
    detail: socle.detail,
    messages: socle.messages,
    brouillon: generation.brouillon,
    genere: generation.genere,
    erreur: generation.erreur ?? socle.erreur,
    debitObserve: dernierDebit(socle.messages),
    compactionEnCours: generation.compactionEnCours,
    envoyer,
    annuler: generation.annuler,
    enregistrerReglages,
  };
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
