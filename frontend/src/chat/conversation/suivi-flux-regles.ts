/*
 * Règles pures du suivi d'un flux de génération : quand un flux est jugé muet, quel délai avant une
 * nouvelle tentative. Aucune dépendance au DOM ni au réseau, donc testables seules.
 */

export const SILENCE_FLUX_MS = 20_000;
/* Avant le premier octet, le serveur prépare encore la réponse (chargement, compaction de départ) : seuil plus large. */
export const SILENCE_AVANT_OCTET_MS = 120_000;
export const PERIODE_SURVEILLANCE_MS = 5_000;
export const DELAI_APRES_FLUX_MS = 150;
const DELAI_MIN_ECHEC_MS = 1_000;
const DELAI_MAX_ECHEC_MS = 10_000;

/**
 * Un suivi par flux. `controle` vit tant que la conversation est suivie (annulation, changement de
 * conversation) ; `tentative` est la connexion courante, qu'on peut couper sans abandonner le suivi.
 */
export interface SuiviFlux {
  readonly proprietaire: string;
  readonly controle: AbortController;
  tentative: AbortController | null;
  /** Heure (ms) du dernier octet reçu, ou du lancement de la tentative. */
  vuMs: number;
  /** Vrai dès qu'un octet de la tentative courante a été reçu. */
  octets: boolean;
}

export function creerSuivi(proprietaire: string, maintenantMs: number): SuiviFlux {
  return { proprietaire, controle: new AbortController(), tentative: null, vuMs: maintenantMs, octets: false };
}

export function fluxMuet(vuMs: number, maintenantMs: number, seuilMs: number = SILENCE_FLUX_MS): boolean {
  return maintenantMs - vuMs >= seuilMs;
}

export function marquerOctet(suivi: SuiviFlux, maintenantMs: number): void {
  suivi.octets = true;
  suivi.vuMs = maintenantMs;
}

/** Connexion neuve, reliée au contrôle du suivi : l'annulation du suivi la coupe aussi. */
export function nouvelleTentative(suivi: SuiviFlux, maintenantMs: number): AbortController {
  const tentative = new AbortController();
  if (suivi.controle.signal.aborted) {
    tentative.abort();
  } else {
    suivi.controle.signal.addEventListener('abort', (): void => tentative.abort(), { once: true });
  }
  suivi.tentative = tentative;
  suivi.vuMs = maintenantMs;
  suivi.octets = false;
  return tentative;
}

/** Coupe la connexion courante si elle est muette. Rend `true` quand une coupure a été faite. */
export function relancerSiMuet(suivi: SuiviFlux | null, maintenantMs: number): boolean {
  const tentative = suivi?.tentative ?? null;
  if (suivi === null || tentative === null || tentative.signal.aborted) {
    return false;
  }
  const seuil = suivi.octets ? SILENCE_FLUX_MS : SILENCE_AVANT_OCTET_MS;
  if (!fluxMuet(suivi.vuMs, maintenantMs, seuil)) {
    return false;
  }
  tentative.abort();
  return true;
}

/** Attente avant de réessayer après un échec réseau : 1 s, puis doublée, plafonnée à 10 s. */
export function delaiApresEchec(echecs: number): number {
  return Math.min(DELAI_MIN_ECHEC_MS * 2 ** Math.max(0, echecs - 1), DELAI_MAX_ECHEC_MS);
}
