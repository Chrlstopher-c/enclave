/*
 * Étapes d'une compaction, en ligne : un point et un libellé par étape, reliés par un filet.
 * Fait → vert (état sain atteint), en cours → pervenche pulsée (activité réelle), à faire → gris.
 * Aucune barre de pourcentage : le serveur ne connaît pas la part restante, il dit l'étape.
 */

import type { ReactElement } from 'react';
import { cn } from '../../shared/design';
import type { EtapeCommande, EtatEtape } from './contrats';

const POINT: Record<EtatEtape, string> = {
  fait: 'bg-ok',
  en_cours: 'bg-accent animate-eh-pulse',
  a_faire: 'border border-border-strong bg-transparent',
};

const LIBELLE: Record<EtatEtape, string> = {
  fait: 'text-text-2',
  en_cours: 'font-medium text-text',
  a_faire: 'text-text-3',
};

export function EtapesProgression({ etapes, echec = false }: { etapes: readonly EtapeCommande[]; echec?: boolean }):
ReactElement {
  return (
    <ol className="flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1 text-2xs" aria-label="Étapes">
      {etapes.map((etape, index) => (
        <li
          key={etape.cle}
          className="flex items-center gap-2"
          aria-current={etape.etat === 'en_cours' ? 'step' : undefined}
        >
          {index > 0 && <span className="h-px w-4 bg-border" aria-hidden="true" />}
          <span
            aria-hidden="true"
            className={cn(
              'h-1.5 w-1.5 shrink-0 rounded-full',
              echec && etape.etat === 'en_cours' ? 'bg-caution' : POINT[etape.etat],
            )}
          />
          <span className={LIBELLE[etape.etat]}>{etape.libelle}</span>
        </li>
      ))}
    </ol>
  );
}
