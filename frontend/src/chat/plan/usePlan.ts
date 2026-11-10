/*
 * Calcul du plan de chargement : l'interface envoie les préférences, le backend décide.
 *
 * Rien n'est recalculé ici — ni couches, ni cache KV, ni budget. Chaque mouvement du curseur de
 * contexte redemande un plan complet, ce qui garantit que ce qui est affiché est exactement ce que
 * le planificateur produirait au chargement. Le délai d'attente évite d'envoyer une requête par
 * pixel parcouru, et chaque nouvelle demande annule la précédente.
 */

import { useCallback, useEffect, useRef, useState } from 'react';
import { messageErreur } from '../api/client';
import type {
  DemandeDeChargement,
  Moteur,
  PlanDeChargement,
  ReponsePlan,
  TypeCacheKV,
} from '../api/contrats';
import { planifier } from '../api/inference-api';
import { journal } from '../api/journal';

/* Assez court pour que le plan suive le geste, assez long pour ne pas inonder le planificateur. */
const DELAI_REPLANIFICATION_MS = 180;

export interface PreferencesLocales {
  /** `null` = aucune préférence : le planificateur choisit et explique son choix. */
  contexte: number | null;
  typeCacheKv: TypeCacheKV;
  moteur: Moteur | null;
  flashAttention: boolean;
  /** Graphes CUDA voulus : vitesse de décodage contre un peu de VRAM. */
  graphesCuda: boolean;
}

export interface EtatPlan {
  plan: PlanDeChargement | null;
  justifications: string[];
  avertissements: string[];
  calculEnCours: boolean;
  erreur: string | null;
  preferences: PreferencesLocales;
  ajusterPreferences: (patch: Partial<PreferencesLocales>) => void;
  adopterPlan: (reponse: ReponsePlan) => void;
}

function preferencesInitiales(demande: DemandeDeChargement | null): PreferencesLocales {
  const source = demande?.preferences;
  return {
    contexte: source?.contexte ?? null,
    typeCacheKv: source?.type_cache_kv ?? 'f16',
    moteur: source?.moteur ?? null,
    flashAttention: source?.flash_attention ?? true,
    graphesCuda: !(source?.desactiver_cuda_graphs ?? false),
  };
}

function fusionner(demande: DemandeDeChargement, locales: PreferencesLocales): DemandeDeChargement {
  return {
    ...demande,
    preferences: {
      ...demande.preferences,
      contexte: locales.contexte,
      type_cache_kv: locales.typeCacheKv,
      moteur: locales.moteur,
      flash_attention: locales.flashAttention,
      desactiver_cuda_graphs: !locales.graphesCuda,
    },
  };
}

/**
 * @param demande entrées mesurées du planificateur. La référence doit être stable (mémoïsée par
 * l'appelant) : un nouvel objet à chaque rendu relancerait une planification en boucle.
 */
export function usePlan(demande: DemandeDeChargement | null): EtatPlan {
  const [preferences, setPreferences] = useState<PreferencesLocales>(() => preferencesInitiales(demande));
  const [reponse, setReponse] = useState<ReponsePlan | null>(null);
  const [calculEnCours, setCalculEnCours] = useState<boolean>(false);
  const [erreur, setErreur] = useState<string | null>(null);
  const controleur = useRef<AbortController | null>(null);

  const ajusterPreferences = useCallback((patch: Partial<PreferencesLocales>): void => {
    setPreferences((actuelles) => ({ ...actuelles, ...patch }));
  }, []);

  const adopterPlan = useCallback((nouvelle: ReponsePlan): void => {
    setReponse(nouvelle);
    setErreur(null);
  }, []);

  useEffect((): (() => void) | undefined => {
    if (demande === null) {
      setReponse(null);
      return undefined;
    }
    const attente = window.setTimeout((): void => {
      controleur.current?.abort();
      const controle = new AbortController();
      controleur.current = controle;
      setCalculEnCours(true);
      planifier(fusionner(demande, preferences), controle.signal)
        .then((resultat): void => {
          setReponse(resultat);
          setErreur(null);
        })
        .catch((cause: unknown): void => {
          if (controle.signal.aborted) {
            return;
          }
          journal.erreur('planification refusée', cause);
          setErreur(messageErreur(cause));
        })
        .finally((): void => {
          if (!controle.signal.aborted) {
            setCalculEnCours(false);
          }
        });
    }, DELAI_REPLANIFICATION_MS);
    return (): void => window.clearTimeout(attente);
  }, [demande, preferences]);

  useEffect((): (() => void) => (): void => controleur.current?.abort(), []);

  return {
    plan: reponse?.plan ?? null,
    justifications: reponse?.justifications ?? [],
    avertissements: reponse?.avertissements ?? [],
    calculEnCours,
    erreur,
    preferences,
    ajusterPreferences,
    adopterPlan,
  };
}
