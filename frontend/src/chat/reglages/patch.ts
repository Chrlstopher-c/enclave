/*
 * Fabrication du patch envoyé au backend : la différence, et rien d'autre.
 *
 * `PATCH /chat/conversations/{id}/reglages` fusionne champ par champ et traite la PRÉSENCE d'une
 * clé comme une demande d'écriture. N'envoyer que les champs réellement modifiés a deux effets :
 * deux panneaux ouverts sur la même conversation ne s'écrasent pas mutuellement sur des champs
 * qu'ils n'ont pas touchés, et un refus de validation nomme un champ que l'utilisateur vient de
 * changer, pas un champ renvoyé par recopie.
 *
 * `historique_max_messages` n'est pas exposé par ce panneau : il n'est donc jamais modifié, donc
 * jamais patché. L'omettre ici n'est pas un oubli, c'est la conséquence de ce périmètre.
 */

import type {
  CleParametre,
  CleReglage,
  MajParametres,
  MajReglages,
  ParametresConversation,
  Reglages,
} from './contrat';

/*
 * Ordre d'affichage du panneau : c'est aussi l'ordre dans lequel les champs non enregistrés sont
 * nommés à l'utilisateur, qui les relit donc là où il vient de les voir.
 */
const CLES_PARAMETRES: readonly CleParametre[] = [
  'temperature',
  'top_p',
  'top_k',
  'min_p',
  'penalite_repetition',
  'penalite_presence',
  'max_tokens',
  'sequences_arret',
  'graine',
];

function memeListe(gauche: readonly string[], droite: readonly string[]): boolean {
  return gauche.length === droite.length && gauche.every((valeur, index) => valeur === droite[index]);
}

function memeValeur(
  enregistre: ParametresConversation,
  brouillon: ParametresConversation,
  cle: CleParametre,
): boolean {
  // Seul champ non scalaire : deux tableaux de même contenu restent deux objets distincts, `===`
  // les dirait différents à chaque rendu et enverrait un patch en boucle.
  if (cle === 'sequences_arret') {
    return memeListe(enregistre.sequences_arret, brouillon.sequences_arret);
  }
  return enregistre[cle] === brouillon[cle];
}

/**
 * Recopie explicite plutôt qu'affectation par clé calculée : c'est le seul moyen de rester typé
 * sans `as`, chaque champ gardant son propre type dans le patch.
 */
function ajouterChamp(patch: MajParametres, source: ParametresConversation, cle: CleParametre): void {
  switch (cle) {
    case 'temperature':
      patch.temperature = source.temperature;
      break;
    case 'top_p':
      patch.top_p = source.top_p;
      break;
    case 'top_k':
      patch.top_k = source.top_k;
      break;
    case 'penalite_repetition':
      patch.penalite_repetition = source.penalite_repetition;
      break;
    case 'max_tokens':
      patch.max_tokens = source.max_tokens;
      break;
    case 'sequences_arret':
      patch.sequences_arret = [...source.sequences_arret];
      break;
    case 'graine':
      patch.graine = source.graine;
      break;
  }
}

export function parametresModifies(
  enregistre: ParametresConversation,
  brouillon: ParametresConversation,
): CleParametre[] {
  return CLES_PARAMETRES.filter((cle) => !memeValeur(enregistre, brouillon, cle));
}

/** Champs dont la valeur affichée diffère de la dernière valeur confirmée par le backend. */
export function reglagesModifies(enregistre: Reglages, brouillon: Reglages): CleReglage[] {
  const modifies: CleReglage[] = parametresModifies(enregistre.parametres, brouillon.parametres);
  if (enregistre.prompt_systeme !== brouillon.prompt_systeme) {
    modifies.unshift('prompt_systeme');
  }
  return modifies;
}

/** Patch minimal, ou `null` quand l'affiché et l'enregistré coïncident — rien à envoyer alors. */
export function construirePatch(enregistre: Reglages, brouillon: Reglages): MajReglages | null {
  const modifies = reglagesModifies(enregistre, brouillon);
  if (modifies.length === 0) {
    return null;
  }
  const patch: MajReglages = {};
  if (modifies.includes('prompt_systeme')) {
    patch.prompt_systeme = brouillon.prompt_systeme;
  }
  const parametres: MajParametres = {};
  for (const cle of CLES_PARAMETRES) {
    if (modifies.includes(cle)) {
      ajouterChamp(parametres, brouillon.parametres, cle);
    }
  }
  if (Object.keys(parametres).length > 0) {
    patch.parametres = parametres;
  }
  return patch;
}
