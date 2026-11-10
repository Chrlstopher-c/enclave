/*
 * Messages glissés pendant que l'agent travaille (demandé par Chris le 2026-11-10, comme Claude Code).
 *
 * Envoyé pendant une génération, un message n'interrompt rien : il part en file côté serveur et
 * l'agent le lit à la fin de son étape en cours (outil, écriture…). Sa lecture se voit dans la
 * réponse (`<consigne>id:…`), et il quitte alors la file affichée. Ce qui n'a pas été lu quand la
 * génération s'arrête part comme un message ordinaire.
 */

import { useCallback, useEffect, useRef, useState } from 'react';
import { glisserConsigne } from '../api/conversations-api';
import { journal } from '../api/journal';

export interface MessageEnAttente {
  readonly id: string;
  readonly texte: string;
}

export interface EtatMessagesEnAttente {
  enAttente: readonly MessageEnAttente[];
  glisser: (texte: string) => void;
}

const LUE = /<consigne>id:([\w-]+)\n/g;

function nouvelId(): string {
  return `c${Date.now().toString(36)}${Math.random().toString(36).slice(2, 8)}`;
}

function idsLus(brouillon: string | null): Set<string> {
  return new Set(brouillon === null ? [] : Array.from(brouillon.matchAll(LUE), (trouve) => trouve[1] ?? ''));
}

export function useMessagesEnAttente(
  conversationId: string | null,
  genere: boolean,
  brouillon: string | null,
  envoyer: (texte: string) => void,
): EtatMessagesEnAttente {
  const [enAttente, setEnAttente] = useState<readonly MessageEnAttente[]>([]);
  // Miroir synchrone de la file : un envoi ne doit jamais partir depuis un `setState` (rejoué en mode strict).
  const file = useRef<readonly MessageEnAttente[]>([]);
  const envoyerRef = useRef(envoyer);
  envoyerRef.current = envoyer;
  const remplacer = useCallback((suivante: readonly MessageEnAttente[]): void => {
    file.current = suivante;
    setEnAttente(suivante);
  }, []);

  useEffect((): void => {
    remplacer([]);
  }, [conversationId, remplacer]);

  useEffect((): void => {
    const lus = idsLus(brouillon);
    if (lus.size > 0 && file.current.some((message) => lus.has(message.id))) {
      remplacer(file.current.filter((message) => !lus.has(message.id)));
    }
  }, [brouillon, remplacer]);

  // Génération finie : ce qui n'a pas été lu part comme un message ordinaire, en un seul envoi.
  useEffect((): void => {
    if (genere || file.current.length === 0) {
      return;
    }
    const restes = file.current;
    remplacer([]);
    envoyerRef.current(restes.map((message) => message.texte).join('\n\n'));
  }, [genere, remplacer]);

  const glisser = useCallback(
    (texte: string): void => {
      if (conversationId === null) {
        return;
      }
      const message = { id: nouvelId(), texte };
      remplacer([...file.current, message]);
      glisserConsigne(conversationId, message.id, texte)
        .then(({ acceptee }): void => {
          // Refusée (plus de génération) : elle part maintenant, sauf si la fin de génération l'a déjà envoyée.
          if (!acceptee && file.current.some((m) => m.id === message.id)) {
            remplacer(file.current.filter((m) => m.id !== message.id));
            envoyerRef.current(texte);
          }
        })
        .catch((cause: unknown): void => {
          // La file locale le garde : il partira comme message ordinaire à la fin de la génération.
          journal.erreur('consigne non transmise', cause);
        });
    },
    [conversationId, remplacer],
  );

  return { enAttente, glisser };
}
