/*
 * Sélection des outils mis à disposition du modèle pour CETTE conversation.
 *
 * Deux vérités gouvernent l'écran, parce qu'un utilisateur qui les ignore fera de mauvais choix :
 *   - chaque outil déclaré occupe la fenêtre de contexte à CHAQUE tour, qu'il serve ou non — le
 *     coût de la sélection est donc affiché comme partout ailleurs : en tokens, en mono ;
 *   - certains outils vont par paires (`recuperer_page` sans `recherche_web`…). L'écran le
 *     SUGGÈRE en ambre, il n'interdit rien : un choix défendable ne se bloque pas.
 *
 * Composant pur : la sélection et le catalogue arrivent en props, la persistance vit dans
 * `useSelectionOutils`. C'est ce qui permet à la page de démonstration de le capturer sans backend.
 */

import type { ReactElement } from 'react';
import { cn } from '../../shared/design';
import {
  LIBELLE_GROUPE,
  PAIRES_SUGGEREES,
  type GroupeOutils,
  type OutilDisponible,
} from './outils-catalogue';

const NOMBRE = new Intl.NumberFormat('fr-FR');

/* L'ordre d'affichage des groupes suit l'ordre du registre : web, fichiers, exécution, présentation. */
const ORDRE_GROUPES: readonly GroupeOutils[] = ['organisation', 'web', 'fichiers', 'execution', 'mcp', 'presentation'];

function Coche({ cochee }: { readonly cochee: boolean }): ReactElement {
  return (
    <span
      aria-hidden="true"
      className={cn(
        'flex h-4 w-4 shrink-0 items-center justify-center rounded-xs border transition-colors duration-fast',
        cochee ? 'border-accent bg-accent text-on-accent' : 'border-border-strong bg-transparent',
      )}
    >
      {cochee && (
        <svg viewBox="0 0 12 12" className="h-3 w-3" fill="none">
          <path d="m2.5 6.5 2.5 2.5 4.5-5" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
        </svg>
      )}
    </span>
  );
}

function CoutTokens({ tokens }: { readonly tokens: number | null }): ReactElement {
  return (
    <span className="shrink-0 font-mono text-2xs tabular-nums text-text-3">
      {tokens === null ? '—' : `${NOMBRE.format(tokens)} tokens`}
    </span>
  );
}

interface LigneOutilProps {
  outil: OutilDisponible;
  actif: boolean;
  onBasculer: () => void;
}

function LigneOutil({ outil, actif, onBasculer }: LigneOutilProps): ReactElement {
  return (
    <li>
      <button
        type="button"
        role="checkbox"
        aria-checked={actif}
        onClick={onBasculer}
        className={cn(
          'flex w-full min-h-[44px] items-center gap-2.5 rounded-sm px-2 py-1.5 text-left',
          'transition-colors duration-fast hover:bg-surface-2 lg:min-h-0',
          'focus-visible:outline-none focus-visible:shadow-[0_0_0_3px_var(--ring)]',
        )}
      >
        <Coche cochee={actif} />
        <span className="min-w-0 flex-1">
          <span className={cn('block truncate font-mono text-xs', actif ? 'text-text' : 'text-text-3')}>
            {outil.nom}
          </span>
          <span className="block truncate text-2xs text-text-3">{outil.description}</span>
        </span>
        <CoutTokens tokens={outil.tokens_definition} />
      </button>
    </li>
  );
}

interface GroupeSectionProps {
  groupe: GroupeOutils;
  outils: readonly OutilDisponible[];
  actifs: ReadonlySet<string>;
  onBasculer: (nom: string) => void;
  onBasculerGroupe: (noms: readonly string[], activer: boolean) => void;
}

function EnTeteGroupe({
  groupe,
  combien,
  total,
  toutActif,
  onBasculer,
}: {
  groupe: GroupeOutils;
  combien: number;
  total: number;
  toutActif: boolean;
  onBasculer: () => void;
}): ReactElement {
  return (
    <button
      type="button"
      onClick={onBasculer}
      // Le geste de groupe complète, il n'alterne pas : un groupe partiel s'active en entier
      // d'abord — couper d'un clic ce qu'on vient de doser à la main serait une perte.
      className={cn(
        'mb-0.5 flex w-full items-baseline gap-2 rounded-sm px-2 py-1 text-left',
        'text-2xs font-medium uppercase tracking-wide text-text-3 transition-colors duration-fast',
        'hover:text-text-2 focus-visible:outline-none focus-visible:shadow-[0_0_0_3px_var(--ring)]',
      )}
    >
      <span>{LIBELLE_GROUPE[groupe]}</span>
      <span className="font-mono tabular-nums normal-case">
        {combien}/{total}
      </span>
      <span className="ml-auto normal-case">{toutActif ? 'tout couper' : 'tout activer'}</span>
    </button>
  );
}

