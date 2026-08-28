/*
 * Fil de la conversation. Le défilement suit le texte tant que l'utilisateur est au bas du fil ;
 * dès qu'il remonte pour relire, on cesse de le suivre — un fil qui reprend la main pendant qu'on
 * lit est le défaut le plus pénible d'une interface de chat.
 *
 * Quand le suivi est décroché, une pastille « reprendre le fil » apparaît au-dessus du composeur :
 * revenir en bas après avoir relu trois écrans plus haut est un geste, pas une glissade — surtout
 * au doigt, où le fil peut faire plusieurs milliers de pixels pendant une génération.
 */

import { AnimatePresence, motion } from 'framer-motion';
import { useEffect, useRef, useState } from 'react';
import type { ReactElement } from 'react';
import { cn, fadeUp } from '../../shared/design';
import type { InfoCompaction, MessageChat } from '../api/contrats';
import { BaliseCompaction } from './BaliseCompaction';
import { Message, MessageEnCours } from './Message';

/* Marge sous laquelle on considère l'utilisateur « au bas du fil ». */
const SEUIL_BAS_PX = 64;

function estEnBas(element: HTMLElement): boolean {
  return element.scrollHeight - element.scrollTop - element.clientHeight < SEUIL_BAS_PX;
}

function PastilleReprise({ visible, onReprendre }: { visible: boolean; onReprendre: () => void }): ReactElement {
  return (
    <AnimatePresence>
      {visible && (
        <motion.button
          type="button"
          variants={fadeUp}
          initial="hidden"
          animate="visible"
          exit="exit"
          onClick={onReprendre}
          className={cn(
            'absolute bottom-3 left-1/2 z-10 -translate-x-1/2 rounded-full border border-border bg-overlay',
            'px-3 py-1.5 text-2xs text-text-2 shadow-2 transition-colors duration-fast',
            'hover:text-text focus-visible:outline-none focus-visible:shadow-[0_0_0_3px_var(--ring)]',
          )}
        >
          ↓ reprendre le fil
        </motion.button>
      )}
    </AnimatePresence>
  );
}

export interface FilMessagesProps {
  messages: MessageChat[];
  brouillon: string | null;
  /**
   * Balise émise en DIRECT pour la réponse en cours, avant qu'elle ne soit persistée : elle se rend
   * au-dessus du brouillon. Au rechargement, la même balise revient portée par `message.compaction`.
   */
  compactionEnCours: InfoCompaction | null;
  vide: ReactElement;
}

interface SuiviDefilement {
  conteneur: { current: HTMLDivElement | null };
  decroche: boolean;
  surDefilement: () => void;
  reprendre: () => void;
}

function useSuiviDefilement(messages: MessageChat[], brouillon: string | null): SuiviDefilement {
  const conteneur = useRef<HTMLDivElement | null>(null);
  const suit = useRef<boolean>(true);
  // Doublon d'état volontaire : `suit` pilote le défilement à chaque fragment sans re-rendu,
  // `decroche` ne change qu'aux franchissements du seuil et ne re-rend que la pastille.
  const [decroche, setDecroche] = useState<boolean>(false);

  useEffect((): void => {
    const element = conteneur.current;
    if (element === null || !suit.current) {
      return;
    }
    element.scrollTop = element.scrollHeight;
  }, [messages, brouillon]);

  const surDefilement = (): void => {
    const element = conteneur.current;
    if (element !== null) {
      suit.current = estEnBas(element);
      setDecroche(!suit.current);
    }
  };

  const reprendre = (): void => {
    const element = conteneur.current;
    if (element !== null) {
      element.scrollTop = element.scrollHeight;
      suit.current = true;
      setDecroche(false);
    }
  };

  return { conteneur, decroche, surDefilement, reprendre };
}

export function FilMessages({
  messages,
  brouillon,
  compactionEnCours,
  vide,
}: FilMessagesProps): ReactElement {
  const { conteneur, decroche, surDefilement, reprendre } = useSuiviDefilement(messages, brouillon);
  const aucunContenu = messages.length === 0 && brouillon === null;
  return (
    // `min-h-0` : sans lui, ce bloc flex refuse de rétrécir sous la hauteur de son contenu et pousse
    // le composeur hors de l'écran dès que le fil s'allonge — visible d'abord sur petit écran.
    <div className="relative min-h-0 flex-1">
      <div
        ref={conteneur}
        onScroll={surDefilement}
        className="h-full overflow-y-auto px-3 py-4 lg:px-6 lg:py-5"
      >
        {aucunContenu ? (
          vide
        ) : (
          <div className="mx-auto flex max-w-3xl flex-col gap-6">
            {messages.map((message) => (
              <div key={message.id} className="flex flex-col gap-6">
                {/* `!= null` et non `!== null` : un message servi par un backend antérieur à la
                    compaction n'a pas du tout ce champ — il vaut `undefined`, pas `null`. */}
                {message.compaction != null && <BaliseCompaction compaction={message.compaction} />}
                <Message message={message} />
              </div>
            ))}
            {compactionEnCours != null && <BaliseCompaction compaction={compactionEnCours} />}
            {brouillon !== null && <MessageEnCours texte={brouillon} />}
          </div>
        )}
      </div>
      <PastilleReprise visible={decroche && !aucunContenu} onReprendre={reprendre} />
    </div>
  );
}
