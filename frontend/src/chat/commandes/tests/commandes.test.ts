/*
 * Tests purs du domaine des commandes : lecture de la saisie, masquage après `/clear`, progression
 * et temporalité. Lancement : `bun test` depuis `frontend/` (ou `bun run` sur ce fichier).
 * Harnais recopié localement, comme dans `markdown/tests` et `artefacts/tests` (pas de types bun).
 */

import type { ActiviteMoteur, MessageChat } from '../../api/contrats';
import { analyserSaisie, completion, estComplete, filtrerCommandes, nomEnFrappe, refusArguments } from '../analyse';
import type { DefinitionCommande } from '../contrats';
import { depuisDebut, dureeGeneration, horodatageLisible } from '../horodatage';
import { heureEffacement, masquerEfface } from '../masquage';
import { dureeEcoulee, etapesDepuisCle, formaterDuree, jetonsEcrits, repereActivite } from '../progression';

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

const COMPACT: DefinitionCommande = {
  nom: 'compact', usage: '/compact [instructions]', description: 'c', arguments: true,
};
const CLEAR: DefinitionCommande = { nom: 'clear', usage: '/clear', description: 'v', arguments: false };
const CATALOGUE = [COMPACT, CLEAR];

/* ---- analyse de la saisie ---- */
verifier('texte ordinaire', analyserSaisie('bonjour', CATALOGUE), { type: 'texte' });
verifier('« / » au milieu = texte', analyserSaisie('et/ou /compact', CATALOGUE), { type: 'texte' });
verifier('échappement //', analyserSaisie('//compact', CATALOGUE), { type: 'litteral', contenu: '/compact' });
verifier('commande nue', analyserSaisie('/compact', CATALOGUE),
  { type: 'commande', nom: 'compact', arguments: '', definition: COMPACT });
verifier('commande + arguments multilignes', analyserSaisie('/compact garde\nles endpoints  ', CATALOGUE),
  { type: 'commande', nom: 'compact', arguments: 'garde\nles endpoints', definition: COMPACT });
verifier('casse ignorée', analyserSaisie('/CLEAR', CATALOGUE),
  { type: 'commande', nom: 'clear', arguments: '', definition: CLEAR });
verifier('inconnue', analyserSaisie('/xyz a', CATALOGUE),
  { type: 'commande', nom: 'xyz', arguments: 'a', definition: null });
verifier('slash seul', analyserSaisie('/', CATALOGUE), { type: 'commande', nom: '', arguments: '', definition: null });

verifier('frappe du nom', nomEnFrappe('/Comp'), 'comp');
verifier('frappe : slash seul', nomEnFrappe('/'), '');
verifier('frappe : arguments commencés', nomEnFrappe('/compact '), null);
verifier('frappe : échappement', nomEnFrappe('//c'), null);
verifier('frappe : texte', nomEnFrappe('salut'), null);

verifier('filtre : préfixe avant contenu', filtrerCommandes(CATALOGUE, 'c').map((c) => c.nom), ['compact', 'clear']);
verifier('filtre : contenu', filtrerCommandes(CATALOGUE, 'ea').map((c) => c.nom), ['clear']);
verifier('filtre : vide = tout', filtrerCommandes(CATALOGUE, '').length, 2);
verifier('filtre : rien', filtrerCommandes(CATALOGUE, 'zz').length, 0);

verifier('complétion avec arguments', completion(COMPACT), '/compact ');
verifier('complétion sans arguments', completion(CLEAR), '/clear');
verifier('complète : exact', estComplete('/clear', CLEAR), true);
verifier('complète : partiel', estComplete('/cl', CLEAR), false);

verifier('refus : /clear avec argument', refusArguments(analyserSaisie('/clear tout', CATALOGUE)) !== null, true);
verifier('refus : /compact avec argument', refusArguments(analyserSaisie('/compact x', CATALOGUE)), null);

/* ---- masquage après /clear ---- */
function message(id: string): MessageChat {
  return {
    id, conversation_id: 'c', role: 'user', contenu: id, tokens_generes: null, tokens_par_seconde: null,
    cree_le: '2026-11-11T10:00:00Z', modele_id: null, interrompu: false, parent_id: null, compaction: null,
  };
}
const FIL = ['a', 'b', 'c', 'd'].map(message);
const eff = (id: string, ancre: string): { id: string; ancre_message_id: string; cree_le: string } =>
  ({ id, ancre_message_id: ancre, cree_le: '2026-11-11T10:00:00Z' });

