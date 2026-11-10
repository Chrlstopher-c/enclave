/*
 * Appels du domaine `inference` (`/api/inference`) consommés par l'écran de chat.
 *
 * `planifier` est appelé chaque fois que l'utilisateur touche une préférence : c'est le backend qui
 * recalcule, jamais l'interface. `charger` renvoie le plan déjà affiché plutôt qu'une demande, pour
 * garantir que ce qui est chargé est exactement ce que l'utilisateur a vu et validé.
 */

import { getJson, postJson } from './client';
import type {
  PlanEprouve,
  DemandeDeChargement,
  PlanDeChargement,
  ReponsePlan,
  SessionChargement,
  StatutInference,
} from './contrats';

const RACINE = '/inference';

export function planifier(demande: DemandeDeChargement, signal?: AbortSignal): Promise<ReponsePlan> {
  return postJson<ReponsePlan>(`${RACINE}/planifier`, { demande }, signal);
}

/**
 * Replanification après échec. La cause n'est pas transmise : le superviseur connaît celle qu'il a
 * réellement observée, et une cause devinée côté interface produirait une dégradation à côté.
 */
export function degrader(demande: DemandeDeChargement, planEchoue: PlanDeChargement): Promise<ReponsePlan> {
  return postJson<ReponsePlan>(`${RACINE}/degrader`, { demande, plan_echoue: planEchoue, cause: null });
}

export function charger(cheminModele: string, plan: PlanDeChargement): Promise<StatutInference> {
  return postJson<StatutInference>(`${RACINE}/charger`, { chemin_modele: cheminModele, plan });
}

/** Plan éprouvé du modèle, ou `null` s'il n'a jamais été chargé avec succès. */
export async function lirePlanEprouve(identifiant: string, signal?: AbortSignal): Promise<PlanEprouve | null> {
  try {
    return await getJson<PlanEprouve>(`${RACINE}/plans-eprouves/${encodeURI(identifiant)}`, signal);
  } catch {
    return null;
  }
}

/** Recharge le modèle exactement comme la dernière fois où il a tenu. */
export function chargerPlanEprouve(identifiant: string): Promise<StatutInference> {
  return postJson<StatutInference>(`${RACINE}/plans-eprouves/${encodeURI(identifiant)}/charger`, {});
}

export function lireEtatInference(signal?: AbortSignal): Promise<StatutInference> {
  return getJson<StatutInference>(`${RACINE}/etat`, signal);
}

export function lireJournalChargement(limite: number, signal?: AbortSignal): Promise<SessionChargement[]> {
  return getJson<SessionChargement[]>(`${RACINE}/journal?limite=${limite}`, signal);
}
