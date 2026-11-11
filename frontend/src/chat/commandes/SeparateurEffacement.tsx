/*
 * Séparateur posé à la place des messages masqués par un `/clear`.
 *
 * Même grammaire que la balise de compaction (filets de part et d'autre, centré, sans auteur) :
 * c'est un événement de système, pas un message. L'action « Revenir à l'état précédent » est un
 * lien pervenche — une action possible, réversible, qui n'appelle aucune mise en garde.
 */

import { motion } from 'framer-motion';
import type { ReactElement } from 'react';
import { cn, fadeUp } from '../../shared/design';
import type { InfoEffacement } from './contrats';
import { heureEffacement } from './masquage';

export interface SeparateurEffacementProps {
  effacement: InfoEffacement;
  masques: number;
  enAnnulation: boolean;
  erreur: string | null;
  onAnnuler: () => void;
}

export function SeparateurEffacement(props: SeparateurEffacementProps): ReactElement {
  const { effacement, masques, enAnnulation } = props;
  return (
    <motion.section variants={fadeUp} initial="hidden" animate="visible" aria-label="Contexte vidé">
      <div className="flex items-center gap-3">
        <span className="h-px flex-1 bg-border" aria-hidden="true" />
        <p className="flex min-w-0 flex-wrap items-center justify-center gap-x-2 gap-y-1 text-center text-2xs">
          <span className="font-medium text-text-2">Contexte vidé · {heureEffacement(effacement.cree_le)}</span>
          <span className="font-mono tabular-nums text-text-3">
            {masques} message{masques > 1 ? 's' : ''} masqué{masques > 1 ? 's' : ''}
          </span>
          <button
            type="button"
            onClick={props.onAnnuler}
            disabled={enAnnulation}
            className={cn(
              'min-h-[44px] rounded-xs px-1.5 font-medium text-accent transition-colors duration-fast lg:min-h-0',
              'hover:bg-accent-soft focus-visible:outline-none focus-visible:shadow-[0_0_0_3px_var(--ring)]',
              'disabled:opacity-45',
            )}
          >
            {enAnnulation ? 'Restauration…' : 'Revenir à l’état précédent'}
          </button>
        </p>
        <span className="h-px flex-1 bg-border" aria-hidden="true" />
      </div>
      {props.erreur !== null && <p className="mt-1 text-center text-2xs text-caution">{props.erreur}</p>}
    </motion.section>
  );
}
