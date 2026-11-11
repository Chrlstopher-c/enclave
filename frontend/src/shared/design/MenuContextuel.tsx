/*
 * Menu contextuel — clic droit, et clavier.
 *
 * Générique et sans dépendance à un domaine : il reçoit des entrées et les rend. C'est ce qui
 * permet de l'utiliser sur une conversation, un message ou un modèle sans le réécrire.
 *
 * Trois exigences non négociables, et chacune corrige un défaut courant de ce type de composant :
 *
 * - **Le clavier ouvre aussi le menu.** La touche Menu et Shift+F10 sont les équivalents clavier du
 *   clic droit ; s'en remettre à la souris seule rendrait ces actions inatteignables.
 * - **Le menu ne sort jamais de l'écran.** Sa position est corrigée après mesure, pas devinée : un
 *   clic droit en bas de la liste ouvrirait sinon un menu à moitié invisible.
 * - **Une action destructrice est signalée**, et ne referme le menu qu'après avoir été déclenchée.
 *
 * Le menu natif du navigateur reste accessible partout où aucun menu n'est défini : on ne supprime
 * pas le clic droit du système, on l'enrichit là où l'application a quelque chose à proposer.
 *
 * - **Le doigt ouvre aussi le menu.** Sous le seuil, aucun des chemins ci-dessus n'existe : ni clic
 *   droit, ni touche Menu. L'appelant reçoit `ouvrirDepuis` et place un `BoutonActions` permanent.
 *   L'appui long n'est PAS retenu comme chemin : rien ne le signale, et il entre en conflit avec la
 *   sélection de texte et le menu natif du système.
 */

