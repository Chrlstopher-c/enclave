import { useCallback, useEffect, useRef, useState } from 'react';
import type { ReactElement } from 'react';
import { Button, Modal } from '../../shared/design';
import type { MessageChat } from '../api/contrats';
import type { Reglages } from './contrat';
import { PanneauReglages } from './PanneauReglages';

/*
 * Enveloppe modale du panneau — point d'intégration dans l'écran de chat.
 *
 * Le pied ne porte qu'une fermeture : il n'y a rien à valider, l'écriture est déjà partie. Un
 * bouton « Enregistrer » ici mentirait deux fois — sur le moment où la valeur est écrite, et sur ce
 * qui se passe quand on ferme sans cliquer.
 *
 * La modale démonte son contenu à la fermeture (`AnimatePresence`), ce qui fait deux choses utiles :
 * la dernière modification en attente part au démontage, et la réouverture repart d'une vérité
 * backend plutôt que d'un brouillon oublié.
 */

/**
 * Mémoire des réglages CONFIRMÉS par le backend, qui survit à la fermeture.
 *
 * Sans elle, rouvrir la modale réafficherait les réglages tels que l'écran appelant les avait lus à
 * l'ouverture de la conversation — donc d'avant les enregistrements qui viennent d'avoir lieu, tant
 * que cet écran ne relit pas la conversation. Ce qui est affiché reste dans tous les cas une réponse
 * du backend : celle du parent, ou celle du dernier PATCH.
 *
 * Une nouvelle valeur de la propriété `reglages` est reprise : depuis le 2026-11-10, le panneau de
 * chargement écrit aussi le plafond de réponse, et l'écran remonte ce qu'il a confirmé.
 */
function useReglagesConnus(conversationId: string, reglages: Reglages): [Reglages, (recus: Reglages) => void] {
  const [connus, setConnus] = useState<Reglages>(reglages);
  const derniers = useRef<Reglages>(reglages);
  useEffect((): void => {
    derniers.current = reglages;
  });
  useEffect((): void => {
    setConnus(derniers.current);
  }, [conversationId, reglages]);
  return [connus, setConnus];
}

export interface ModaleReglagesProps {
  readonly ouvert: boolean;
  readonly conversationId: string;
  readonly reglages: Reglages;
  /** Messages persistés : ils adossent le plafond de réponse à des mesures réelles. */
  readonly messages?: readonly MessageChat[];
  readonly onFermer: () => void;
  /** Réglages confirmés par le backend, pour que l'écran appelant reste à jour sans les relire. */
  readonly onEnregistre?: (reglages: Reglages) => void;
}

function PiedFermeture({ onFermer }: { onFermer: () => void }): ReactElement {
  return (
    <Button variant="secondary" size="sm" onClick={onFermer}>
      Fermer
    </Button>
  );
}

export function ModaleReglages({
  ouvert,
  conversationId,
  reglages,
  messages = [],
  onFermer,
  onEnregistre,
}: ModaleReglagesProps): ReactElement {
  const [connus, memoriser] = useReglagesConnus(conversationId, reglages);
  const confirmer = useCallback(
    (recus: Reglages): void => {
      memoriser(recus);
      onEnregistre?.(recus);
    },
    [memoriser, onEnregistre],
  );
  return (
    <Modal
      open={ouvert}
      onClose={onFermer}
      title="Réglages de la conversation"
      size="lg"
      footer={<PiedFermeture onFermer={onFermer} />}
    >
      <PanneauReglages
        conversationId={conversationId}
        reglages={connus}
        messages={messages}
        onEnregistre={confirmer}
      />
    </Modal>
  );
}
