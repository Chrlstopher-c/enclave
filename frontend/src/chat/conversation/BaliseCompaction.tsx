/*
 * Balise de compaction du contexte — un ÉVÉNEMENT DE SYSTÈME dans le fil, pas un message.
 *
 * Elle reprend la grammaire des replis (même chevron, même mécanique de dépliage que
 * `BlocRaisonnement` et `CarteOutil`) mais s'en distingue : centrée, encadrée d'un filet, elle ne
 * s'attribue à aucun auteur. Elle dit ce que le MOTEUR relit désormais à la place des tours anciens —
 * l'historique complet, lui, reste au-dessus, intact. Aucune couleur en dur : les tokens de thème
 * seuls, comme partout dans le fil.
 */

import { AnimatePresence, motion } from 'framer-motion';
import { useId, useState } from 'react';
import type { ReactElement } from 'react';
import { cn, fadeUp } from '../../shared/design';
import { Chevron } from '../raisonnement/Chevron';
import type { InfoCompaction } from '../api/contrats';

const NOMBRE = new Intl.NumberFormat('fr-FR');

/* Le résumé peut être long : déplié, il défile chez lui plutôt que de pousser le fil. */
const CLASSE_DEFILEMENT = 'max-h-72 overflow-y-auto overscroll-contain';

function pourcent(tokens: number, total: number): string {
  if (total <= 0) {
    return '—';
  }
  return `${Math.round((tokens / total) * 100)} %`;
}

interface EnteteProps {
  compaction: InfoCompaction;
  ouvert: boolean;
  cible: string;
  onBasculer: () => void;
}

function Entete({ compaction, ouvert, cible, onBasculer }: EnteteProps): ReactElement {
  const avant = pourcent(compaction.tokens_avant, compaction.contexte_total);
  const apres = pourcent(compaction.tokens_apres, compaction.contexte_total);
  return (
    <button
      type="button"
      onClick={onBasculer}
      aria-expanded={ouvert}
      aria-controls={cible}
      className={cn(
        'flex w-full min-h-[44px] flex-wrap items-center justify-center gap-x-2 gap-y-1 rounded-sm px-2.5 py-2',
        'text-center text-2xs text-text-3 lg:min-h-0 lg:flex-nowrap lg:py-1',
        'transition-colors duration-fast ease-out hover:bg-surface hover:text-text-2',
        'focus-visible:outline-none focus-visible:shadow-[0_0_0_3px_var(--ring)]',
      )}
    >
      <Chevron ouvert={ouvert} />
      <span aria-hidden="true">🗜</span>
      <span className="font-medium">Contexte compacté</span>
      <span className="font-mono tabular-nums">
        {NOMBRE.format(compaction.nb_messages_resumes)} messages résumés
      </span>
      <span className="font-mono tabular-nums text-text-2">
        {avant} → {apres}
      </span>
    </button>
  );
}

export interface BaliseCompactionProps {
  compaction: InfoCompaction;
}

export function BaliseCompaction({ compaction }: BaliseCompactionProps): ReactElement {
  const [ouvert, setOuvert] = useState<boolean>(false);
  const cible = useId();
  return (
    // Un filet de part et d'autre : la balise coupe visuellement le fil à l'endroit de la coupe
    // réelle, sans s'imposer comme une bulle.
    <section className="my-1 flex items-center gap-3" aria-label="Compaction du contexte">
      <span className="h-px flex-1 bg-border" aria-hidden="true" />
      <div className="min-w-0 max-w-xl flex-[0_1_auto]">
        <Entete compaction={compaction} ouvert={ouvert} cible={cible} onBasculer={() => setOuvert(!ouvert)} />
        <AnimatePresence initial={false}>
          {ouvert && (
            <motion.div id={cible} variants={fadeUp} initial="hidden" animate="visible" exit="exit">
              <div className={cn('rounded-sm border border-border bg-surface px-3 py-2', CLASSE_DEFILEMENT)}>
                <p className="whitespace-pre-wrap text-xs leading-relaxed text-text-2">{compaction.resume}</p>
              </div>
            </motion.div>
          )}
        </AnimatePresence>
      </div>
      <span className="h-px flex-1 bg-border" aria-hidden="true" />
    </section>
  );
}
