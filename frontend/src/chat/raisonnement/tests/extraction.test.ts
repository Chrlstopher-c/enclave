/*
 * Tests purs de la séparation raisonnement / réponse — aucune dépendance, aucun rendu.
 *
 * Lancement : `bun run frontend/src/chat/raisonnement/tests/extraction.test.ts`
 * Le fichier lève à la fin s'il reste un échec : le code de sortie est non nul, exploitable en CI.
 *
 * Le dernier test rejoue l'invariant du backend (`test_contexte.py`) : aucun caractère perdu.
 * C'est la seule garantie qui compte pendant le streaming — un découpage qui « range » du texte
 * hors des deux parts le ferait disparaître de l'écran sans aucun message d'erreur.
 */

import { CONVENTIONS_RAISONNEMENT } from '../conventions';
import { segmenterReponse, type SegmentRaisonnement } from '../extraction';

let echecs = 0;

function verifier(nom: string, obtenu: unknown, attendu: unknown): void {
  const gauche = JSON.stringify(obtenu);
  const droite = JSON.stringify(attendu);
  if (gauche === droite) {
    console.log(`ok    ${nom}`);
    return;
  }
  echecs += 1;
  console.error(`ÉCHEC ${nom}\n  obtenu  : ${gauche}\n  attendu : ${droite}`);
}

/** Longueur des balises retirées par l'extraction, pour recomposer la longueur de la source. */
function longueurBalises(segment: SegmentRaisonnement): number {
  const convention = CONVENTIONS_RAISONNEMENT.find((candidate) => candidate.nom === segment.convention);
  if (convention === undefined) {
    throw new Error(`convention inconnue : ${segment.convention}`);
  }
  return convention.ouvrante.length + (segment.complet ? convention.fermante.length : 0);
}

function testerSansRaisonnement(): void {
  const segmentee = segmenterReponse('Bonjour, voici la réponse.');
  verifier('texte sans balise : tout est visible', segmentee.visible, 'Bonjour, voici la réponse.');
  verifier('aucun bloc de raisonnement', segmentee.raisonnements.length, 0);
  verifier('rien en cours', segmentee.enCours, false);
}

function testerBlocFerme(): void {
  const segmentee = segmenterReponse('<think>je réfléchis</think>Réponse.');
  verifier('réponse isolée du raisonnement', segmentee.visible, 'Réponse.');
  verifier(
    'contenu du bloc, balises retirées',
    segmentee.raisonnements.map((segment) => [segment.texte, segment.complet, segment.convention]),
    [['je réfléchis', true, 'think']],
  );
  verifier('bloc refermé : rien en cours', segmentee.enCours, false);
}

function testerBlocOuvert(): void {
  const segmentee = segmenterReponse('début<think>coupé au milieu');
  verifier('texte avant la balise conservé', segmentee.visible, 'début');
  verifier(
    'bloc jamais refermé : incomplet, et prolongé jusqu\'à la fin du texte reçu',
    segmentee.raisonnements.map((segment) => [segment.texte, segment.complet]),
    [['coupé au milieu', false]],
  );
  verifier('raisonnement en cours signalé', segmentee.enCours, true);
}

function testerPlusieursBlocs(): void {
  const segmentee = segmenterReponse('a<think>un</think>b<think>deux</think>c');
  verifier('parts visibles recollées dans l\'ordre', segmentee.visible, 'abc');
  verifier(
    'deux blocs, dans l\'ordre d\'émission',
    segmentee.raisonnements.map((segment) => segment.texte),
    ['un', 'deux'],
  );
}

function testerReponseVide(): void {
  const toutEnRaisonnement = segmenterReponse('<think>tout le budget est passé ici</think>');
  verifier('réponse vide quand tout est raisonnement', toutEnRaisonnement.visible, '');
  verifier('le bloc reste complet', toutEnRaisonnement.raisonnements[0]?.complet ?? null, true);

  const vide = segmenterReponse('<think></think>Réponse.');
  verifier('bloc vide toléré', vide.raisonnements[0]?.texte ?? null, '');
  verifier('réponse toujours lue après un bloc vide', vide.visible, 'Réponse.');
}

function testerAucunCaracterePerdu(): void {
  const sources = [
    'Bonjour.',
    '<think>un</think>réponse',
    'a<think>un</think>b<think>deux</think>c',
    'début<think>jamais refermé',
    '<think>seulement du raisonnement</think>',
  ];
  for (const source of sources) {
    const segmentee = segmenterReponse(source);
    const balises = segmentee.raisonnements.reduce((total, segment) => total + longueurBalises(segment), 0);
    const raisonne = segmentee.raisonnements.reduce((total, segment) => total + segment.texte.length, 0);
    verifier(`aucun caractère perdu : « ${source} »`, segmentee.visible.length + raisonne + balises, source.length);
  }
}

function testerConsigneGlissee(): void {
  const source = 'Je lis.<outil>x</outil>\n<etape-fin/>\n<consigne>id:k1\nUtilise pnpm</consigne>\nBilan.';
  const segmentee = segmenterReponse(source);
  const consigne = segmentee.raisonnements.find((segment) => segment.convention === 'consigne');
  verifier('consigne glissée reconnue', consigne?.texte ?? '', 'id:k1\nUtilise pnpm');
  verifier('la réponse reste visible après la consigne', segmentee.visible.trim(), 'Bilan.');
}

testerSansRaisonnement();
testerConsigneGlissee();
testerBlocFerme();
testerBlocOuvert();
testerPlusieursBlocs();
testerReponseVide();
testerAucunCaracterePerdu();

if (echecs > 0) {
  throw new Error(`${echecs} test(s) en échec`);
}
console.log('extraction du raisonnement : tous les tests passent');
