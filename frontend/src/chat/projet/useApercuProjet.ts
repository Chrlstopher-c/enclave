/*
 * Aperçu de l'app d'un projet : ports en écoute dans l'atelier, et ouverture de l'un d'eux.
 *
 * L'onglet est ouvert AVANT l'appel réseau : un `window.open` lancé après un `await` n'est plus
 * rattaché au clic, et le navigateur le bloque comme une fenêtre surgissante.
 */

import { useCallback, useState } from 'react';
import { messageErreur } from '../api/client';
import { lireApercu, pointerApercu, type EtatApercu } from './api-projet';

export interface EtatApercuProjet {
  readonly apercu: EtatApercu | null;
  readonly erreur: string | null;
  readonly chercher: () => void;
  readonly ouvrir: (port: number) => void;
}

export function useApercuProjet(projet: string | null): EtatApercuProjet {
  const [apercu, setApercu] = useState<EtatApercu | null>(null);
  const [erreur, setErreur] = useState<string | null>(null);

  const chercher = useCallback((): void => {
    if (projet === null) {
      return;
    }
    setErreur(null);
    lireApercu(projet)
      .then(setApercu)
      .catch((cause: unknown): void => setErreur(messageErreur(cause)));
  }, [projet]);

  const ouvrir = useCallback((port: number): void => {
    if (projet === null) {
      return;
    }
    const onglet = window.open('about:blank', '_blank');
    setErreur(null);
    pointerApercu(projet, port)
      .then((etat: EtatApercu): void => {
        setApercu(etat);
        if (onglet !== null) {
          onglet.location.href = etat.url;
        }
      })
      .catch((cause: unknown): void => {
        onglet?.close();
        setErreur(messageErreur(cause));
      });
  }, [projet]);

  return { apercu, erreur, chercher, ouvrir };
}
