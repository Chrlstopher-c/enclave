/*
 * Notes sous une réponse du modèle : chaque note devient un exemple d'entraînement.
 *
 * - Réponse seule : 👍 / 👎 (exemples non appariés, méthode KTO).
 * - Tour à plusieurs variantes (rejouer) : les pouces deviennent « meilleure » / « pire », un seul de
 *   chaque par tour — des paires pour la DPO, signal plus fiable qu'un jugement dans l'absolu.
 * - Après un 👎 ou un « pire » : raisons en un clic, seulement celles qu'aucun contrôle automatique
 *   ne voit (le CTA, la longueur, les interdits et la recopie du brief sont mesurés à l'export).
 * - « Corriger » : la version réécrite devient un exemple SFT.
 * Un second clic sur un pouce actif retire la note.
 */

import { useState, type ReactElement, type ReactNode } from 'react';
import { Button, Modal, cn } from '../shared/design';
import type { Raison, Verdict } from './api';
import { IconeCorriger, IconePouceBas, IconePouceHaut } from './icones';
import { useVerdict } from './useVerdict';

const CLASSE_BOUTON =
  'inline-flex min-h-[44px] min-w-[44px] items-center justify-center rounded-xs text-text-2 ' +
  'lg:h-5 lg:w-5 lg:min-h-0 lg:min-w-0 transition-colors duration-fast ease-out ' +
  'hover:bg-surface-2 hover:text-text focus-visible:outline-none focus-visible:shadow-[0_0_0_2px_var(--ring)]';
const CLASSE_ACTIF = 'bg-surface-2 text-text';
const CLASSE_ZONE =
  'h-72 w-full resize-y rounded-sm border border-border-strong bg-surface px-2 py-1.5 ' +
  'text-sm text-text outline-none focus:shadow-[0_0_0_3px_var(--ring)]';
const CLASSE_PANNEAU =
  'absolute right-0 top-full z-20 mt-1 flex w-72 flex-wrap gap-1 rounded-sm border border-border ' +
  'bg-overlay p-1.5 shadow-1';
const CLASSE_PUCE = 'rounded-xs border border-border px-1.5 py-0.5 text-xs transition-colors duration-fast';

const LIBELLES_CLAUDE: Record<Verdict, string> = {
  positif: '👍',
  negatif: '👎',
  correction: 'corrigé',
  meilleure: 'meilleure',
  pire: 'pire',
};

const RAISONS: ReadonlyArray<readonly [Raison, string]> = [
  ['accroche_faible', 'Accroche faible'],
  ['ton', 'Ton à côté'],
  ['fait_invente', 'Fait inventé'],
  ['cliche_ia', 'Cliché / ton IA'],
  ['francais', 'Français maladroit'],
  ['generique', 'Trop générique'],
  ['hors_brief', 'Hors brief'],
  ['structure', 'Structure du canal'],
];

/** Texte livré, sans le raisonnement : c'est lui qu'on corrige. */
function texteFinal(contenu: string): string {
  const fin = contenu.lastIndexOf('</think>');
  return (fin >= 0 ? contenu.slice(fin + '</think>'.length) : contenu).trim();
}

interface BoutonProps {
  libelle: string;
  actif: boolean;
  onClic: () => void;
  children: ReactNode;
}

function BoutonRetour({ libelle, actif, onClic, children }: BoutonProps): ReactElement {
  return (
    <button type="button" className={cn(CLASSE_BOUTON, actif && CLASSE_ACTIF)} onClick={onClic}
      aria-label={libelle} aria-pressed={actif} title={libelle}>
      {children}
    </button>
  );
}

interface PanneauProps {
  choisies: Raison[];
  onBasculer: (raison: Raison) => void;
  onFermer: () => void;
}

