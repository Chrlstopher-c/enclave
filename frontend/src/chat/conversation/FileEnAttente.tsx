/*
 * Messages glissés pendant que l'agent travaille, pas encore lus : ils attendent la fin de son étape.
 */

import type { ReactElement } from 'react';
import type { MessageEnAttente } from './useMessagesEnAttente';

const CLASSE_LIGNE =
  'flex items-start gap-2 rounded-sm border border-dashed border-border px-2.5 py-1.5 text-xs text-text-2';

export function FileEnAttente({ messages }: { messages: readonly MessageEnAttente[] }): ReactElement | null {
  if (messages.length === 0) {
    return null;
  }
  return (
    <ul className="mx-auto mb-2 flex max-w-3xl flex-col gap-1" aria-label="Messages en attente">
      {messages.map((message) => (
        <li key={message.id} className={CLASSE_LIGNE}>
          <span className="mt-1 size-1.5 shrink-0 animate-pulse rounded-full bg-accent" aria-hidden="true" />
          <span className="min-w-0 flex-1 whitespace-pre-wrap break-words">{message.texte}</span>
          <span className="shrink-0 text-2xs text-text-3">lu à la fin de l’étape</span>
        </li>
      ))}
    </ul>
  );
}
