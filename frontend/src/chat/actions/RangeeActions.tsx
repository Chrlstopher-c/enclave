/*
 * Rangée d'actions d'un message : copier, modifier, rejouer.
 *
 * Une rangée plutôt qu'un bouton flottant unique : à trois icônes, un cluster posé sur le coin
 * d'une bulle devient illisible et se marche dessus avec le pied de message.
 *
 * Rien n'est masqué selon le contexte : un bouton indisponible est DÉSACTIVÉ et dit pourquoi par
 * son `title`. Une action qui disparaît rend la rangée imprévisible — on ne sait plus si elle
 * n'existe pas ou si on l'a manquée.
 */

import type { ReactElement, ReactNode } from 'react';
import { cn } from '../../shared/design';
import { BoutonAction } from './BoutonAction';
import { BoutonCopier } from './BoutonCopier';
import { IconeEditer, IconeRejouer } from './icones';

const MOTIF_OCCUPE = 'Une génération est en cours';
const MOTIF_EDITER = 'Modifier — crée une variante, l’original est conservé';
const MOTIF_REJOUER = 'Rejouer — crée une variante, la réponse actuelle est conservée';

/*
 * `bg-overlay` et non `bg-surface-2` : la rangée flotte au-dessus du fil ET au-dessus de la bulle
 * utilisateur, qui est elle-même en `surface-2` — elle y deviendrait invisible.
 */
const CLASSE_RANGEE =
  'inline-flex items-center gap-0.5 rounded-sm border border-border bg-overlay px-1 py-0.5 shadow-1';

export interface RangeeActionsProps {
  /** Texte exact du message — pour une réponse, la source Markdown telle que le modèle l'a écrite. */
  texte: string;
  editable: boolean;
  /** Faux sur un message `system` : le backend refuse d'y brancher quoi que ce soit (422). */
  rejouable: boolean;
  /** Génération en cours : rejeu et modification refusés ; la copie, elle, reste possible. */
  occupe: boolean;
  onEditer: () => void;
  onRejouer: () => void;
  className?: string;
  /** Actions venues d'un autre domaine (notes de `retours` sous une réponse), posées en fin de rangée. */
  children?: ReactNode;
}

export function RangeeActions({
  texte,
  editable,
  rejouable,
  occupe,
  onEditer,
  onRejouer,
  className,
  children,
}: RangeeActionsProps): ReactElement {
  return (
    <span className={cn(CLASSE_RANGEE, className)}>
      <BoutonCopier texte={texte} />
      {editable && (
        <BoutonAction
          libelle="Modifier ce message"
          titre={occupe ? MOTIF_OCCUPE : MOTIF_EDITER}
          desactive={occupe}
          onClic={onEditer}
        >
          <IconeEditer />
        </BoutonAction>
      )}
      {rejouable && (
        <BoutonAction
          libelle="Rejouer à partir de ce message"
          titre={occupe ? MOTIF_OCCUPE : MOTIF_REJOUER}
          desactive={occupe}
          onClic={onRejouer}
        >
          <IconeRejouer />
        </BoutonAction>
      )}
      {children}
    </span>
  );
}
