/*
 * Interface publique des réglages de conversation — seul point d'import autorisé depuis le reste
 * de l'écran de chat.
 *
 * Deux façons de l'intégrer, selon la place disponible :
 *
 *   <ModaleReglages ouvert={…} conversationId={id} reglages={detail.reglages}
 *                   messages={messages} onFermer={…} onEnregistre={…} />
 *   <PanneauReglages conversationId={id} reglages={detail.reglages} messages={messages} />
 *
 * `messages` est facultatif : sans lui, la section du plafond dit simplement qu'elle n'a rien à
 * mesurer, au lieu d'afficher un constat fabriqué.
 *
 * Le découpage interne (champs, hook d'enregistrement, lecture des mesures) reste privé : il doit
 * pouvoir changer sans toucher l'appelant.
 */

export { ModaleReglages, type ModaleReglagesProps } from './ModaleReglages';
export { PanneauReglages, type PanneauReglagesProps } from './PanneauReglages';
export { PlafondReponseRapide, type PlafondReponseRapideProps } from './PlafondReponseRapide';
export type { MajParametres, MajReglages, Reglages } from './contrat';
export { useReglagesConversation, type EtatEnregistrement, type PilotageReglages } from './useReglagesConversation';
