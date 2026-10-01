/*
 * Câblage du projet confié sur l'écran du chat : liaison, modale de projet, panneau des fichiers.
 * Sorti de `ChatEcran` pour que l'écran ne fasse que disposer ses colonnes.
 */

import { useState } from 'react';
import { useProjetConversation, type EtatProjetConversation } from './useProjetConversation';

export interface EtatProjetEcran {
  readonly liaison: EtatProjetConversation;
  readonly modaleOuverte: boolean;
  readonly fermerModale: () => void;
  /** Projet dont le panneau de fichiers est affiché, `null` si le panneau est fermé. */
  readonly projetPanneau: string | null;
  readonly fermerPanneau: () => void;
  readonly actions: {
    readonly projet: string | null;
    readonly onProjet: () => void;
    readonly onFichiers: () => void;
    readonly fichiersOuverts: boolean;
  };
}

export function useProjetEcran(conversationId: string | null): EtatProjetEcran {
  const liaison = useProjetConversation(conversationId);
  const [modaleOuverte, setModaleOuverte] = useState<boolean>(false);
  const [panneauOuvert, setPanneauOuvert] = useState<boolean>(false);
  const projetPanneau = panneauOuvert ? liaison.projet : null;
  return {
    liaison,
    modaleOuverte,
    fermerModale: () => setModaleOuverte(false),
    projetPanneau,
    fermerPanneau: () => setPanneauOuvert(false),
    actions: {
      projet: liaison.projet,
      onProjet: () => setModaleOuverte(true),
      onFichiers: () => setPanneauOuvert((o) => !o),
      fichiersOuverts: projetPanneau !== null,
    },
  };
}
