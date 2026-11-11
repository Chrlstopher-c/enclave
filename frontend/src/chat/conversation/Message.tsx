/*
 * Un message du fil. Le tour utilisateur reste du texte brut dans une surface distincte, aligné à
 * droite ; la réponse du modèle est rendue en Markdown sur toute la largeur, comme un document.
 * La distinction d'auteur vient de la position et de la surface — jamais d'une couleur : l'accent
 * est réservé aux actions et à l'activité (DESIGN.md).
 *
 * Sous chaque réponse, une ligne de mesures à la manière du panneau de plan : mono, chiffres
 * tabulaires, texte tertiaire. Chaque valeur vient du backend et n'apparaît que si elle existe —
 * un moteur qui ne rapporte pas son débit ne se voit pas attribuer un chiffre inventé.
 *
 * Au survol (ou au focus, pour le clavier), chaque message dit QUAND il a été écrit — et une
 * réponse, combien de temps elle a pris. Révélé plutôt qu'affiché en permanence : c'est une
 * information qu'on va chercher, pas une qu'on lit à chaque tour.
 */

/* Révélation au survol du message ; toujours visible au doigt, où le survol n'existe pas. */
const CLASSE_REVELEE =
  'opacity-100 transition-opacity duration-fast lg:opacity-0 lg:group-hover:opacity-100 ' +
  'lg:group-focus-within:opacity-100';

import { motion } from 'framer-motion';
import type { ReactElement } from 'react';
import { Badge, cn, fadeUp } from '../../shared/design';
import type { MessageChat } from '../api/contrats';
import { EnveloppeMessage } from '../actions';
import { dureeGeneration, horodatageLisible } from '../commandes';
import { ReponseModele } from '../raisonnement';
import { formaterDebit, formaterHeure } from '../plan/format';

/*
 * Le modèle est affiché À CÔTÉ des mesures parce qu'il les qualifie : 31 tok/s ne veut rien dire
 * sans savoir qui a produit ces tokens, et une conversation peut changer de modèle en cours de
 * route. `modele_id` est celui enregistré au moment de la réponse — pas le modèle chargé
 * maintenant, qui pourrait déjà être un autre.
 *
 * Seul le nom de fichier est montré : l'identifiant complet vaut `<depot>::<fichier>` et
 * occuperait toute la ligne. Le reste est dans l'infobulle.
 */
function nomCourt(identifiant: string): string {
  const apresDepot = identifiant.split('::').at(-1) ?? identifiant;
  return apresDepot.replace(/\.gguf$/i, '');
}

function Mesures({ message }: { message: MessageChat }): ReactElement {
  const debit = message.tokens_par_seconde;
  const tokens = message.tokens_generes;
  const modele = message.modele_id;
  return (
    <div className="mt-1.5 flex flex-wrap items-center gap-x-2.5 gap-y-1 font-mono text-2xs tabular-nums text-text-3">
      <span title={horodatageLisible(message.cree_le)}>{formaterHeure(message.cree_le)}</span>
      {modele !== null && (
        <span className="max-w-full truncate text-text-2 lg:max-w-[22rem]" title={modele}>
          {nomCourt(modele)}
        </span>
      )}
      {tokens !== null && <span>{tokens} tokens</span>}
      {debit !== null && <span>{formaterDebit(debit)}</span>}
      {message.interrompu && <Badge tone="caution">interrompu</Badge>}
      <Temporalite message={message} />
    </div>
  );
}

function Temporalite({ message }: { message: MessageChat }): ReactElement {
  const duree = dureeGeneration(message.tokens_generes, message.tokens_par_seconde);
  return (
    <span className={cn('text-text-3', CLASSE_REVELEE)}>
      {horodatageLisible(message.cree_le)}
      {duree !== null && <span title="Durée d’écriture, relecture du contexte exclue"> · écrite en {duree}</span>}
    </span>
  );
}

export interface MessageProps {
  message: MessageChat;
}

/*
 * `EnveloppeMessage` porte les actions au survol (copier, éditer, rejouer en sous-branche). Elle
 * est neutre hors d'un fournisseur d'actions : un message rendu ailleurs reste un message.
 *
 * `ReponseModele` sépare d'abord le travail intermédiaire (raisonnement, cartes d'outils,
 * artefacts) du texte visible, puis rend le Markdown. Les messages utilisateur restent en texte
 * brut — ce qu'on a tapé s'affiche tel qu'on l'a tapé.
 */
export function Message({ message }: MessageProps): ReactElement {
  const utilisateur = message.role === 'user';
  return (
    <motion.article
      variants={fadeUp}
      initial="hidden"
      animate="visible"
      className={cn('group flex', utilisateur ? 'justify-end' : 'justify-start')}
    >
      {/* La largeur est portée par CE conteneur, pas par la bulle : l'enveloppe d'actions insère un
          bloc entre le flex et la bulle, et un `max-w-[80%]` posé plus bas se calculerait alors par
          rapport à cet intercalaire — ce qui écrasait les messages sur deux ou trois mots. */}
      {/* 80 % d'une colonne de 390 px laisse 78 px de vide pour une bulle déjà à l'étroit : au doigt
          la retenue tombe à 92 %, la distinction gauche/droite suffisant à identifier l'auteur. */}
      <div className={cn('min-w-0', utilisateur ? 'max-w-[92%] lg:max-w-[80%]' : 'w-full')}>
        <EnveloppeMessage message={message}>
          <div className={cn(utilisateur && 'rounded-md bg-surface-2 px-3.5 py-2.5')}>
            {utilisateur ? (
              <p className="whitespace-pre-wrap break-words text-sm leading-relaxed text-text">{message.contenu}</p>
            ) : (
              <ReponseModele source={message.contenu} />
            )}
            {!utilisateur && <Mesures message={message} />}
          </div>
          {utilisateur && (
            <p className={cn('mt-1 text-right font-mono text-2xs tabular-nums text-text-3', CLASSE_REVELEE)}>
              {horodatageLisible(message.cree_le)}
            </p>
          )}
        </EnveloppeMessage>
      </div>
    </motion.article>
  );
}

export interface MessageEnCoursProps {
  texte: string;
}

/* Réponse en cours de réception : même rendu que la version finale, plus un curseur d'activité. */
export function MessageEnCours({ texte }: MessageEnCoursProps): ReactElement {
  return (
    <article className="w-full">
      {texte === '' ? (
        <p className="text-sm text-text-2">
          <span className="mr-1.5 inline-block h-2 w-2 animate-eh-pulse rounded-full bg-accent align-middle" />
          le modèle répond…
        </p>
      ) : (
        // `actif` distingue un bloc de raisonnement qui grandit d'un bloc figé : pendant le
        // streaming, tant que `</think>` n'est pas arrivé, rien ne permet encore de savoir que le
        // texte reçu est du raisonnement. On l'affiche donc, quitte à le replier ensuite — le
        // masquer ferait croire à une génération bloquée.
        <ReponseModele source={texte} actif />
      )}
    </article>
  );
}
