/*
 * Enveloppe d'un message : ce qui rend ses actions et ses variantes atteignables.
 *
 * Trois contraintes tiennent la mise en page :
 *
 * 1. Rien ne bouge à l'apparition. La rangée d'actions est HORS FLUX (`absolute` dans un conteneur
 *    de hauteur nulle, ancré au bas du message) : elle se pose dans l'espace inter-messages sans
 *    jamais repousser le texte. Réserver sa hauteur en flux coûterait une bande vide sous chaque
 *    message, sur un écran dont DESIGN.md exige la densité.
 * 2. Survol ET focus clavier. `group-hover` seul rendrait les actions inatteignables sans souris ;
 *    `group-focus-within` les révèle dès qu'un de leurs boutons prend le focus par tabulation.
 * 3. Sous 1024 px, la rangée est VISIBLE EN PERMANENCE et rendue EN FLUX sous le message. Le survol
 *    n'existe pas au doigt : une action seulement au survol est une action absente. Elle passe en
 *    flux parce que ses boutons y font 44 px de haut — hors flux, ils recouvriraient le message
 *    suivant, l'espace inter-messages n'en faisant que 20. Rien ne « bouge à l'apparition » pour
 *    autant : sur ces écrans la rangée n'apparaît jamais, elle est là dès le rendu. À partir de
 *    `lg:`, le comportement de bureau est restitué à l'identique.
 *
 * La navigation entre variantes, elle, n'est PAS conditionnée au survol — c'est une information sur
 * l'état de la conversation, pas une action.
 */

import type { ReactElement, ReactNode } from 'react';
import { BoutonsRetour } from '../../retours';
import type { MessageChat } from '../api/contrats';
import { useActionsMessages, type ActionsMessages } from './fournisseur';
import { EditeurEnPlace } from './EditeurEnPlace';
import { NavigationBranches } from './NavigationBranches';
import { RangeeActions } from './RangeeActions';

const CLASSE_REVELEE =
  'ml-auto pointer-events-auto opacity-100 transition-opacity duration-fast ease-out ' +
  'lg:pointer-events-none lg:opacity-0 ' +
  'lg:group-hover/msg:pointer-events-auto lg:group-hover/msg:opacity-100 ' +
  'lg:group-focus-within/msg:pointer-events-auto lg:group-focus-within/msg:opacity-100';

/* En flux sous le message au doigt, hors flux (ancré au bas du message) à partir de `lg:`. */
const CLASSE_BARRE =
  'mt-1 flex flex-wrap items-start gap-2 ' +
  'lg:pointer-events-none lg:absolute lg:inset-x-0 lg:top-full lg:z-10 lg:mt-0 lg:h-0 lg:flex-nowrap';

interface BarreProps {
  message: MessageChat;
  actions: ActionsMessages;
}

function Barre({ message, actions }: BarreProps): ReactElement {
  const freres = actions.variantes[message.id] ?? [];
  const index = freres.indexOf(message.id);
  const activer = (cible: string | undefined): void => {
    if (cible !== undefined) {
      actions.activerVariante(cible);
    }
  };
  return (
    <div className={CLASSE_BARRE}>
      {index >= 0 && freres.length > 1 && (
        <span className="pointer-events-auto pt-1">
          <NavigationBranches
            position={index + 1}
            total={freres.length}
            occupe={actions.occupe}
            onPrecedente={() => activer(freres[index - 1])}
            onSuivante={() => activer(freres[index + 1])}
          />
        </span>
      )}
      <span className={CLASSE_REVELEE}>
        <RangeeActions
          texte={message.contenu}
          editable={message.role === 'user'}
          rejouable={message.role !== 'system'}
          occupe={actions.occupe}
          onEditer={() => actions.demarrerEdition(message)}
          onRejouer={() => actions.rejouer(message)}
        >
          {message.role === 'assistant' && !message.interrompu && (
            <BoutonsRetour conversationId={message.conversation_id} messageId={message.id} contenu={message.contenu}
              comparaison={freres.length > 1} />
          )}
        </RangeeActions>
      </span>
    </div>
  );
}

interface CorpsProps extends BarreProps {
  children: ReactNode;
}

function CorpsActionnable({ message, actions, children }: CorpsProps): ReactElement {
  if (actions.messageEnEdition === message.id) {
    return (
      <EditeurEnPlace
        contenuInitial={message.contenu}
        occupe={actions.occupe}
        onAnnuler={actions.annulerEdition}
        onConfirmer={(contenu) => actions.confirmerEdition(message, contenu)}
      />
    );
  }
  return (
    <div className="group/msg relative">
      {children}
      <Barre message={message} actions={actions} />
    </div>
  );
}

export interface EnveloppeMessageProps {
  message: MessageChat;
  /** Le message rendu tel qu'il l'est déjà : bulle utilisateur ou Markdown de la réponse. */
  children: ReactNode;
}

/**
 * À poser autour du corps d'un message dans le fil. Hors fournisseur d'actions, elle est neutre et
 * rend ses enfants inchangés : un message affiché dans un autre contexte reste un message.
 */
export function EnveloppeMessage({ message, children }: EnveloppeMessageProps): ReactElement {
  const actions = useActionsMessages();
  if (actions === null) {
    return <>{children}</>;
  }
  return (
    <CorpsActionnable message={message} actions={actions}>
      {children}
    </CorpsActionnable>
  );
}
