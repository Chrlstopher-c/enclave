/*
 * Fil de la conversation. Le défilement suit le texte tant que l'utilisateur est au bas du fil ;
 * dès qu'il remonte pour relire, on cesse de le suivre — un fil qui reprend la main pendant qu'on
 * lit est le défaut le plus pénible d'une interface de chat.
 *
 * Quand le suivi est décroché, une pastille « reprendre le fil » apparaît au-dessus du composeur :
 * revenir en bas après avoir relu trois écrans plus haut est un geste, pas une glissade — surtout
 * au doigt, où le fil peut faire plusieurs milliers de pixels pendant une génération.
 *
 * COMMANDES — le fil masque ce qu'un `/clear` a effacé (séparateur annulable à sa place) et montre
 * la progression d'une `/compact` en cours au bas du fil. L'état vient du magasin des commandes,
 * indexé par la conversation des messages affichés : le fil n'a pas besoin qu'on la lui passe.
 */

import { AnimatePresence, motion } from 'framer-motion';
import { useEffect, useRef, useState } from 'react';
import type { ReactElement } from 'react';
import { cn, fadeUp } from '../../shared/design';
import type { InfoCompaction, MessageChat } from '../api/contrats';
import {
  CarteCommande,
  ecarterCommande,
  masquerEfface,
  SeparateurEffacement,
  useEffacements,
  useEtatCommandes,
  type EtatCommandes,
  type EtatEffacements,
  type VueEffacee,
} from '../commandes';
import { BaliseCompaction } from './BaliseCompaction';
import { ActiviteEnDirect } from './ActiviteEnDirect';
import { Message, MessageEnCours } from './Message';
import type { ActiviteRecue } from './useGeneration';

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
  /** Ce que le moteur fait en ce moment : débit, phase, fichier en cours d'écriture. */
  activite?: ActiviteRecue | null;
  vide: ReactElement;
}

interface SuiviDefilement {
  conteneur: { current: HTMLDivElement | null };
  decroche: boolean;
  surDefilement: () => void;
  reprendre: () => void;
}

function useSuiviDefilement(messages: MessageChat[], brouillon: string | null, autre: unknown): SuiviDefilement {
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
  }, [messages, brouillon, autre]);

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

/* La balise d'une `/compact` qui vient de finir passe avant celle, plus ancienne, du fil pas encore relu. */
function baliseDe(message: MessageChat, commandes: EtatCommandes): InfoCompaction | null {
  if (commandes.compaction !== null && commandes.compaction.message_id === message.id) {
    return commandes.compaction;
  }
  // `?? null` : un message servi par un backend antérieur à la compaction n'a pas ce champ.
  return message.compaction ?? null;
}

function useCommandesDuFil(messages: MessageChat[]): {
  conversationId: string | null;
  commandes: EtatCommandes;
  effacements: EtatEffacements;
} {
  const conversationId = messages[0]?.conversation_id ?? null;
  const commandes = useEtatCommandes(conversationId);
  const effacements = useEffacements(conversationId, commandes.effacements !== null);
  return { conversationId, commandes, effacements };
}

export function FilMessages(props: FilMessagesProps): ReactElement {
  const { messages, brouillon, vide } = props;
  const { conversationId, commandes, effacements } = useCommandesDuFil(messages);
  const vue = masquerEfface(messages, commandes.effacements ?? []);
  const { conteneur, decroche, surDefilement, reprendre } = useSuiviDefilement(
    messages, brouillon, commandes.commande?.commande.etape ?? vue.masques,
  );
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
          <CorpsFil {...props} vue={vue} conversationId={conversationId} commandes={commandes}
            effacements={effacements} />
        )}
      </div>
      <PastilleReprise visible={decroche && !aucunContenu} onReprendre={reprendre} />
    </div>
  );
}

interface CorpsFilProps extends Omit<FilMessagesProps, 'messages'> {
  vue: VueEffacee;
  conversationId: string | null;
  commandes: EtatCommandes;
  effacements: EtatEffacements;
}

function MessagesVisibles({ vue, commandes }: { vue: VueEffacee; commandes: EtatCommandes }): ReactElement {
  return (
    <>
      {vue.visibles.map((message) => {
        const balise = baliseDe(message, commandes);
        return (
          <div key={message.id} className="flex flex-col gap-6">
            {balise !== null && <BaliseCompaction compaction={balise} />}
            <Message message={message} />
          </div>
        );
      })}
    </>
  );
}

function CarteDuFil({ conversationId, commandes }: { conversationId: string | null; commandes: EtatCommandes }):
ReactElement {
  return (
    <AnimatePresence>
      {commandes.commande !== null && conversationId !== null && (
        <CarteCommande
          key={commandes.commande.commande.id}
          recue={commandes.commande}
          onFermer={() => ecarterCommande(conversationId)}
        />
      )}
    </AnimatePresence>
  );
}

/* Après un `/clear` qui a tout masqué, l'accueil d'une conversation neuve revient SOUS le séparateur. */
function CorpsFil(props: CorpsFilProps): ReactElement {
  const { vue, brouillon, compactionEnCours, activite = null, commandes, effacements } = props;
  const filVide = vue.visibles.length === 0 && brouillon === null && commandes.commande === null;
  const effacement = vue.effacement;
  return (
    <div className="mx-auto flex min-h-full max-w-3xl flex-col gap-6">
      {effacement !== null && (
        <SeparateurEffacement
          effacement={effacement}
          masques={vue.masques}
          enAnnulation={effacements.enAnnulation}
          erreur={effacements.erreur}
          onAnnuler={() => void effacements.annuler(effacement.id)}
        />
      )}
      <MessagesVisibles vue={vue} commandes={commandes} />
      {compactionEnCours != null && <BaliseCompaction compaction={compactionEnCours} />}
      {brouillon !== null && <MessageEnCours texte={brouillon} />}
      {brouillon !== null && <ActiviteEnDirect activite={activite} />}
      <CarteDuFil conversationId={props.conversationId} commandes={commandes} />
      {filVide && <div className="flex-1">{props.vide}</div>}
    </div>
  );
}
