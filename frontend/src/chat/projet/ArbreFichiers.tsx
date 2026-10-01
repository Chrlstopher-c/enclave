/*
 * Arborescence repliable du projet. Les dossiers s'ouvrent au clic ; un fichier modifié depuis le
 * dernier instantané porte la couleur de son état (ajouté, modifié).
 */

import { useState, type ReactElement } from 'react';
import { cn } from '../../shared/design';
import { Chevron } from '../raisonnement/Chevron';
import type { EtatModification } from './api-projet';
import type { NoeudArbre } from './arbre';

export const COULEUR_ETAT: Record<EtatModification, string> = {
  A: 'text-ok',
  M: 'text-caution',
  D: 'text-critical',
};

interface ArbreProps {
  readonly noeuds: readonly NoeudArbre[];
  readonly etats: ReadonlyMap<string, EtatModification>;
  readonly selection: string | null;
  readonly onFichier: (chemin: string) => void;
}

function Noeud({ noeud, profondeur, ...props }: Omit<ArbreProps, 'noeuds'> & {
  readonly noeud: NoeudArbre;
  readonly profondeur: number;
}): ReactElement {
  const [ouvert, setOuvert] = useState<boolean>(profondeur === 0);
  const retrait = { paddingLeft: `${profondeur * 0.75 + 0.25}rem` };
  if (noeud.enfants === null) {
    const etat = props.etats.get(noeud.chemin);
    return (
      <button type="button" style={retrait} onClick={() => props.onFichier(noeud.chemin)}
        className={cn('block w-full truncate rounded py-0.5 pr-1 text-left font-mono text-2xs hover:bg-surface-2',
          etat === undefined ? 'text-text-2' : COULEUR_ETAT[etat],
          props.selection === noeud.chemin && 'bg-surface-2')}>
        {noeud.nom}
      </button>
    );
  }
  return (
    <div>
      <button type="button" style={retrait} onClick={() => setOuvert((o) => !o)}
        className={cn('flex w-full items-center gap-1 rounded py-0.5 text-left font-mono text-2xs text-text',
          'hover:bg-surface-2')}>
        <Chevron ouvert={ouvert} />
        <span className="truncate">{noeud.nom}/</span>
      </button>
      {ouvert && noeud.enfants.map((enfant) => (
        <Noeud key={enfant.chemin} noeud={enfant} profondeur={profondeur + 1} {...props} />
      ))}
    </div>
  );
}

export function ArbreFichiers({ noeuds, ...props }: ArbreProps): ReactElement {
  if (noeuds.length === 0) {
    return <p className="p-2 text-2xs text-text-3">Le projet est vide.</p>;
  }
  return (
    <div className="space-y-px">
      {noeuds.map((noeud) => <Noeud key={noeud.chemin} noeud={noeud} profondeur={0} {...props} />)}
    </div>
  );
}
