/*
 * Vocabulaire des réglages : bornes RÉELLES du backend et ce que chaque paramètre fait.
 *
 * Les bornes sont recopiées de `backend/chat/modeles.py` (`ParametresEchantillonnage`) et de nulle
 * part ailleurs. Proposer une plage plus large ferait perdre une saisie sur un refus à
 * l'enregistrement ; une plage plus étroite interdirait un réglage que le backend accepte. Quand le
 * backend ne pose PAS de borne, la borne vaut `null` ici : on n'en invente pas une « raisonnable ».
 *
 * Les phrases d'effet décrivent ce que le moteur fait de la valeur, vérifié dans
 * `backend/inference/engines_adapters/adaptateur_llama_cpp.py` (`_arguments_echantillonnage`) et
 * `backend/inference/__init__.py` (`_options_depuis`) : un réglage laissé à sa valeur neutre n'est
 * pas transmis au moteur, qui garde alors son propre défaut.
 */

import { formaterTokens } from '../plan/format';
import type { CleReglage } from './contrat';

/** Plafond de `max_tokens` — `MAX_TOKENS_PLAFOND` du domaine chat, qui borne aussi sa boucle. */
export const PLAFOND_MAX_TOKENS = 262_144;

/** Bornes d'un curseur : le backend en pose deux, donc les deux existent. */
export interface Plage {
  readonly min: number;
  readonly max: number;
  /** Granularité du curseur : une commodité de saisie, pas une contrainte du backend. */
  readonly pas: number;
}

/** Bornes d'un entier saisi. `null` = le backend n'en pose aucune de ce côté. */
export interface PlageEntiere {
  readonly min: number | null;
  readonly max: number | null;
}

export interface DefinitionParametre {
  readonly libelle: string;
  /** Ce que la valeur fait réellement. Pas une paraphrase du libellé. */
  readonly effet: string;
  /** Sens de la valeur neutre ou vide, quand elle en a un propre. Vide sinon. */
  readonly absence: string;
}

export interface DefinitionCurseur extends DefinitionParametre {
  readonly plage: Plage;
}

export interface DefinitionEntier extends DefinitionParametre {
  readonly plage: PlageEntiere;
}

const DECIMALES_2 = new Intl.NumberFormat('fr-FR', {
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
});

/** Valeur d'un curseur, largeur fixe : un chiffre qui bouge ne saute pas horizontalement. */
export function formaterDecimal(valeur: number): string {
  return DECIMALES_2.format(valeur);
}

export function formaterPlage(plage: Plage): string {
  return `${formaterDecimal(plage.min)} – ${formaterDecimal(plage.max)}`;
}

/** Bornes d'un entier, dites telles qu'elles sont — y compris quand il n'y en a qu'une, ou aucune. */
export function formaterPlageEntiere(plage: PlageEntiere): string {
  const { min, max } = plage;
  if (min !== null && max !== null) {
    return `${formaterTokens(min)} – ${formaterTokens(max)}`;
  }
  if (min !== null) {
    return `≥ ${formaterTokens(min)}, aucune borne haute`;
  }
  if (max !== null) {
    return `≤ ${formaterTokens(max)}`;
  }
  return 'entier, aucune borne';
}

export const TEMPERATURE: DefinitionCurseur = {
  libelle: 'Température',
  effet:
    'Étale ou resserre la distribution avant le tirage du jeton suivant. À 0 le jeton le plus '
    + 'probable est toujours retenu ; au-delà de 1, des jetons improbables passent devant.',
  absence: '',
  plage: { min: 0, max: 2, pas: 0.05 },
};

export const TOP_P: DefinitionCurseur = {
  libelle: 'Top-p',
  effet:
    'Ne tire que parmi les jetons les plus probables, jusqu’à ce que leurs probabilités cumulées '
    + 'atteignent cette part. À 1, aucun jeton n’est écarté par ce critère.',
  absence: '',
  // `gt=0` côté backend : zéro est refusé, le pas de 0,01 fait donc du 0,01 le plancher atteignable.
  plage: { min: 0.01, max: 1, pas: 0.01 },
};