function GroupeSection({ groupe, outils, actifs, onBasculer, onBasculerGroupe }: GroupeSectionProps): ReactElement {
  const noms = outils.map((outil) => outil.nom);
  const combien = noms.filter((nom) => actifs.has(nom)).length;
  const toutActif = combien === noms.length;
  return (
    <section>
      <EnTeteGroupe
        groupe={groupe}
        combien={combien}
        total={noms.length}
        toutActif={toutActif}
        onBasculer={() => onBasculerGroupe(noms, !toutActif)}
      />
      <ul className="space-y-0.5">
        {outils.map((outil) => (
          <LigneOutil
            key={outil.nom}
            outil={outil}
            actif={actifs.has(outil.nom)}
            onBasculer={() => onBasculer(outil.nom)}
          />
        ))}
      </ul>
    </section>
  );
}

/* Une suggestion par paire cassée — le membre coché sans son complément. Jamais bloquant. */
function NotesPaires({ actifs }: { readonly actifs: ReadonlySet<string> }): ReactElement | null {
  const cassees = PAIRES_SUGGEREES.filter((paire) => actifs.has(paire.actif) && !actifs.has(paire.requis));
  if (cassees.length === 0) {
    return null;
  }
  return (
    <ul className="space-y-1">
      {cassees.map((paire) => (
        <li key={`${paire.actif}-${paire.requis}`} className="text-2xs leading-relaxed text-caution">
          <span className="font-mono">{paire.actif}</span> sans <span className="font-mono">{paire.requis}</span> :{' '}
          {paire.raison}.
        </li>
      ))}
    </ul>
  );
}

function PiedTotal({
  catalogue,
  actifs,
}: {
  readonly catalogue: readonly OutilDisponible[];
  readonly actifs: ReadonlySet<string>;
}): ReactElement {
  const retenus = catalogue.filter((outil) => actifs.has(outil.nom));
  const mesures = retenus.filter((outil) => outil.tokens_definition !== null);
  const total = mesures.reduce((somme, outil) => somme + (outil.tokens_definition ?? 0), 0);
  return (
    <p className="border-t border-border pt-2 font-mono text-2xs tabular-nums text-text-2">
      {retenus.length} outil{retenus.length > 1 ? 's' : ''} actif{retenus.length > 1 ? 's' : ''}
      {mesures.length === retenus.length && retenus.length > 0
        ? ` · ${NOMBRE.format(total)} tokens de définitions à chaque tour`
        : ' · coût des définitions non mesuré'}
    </p>
  );
}

export interface PanneauOutilsProps {
  readonly catalogue: readonly OutilDisponible[];
  readonly actifs: ReadonlySet<string>;
  readonly persistee: boolean;
  readonly onBasculer: (nom: string) => void;
  readonly onBasculerGroupe: (noms: readonly string[], activer: boolean) => void;
}

export function PanneauOutils(props: PanneauOutilsProps): ReactElement {
  const { catalogue, actifs, persistee } = props;
  return (
    <div className="space-y-3">
      <p className="text-2xs leading-relaxed text-text-3">
        Chaque outil déclaré occupe la fenêtre de contexte à chaque tour, qu’il serve ou non. Couper
        ce qui ne sert pas rend des tokens à la conversation.
      </p>
      {!persistee && (
        <p className="text-2xs leading-relaxed text-caution">
          Sélection non persistée : le backend ne sert pas encore la route des outils. Les choix
          faits ici ne survivront pas à la conversation.
        </p>
      )}
      {ORDRE_GROUPES.map((groupe) => (
        <GroupeSection
          key={groupe}
          groupe={groupe}
          outils={catalogue.filter((outil) => outil.groupe === groupe)}
          actifs={actifs}
          onBasculer={props.onBasculer}
          onBasculerGroupe={props.onBasculerGroupe}
        />
      ))}
      <NotesPaires actifs={actifs} />
      <PiedTotal catalogue={catalogue} actifs={actifs} />
    </div>
  );
}
