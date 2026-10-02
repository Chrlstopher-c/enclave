/*
 * Lecture d'un bloc d'outil pour l'affichage en carte : quel outil, sur quoi, dans quel état.
 *
 * Le backend émet `<outil><entree>nom(cle : valeur, …)</entree><sortie>…</sortie></outil>`
 * (`backend/inference/harnais_outils.py`, `_annonce`). Ce module transforme cette forme textuelle
 * en une lecture d'un coup d'œil — libellé français, argument principal, état — sans jamais
 * prétendre comprendre ce qu'il ne reconnaît pas : un outil inconnu garde son nom brut et sa
 * première ligne d'arguments, il n'emprunte ni libellé ni cible qui mentiraient.
 *
 * Fonctions pures, testables sans rendu (`tests/lecture-appel.test.ts`).
 */

import { decouperAppel } from './appel-outil';

/** Clé d'icône monochrome — le dessin vit dans `icones.tsx`, la carte ne connaît que le mot. */
export type IconeOutil =
  | 'loupe'
  | 'globe'
  | 'document'
  | 'crayon'
  | 'dossier'
  | 'terminal'
  | 'code'
  | 'cadre'
  | 'outil';

export interface DescripteurOutil {
  /** Libellé français court, affiché à la place du nom technique. */
  readonly libelle: string;
  readonly icone: IconeOutil;
  /**
   * Clés candidates de l'argument principal, dans l'ordre de priorité. Les alias y figurent parce
   * que `_annonce` affiche les arguments TELS QUE REÇUS, avant normalisation : un modèle qui écrit
   * `pattern` au lieu de `motif` doit quand même produire une cible lisible.
   */
  readonly cles: readonly string[];
}

/*
 * Les dix outils du harnais (`backend/outils/registre.py`). Un outil absent d'ici s'affiche avec
 * son nom brut — c'est voulu : inventer un libellé pour un outil ajouté côté backend sans mise à
 * jour ici serait pire qu'un nom technique exact.
 */
export const OUTILS_CONNUS: Readonly<Record<string, DescripteurOutil>> = {
  suivre_taches: { libelle: 'Tâches', icone: 'document', cles: ['taches', 'todos'] },
  mcp_outils: { libelle: 'MCP', icone: 'code', cles: ['serveur', 'outil'] },
  mcp_appeler: { libelle: 'MCP', icone: 'code', cles: ['outil', 'serveur'] },
  recherche_web: { libelle: 'Recherche web', icone: 'loupe', cles: ['requete', 'query', 'q'] },
  recuperer_page: { libelle: 'Page web', icone: 'globe', cles: ['url', 'lien', 'adresse'] },
  ecrire_fichier: { libelle: 'Écriture', icone: 'crayon', cles: ['chemin', 'path', 'fichier', 'nom'] },
  ecrire_fichiers: { libelle: 'Écriture groupée', icone: 'crayon', cles: ['fichiers', 'files'] },
  plan_fichier: { libelle: 'Plan', icone: 'document', cles: ['chemin', 'path', 'fichier'] },
  lire_fichier: { libelle: 'Lecture', icone: 'document', cles: ['chemin', 'path', 'fichier', 'nom'] },
  modifier_fichier: { libelle: 'Modification', icone: 'crayon', cles: ['chemin', 'path', 'fichier', 'nom'] },
  lister_fichiers: { libelle: 'Dossier', icone: 'dossier', cles: ['motif', 'pattern', 'glob', 'chemin'] },
  chercher_dans_fichiers: { libelle: 'Recherche fichiers', icone: 'loupe', cles: ['motif', 'pattern', 'texte'] },
  executer_python: { libelle: 'Python', icone: 'code', cles: ['fichier', 'chemin', 'code', 'source'] },
  executer_commande: { libelle: 'Commande', icone: 'terminal', cles: ['commande', 'command', 'cmd', 'shell'] },
  presenter_fichier: { libelle: 'Fichier présenté', icone: 'cadre', cles: ['fichier_id', 'nom', 'chemin'] },
  creer_artefact: { libelle: 'Artefact', icone: 'cadre', cles: ['titre', 'nom'] },
};

export type EtatAppel = 'en_cours' | 'termine' | 'echec' | 'interrompu';

export interface AppelLisible {
  /** Nom technique de l'outil, tel qu'émis. */
  readonly nom: string;
  readonly libelle: string;
  readonly icone: IconeOutil;
  /** Argument principal, ramené à sa première ligne — la cible de l'appel, pas son détail. */
  readonly cible: string | null;
  /** Entrée complète, pour le détail déplié. */
  readonly entree: string;
  readonly sortie: string;
  readonly etat: EtatAppel;
}

