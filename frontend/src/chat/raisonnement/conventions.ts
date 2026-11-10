/*
 * Conventions de balisage du raisonnement.
 *
 * Une seule est CONSTATÉE sur les modèles servis par le projet : `<think>` / `</think>` (famille
 * Qwen3, DeepSeek-R1). Le backend la reconnaît littéralement dans
 * `backend/inference/engines_adapters/contrat.py` (`BALISE_RAISONNEMENT_OUVRANTE`), et c'est de là
 * que vient le poste « raisonnement » du panneau de contexte.
 *
 * La liste est le point d'extension : ajouter une convention observée = ajouter une entrée, rien
 * d'autre à toucher. Aucune n'est ajoutée « au cas où » — un format non constaté découperait des
 * réponses sur une balise imaginaire, et ferait disparaître du texte réel de l'écran.
 *
 * Toute entrée ajoutée ici doit l'être aussi côté backend : sinon le texte serait masqué à l'écran
 * tout en restant compté dans le poste « réponses » du contexte, et les deux affichages mentiraient
 * l'un par rapport à l'autre.
 */

export interface ConventionRaisonnement {
  /** Nom court, repris tel quel dans l'interface quand plusieurs conventions coexistent. */
  readonly nom: string;
  readonly ouvrante: string;
  readonly fermante: string;
}

export const CONVENTIONS_RAISONNEMENT: readonly ConventionRaisonnement[] = [
  { nom: 'think', ouvrante: '<think>', fermante: '</think>' },
  // CONSTATÉE le 2026-08-14 sur les dérivés Qwen3.6 abliterated chargés ici : la balise sort telle
  // quelle dans la réponse et s'affiche à l'écran. Ajoutée pour cette raison, pas par précaution.
  { nom: 'process', ouvrante: '<process>', fermante: '</process>' },
  // Posée par NOTRE harnais, pas par un modèle : `backend/inference/__init__.py` encadre ainsi
  // chaque appel d'outil et son résultat. Repliée comme le raisonnement — c'est du travail
  // intermédiaire, pas la réponse —, mais nommée « outil » pour que la distinction reste nette.
  { nom: 'outil', ouvrante: '<outil>', fermante: '</outil>' },
  // L'appel émis par le MODÈLE, dans son propre balisage. Il traverse le flux avant d'être exécuté
  // — il est lu à la fin du tour, pas retiré du texte au vol — et il s'affichait donc en clair au
  // milieu de la réponse. Replié ici : c'est une instruction machine, pas un propos adressé au
  // lecteur. Les deux dialectes constatés ont la même balise englobante.
  { nom: 'appel', ouvrante: '<tool_call>', fermante: '</tool_call>' },
  // Certains gabarits l'émettent sans englobant. Même traitement, pour la même raison.
  { nom: 'appel', ouvrante: '<function=', fermante: '</function>' },
  // Posée par NOTRE harnais (`backend/inference/consignes.py`) : un message que l'utilisateur a glissé
  // pendant le travail, lu par l'agent à la fin de son étape. Rendu à sa place, comme un message à lui.
  { nom: 'consigne', ouvrante: '<consigne>', fermante: '</consigne>' },
];

/** Libellé affiché en tête d'un bloc replié, par convention. */
export const LIBELLE_CONVENTION: Readonly<Record<string, string>> = {
  think: 'Raisonnement',
  process: 'Raisonnement',
  outil: 'Outil',
  // « Note de travail » plutôt qu'« Étape » : le contenu est le commentaire que le modèle écrit
  // entre deux appels (« je vais chercher », « je synthétise ») — le nommer par sa nature dit au
  // lecteur s'il vaut d'être déplié, un numéro d'étape ne dit rien.
  etape: 'Note de travail',
  appel: 'Appel du modèle',
  consigne: 'Ton message',
};
