/*
 * Palette des commandes, ouverte au-dessus de la saisie dès qu'un « / » commence le message.
 *
 * Une surface flottante (`overlay` + ombre 2) et non un menu système : elle doit rester lisible
 * au-dessus du fil, sans voile. La rangée choisie se distingue par la surface et un filet
 * pervenche — l'accent dit « action possible », c'est exactement ce que la rangée est.
 * `onMouseDown` empêche la perte du focus : la saisie reste active, au doigt comme à la souris.
 */

import { motion } from 'framer-motion';
import type { ReactElement } from 'react';
import { cn, fadeUp } from '../../shared/design';
import type { DefinitionCommande } from './contrats';
import type { EtatPalette } from './useSaisieCommande';

function argumentsUsage(definition: DefinitionCommande): string {
  return definition.usage.replace(new RegExp(`^/${definition.nom}\\s*`), '');
}

function Rangee({ definition, choisie, onChoisir, onSurvol }: {
  definition: DefinitionCommande;
  choisie: boolean;
  onChoisir: () => void;
  onSurvol: () => void;
}): ReactElement {
  return (
    <li role="option" aria-selected={choisie}>
      <button
        type="button"
        tabIndex={-1}
        onMouseDown={(evenement) => evenement.preventDefault()}
        onClick={onChoisir}
        onMouseEnter={onSurvol}
        className={cn(
          'relative flex w-full min-w-0 flex-col gap-0.5 px-3 py-2 text-left lg:flex-row lg:items-baseline lg:gap-3',
          'min-h-[44px] transition-colors duration-fast lg:min-h-0',
          choisie ? 'bg-surface-2' : 'hover:bg-surface',
        )}
      >
        {choisie && <span className="absolute inset-y-1.5 left-0 w-0.5 rounded-full bg-accent" aria-hidden="true" />}
        <span className="shrink-0 font-mono text-xs">
          <span className="text-text">/{definition.nom}</span>
          {argumentsUsage(definition) !== '' && <span className="text-text-3"> {argumentsUsage(definition)}</span>}
        </span>
        <span className="min-w-0 text-2xs text-text-2 lg:truncate">{definition.description}</span>
      </button>
    </li>
  );
}

function Touche({ children }: { children: string }): ReactElement {
  return <kbd className="rounded-xs border border-border px-1 font-mono text-[inherit] text-text-2">{children}</kbd>;
}

function Etat({ palette }: { palette: EtatPalette }): ReactElement | null {
  if (palette.etat === 'chargement') {
    return <p className="px-3 py-2 text-2xs text-text-3">Lecture des commandes…</p>;
  }
  if (palette.etat === 'erreur') {
    return (
      <p className="flex items-center justify-between gap-2 px-3 py-2 text-2xs text-caution">
        Liste des commandes indisponible.
        <button
          type="button"
          onMouseDown={(evenement) => evenement.preventDefault()}
          onClick={palette.recharger}
          className="text-accent hover:underline"
        >
          Réessayer
        </button>
      </p>
    );
  }
  return null;
}

export interface PaletteCommandesProps {
  palette: EtatPalette;
  onChoisir: (definition: DefinitionCommande) => void;
  onSurvol: (index: number) => void;
}

export function PaletteCommandes({ palette, onChoisir, onSurvol }: PaletteCommandesProps): ReactElement {
  return (
    <motion.div
      variants={fadeUp}
      initial="hidden"
      animate="visible"
      exit="exit"
      className={cn(
        'absolute inset-x-0 bottom-full z-20 mb-2 overflow-hidden rounded-md border border-border',
        'bg-overlay shadow-2',
      )}
    >
      <p className="px-3 pb-1 pt-2 text-2xs font-medium text-text-3">Commandes</p>
      <Etat palette={palette} />
      <ul role="listbox" aria-label="Commandes" className="max-h-64 overflow-y-auto pb-1">
        {palette.choix.map((definition, index) => (
          <Rangee
            key={definition.nom}
            definition={definition}
            choisie={index === palette.index}
            onChoisir={() => onChoisir(definition)}
            onSurvol={() => onSurvol(index)}
          />
        ))}
      </ul>
      <p className="hidden gap-3 border-t border-border px-3 py-1.5 text-2xs text-text-3 lg:flex">
        <span><Touche>↑↓</Touche> choisir</span>
        <span><Touche>Tab</Touche> compléter</span>
        <span><Touche>Entrée</Touche> exécuter</span>
        <span><Touche>Échap</Touche> fermer</span>
      </p>
    </motion.div>
  );
}