function PanneauRaisons({ choisies, onBasculer, onFermer }: PanneauProps): ReactElement {
  return (
    <div className={CLASSE_PANNEAU} role="group" aria-label="Pourquoi ?">
      {RAISONS.map(([code, libelle]) => (
        <button key={code} type="button" aria-pressed={choisies.includes(code)} onClick={() => onBasculer(code)}
          className={cn(CLASSE_PUCE, choisies.includes(code) ? 'bg-surface-2 text-text' : 'text-text-2')}>
          {libelle}
        </button>
      ))}
      <button type="button" onClick={onFermer} className={cn(CLASSE_PUCE, 'ml-auto text-text-2')}>OK</button>
    </div>
  );
}

interface FenetreProps {
  initial: string;
  onFermer: () => void;
  onValider: (texte: string) => void;
}

function FenetreCorrection({ initial, onFermer, onValider }: FenetreProps): ReactElement {
  const [texte, setTexte] = useState(initial);
  const pied = (
    <div className="flex justify-end gap-2">
      <Button variant="ghost" size="sm" onClick={onFermer}>Annuler</Button>
      <Button variant="primary" size="sm" disabled={!texte.trim()} onClick={() => onValider(texte.trim())}>
        Enregistrer la correction
      </Button>
    </div>
  );
  return (
    <Modal open onClose={onFermer} title="Corriger la réponse" size="lg" footer={pied}>
      <p className="mb-2 text-sm text-text-2">Écris la version que tu aurais voulue : elle servira d'exemple.</p>
      <textarea autoFocus value={texte} onChange={(e) => setTexte(e.target.value)} className={CLASSE_ZONE}
        aria-label="Texte corrigé" />
    </Modal>
  );
}

export interface BoutonsRetourProps {
  conversationId: string;
  messageId: string;
  contenu: string;
  /** Vrai quand le tour a plusieurs variantes : on désigne alors la meilleure et la pire. */
  comparaison: boolean;
}

export function BoutonsRetour({ conversationId, messageId, contenu, comparaison }: BoutonsRetourProps): ReactElement {
  const { verdict, verdictClaude, raisons, erreur, noter } = useVerdict(conversationId, messageId);
  const [correction, setCorrection] = useState(false);
  const [panneau, setPanneau] = useState(false);
  const [haut, bas]: [Verdict, Verdict] = comparaison ? ['meilleure', 'pire'] : ['positif', 'negatif'];
  const noterBas = (): void => {
    setPanneau(verdict !== bas);
    void noter(bas);
  };
  const basculer = (raison: Raison): void => {
    const suivantes = raisons.includes(raison) ? raisons.filter((r) => r !== raison) : [...raisons, raison];
    void noter(bas, { raisons: suivantes });
  };
  return (
    <span className="relative inline-flex items-center gap-0.5" title={erreur ?? undefined}>
      <BoutonRetour libelle={comparaison ? 'Meilleure variante' : 'Bonne réponse'} actif={verdict === haut}
        onClic={() => { setPanneau(false); void noter(haut); }}>
        <IconePouceHaut />
      </BoutonRetour>
      <BoutonRetour libelle={comparaison ? 'Pire variante' : 'Mauvaise réponse'} actif={verdict === bas}
        onClic={noterBas}>
        <IconePouceBas />
      </BoutonRetour>
      <BoutonRetour libelle="Corriger cette réponse" actif={verdict === 'correction'} onClic={() => setCorrection(true)}>
        <IconeCorriger />
      </BoutonRetour>
      {verdictClaude !== null && (
        <span className="ml-1 rounded-xs border border-border px-1 text-xs text-text-2" title="Note posée par Claude (MCP)">
          Claude : {LIBELLES_CLAUDE[verdictClaude]}
        </span>
      )}
      {panneau && verdict === bas && (
        <PanneauRaisons choisies={raisons} onBasculer={basculer} onFermer={() => setPanneau(false)} />
      )}
      {correction && (
        <FenetreCorrection initial={texteFinal(contenu)} onFermer={() => setCorrection(false)}
          onValider={(texte) => { setCorrection(false); void noter('correction', { correction: texte }); }} />
      )}
    </span>
  );
}
