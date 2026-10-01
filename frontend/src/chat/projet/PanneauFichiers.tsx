/*
 * Panneau « Fichiers du projet » : voir ce que l'agent construit pendant qu'il le construit.
 *
 * Deux onglets — l'arborescence complète, et les fichiers changés depuis le dernier instantané
 * (pris avant chaque tour de l'agent, donc : ce que son tour en cours ou son dernier tour a fait).
 * Le bas du panneau montre le fichier choisi, ou son diff.
 */

import { useMemo, useState, type ReactElement } from 'react';
import { Button, cn } from '../../shared/design';
import type { Modification, ModificationsProjet } from './api-projet';
import { construireArbre } from './arbre';
import { ArbreFichiers, COULEUR_ETAT } from './ArbreFichiers';
import { useFichiersProjet, type EtatFichiersProjet } from './useFichiersProjet';
import { VueFichier } from './VueFichier';

type Onglet = 'arbre' | 'modifications';

interface PanneauFichiersProps {
  readonly projet: string;
  readonly onFermer: () => void;
}

function heure(date: number): string {
  return new Date(date * 1000).toLocaleTimeString('fr-FR', { hour: '2-digit', minute: '2-digit' });
}

function ListeModifications({ modifications, selection, onDiff }: {
  readonly modifications: ModificationsProjet | null;
  readonly selection: string | null;
  readonly onDiff: (chemin: string) => void;
}): ReactElement {
  if (modifications === null) {
    return <p className="p-2 text-2xs text-text-3">Chargement…</p>;
  }
  if (modifications.reference === null) {
    return (
      <p className="p-2 text-2xs text-text-3">
        Pas encore d’instantané : il est pris avant le premier tour de l’agent.
      </p>
    );
  }
  return (
    <div className="space-y-px">
      <p className="px-2 pb-1 text-2xs text-text-3">Depuis l’instantané de {heure(modifications.reference.date)}</p>
      {modifications.fichiers.length === 0 && <p className="p-2 text-2xs text-text-3">Aucun changement.</p>}
      {modifications.fichiers.map((m: Modification) => (
        <button key={m.chemin} type="button" onClick={() => onDiff(m.chemin)}
          className={cn('flex w-full items-center gap-2 rounded px-2 py-0.5 text-left font-mono text-2xs',
            'hover:bg-surface-2', selection === m.chemin && 'bg-surface-2')}>
          <span className={cn('w-3 shrink-0 font-semibold', COULEUR_ETAT[m.etat])}>{m.etat}</span>
          <span className="min-w-0 flex-1 truncate text-text-2">{m.chemin}</span>
          {m.ajouts !== null && <span className="text-ok">+{m.ajouts}</span>}
          {m.suppressions !== null && <span className="text-critical">−{m.suppressions}</span>}
        </button>
      ))}
    </div>
  );
}

function BoutonOnglet({ actif, onClick, children }: {
  readonly actif: boolean;
  readonly onClick: () => void;
  readonly children: string;
}): ReactElement {
  return (
    <Button size="sm" variant={actif ? 'secondary' : 'ghost'} onClick={onClick}>
      {children}
    </Button>
  );
}

function EntetePanneau({ projet, onglet, nombre, onOnglet, onFermer }: {
  readonly projet: string;
  readonly onglet: Onglet;
  readonly nombre: number;
  readonly onOnglet: (onglet: Onglet) => void;
  readonly onFermer: () => void;
}): ReactElement {
  return (
    <div className="flex items-center gap-1 border-b border-border px-2 py-2">
      <BoutonOnglet actif={onglet === 'arbre'} onClick={() => onOnglet('arbre')}>Fichiers</BoutonOnglet>
      <BoutonOnglet actif={onglet === 'modifications'} onClick={() => onOnglet('modifications')}>
        {nombre > 0 ? `Modifications (${nombre})` : 'Modifications'}
      </BoutonOnglet>
      <span className="min-w-0 flex-1 truncate text-right font-mono text-2xs text-text-3">{projet}</span>
      <Button size="sm" variant="ghost" className="hidden lg:inline-flex" aria-label="Fermer" onClick={onFermer}>
        ✕
      </Button>
    </div>
  );
}

function ZoneLecture({ etat }: { readonly etat: EtatFichiersProjet }): ReactElement {
  if (etat.selection === null) {
    return (
      <p className="p-2 text-2xs text-text-3">Choisis un fichier pour le lire, ou une modification pour son diff.</p>
    );
  }
  return (
    <>
      <p className="sticky top-0 truncate border-b border-border bg-bg px-2 py-1 font-mono text-2xs text-text">
        {etat.selection.chemin}{etat.selection.mode === 'diff' ? ' — diff' : ''}
      </p>
      <VueFichier vue={etat.vue} />
    </>
  );
}

function ZoneListe({ etat, onglet }: { readonly etat: EtatFichiersProjet; readonly onglet: Onglet }): ReactElement {
  const noeuds = useMemo(() => construireArbre(etat.arbre?.fichiers ?? []), [etat.arbre]);
  const etats = useMemo(
    () => new Map((etat.modifications?.fichiers ?? []).map((m) => [m.chemin, m.etat] as const)),
    [etat.modifications],
  );
  const choisi = etat.selection?.chemin ?? null;
  return (
    <div className="max-h-[45%] min-h-[6rem] overflow-y-auto border-b border-border p-1">
      {onglet === 'arbre' ? (
        <ArbreFichiers noeuds={noeuds} etats={etats} selection={choisi}
          onFichier={(chemin) => etat.selectionner({ chemin, mode: 'fichier' })} />
      ) : (
        <ListeModifications modifications={etat.modifications} selection={choisi}
          onDiff={(chemin) => etat.selectionner({ chemin, mode: 'diff' })} />
      )}
      {etat.arbre?.tronque === true && <p className="p-2 text-2xs text-caution">Liste tronquée.</p>}
    </div>
  );
}

export function PanneauFichiers({ projet, onFermer }: PanneauFichiersProps): ReactElement {
  const etat = useFichiersProjet(projet, true);
  const [onglet, setOnglet] = useState<Onglet>('arbre');
  return (
    <aside className={cn('flex h-full w-full min-w-0 flex-col bg-bg',
      'lg:w-[28rem] lg:shrink-0 lg:border-l lg:border-border')}>
      <EntetePanneau projet={projet} onglet={onglet} nombre={etat.modifications?.fichiers.length ?? 0}
        onOnglet={setOnglet} onFermer={onFermer} />
      {etat.erreur !== null && <p className="px-2 py-1 text-2xs text-critical">{etat.erreur}</p>}
      <ZoneListe etat={etat} onglet={onglet} />
      <div className="min-h-0 flex-1 overflow-auto">
        <ZoneLecture etat={etat} />
      </div>
    </aside>
  );
}
