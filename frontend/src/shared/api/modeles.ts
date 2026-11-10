/*
 * Client du domaine `models` — recherche Hugging Face, téléchargements, registre local.
 *
 * ⚠ CONTRAT PROVISOIRE. `backend/models/` expose son interface Python
 * (`backend/models/__init__.py`) mais AUCUNE couche HTTP : il n'existe pas encore de
 * `backend/models/api.py`. Les chemins ci-dessous suivent la convention des trois routeurs déjà
 * livrés (`/api/<domaine>/<ressource>`) et sont volontairement identiques à ceux que le domaine
 * frontend `models` a retenus dans son propre `api/routes.ts` : deux hypothèses divergentes
 * coûteraient deux corrections au lieu d'une.
 *
 * `metadonnees` et `coherence` n'ont d'équivalent nulle part ailleurs pour l'instant. Ils sont
 * pourtant indispensables : le planificateur exige des métadonnées LUES dans le GGUF, et c'est le
 * seul chemin pour les obtenir depuis l'interface.
 */

import { fluxJson } from './sse';
import { requeteJson } from './transport';
import type {
  FormatRecherche,
  MetadonneesGGUF,
  MetadonneesSafetensors,
  ModeleEnregistre,
  Ordre,
  PageRecherche,
  RapportCoherence,
  ResultatRecherche,
  ResumeSynchronisation,
  Telechargement,
  TriRecherche,
} from './types-modeles';

const RACINE = '/models';
const REGISTRE = `${RACINE}/registre`;
const TELECHARGEMENTS = `${RACINE}/telechargements`;

/** L'API du Hub est lente et distante : un délai de requête ordinaire ne suffit pas. */
const DELAI_HUB_MS = 60_000;

export interface CriteresRecherche {
  readonly requete?: string;
  readonly formats?: readonly FormatRecherche[];
  readonly tri?: TriRecherche;
  readonly ordre?: Ordre;
  readonly page?: number;
  readonly taille_page?: number;
  readonly signal?: AbortSignal;
}

export function rechercherModeles(criteres: CriteresRecherche = {}): Promise<PageRecherche> {
  return requeteJson<PageRecherche>(`${RACINE}/recherche`, {
    parametres: {
      requete: criteres.requete,
      formats: criteres.formats,
      tri: criteres.tri,
      ordre: criteres.ordre,
      page: criteres.page,
      taille_page: criteres.taille_page,
    },
    delaiMs: DELAI_HUB_MS,
    signal: criteres.signal,
  });
}

/** Fiche complète d'un dépôt, tailles de fichiers comprises — tout reste « annoncé », pas mesuré. */
export function detailsDepot(depot: string, signal?: AbortSignal): Promise<ResultatRecherche> {
  return requeteJson<ResultatRecherche>(`${RACINE}/depots/${encodeURIComponent(depot)}`, {
    delaiMs: DELAI_HUB_MS,
    signal,
  });
}

export function listerModelesLocaux(signal?: AbortSignal): Promise<readonly ModeleEnregistre[]> {
  return requeteJson<readonly ModeleEnregistre[]>(REGISTRE, { signal });
}

function cheminEntree(identifiant: string, suffixe = ''): string {
  return `${REGISTRE}/${encodeURIComponent(identifiant)}${suffixe}`;
}

export function obtenirModele(identifiant: string, signal?: AbortSignal): Promise<ModeleEnregistre> {
  return requeteJson<ModeleEnregistre>(cheminEntree(identifiant), { signal });
}

/** Retire l'entrée du registre. Les fichiers restent sur le disque. */
export function oublierModele(identifiant: string): Promise<{ readonly oublie: boolean }> {
  return requeteJson(cheminEntree(identifiant), { methode: 'DELETE' });
}

/**
 * Métadonnées LUES dans l'en-tête GGUF — seule source valable pour planifier un chargement.
 * `null` quand le modèle n'est pas au format GGUF.
 */
export function metadonneesModele(identifiant: string, signal?: AbortSignal): Promise<MetadonneesGGUF | null> {
  return requeteJson<MetadonneesGGUF | null>(cheminEntree(identifiant, '/metadonnees'), { signal });
}

/**
 * Métadonnées LUES dans le `config.json` safetensors — source du planificateur pour ce format.
 * `null` quand le modèle n'est pas au format safetensors. Symétrique de `metadonneesModele`.
 */
export function metadonneesSafetensors(
  identifiant: string,
  signal?: AbortSignal,
): Promise<MetadonneesSafetensors | null> {
  return requeteJson<MetadonneesSafetensors | null>(
    cheminEntree(identifiant, '/metadonnees-safetensors'),
    { signal },
  );
}

/** Confronte ce que le modèle déclare à ce qu'il contient réellement. */
export function verifierModele(identifiant: string, signal?: AbortSignal): Promise<RapportCoherence> {
  return requeteJson<RapportCoherence>(cheminEntree(identifiant, '/coherence'), { delaiMs: DELAI_HUB_MS, signal });
}

/** Réaligne le registre sur le contenu réel du disque. */
export function synchroniserRegistre(): Promise<ResumeSynchronisation> {
  return requeteJson<ResumeSynchronisation>(`${REGISTRE}/synchronisation`, {
    methode: 'POST',
    delaiMs: DELAI_HUB_MS,
  });
}

export interface DemandeTelechargement {
  readonly depot: string;
  /** Un seul fichier GGUF, ou tout le dépôt si omis. */
  readonly fichier?: string | null;
  readonly revision?: string;
}

export function listerTelechargements(signal?: AbortSignal): Promise<readonly Telechargement[]> {
  return requeteJson<readonly Telechargement[]>(TELECHARGEMENTS, { signal });
}

export function demarrerTelechargement(demande: DemandeTelechargement): Promise<Telechargement> {
  return requeteJson<Telechargement>(TELECHARGEMENTS, { methode: 'POST', corps: demande });
}

/**
 * `supprimerFichiers` décide du sort des octets déjà écrits. Le défaut les CONSERVE : un transfert
 * de plusieurs gigaoctets interrompu doit pouvoir reprendre, pas repartir de zéro.
 */
export function annulerTelechargement(identifiant: string, supprimerFichiers = false): Promise<Telechargement> {
  return requeteJson<Telechargement>(`${TELECHARGEMENTS}/${encodeURIComponent(identifiant)}`, {
    methode: 'DELETE',
    parametres: { supprimer_fichiers: supprimerFichiers },
  });
}

/** Reprend un transfert interrompu là où il s'était arrêté. */
export function relancerTelechargement(identifiant: string): Promise<Telechargement> {
  return requeteJson<Telechargement>(`${TELECHARGEMENTS}/${encodeURIComponent(identifiant)}/relance`, {
    methode: 'POST',
  });
}

/**
 * Flux de progression des transferts. Chaque événement est un état complet, pas un delta : une
 * connexion tardive n'a rien à reconstituer. Route la moins certaine du fichier — aucun autre
 * domaine ne l'a encore supposée.
 */
export function fluxTelechargements(signal?: AbortSignal): AsyncGenerator<Telechargement> {
  return fluxJson<Telechargement>(`${TELECHARGEMENTS}/flux`, { methode: 'GET', signal });
}