export const PENALITE_REPETITION: DefinitionCurseur = {
  libelle: 'Pénalité de répétition',
  effet:
    'Abaisse la probabilité des jetons déjà présents dans le contexte. À 1 le modèle est libre de '
    + 'se répéter ; plus haut il évite ce qu’il a déjà écrit, y compris les mots dont il a besoin.',
  absence: '',
  plage: { min: 0, max: 2, pas: 0.01 },
};

export const MIN_P: DefinitionCurseur = {
  libelle: 'Min-p',
  effet:
    'Écarte les jetons dont la probabilité est inférieure à cette fraction de celle du plus probable. '
    + 'Qwen3.6 recommande 0 : le critère est alors inactif.',
  absence: '',
  plage: { min: 0, max: 1, pas: 0.01 },
};

export const PENALITE_PRESENCE: DefinitionCurseur = {
  libelle: 'Pénalité de présence',
  effet:
    'Pénalise d’un montant fixe tout jeton déjà apparu : c’est le réglage que Qwen recommande contre les '
    + 'boucles de répétition (jusqu’à 1,5). Trop haut, il mélange les langues et dégrade le code.',
  absence: '',
  plage: { min: 0, max: 2, pas: 0.05 },
};

export const TOP_K: DefinitionEntier = {
  libelle: 'Top-k',
  effet:
    'Ne garde que les k jetons les plus probables avant le tirage. Se combine avec top-p : le plus '
    + 'restrictif des deux commande.',
  absence: '0 désactive le critère — le réglage n’est alors pas transmis au moteur.',
  // `ge=0` seul : le backend ne pose aucune borne haute, on n'en fabrique pas.
  plage: { min: 0, max: null },
};

export const MAX_TOKENS: DefinitionEntier = {
  libelle: 'Plafond de réponse',
  effet:
    'Nombre maximal de jetons produits pour une réponse, blocs de raisonnement compris. Le moteur '
    + 'coupe net à cette valeur, où qu’en soit la phrase.',
  absence:
    'Vide = aucun plafond : la génération s’arrête alors sur la fenêtre de contexte servie par le '
    + 'moteur, pas sur un nombre posé ici.',
  plage: { min: 1, max: PLAFOND_MAX_TOKENS },
};

export const GRAINE: DefinitionEntier = {
  libelle: 'Graine',
  effet:
    'Fixe le tirage aléatoire : à graine, réglages et historique identiques, la même question '
    + 'redonne la même réponse.',
  absence: 'Vide = tirage différent à chaque génération.',
  // Aucune borne côté backend : ni minimum, ni maximum.
  plage: { min: null, max: null },
};

export const SEQUENCES_ARRET: DefinitionParametre = {
  libelle: 'Séquences d’arrêt',
  effet:
    'Le moteur interrompt la génération dès qu’il produit l’une de ces chaînes, et ne l’écrit pas '
    + 'dans la réponse.',
  absence: 'Aucune séquence : seul le marqueur de fin du modèle arrête la génération.',
};

export const PROMPT_SYSTEME: DefinitionParametre = {
  libelle: 'Prompt système',
  effet:
    'Instructions replacées en tête du prompt à chaque tour. Elles occupent du contexte en '
    + 'permanence, avant le premier message de la conversation.',
  absence: '',
};

/** Libellés indexés par clé : sert à nommer les champs qu’un enregistrement a laissés de côté. */
export const LIBELLES: Record<CleReglage, string> = {
  prompt_systeme: PROMPT_SYSTEME.libelle,
  temperature: TEMPERATURE.libelle,
  top_p: TOP_P.libelle,
  top_k: TOP_K.libelle,
  min_p: MIN_P.libelle,
  penalite_repetition: PENALITE_REPETITION.libelle,
  penalite_presence: PENALITE_PRESENCE.libelle,
  max_tokens: MAX_TOKENS.libelle,
  sequences_arret: SEQUENCES_ARRET.libelle,
  graine: GRAINE.libelle,
};
