/*
 * Aperçu local du chemin pendant qu'une branche se crée.
 *
 * Le serveur est seul à décider du chemin actif. Mais entre le clic et sa réponse, l'écran doit
 * montrer ce que l'utilisateur vient de faire, sinon un rejeu semble ne rien déclencher et l'ancien
 * texte reste affiché pendant que la nouvelle réponse arrive dessous.
 *
 * Ces fonctions ne DEVINENT rien : elles rejouent localement le geste déjà envoyé au serveur —
 * couper au point de bifurcation, afficher le texte réellement transmis. Aucune valeur mesurée
 * (tokens, débit) n'est fabriquée, et l'aperçu est effacé dès que la vraie vue de branche revient.
 */

import type { MessageChat } from '../api/contrats';

/** Point où la conversation se dédouble, tel qu'il vient d'être demandé au serveur. */
export interface Bifurcation {
  /** Message ciblé par le rejeu ou l'édition. */
  message_id: string;
  /** Le message ciblé reste-t-il sur le chemin ? Vrai pour une édition et un rejeu de tour utilisateur. */
  inclure: boolean;
  /** Texte réécrit par une édition ; `null` pour un rejeu, qui ne touche à aucun texte. */
  contenu: string | null;
}

/**
 * Coupe le chemin au point de bifurcation, et applique le texte réécrit s'il y en a un.
 *
 * Cible absente du chemin (branche déjà basculée sous les pieds de l'utilisateur) : on rend le
 * chemin inchangé plutôt qu'un chemin tronqué au hasard. Une position inconnue ne se devine pas.
 */
export function appliquerBifurcation(
  chemin: readonly MessageChat[],
  bifurcation: Bifurcation,
): MessageChat[] {
  const index = chemin.findIndex((message) => message.id === bifurcation.message_id);
  if (index < 0) {
    return [...chemin];
  }
  const coupe = chemin.slice(0, bifurcation.inclure ? index + 1 : index);
  const cible = coupe[coupe.length - 1];
  if (bifurcation.contenu === null || cible === undefined) {
    return coupe;
  }
  return [...coupe.slice(0, -1), { ...cible, contenu: bifurcation.contenu }];
}

/*
 * Identifiant local d'un message pas encore persisté. Il ne ressemble volontairement à aucun
 * identifiant serveur : rien ne doit pouvoir le confondre avec un message réellement écrit.
 */
const PREFIXE_LOCAL = 'apercu-';

/**
 * Message utilisateur affiché avant que le serveur ne l'ait écrit.
 *
 * Duplique volontairement `messageLocal` de `useConversation` : les deux vivent le temps d'une
 * génération et disparaissent à la relecture, mais l'un sert la liste amont et l'autre le chemin de
 * branche. Les mutualiser coupleraient deux états dont les durées de vie ne coïncident pas.
 */
export function messageOptimiste(conversationId: string, contenu: string): MessageChat {
  return {
    id: `${PREFIXE_LOCAL}${Date.now()}`,
    conversation_id: conversationId,
    role: 'user',
    contenu,
    tokens_generes: null,
    tokens_par_seconde: null,
    cree_le: new Date().toISOString(),
    modele_id: null,
    interrompu: false,
    parent_id: null,
    compaction: null,
  };
}