import { AnimatePresence, motion, useReducedMotion } from 'framer-motion';
import { useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react';
import type { ReactElement, ReactNode } from 'react';

import { cn } from './cn';
import { TONE_VAR } from './tones';
import { useEstGrandEcran } from './useEstGrandEcran';

/** Marge conservée avec le bord de la fenêtre lors du recadrage. */
const MARGE_ECRAN = 8;

export interface EntreeMenu {
  readonly libelle: string;
  readonly onChoisir: () => void;
  /** Rend l'entrée inerte, sans la cacher : une action absente est plus déroutante qu'une action grisée. */
  readonly desactivee?: boolean;
  /** Colore l'entrée en critique et l'isole des autres. */
  readonly destructive?: boolean;
  readonly raccourci?: string;
}

interface Position {
  readonly x: number;
  readonly y: number;
}

interface PanneauProps {
  readonly position: Position;
  readonly entrees: readonly EntreeMenu[];
  readonly onFermer: () => void;
  /** Sous le seuil : plein écran ancré en bas, à portée du pouce, plutôt qu'au point de contact. */
  readonly ancrageBas: boolean;
  /** Élément porteur du menu : seul un défilement qui le déplace referme le menu. */
  readonly ancre: React.RefObject<HTMLDivElement | null>;
}

function Panneau({ position, entrees, onFermer, ancrageBas, ancre }: PanneauProps): ReactElement {
  const panneau = useRef<HTMLDivElement>(null);
  const [corrigee, setCorrigee] = useState<Position>(position);
  const reduit = useReducedMotion() === true;

  // Recadrage APRÈS mesure : la taille du menu dépend de ses entrées, donc elle n'est connue
  // qu'une fois rendu. `useLayoutEffect` évite l'image intermédiaire hors écran.
  useLayoutEffect(() => {
    const boite = panneau.current?.getBoundingClientRect();
    if (boite === undefined || ancrageBas) {
      return;
    }
    const debordeX = position.x + boite.width - window.innerWidth + MARGE_ECRAN;
    const debordeY = position.y + boite.height - window.innerHeight + MARGE_ECRAN;
    setCorrigee({
      x: debordeX > 0 ? Math.max(MARGE_ECRAN, position.x - boite.width) : position.x,
      y: debordeY > 0 ? Math.max(MARGE_ECRAN, position.y - debordeY) : position.y,
    });
  }, [position, ancrageBas]);

  useEffect(() => {
    const surTouche = (evenement: KeyboardEvent): void => {
      if (evenement.key === 'Escape') onFermer();
    };
    // `capture` : le menu se ferme avant que le clic n'atteigne l'élément visé, sinon un clic
    // ailleurs déclencherait l'action de cet autre élément en plus de fermer le menu.
    // Un appui DANS le menu n'est pas un clic extérieur : le fermer ici démontait l'entrée avant le
    // `click`, qui ne partait donc jamais (la sortie animée laissait le nœud quelques dizaines de ms).
    const surPointeur = (evenement: PointerEvent): void => {
      if (evenement.target instanceof Node && panneau.current?.contains(evenement.target) === true) return;
      onFermer();
    };
    // Seul le défilement d'un conteneur de l'élément porteur déplace ce qu'on visait. Le fil qui
    // défile tout seul pendant une génération ne doit pas refermer un menu ouvert sur la liste.
    const surDefilement = (evenement: Event): void => {
      const cible = evenement.target;
      if (cible instanceof Node && ancre.current !== null && !cible.contains(ancre.current)) return;
      onFermer();
    };
    window.addEventListener('keydown', surTouche);
    window.addEventListener('pointerdown', surPointeur, true);
    window.addEventListener('scroll', surDefilement, true);
    return () => {
      window.removeEventListener('keydown', surTouche);
      window.removeEventListener('pointerdown', surPointeur, true);
      window.removeEventListener('scroll', surDefilement, true);
    };
  }, [onFermer, ancre]);

  return (
    <motion.div
      ref={panneau}
      role="menu"
      initial={{ opacity: 0, scale: ancrageBas ? 1 : 0.97, y: ancrageBas ? 12 : 0 }}
      animate={{ opacity: 1, scale: 1, y: 0 }}
      exit={{ opacity: 0, scale: ancrageBas ? 1 : 0.97, y: ancrageBas ? 12 : 0 }}
      transition={{ duration: reduit ? 0 : 0.09, ease: 'easeOut' }}
      style={ancrageBas ? undefined : { left: corrigee.x, top: corrigee.y }}
      className={cn(
        'fixed z-50 rounded-md border border-border bg-surface-2 p-1 shadow-3',
        ancrageBas
          ? 'eh-marge-sure-bas inset-x-2 bottom-2 max-h-[70dvh] overflow-y-auto'
          : 'min-w-[11rem] origin-top-left',
      )}
      onContextMenu={(evenement) => evenement.preventDefault()}
    >
      {entrees.map((entree, index) => (
        <Entree key={entree.libelle} entree={entree} premiere={index === 0} onFermer={onFermer} />
      ))}
    </motion.div>
  );
}

interface EntreeProps {
  readonly entree: EntreeMenu;
  readonly premiere: boolean;
  readonly onFermer: () => void;
}

function Entree({ entree, premiere, onFermer }: EntreeProps): ReactElement {
  return (
    <button
      type="button"
      role="menuitem"
      disabled={entree.desactivee}
      onClick={() => {
        entree.onChoisir();
        onFermer();
      }}
      className={cn(
        'flex w-full items-center justify-between gap-6 rounded-sm px-2 text-left text-xs',
        // Cible tactile au doigt ; la densité de bureau revient au-dessus du seuil.
        'min-h-[44px] py-2 lg:min-h-0 lg:py-1.5',
        'transition-colors duration-fast ease-out',
        'focus-visible:outline-none focus-visible:shadow-[inset_0_0_0_2px_var(--ring)]',
        // `surface-3` n'existe pas dans le préset : le survol était invisible. `surface-2` est
        // la seule surface de contraste définie.
        entree.desactivee
          ? 'cursor-not-allowed text-text-3'
          : 'text-text-2 hover:bg-surface-2 hover:text-text',
        entree.destructive && !entree.desactivee && 'hover:bg-critical-soft',
        // Les actions destructrices sont séparées du reste : un clic mal placé ne doit pas
        // tomber sur « supprimer » parce qu'il est collé à « renommer ».
        entree.destructive && !premiere && 'mt-1 border-t border-border pt-2',
      )}
      style={entree.destructive && !entree.desactivee ? { color: TONE_VAR.critical } : undefined}
    >
      <span>{entree.libelle}</span>
      {entree.raccourci !== undefined && <span className="font-mono text-2xs text-text-3">{entree.raccourci}</span>}
    </button>
  );
}

/** Ce que reçoit un enfant-fonction pour poser son propre déclencheur tactile. */
export interface ApiMenuContextuel {
  readonly ouvert: boolean;
  /** Ancre le menu sur la boîte d'un élément — typiquement le `BoutonActions` cliqué. */
  readonly ouvrirDepuis: (element: HTMLElement | null) => void;
}

export interface MenuContextuelProps {
  readonly entrees: readonly EntreeMenu[];
  /** Enfant simple, ou fonction si l'appelant doit placer lui-même un `BoutonActions`. */
  readonly children: ReactNode | ((api: ApiMenuContextuel) => ReactNode);
  readonly className?: string;
}

/**
 * Enveloppe un élément et lui attache un menu au clic droit, à la touche Menu, à Shift+F10 —
 * et, via `ouvrirDepuis`, à un bouton visible pour le doigt.
 */
interface OuvertureMenu {
  readonly position: Position | null;
  readonly setPosition: (position: Position | null) => void;
  readonly fermer: () => void;
  readonly ouvrirDepuis: (element: HTMLElement | null) => void;
}

function useOuvertureMenu(): OuvertureMenu {
  const [position, setPosition] = useState<Position | null>(null);
  const instantFermeture = useRef<number>(0);
  const fermer = useCallback((): void => {
    instantFermeture.current = Date.now();
    setPosition(null);
  }, []);
  const ouvrirDepuis = useCallback((element: HTMLElement | null): void => {
    // Le menu ouvert se ferme au `pointerdown`, qui précède le `click` du déclencheur : sans ce
    // garde, appuyer une seconde fois sur le bouton refermerait puis rouvrirait aussitôt le menu.
    if (element === null || Date.now() - instantFermeture.current < 300) {
      return;
    }
    const boite = element.getBoundingClientRect();
    setPosition({ x: boite.left, y: boite.bottom + 4 });
  }, []);
  return { position, setPosition, fermer, ouvrirDepuis };
}

export function MenuContextuel({ entrees, children, className }: MenuContextuelProps): ReactElement {
  const { position, setPosition, fermer, ouvrirDepuis } = useOuvertureMenu();
  const estGrandEcran = useEstGrandEcran();
  const ancre = useRef<HTMLDivElement>(null);

  const surClavier = useCallback((evenement: React.KeyboardEvent<HTMLDivElement>): void => {
    if (evenement.key !== 'ContextMenu' && !(evenement.shiftKey && evenement.key === 'F10')) {
      return;
    }
    evenement.preventDefault();
    // Sans souris, le menu s'ancre sur l'élément lui-même plutôt que sur un curseur inexistant.
    const boite = evenement.currentTarget.getBoundingClientRect();
    setPosition({ x: boite.left + 8, y: boite.bottom - 4 });
  }, [setPosition]);

  return (
    <div
      ref={ancre}
      className={className}
      onContextMenu={(evenement) => {
        evenement.preventDefault();
        setPosition({ x: evenement.clientX, y: evenement.clientY });
      }}
      onKeyDown={surClavier}
    >
      {typeof children === 'function' ? children({ ouvert: position !== null, ouvrirDepuis }) : children}
      <AnimatePresence>
        {position !== null && (
          <Panneau position={position} entrees={entrees} onFermer={fermer} ancrageBas={!estGrandEcran} ancre={ancre} />
        )}
      </AnimatePresence>
    </div>
  );
}
