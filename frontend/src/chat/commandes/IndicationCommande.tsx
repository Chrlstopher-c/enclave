/*
 * Ligne d'indication au-dessus de la saisie : ce que fera la touche Entrée.
 *
 * Une commande reconnue porte un badge pervenche (action possible) et son usage en grisé ; une
 * commande inconnue reste discrète — elle partira comme un message, ce n'est pas une erreur.
 * L'ambre est gardé pour ce qui empêche réellement l'exécution (refus, réponse en cours).
 */

import type { ReactElement } from 'react';
import { Badge } from '../../shared/design';
import type { DefinitionCommande } from './contrats';
import type { SaisieCommande } from './useSaisieCommande';

type Indication =
  | { type: 'note'; texte: string; ton: 'text-text-3' | 'text-caution' }
  | { type: 'commande'; definition: DefinitionCommande; envoi: boolean };

function lireIndication(saisie: SaisieCommande): Indication | null {
  const { analyse, erreur } = saisie;
  if (erreur !== null) {
    return { type: 'note', texte: erreur, ton: 'text-caution' };
  }
  if (analyse.type === 'litteral') {
    return { type: 'note', texte: 'Texte littéral : le message commencera par « / ».', ton: 'text-text-3' };
  }
  if (analyse.type !== 'commande' || saisie.palette !== null) {
    return null;
  }
  if (analyse.definition === null && saisie.catalogue !== 'pret') {
    return saisie.catalogue === 'erreur'
      ? { type: 'note', texte: 'Commandes indisponibles : tapez « / » seul pour réessayer.', ton: 'text-caution' }
      : { type: 'note', texte: 'Lecture de la liste des commandes…', ton: 'text-text-3' };
  }
  if (analyse.definition === null) {
    const texte = analyse.nom === ''
      ? 'Tapez le nom d’une commande.'
      : 'Commande inconnue : Entrée l’envoie comme message.';
    return { type: 'note', texte, ton: 'text-text-3' };
  }
  return { type: 'commande', definition: analyse.definition, envoi: saisie.envoi };
}

export function IndicationCommande({ saisie }: { saisie: SaisieCommande }): ReactElement | null {
  const indication = lireIndication(saisie);
  if (indication === null) {
    return null;
  }
  return (
    <p className="mb-1.5 flex min-w-0 items-center gap-2 px-1 text-2xs" aria-live="polite">
      {indication.type === 'note' ? (
        <span className={indication.ton}>{indication.texte}</span>
      ) : (
        <>
          <Badge tone="accent">Commande /{indication.definition.nom}</Badge>
          <span className="min-w-0 truncate font-mono text-text-3">{indication.definition.usage}</span>
          {indication.envoi && <span className="shrink-0 text-text-3">· envoi…</span>}
        </>
      )}
    </p>
  );
}
