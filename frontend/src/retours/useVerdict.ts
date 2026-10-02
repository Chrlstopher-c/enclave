/*
 * Verdict (et raisons) d'un message, lus une fois par conversation puis tenus à jour localement.
 *
 * Les verdicts d'une conversation sont lus UNE fois (promesse mise en cache par conversation) : chaque
 * réponse du fil n'émet pas sa propre requête. Un verdict comparatif (« meilleure », « pire ») retire
 * le même verdict aux variantes sœurs côté serveur : le cache de la conversation est alors invalidé.
 */

import { useCallback, useEffect, useState } from 'react';
import { envoyerRetour, lireRetours, retirerRetour, type Raison, type ResumeRetours, type Verdict } from './api';

const cache = new Map<string, Promise<ResumeRetours | null>>();

function retoursDe(conversationId: string): Promise<ResumeRetours | null> {
  let promesse = cache.get(conversationId);
  if (promesse === undefined) {
    promesse = lireRetours(conversationId).catch((cause: unknown) => {
      console.error('Lecture des retours impossible', cause);
      cache.delete(conversationId);
      return null;
    });
    cache.set(conversationId, promesse);
  }
  return promesse;
}

export interface EtatVerdict {
  verdict: Verdict | null;
  verdictClaude: Verdict | null;
  raisons: Raison[];
  erreur: string | null;
  noter: (verdict: Verdict, options?: { correction?: string; raisons?: Raison[] }) => Promise<void>;
}

export function useVerdict(conversationId: string, messageId: string): EtatVerdict {
  const [verdict, setVerdict] = useState<Verdict | null>(null);
  const [raisons, setRaisons] = useState<Raison[]>([]);
  const [verdictClaude, setVerdictClaude] = useState<Verdict | null>(null);
  const [erreur, setErreur] = useState<string | null>(null);

  useEffect(() => {
    let actif = true;
    void retoursDe(conversationId).then((resume) => {
      if (!actif || resume === null) return;
      setVerdict(resume.par_message[messageId] ?? null);
      setRaisons(resume.raisons_par_message[messageId] ?? []);
      setVerdictClaude(resume.claude_par_message[messageId] ?? null);
    });
    return () => {
      actif = false;
    };
  }, [conversationId, messageId]);

  const noter = useCallback(
    async (nouveau: Verdict, options: { correction?: string; raisons?: Raison[] } = {}): Promise<void> => {
      const retirer = nouveau === verdict && nouveau !== 'correction' && options.raisons === undefined;
      try {
        if (retirer) await retirerRetour(messageId);
        else await envoyerRetour({ conversation_id: conversationId, message_id: messageId, verdict: nouveau, ...options });
        setVerdict(retirer ? null : nouveau);
        setRaisons(retirer ? [] : (options.raisons ?? []));
        setErreur(null);
        cache.delete(conversationId);
      } catch (cause: unknown) {
        console.error('Retour non enregistré', cause);
        setErreur(cause instanceof Error ? cause.message : 'Retour non enregistré');
      }
    },
    [conversationId, messageId, verdict],
  );

  return { verdict, verdictClaude, raisons, erreur, noter };
}
