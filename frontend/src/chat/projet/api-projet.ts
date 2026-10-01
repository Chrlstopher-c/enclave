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
 *   GET   /projets/{nom}/arbre                       -> ArbreProjet
 *   GET   /projets/{nom}/fichier?chemin=             -> ContenuFichier
 *   GET   /projets/{nom}/modifications               -> ModificationsProjet
 *   GET   /projets/{nom}/diff?chemin=                -> DiffFichier
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

export interface EntreeArbre {
  readonly chemin: string;
  readonly taille: number;
}

export interface ArbreProjet {
  readonly fichiers: readonly EntreeArbre[];
  readonly tronque: boolean;
}

export interface ContenuFichier {
  readonly chemin: string;
  readonly taille: number;
  readonly contenu: string | null;
  readonly binaire: boolean;
  readonly tronque: boolean;
}

export type EtatModification = 'A' | 'M' | 'D';

export interface Modification {
  readonly chemin: string;
  readonly etat: EtatModification;
  readonly ajouts: number | null;
  readonly suppressions: number | null;
}

export interface ModificationsProjet {
  readonly reference: Instantane | null;
  readonly fichiers: readonly Modification[];
}

export interface DiffFichier {
  readonly chemin: string;
  readonly diff: string;
  readonly tronque: boolean;
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

function cheminProjet(nom: string, route: string): string {
  return `/projets/${encodeURIComponent(nom)}/${route}`;
}

export function lireArbre(nom: string, signal?: AbortSignal): Promise<ArbreProjet> {
  return getJson<ArbreProjet>(cheminProjet(nom, 'arbre'), signal);
}

export function lireFichierProjet(nom: string, chemin: string, signal?: AbortSignal): Promise<ContenuFichier> {
  return getJson<ContenuFichier>(cheminProjet(nom, `fichier?chemin=${encodeURIComponent(chemin)}`), signal);
}

export function lireModifications(nom: string, signal?: AbortSignal): Promise<ModificationsProjet> {
  return getJson<ModificationsProjet>(cheminProjet(nom, 'modifications'), signal);
}

export function lireDiff(nom: string, chemin: string, signal?: AbortSignal): Promise<DiffFichier> {
  return getJson<DiffFichier>(cheminProjet(nom, `diff?chemin=${encodeURIComponent(chemin)}`), signal);
}
