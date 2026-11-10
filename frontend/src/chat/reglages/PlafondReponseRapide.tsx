import type { ReactElement } from 'react';
import type { Reglages } from './contrat';
import { ChampEntierOptionnel } from './Champs';
import { MAX_TOKENS } from './definitions';
import { useReglagesConversation } from './useReglagesConversation';

/*
 * Plafond de réponse posé depuis le panneau de chargement, sans ouvrir la modale de réglages.
 *
 * Demandé le 2026-11-10 : on règle le contexte au chargement, et la longueur de sortie va avec — un
 * modèle de raisonnement coupé net par un plafond trop bas ne finit pas sa réponse. C'est le MÊME
 * réglage que la modale (`max_tokens` de la conversation), écrit par le même mécanisme différé ;
 * l'écran remonte la valeur confirmée pour que les deux affichent la même chose.
 */

export interface PlafondReponseRapideProps {
  readonly conversationId: string;
  readonly reglages: Reglages;
  readonly onEnregistre: (reglages: Reglages) => void;
}

export function PlafondReponseRapide({
  conversationId,
  reglages,
  onEnregistre,
}: PlafondReponseRapideProps): ReactElement {
  const pilotage = useReglagesConversation(conversationId, reglages, onEnregistre);
  return (
    <div className="min-w-0 space-y-1 border-t border-border pt-3">
      <ChampEntierOptionnel
        id="chargement-max-tokens"
        definition={MAX_TOKENS}
        valeur={pilotage.valeurs.parametres.max_tokens}
        etiquetteVide="aucun plafond"
        onChanger={(max_tokens) => pilotage.modifierParametres({ max_tokens })}
      />
      <p className="text-2xs text-text-3">Vaut pour la conversation ouverte, comme dans ses réglages.</p>
    </div>
  );
}
