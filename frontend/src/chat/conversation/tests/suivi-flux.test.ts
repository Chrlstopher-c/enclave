/*
 * Tests purs du suivi de flux : décision « muet ou non », coupure de la connexion, délais de reprise,
 * fusion par identifiant des listes relues. Lancement : `bun test` depuis `frontend/`.
 * Harnais local, comme dans `commandes/tests` (pas de types bun).
 */

import { fusionnerParId, memeContenu } from '../fusion-par-id';
import {
  creerSuivi,
  delaiApresEchec,
  fluxMuet,
  marquerOctet,
  nouvelleTentative,
  relancerSiMuet,
  SILENCE_AVANT_OCTET_MS,
  SILENCE_FLUX_MS,
} from '../suivi-flux-regles';

let echecs = 0;

function verifier(nom: string, obtenu: unknown, attendu: unknown): void {
  const gauche = JSON.stringify(obtenu);
  const droite = JSON.stringify(attendu);
  if (gauche === droite) {
    console.log(`ok    ${nom}`);
    return;
  }
  echecs += 1;
  console.log(`ÉCHEC ${nom}\n  obtenu  : ${gauche}\n  attendu : ${droite}`);
}

const T0 = 1_000_000;

/* ---- muet ou non ---- */
verifier('flux récent : pas muet', fluxMuet(T0, T0 + SILENCE_FLUX_MS - 1), false);
verifier('flux silencieux au seuil : muet', fluxMuet(T0, T0 + SILENCE_FLUX_MS), true);

/* ---- coupure de la connexion muette, jamais de la saine ---- */
{
  const sain = creerSuivi('a', T0);
  nouvelleTentative(sain, T0);
  verifier('connexion saine non coupée', relancerSiMuet(sain, T0 + 1_000), false);
  verifier('connexion saine : signal intact', sain.tentative?.signal.aborted, false);
}
{
  const muet = creerSuivi('a', T0);
  const tentative = nouvelleTentative(muet, T0);
  marquerOctet(muet, T0);
  verifier('connexion muette coupée', relancerSiMuet(muet, T0 + SILENCE_FLUX_MS + 5), true);
  verifier('connexion muette : signal abort', tentative.signal.aborted, true);
  verifier('suivi lui-même intact', muet.controle.signal.aborted, false);
}
verifier('sans suivi : rien', relancerSiMuet(null, T0 + SILENCE_FLUX_MS * 3), false);
verifier('sans connexion : rien', relancerSiMuet(creerSuivi('a', T0), T0 + SILENCE_FLUX_MS * 3), false);

/* ---- avant le premier octet : seuil plus large, puis seuil normal ---- */
{
  const enAttente = creerSuivi('a', T0);
  nouvelleTentative(enAttente, T0);
  verifier('en-têtes lents : pas coupés à 20 s', relancerSiMuet(enAttente, T0 + SILENCE_FLUX_MS + 1), false);
  verifier('en-têtes muets au-delà de 120 s : coupés', relancerSiMuet(enAttente, T0 + SILENCE_AVANT_OCTET_MS), true);
}
{
  const recevant = creerSuivi('a', T0);
  nouvelleTentative(recevant, T0);
  marquerOctet(recevant, T0 + 1_000);
  verifier('flux qui a donné un octet : seuil de 20 s', relancerSiMuet(recevant, T0 + 1_000 + SILENCE_FLUX_MS), true);
}

/* ---- annulation du suivi = coupure de chaque connexion ---- */
{
  const suivi = creerSuivi('a', T0);
  const tentative = nouvelleTentative(suivi, T0);
  suivi.controle.abort();
  verifier('annuler le suivi coupe la connexion', tentative.signal.aborted, true);
}
{
  const suivi = creerSuivi('a', T0);
  suivi.controle.abort();
  const tardive = nouvelleTentative(suivi, T0);
  verifier('connexion créée sur un suivi annulé : née coupée', tardive.signal.aborted, true);
}

/* ---- délais de reprise : bornés, croissants ---- */
verifier('premier échec : 1 s', delaiApresEchec(1), 1_000);
verifier('deuxième échec : 2 s', delaiApresEchec(2), 2_000);
verifier('plafond : 10 s', delaiApresEchec(20), 10_000);

/* ---- fusion par identifiant ---- */
type Element = { id: string; texte: string };
const avant: Element[] = [{ id: 'a', texte: '1' }, { id: 'b', texte: '2' }];
const memeAvant = avant[0];
const identiques = fusionnerParId(avant, [{ id: 'a', texte: '1' }, { id: 'b', texte: '2' }]);
verifier('liste identique : même tableau', identiques === avant, true);
verifier('élément inchangé : même objet', identiques[0] === memeAvant, true);

const modifiee = fusionnerParId(avant, [{ id: 'b', texte: '2' }, { id: 'a', texte: 'x' }, { id: 'c', texte: '3' }]);
verifier('ordre et contenu suivent le serveur', modifiee.map((e) => `${e.id}${e.texte}`), ['b2', 'ax', 'c3']);
verifier('élément modifié : nouvel objet', modifiee[1] !== memeAvant, true);
verifier('élément retiré disparaît', fusionnerParId(avant, [{ id: 'a', texte: '1' }]).length, 1);
verifier('memeContenu : égalité profonde', memeContenu({ x: [1] }, { x: [1] }), true);
verifier('memeContenu : différence', memeContenu({ x: [1] }, { x: [2] }), false);

if (echecs > 0) {
  throw new Error(`${echecs} test(s) en échec.`);
}
console.log('Tous les tests du suivi de flux passent.');
