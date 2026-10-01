/*
 * Lecture d'un fichier du projet, ou de son diff depuis le dernier instantané (lignes colorées).
 */

import type { ReactElement } from 'react';
import { cn } from '../../shared/design';
import type { VueSelection } from './useFichiersProjet';

function couleurLigneDiff(ligne: string): string {
  if (ligne.startsWith('+++') || ligne.startsWith('---') || ligne.startsWith('diff ') || ligne.startsWith('index ')) {
    return 'text-text-3';
  }
  if (ligne.startsWith('@@')) {
    return 'text-accent';
  }
  if (ligne.startsWith('+')) {
    return 'bg-ok-soft text-ok';
  }
  return ligne.startsWith('-') ? 'bg-critical-soft text-critical' : 'text-text-2';
}

function Diff({ texte }: { readonly texte: string }): ReactElement {
  if (texte.trim() === '') {
    return <p className="p-2 text-2xs text-text-3">Aucun changement depuis le dernier instantané.</p>;
  }
  return (
    <pre className="min-w-max font-mono text-2xs leading-5">
      {texte.split('\n').map((ligne, rang) => (
        <div key={rang} className={cn('px-2', couleurLigneDiff(ligne))}>{ligne || ' '}</div>
      ))}
    </pre>
  );
}

function Contenu({ texte }: { readonly texte: string }): ReactElement {
  const lignes = texte.split('\n');
  return (
    <pre className="min-w-max font-mono text-2xs leading-5 text-text-2">
      {lignes.map((ligne, rang) => (
        <div key={rang} className="flex">
          <span className="w-10 shrink-0 select-none pr-2 text-right text-text-3">{rang + 1}</span>
          <span>{ligne || ' '}</span>
        </div>
      ))}
    </pre>
  );
}

export function VueFichier({ vue }: { readonly vue: VueSelection | null }): ReactElement {
  if (vue === null) {
    return <p className="p-2 text-2xs text-text-3">Chargement…</p>;
  }
  if (vue.mode === 'diff') {
    return (
      <>
        <Diff texte={vue.diff.diff} />
        {vue.diff.tronque && <p className="p-2 text-2xs text-caution">Diff tronqué.</p>}
      </>
    );
  }
  const { fichier } = vue;
  if (fichier.binaire || fichier.contenu === null) {
    return <p className="p-2 text-2xs text-text-3">Fichier binaire ({fichier.taille} octets).</p>;
  }
  return (
    <>
      <Contenu texte={fichier.contenu} />
      {fichier.tronque && <p className="p-2 text-2xs text-caution">Affichage tronqué ({fichier.taille} octets).</p>}
    </>
  );
}