verifier('aucun effacement', masquerEfface(FIL, []).visibles.map((m) => m.id), ['a', 'b', 'c', 'd']);
verifier('effacement : ancre incluse', masquerEfface(FIL, [eff('e1', 'b')]).visibles.map((m) => m.id), ['c', 'd']);
verifier('effacement : compte masqué', masquerEfface(FIL, [eff('e1', 'b')]).masques, 2);
verifier('dernier effacement gagne', masquerEfface(FIL, [eff('e1', 'a'), eff('e2', 'c')]).effacement?.id, 'e2');
verifier('ancre hors chemin : précédent', masquerEfface(FIL, [eff('e1', 'a'), eff('e2', 'zz')]).effacement?.id, 'e1');
verifier('clear en fin de fil : vide', masquerEfface(FIL, [eff('e1', 'd')]).visibles.length, 0);
verifier('ancre inconnue : rien masqué', masquerEfface(FIL, [eff('e1', 'zz')]).masques, 0);

const midi = new Date(2026, 10, 11, 12, 0);
verifier('heure du jour', heureEffacement(new Date(2026, 10, 11, 9, 5).toISOString(), midi), '09:05');
verifier('heure illisible', heureEffacement('n/a', midi), '');

/* ---- progression ---- */
verifier('durée : secondes', formaterDuree(14_900), '14 s');
verifier('durée : minutes', formaterDuree(67_000), '1 min 07 s');
verifier('durée : heures', formaterDuree(3_780_000), '1 h 03 min');
verifier('durée : négative bornée', formaterDuree(-5), '0 s');
verifier('écoulé : en cours prolongé', dureeEcoulee(8400, 1000, 3000, true), 10_400);
verifier('écoulé : figé si fini', dureeEcoulee(8400, 1000, 3000, false), 8400);
verifier('jetons écrits', jetonsEcrits(6596), '6 596 jetons écrits');
verifier('jetons nuls', jetonsEcrits(0), null);
verifier('étapes depuis « resume »', etapesDepuisCle('resume').map((e) => e.etat), ['fait', 'en_cours', 'a_faire']);

const base: ActiviteMoteur = { phase: 'execution', tokens: 120, tokens_par_seconde: 0 };
const compaction = {
  etape: 'resume' as const, detail: '', resumeur: 'local' as const, tokens: null, tokens_par_seconde: null, duree_ms: 0,
};
verifier('compaction l’emporte sur « Exécute »', repereActivite({ ...base, compaction }, false).libelle,
  'Compacte le contexte');
verifier('lecture : pas de jetons ni d’outil', (({ montrerJetons, montrerOutil }) => [montrerJetons, montrerOutil])(
  repereActivite({ ...base, phase: 'lecture' }, false)), [false, false]);
verifier('lecture : jamais « silence »', repereActivite({ ...base, phase: 'lecture' }, true).mesure, 'lecture');
verifier('rédaction : jetons écrits', repereActivite({ ...base, phase: 'texte' }, false).montrerJetons, true);
verifier('rédaction silencieuse', repereActivite({ ...base, phase: 'texte' }, true).mesure, 'silence');

/* ---- temporalité ---- */
verifier('aujourd’hui', horodatageLisible(new Date(2026, 10, 11, 14, 32).toISOString(), midi), 'aujourd’hui 14:32');
verifier('hier', horodatageLisible(new Date(2026, 10, 10, 9, 10).toISOString(), midi), 'hier 09:10');
verifier('autre année', horodatageLisible(new Date(2025, 0, 3, 8, 0).toISOString(), midi).includes('2025'), true);
verifier('durée de génération', dureeGeneration(670, 10), '≈ 1 min 07 s');
verifier('durée inconnue', dureeGeneration(670, null), null);
verifier('au travail depuis', depuisDebut(new Date(midi.getTime() - 67_000).toISOString(), midi.getTime()),
  '1 min 07 s');
verifier('sans début : rien', depuisDebut(undefined, midi.getTime()), null);

if (echecs > 0) {
  throw new Error(`${echecs} test(s) en échec.`);
}
console.log('Tous les tests des commandes passent.');
