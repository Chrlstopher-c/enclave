/*
 * Suivi du chargement d'un modèle : déclenchement, état réel, journal, et plan dégradé après échec.
 *
 * Aucune progression n'est simulée. Le backend ne publie pas de pourcentage — il publie des faits
 * datés (le journal de session) et un état. L'écran affiche ces faits et le temps écoulé ; c'est
 * moins flatteur qu'une barre qui glisse, et c'est la seule chose vraie.
 */

import { useCallback, useEffect, useRef, useState } from 'react';
import { messageErreur } from '../api/client';
import type {
  DemandeDeChargement,
  EntreeJournal,
  PlanDeChargement,
  ReponsePlan,
  SessionChargement,
  StatutInference,
} from '../api/contrats';
import { charger, chargerPlanEprouve, degrader, lireEtatInference, lireJournalChargement } from '../api/inference-api';
import { journal } from '../api/journal';

const INTERVALLE_SONDAGE_MS = 800;
/* Borne dure du sondage : 10 minutes, au-delà desquelles un chargement n'est plus « en cours ». */
const SONDAGES_MAX = Math.ceil((10 * 60 * 1000) / INTERVALLE_SONDAGE_MS);
const ENTREES_AFFICHEES_MAX = 40;

export interface EtatChargementModele {
  statut: StatutInference | null;
  entrees: EntreeJournal[];
  debutMs: number | null;
  planDegrade: ReponsePlan | null;
  erreur: string | null;
  demarrer: (cheminModele: string, plan: PlanDeChargement) => Promise<void>;
  /** Rejoue le dernier plan qui a réellement chargé ce modèle. */
  demarrerEprouve: (identifiant: string) => Promise<void>;
  proposerDegradation: (demande: DemandeDeChargement, planEchoue: PlanDeChargement) => Promise<void>;
  oublierDegradation: () => void;
}

async function lireDerniereSession(): Promise<EntreeJournal[]> {
  const sessions = await lireJournalChargement(1);
  const derniere: SessionChargement | undefined = sessions[0];
  return derniere === undefined ? [] : derniere.entrees.slice(-ENTREES_AFFICHEES_MAX);
}

export function useChargement(): EtatChargementModele {
  const [statut, setStatut] = useState<StatutInference | null>(null);
  const [entrees, setEntrees] = useState<EntreeJournal[]>([]);
  const [debutMs, setDebutMs] = useState<number | null>(null);
  const [planDegrade, setPlanDegrade] = useState<ReponsePlan | null>(null);
  const [erreur, setErreur] = useState<string | null>(null);
  const sondages = useRef<number>(0);

  const rafraichir = useCallback(async (): Promise<StatutInference | null> => {
    try {
      const [prochain, faits] = await Promise.all([lireEtatInference(), lireDerniereSession()]);
      setStatut(prochain);
      setEntrees(faits);
      return prochain;
    } catch (cause) {
      journal.erreur('lecture de l’état d’inférence impossible', cause);
      setErreur(messageErreur(cause));
      return null;
    }
  }, []);

  useEffect((): void => {
    void rafraichir();
  }, [rafraichir]);

  // Sondage borné : il ne tourne que pendant un chargement, et pas au-delà de SONDAGES_MAX.
  useEffect((): (() => void) | undefined => {
    if (statut?.etat !== 'en_cours') {
      sondages.current = 0;
      return undefined;
    }
    const minuteur = window.setInterval((): void => {
      sondages.current += 1;
      if (sondages.current > SONDAGES_MAX) {
        journal.avertissement('sondage du chargement interrompu : borne atteinte');
        window.clearInterval(minuteur);
        return;
      }
      void rafraichir();
    }, INTERVALLE_SONDAGE_MS);
    return (): void => window.clearInterval(minuteur);
  }, [statut?.etat, rafraichir]);

  const lancer = useCallback(async (requete: () => Promise<StatutInference>): Promise<void> => {
    setErreur(null);
    setPlanDegrade(null);
    setDebutMs(Date.now());
    try {
      setStatut(await requete());
    } catch (cause) {
      journal.erreur('chargement refusé', cause);
      setErreur(messageErreur(cause));
    }
  }, []);
  const demarrer = useCallback(
    (cheminModele: string, plan: PlanDeChargement): Promise<void> => lancer(() => charger(cheminModele, plan)),
    [lancer],
  );
  const demarrerEprouve = useCallback(
    (identifiant: string): Promise<void> => lancer(() => chargerPlanEprouve(identifiant)),
    [lancer],
  );

  const proposerDegradation = useCallback(
    async (demande: DemandeDeChargement, planEchoue: PlanDeChargement): Promise<void> => {
      try {
        setPlanDegrade(await degrader(demande, planEchoue));
      } catch (cause) {
        journal.erreur('aucun plan dégradé disponible', cause);
        setErreur(messageErreur(cause));
      }
    },
    [],
  );

  const oublierDegradation = useCallback((): void => setPlanDegrade(null), []);

  return {
    statut, entrees, debutMs, planDegrade, erreur, demarrer, demarrerEprouve, proposerDegradation, oublierDegradation,
  };
}
