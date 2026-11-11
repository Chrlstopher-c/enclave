/*
 * Suivi d'un flux de génération jusqu'à sa fin RÉELLE. Une connexion qui se ferme n'est pas une fin :
 * la veille du téléphone, un proxy ou un réseau coupé ferment un flux que le serveur continue de
 * produire. Seul le serveur tranche : on se raccroche (`GET /flux`) jusqu'à sa réponse 204.
 */

import { ErreurApi } from '../api/client';
import { rejoindreFluxGeneration, type RappelsFlux } from '../api/flux-generation';
import { journal } from '../api/journal';
import { DELAI_APRES_FLUX_MS, delaiApresEchec, nouvelleTentative, type SuiviFlux } from './suivi-flux-regles';

type Issue = 'ouvert' | 'vide' | 'coupe' | 'echec' | 'arret';

function attendre(ms: number, signal: AbortSignal): Promise<void> {
  return new Promise((resolve): void => {
    if (signal.aborted || ms <= 0) {
      resolve();
      return;
    }
    const minuterie = window.setTimeout(resolve, ms);
    signal.addEventListener('abort', (): void => {
      window.clearTimeout(minuterie);
      resolve();
    }, { once: true });
  });
}

function issueDe(suivi: SuiviFlux, tentative: AbortController, cause: unknown): Issue {
  if (suivi.controle.signal.aborted) {
    return 'arret';
  }
  if (cause instanceof ErreurApi && cause.statut >= 400) {
    journal.erreur('raccrochage refusé, arrêt du suivi', cause);
    return 'arret';
  }
  if (tentative.signal.aborted && !suivi.controle.signal.aborted) {
    return 'coupe';
  }
  journal.avertissement('flux interrompu, nouvel essai', cause);
  return 'echec';
}

async function unTour(suivi: SuiviFlux, rappels: RappelsFlux, tentative: AbortController): Promise<Issue> {
  try {
    return (await rejoindreFluxGeneration(suivi.proprietaire, rappels, tentative.signal)) ? 'ouvert' : 'vide';
  } catch (cause) {
    return issueDe(suivi, tentative, cause);
  }
}

function delaiDe(issue: Issue, echecs: number): number {
  if (issue === 'ouvert') return DELAI_APRES_FLUX_MS;
  if (issue === 'echec') return delaiApresEchec(echecs);
  return 0;
}

/** Rappels qui comptent les événements reçus : un flux « ouvert » sans rien dedans n'est pas du direct. */
function rappelsComptes(rappels: RappelsFlux, compteur: { recus: number }): RappelsFlux {
  return {
    onEvenement: (evenement): void => {
      compteur.recus += 1;
      rappels.onEvenement(evenement);
    },
    onOctet: rappels.onOctet,
  };
}

/**
 * Se raccroche jusqu'à 204 (plus rien en cours) ou jusqu'à un refus HTTP. Rend le nombre de flux
 * réellement ouverts ; s'arrête dès que `suivi.controle` est annulé.
 */
export async function suivreJusquAuBout(suivi: SuiviFlux, rappels: RappelsFlux): Promise<number> {
  let ouverts = 0;
  let echecs = 0;
  while (!suivi.controle.signal.aborted) {
    const compteur = { recus: 0 };
    const tentative = nouvelleTentative(suivi, Date.now());
    let issue = await unTour(suivi, rappelsComptes(rappels, compteur), tentative);
    if (issue === 'ouvert' && compteur.recus === 0) {
      issue = 'vide';
    }
    if (issue === 'vide' || issue === 'arret') {
      break;
    }
    if (issue === 'ouvert') ouverts += 1;
    echecs = issue === 'echec' ? echecs + 1 : 0;
    await attendre(delaiDe(issue, echecs), suivi.controle.signal);
  }
  return ouverts;
}