/*
 * Préfixes d'échec ÉMIS PAR LE HARNAIS lui-même (`backend/outils/registre.py`, `_REDITE`). Un outil
 * en échec attendu (`EchecOutil`) rend un texte libre que rien ne distingue d'un résultat : ces
 * cas-là s'affichent « terminé ». La détection fiable exigerait que le backend persiste l'issue
 * dans le balisage — limite documentée dans le rapport, pas contournée par une devinette.
 */
const PREFIXES_ECHEC: readonly string[] = [
  "Échec de l'outil : ",
  "L'outil « ",
  'Failed:',
];

function nomDepuisEntree(entree: string): { nom: string; detail: string } {
  const parenthese = entree.indexOf('(');
  if (parenthese < 0) {
    return { nom: entree.trim(), detail: '' };
  }
  const nom = entree.slice(0, parenthese).trim();
  // La parenthèse fermante peut manquer si l'aperçu backend a tronqué : on retire seulement celle
  // qui clôt réellement la fin du texte.
  const brut = entree.slice(parenthese + 1);
  return { nom, detail: brut.endsWith(')') ? brut.slice(0, -1) : brut };
}

/*
 * Coupe une valeur d'argument à la clé suivante. La forme `, cle : ` peut apparaître dans une
 * valeur en prose ; le risque est assumé parce qu'il ne coûte qu'une cible raccourcie sur la
 * carte — le détail déplié montre toujours l'entrée entière.
 */
const SEPARATEUR_ARGUMENT = /,\s(?=[\w-]+ : )/;

function valeurPourCle(detail: string, cle: string): string | null {
  const marque = `${cle} : `;
  const debut = detail.indexOf(marque);
  if (debut < 0) {
    return null;
  }
  const reste = detail.slice(debut + marque.length);
  const ligne = reste.split('\n')[0] ?? reste;
  const coupe = ligne.split(SEPARATEUR_ARGUMENT)[0] ?? ligne;
  const propre = coupe.trim();
  return propre === '' ? null : propre;
}

function cibleDepuisDetail(detail: string, cles: readonly string[]): string | null {
  for (const cle of cles) {
    const valeur = valeurPourCle(detail, cle);
    if (valeur !== null) {
      return valeur;
    }
  }
  // Aucune clé connue : la première ligne du détail reste plus parlante qu'un vide.
  const ligne = detail.split('\n')[0]?.trim() ?? '';
  return ligne === '' ? null : ligne;
}

function etatDepuisSortie(
  sortie: string,
  termine: boolean,
  actif: boolean,
  echecDeclare: boolean,
): EtatAppel {
  if (!termine) {
    // Sans génération en cours, une sortie jamais refermée est un appel coupé net (arrêt manuel,
    // plafond de tokens) : le dire évite un « en cours » qui pulserait pour toujours.
    return actif ? 'en_cours' : 'interrompu';
  }
  // L'issue DÉCLARÉE par le harnais prime : depuis le 26/08/2026 il écrit `<sortie etat="echec">`,
  // et il tient ce fait de l'exécution même de l'outil. Aucune lecture de texte ne peut faire mieux.
  if (echecDeclare) {
    return 'echec';
  }
  // Repli par préfixe, pour les messages ENREGISTRÉS AVANT cette date, dont la sortie ne porte
  // aucun attribut. Il ne s'applique donc qu'à de l'historique : c'est ce qui permet de le
  // supprimer un jour sans rien casser, alors qu'il était jusqu'ici la seule source — et une
  // lecture par préfixe ne survit ni à une reformulation, ni à une traduction, ni à un
  // `EchecOutil` au texte libre.
  return PREFIXES_ECHEC.some((prefixe) => sortie.startsWith(prefixe)) ? 'echec' : 'termine';
}

/**
 * Lit un segment d'outil (`convention === 'outil'`). Rend `null` quand le texte ne porte pas le
 * balisage attendu — l'appelant retombe alors sur un bloc replié générique, jamais sur du vide.
 *
 * `actif` distingue « l'outil travaille » de « la génération a été coupée en plein appel » : le
 * texte seul ne peut pas le savoir.
 */
export function lireAppel(texte: string, actif: boolean): AppelLisible | null {
  const appel = decouperAppel(texte);
  if (appel === null || appel.entree === '') {
    return null;
  }
  const { nom, detail } = nomDepuisEntree(appel.entree);
  const connu = OUTILS_CONNUS[nom];
  return {
    nom,
    libelle: connu?.libelle ?? nom,
    icone: connu?.icone ?? 'outil',
    cible: cibleDepuisDetail(detail, connu?.cles ?? []),
    entree: appel.entree,
    sortie: appel.sortie,
    etat: etatDepuisSortie(appel.sortie, appel.termine, actif, appel.echec),
  };
}
