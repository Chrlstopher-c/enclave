/*
 * Interface publique du client API — seul point d'import autorisé pour les écrans.
 *
 * Les domaines `models`, `chat` et `system` du frontend importent d'ici, jamais d'un fichier
 * interne : le découpage (transport, SSE, types par domaine) doit pouvoir changer sans les
 * toucher. Aucun écran n'appelle `fetch` directement — c'est ce qui rend la gestion d'erreur et
 * les délais réellement uniformes.
 */

export { ErreurApi, CODE_DELAI, CODE_FLUX_TROP_LONG, CODE_ILLISIBLE, CODE_RESEAU } from './erreurs';
export type { DetailErreur } from './erreurs';

export { BASE_API } from './transport';
export type { MethodeHttp, OptionsRequete } from './transport';

export { SENTINELLE_FIN } from './sse';
export type { OptionsFlux } from './sse';

export { lireProfilMachine } from './systeme';
export type * from './types-systeme';

export {
  annulerInstallationVllm,
  fluxInstallationVllm,
  lireEtatMoteurs,
  lireSanteLlamaCpp,
  listerVersionsVllm,
  supprimerVersionVllm,
} from './moteurs';
export type { OptionsEtatMoteurs } from './moteurs';
export type * from './types-moteurs';

export {
  attendreEtatInference,
  chargerModele,
  degraderPlan,
  dechargerModele,
  genererDirect,
  lireEtatInference,
  lireJournalChargements,
  mesurerOccupationContexte,
  planifierChargement,
  sonderSanteInference,
} from './inference';
export type { DemandeDegradation, DemandeGenerationDirecte, RequeteChargement } from './inference';
export type * from './types-plan';
export type * from './types-inference';

export {
  annulerGeneration,
  creerConversation,
  genererDansConversation,
  lireConversation,
  lireReglages,
  listerConversations,
  listerMessages,
  modifierConversation,
  modifierReglages,
  supprimerConversation,
  viderMessages,
} from './chat';
export { MAX_TOKENS_PLAFOND } from './types-chat';
export type * from './types-chat';

export {
  annulerTelechargement,
  demarrerTelechargement,
  detailsDepot,
  fluxTelechargements,
  listerModelesLocaux,
  listerTelechargements,
  metadonneesModele,
  metadonneesSafetensors,
  obtenirModele,
  oublierModele,
  rechercherModeles,
  relancerTelechargement,
  synchroniserRegistre,
  verifierModele,
} from './modeles';
export type { CriteresRecherche, DemandeTelechargement } from './modeles';
export type * from './types-modeles';

export {
  couchesCpu,
  environnementDuPlan,
  estPlanDegrade,
  exigeEjection,
  vramRequiseOctets,
  vramRestanteOctets,
} from './derivations';
