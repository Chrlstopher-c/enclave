/*
 * Moteur Strata (Qwen3.8-Flash-Next) : servi sur l'hôte, chargé à la place du modèle actif.
 * Le superviseur décharge d'abord ce qui tient la carte ; l'avancement se lit dans l'en-tête.
 */
import { useCallback, useEffect, useState } from 'react';

import { journal, messageErreur, obtenir, poster } from '../api/client';

export interface SondeStrata {
  readonly joignable: boolean;
  readonly charge: boolean;
  readonly modele: string | null;
  readonly contexte: number | null;
  readonly detail: string;
}

export interface EtatStrata {
  readonly sonde: SondeStrata | null;
  readonly envoi: boolean;
  readonly erreur: string | null;
  readonly charger: () => void;
}

const SONDE_MS = 15_000;

export function useStrata(): EtatStrata {
  const [sonde, setSonde] = useState<SondeStrata | null>(null);
  const [envoi, setEnvoi] = useState(false);
  const [erreur, setErreur] = useState<string | null>(null);

  const relire = useCallback((): void => {
    obtenir<SondeStrata>('/inference/strata')
      .then(setSonde)
      .catch((cause: unknown) => journal.erreur('sonde Strata', cause));
  }, []);

  useEffect(() => {
    relire();
    const minuterie = window.setInterval(relire, SONDE_MS);
    return (): void => window.clearInterval(minuterie);
  }, [relire]);

  const charger = useCallback((): void => {
    setEnvoi(true);
    setErreur(null);
    poster('/inference/strata/charger')
      .catch((cause: unknown) => {
        journal.erreur('chargement Strata', cause);
        setErreur(messageErreur(cause));
      })
      .finally(() => {
        setEnvoi(false);
        relire();
      });
  }, [relire]);

  return { sonde, envoi, erreur, charger };
}
