/*
 * Mode projet — routes du backend :
 *   GET   /projets                                   -> CatalogueProjets
 *   POST  /projets                                   <- { nom }
 *   GET   /projets/{nom}/instantanes                 -> Instantane[]
 *   POST  /projets/{nom}/instantanes/{sha}/restaurer
 *   GET   /chat/conversations/{id}/projet            -> { projet: string | null }
 *   PATCH /chat/conversations/{id}/projet            <- { projet: string | null }
 *   GET   /projets/{nom}/apercu                      -> EtatApercu
 *   POST  /projets/{nom}/apercu                      <- { port }
 */

import { getJson, patchJson, postJson } from '../api/client';

export interface Projet {
  readonly nom: string;
  readonly modifie_le: number;
  readonly instantanes: boolean;
}

export interface CatalogueProjets {
  readonly actif: boolean;
  readonly racine: string | null;
  readonly projets: readonly Projet[];
}

export interface Instantane {
  readonly sha: string;
  readonly date: number;
  readonly message: string;
}

export interface EtatApercu {
  readonly port: number | null;
  readonly ports: readonly number[];
  readonly url: string;
}

interface Liaison {
  readonly projet: string | null;
}

export const MOTIF_NOM_PROJET = /^[a-z0-9][a-z0-9._-]{0,62}$/;

export function listerProjets(signal?: AbortSignal): Promise<CatalogueProjets> {
  return getJson<CatalogueProjets>('/projets', signal);
}

export function creerProjet(nom: string): Promise<Projet> {
  return postJson<Projet>('/projets', { nom });
}

export function listerInstantanes(nom: string, signal?: AbortSignal): Promise<Instantane[]> {
  return getJson<Instantane[]>(`/projets/${encodeURIComponent(nom)}/instantanes`, signal);
}

export function restaurerInstantane(nom: string, sha: string): Promise<unknown> {
  return postJson<unknown>(`/projets/${encodeURIComponent(nom)}/instantanes/${sha}/restaurer`, {});
}

export async function lireProjetConversation(conversationId: string, signal?: AbortSignal): Promise<string | null> {
  const liaison = await getJson<Liaison>(`/chat/conversations/${conversationId}/projet`, signal);
  return liaison.projet;
}

export async function lierProjet(conversationId: string, projet: string | null): Promise<string | null> {
  const liaison = await patchJson<Liaison>(`/chat/conversations/${conversationId}/projet`, { projet });
  return liaison.projet;
}

export function lireApercu(nom: string, signal?: AbortSignal): Promise<EtatApercu> {
  return getJson<EtatApercu>(`/projets/${encodeURIComponent(nom)}/apercu`, signal);
}

export function pointerApercu(nom: string, port: number): Promise<EtatApercu> {
  return postJson<EtatApercu>(`/projets/${encodeURIComponent(nom)}/apercu`, { port });
}
