/*
 * Catalogue des outils que le harnais peut mettre à disposition du modèle.
 *
 * L'ordre est CELUI DU REGISTRE (`backend/outils/registre.py`) : c'est l'ordre dans lequel le
 * modèle voit les déclarations, il a un sens, on ne le réordonne pas alphabétiquement. Ce
 * catalogue local est le repli tant que la route `GET /chat/outils` (contrat proposé au backend,
 * voir le rapport) n'existe pas ; quand elle existera, elle fera foi — notamment pour le coût en
 * tokens des définitions, que seul le backend peut mesurer avec le vrai gabarit du modèle.
 *
 * Les groupes servent le geste « tout le web », « tous les fichiers » : c'est ce qui gardera
 * l'écran utilisable le jour où il y aura trente outils au lieu de dix.
 */

export type GroupeOutils = 'organisation' | 'web' | 'fichiers' | 'execution' | 'mcp' | 'presentation';

export interface OutilDisponible {
  readonly nom: string;
  readonly description: string;
  readonly groupe: GroupeOutils;
  /** Tokens occupés par la déclaration de l'outil, mesurés par le backend ; `null` = non mesuré. */
  readonly tokens_definition: number | null;
}

export const LIBELLE_GROUPE: Readonly<Record<GroupeOutils, string>> = {
  organisation: 'Organisation',
  web: 'Web',
  fichiers: 'Fichiers',
  execution: 'Exécution',
  mcp: 'MCP',
  presentation: 'Présentation',
};

export const CATALOGUE_OUTILS: readonly OutilDisponible[] = [
  {
    nom: 'suivre_taches',
    description: 'tient la liste de tâches de l’agent ; le tour ne finit pas tant qu’une tâche reste ouverte',
    groupe: 'organisation',
    tokens_definition: null,
  },
  {
    nom: 'recherche_web',
    description: 'cherche sur le web via SearXNG',
    groupe: 'web',
    tokens_definition: null,
  },
  {
    nom: 'recuperer_page',
    description: 'lit le contenu d’une page dont on a l’adresse',
    groupe: 'web',
    tokens_definition: null,
  },
  {
    nom: 'ecrire_fichier',
    description: 'écrit un fichier dans le bac de la conversation',
    groupe: 'fichiers',
    tokens_definition: null,
  },
  {
    nom: 'ecrire_fichiers',
    description: 'écrit plusieurs fichiers en un seul appel',
    groupe: 'fichiers',
    tokens_definition: null,
  },
  {
    nom: 'plan_fichier',
    description: 'structure d’un fichier (sections et lignes) avant de le lire par plage',
    groupe: 'fichiers',
    tokens_definition: null,
  },
  {
    nom: 'lire_fichier',
    description: 'relit un fichier du bac',
    groupe: 'fichiers',
    tokens_definition: null,
  },
  {
    nom: 'modifier_fichier',
    description: 'modifie une portion d’un fichier existant',
    groupe: 'fichiers',
    tokens_definition: null,
  },
  {
    nom: 'lister_fichiers',
    description: 'liste ce que le bac contient vraiment',
    groupe: 'fichiers',
    tokens_definition: null,
  },
  {
    nom: 'chercher_dans_fichiers',
    description: 'cherche un texte littéral avec fichier et numéro de ligne',
    groupe: 'fichiers',
    tokens_definition: null,
  },
  {
    nom: 'executer_python',
    description: 'exécute du Python confiné',
    groupe: 'execution',
    tokens_definition: null,
  },
  {
    nom: 'executer_commande',
    description: 'exécute une commande shell confinée (gcc, curl, git…)',
    groupe: 'execution',
    tokens_definition: null,
  },
  {
    nom: 'serveur_fond',
    description: 'lance un serveur de dev en arrière-plan, lit son journal, l’arrête',
    groupe: 'execution',
    tokens_definition: null,
  },
  {
    nom: 'presenter_fichier',
    description: 'affiche un fichier existant dans le fil',
    groupe: 'presentation',
    tokens_definition: null,
  },
  {
    nom: 'mcp_outils',
    description: 'liste les outils d’un serveur MCP déclaré dans ~agent/mcp.json',
    groupe: 'mcp',
    tokens_definition: null,
  },
  {
    nom: 'mcp_appeler',
    description: 'appelle un outil d’un serveur MCP (navigateur Playwright pour les tests e2e…)',
    groupe: 'mcp',
    tokens_definition: null,
  },
];

/*
 * Paires dont la séparation est presque toujours une erreur d'inattention. On SUGGÈRE, on
 * n'interdit pas : il existe des usages légitimes d'un membre seul (lire une URL connue sans
 * chercher), et une interface qui interdit un choix défendable se contourne au lieu de se lire.
 */
export interface PaireSuggeree {
  /** L'outil coché… */
  readonly actif: string;
  /** …qui a peu de sens sans celui-ci. */
  readonly requis: string;
  readonly raison: string;
}

export const PAIRES_SUGGEREES: readonly PaireSuggeree[] = [
  {
    actif: 'recuperer_page',
    requis: 'recherche_web',
    raison: 'sans recherche, le modèle n’a pas d’adresses à lire',
  },
  {
    actif: 'modifier_fichier',
    requis: 'lire_fichier',
    raison: 'modifier sans relire, c’est éditer à l’aveugle',
  },
  {
    actif: 'presenter_fichier',
    requis: 'lire_fichier',
    raison: 'présenter suppose de savoir ce que le bac contient',
  },
];
