import { motion } from 'framer-motion';
import type { ReactElement } from 'react';
import { Badge, Card, cn, Progress, TONE_VAR } from '../../shared/design';
import type { Tone } from '../../shared/design';
import type { TacheAgent } from '../api/contrats';

/*
 * Le plan de l'agent (`suivre_taches`), lisible hors du fil et coché au fil de son avancée.
 *
 * Demandé le 2026-11-10 : l'agent posait un plan en six étapes, mais on ne le voyait que comme un
 * appel d'outil replié dans la conversation. Ici il reste sous les yeux pendant tout le travail, et
 * après : le dernier plan reçu tient jusqu'au changement de conversation.
 */

const ETATS: Record<TacheAgent['etat'], { marque: string; tone: Tone; libelle: string }> = {
  a_faire: { marque: '○', tone: 'neutral', libelle: 'à faire' },
  en_cours: { marque: '◐', tone: 'accent', libelle: 'en cours' },
  fait: { marque: '✓', tone: 'ok', libelle: 'fait' },
  bloque: { marque: '!', tone: 'caution', libelle: 'bloqué' },
  abandonne: { marque: '–', tone: 'neutral', libelle: 'abandonné' },
};

function LigneTache({ tache }: { tache: TacheAgent }): ReactElement {
  const etat = ETATS[tache.etat];
  const signale = tache.etat === 'en_cours' || tache.etat === 'bloque';
  return (
    <motion.li layout className="flex min-w-0 items-start gap-2">
      <span
        aria-hidden
        className="mt-px w-4 shrink-0 text-center text-xs font-semibold"
        style={{ color: TONE_VAR[etat.tone] }}
      >
        {etat.marque}
      </span>
      <span
        className={cn(
          'min-w-0 flex-1 text-xs leading-relaxed',
          tache.etat === 'fait' && 'text-text-3',
          tache.etat === 'abandonne' && 'text-text-3 line-through',
          tache.etat === 'en_cours' && 'font-medium text-text',
          (tache.etat === 'a_faire' || tache.etat === 'bloque') && 'text-text-2',
        )}
      >
        {tache.titre}
      </span>
      {signale && (
        <Badge tone={etat.tone} dot={tache.etat === 'en_cours'} pulse={tache.etat === 'en_cours'}>
          {etat.libelle}
        </Badge>
      )}
    </motion.li>
  );
}

export interface PlanAgentProps {
  taches: TacheAgent[] | null;
}

export function PlanAgent({ taches }: PlanAgentProps): ReactElement | null {
  if (taches === null || taches.length === 0) {
    return null;
  }
  const faites = taches.filter((tache) => tache.etat === 'fait').length;
  return (
    <Card title="Plan de l'agent" padding="sm">
      <div className="min-w-0 space-y-3">
        <Progress value={faites} max={taches.length} tone="ok" format={(v, m) => `${v} / ${m}`} />
        <ul className="min-w-0 space-y-1.5">
          {taches.map((tache, index) => (
            <LigneTache key={`${index}-${tache.titre}`} tache={tache} />
          ))}
        </ul>
      </div>
    </Card>
  );
}
