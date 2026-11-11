import { Component, useCallback, useEffect, useState } from 'react';
import type { ErrorInfo, ReactElement, ReactNode } from 'react';
import { AnimatePresence, motion, usePresence } from 'framer-motion';

import { ChatEcran } from './chat';
import { useCible } from './cible';
import { EcranModeles } from './models';
import { EcranSysteme } from './system';
import {
  Button,
  cn,
  fadeUp,
  TONE_VAR,
  transitionBase,
  useEstGrandEcran,
  useHauteurVisuelle,
  type Tone,
} from './shared/design';
import { dechargerModele, lireEtatInference, type EtatChargement, type StatutInference } from './shared/api';

/*
 * Mise en page générale et navigation entre les trois écrans du MVP.
 *
 * Contrat avec les domaines : chaque dossier d'écran expose SON composant depuis son `index.ts`
 * (`models` -> `EcranModeles`, `chat` -> `ChatEcran`, `system` -> `EcranSysteme`). Rien d'autre
 * n'est importé d'eux — App ne connaît ni leurs hooks, ni leurs sous-composants.
 *
 * App est aussi le seul point de RENCONTRE des domaines : choisir un modèle dans `models` doit
 * produire une cible que `chat` sait planifier, et cela demande de croiser trois mesures. Ce
 * croisement est délégué à `cible/`, jamais fait ici ni dans un domaine — un domaine qui en
 * connaîtrait deux autres cesserait d'être remplaçable.
 *
 * L'état d'inférence est affiché ici, dans le bandeau, parce qu'il est vrai pour toute
 * l'application : le GPU est une ressource exclusive, un seul modèle est chargé à la fois. Le
 * savoir depuis n'importe quel écran évite de retourner sur Système pour comprendre pourquoi une
 * génération refuse de démarrer.
 *
 * Sous 1024 px, les onglets quittent l'entête pour une barre basse : le haut d'un téléphone tenu à
 * une main n'est pas atteignable au pouce, et l'entête doit de toute façon céder la place à l'état
 * d'inférence et à l'éjection, qui restent visibles partout parce que le GPU est exclusif. La barre
 * n'est rendue QU'À UN SEUL ENDROIT à la fois (le seuil est lu en JS) : deux instances
 * simultanées feraient courir le trait `layoutId="onglet-actif"` entre deux parents.
 */

type Ecran = 'modeles' | 'chat' | 'systeme';

type Theme = 'dark' | 'light';

const ONGLETS: readonly { readonly cle: Ecran; readonly libelle: string }[] = [
  { cle: 'modeles', libelle: 'Modèles' },
  { cle: 'chat', libelle: 'Chat' },
  { cle: 'systeme', libelle: 'Système' },
];

/** Le bandeau reflète l'état réel : il sonde, il ne suppose pas ce qu'un écran a pu déclencher. */
const INTERVALLE_ETAT_MS = 5_000;

const CLE_THEME = 'echohub.theme';

const TONE_ETAT: Record<EtatChargement, Tone> = {
  inactif: 'neutral',
  en_cours: 'accent',
  pret: 'ok',
  echoue: 'critical',
};

const LIBELLE_ETAT: Record<EtatChargement, string> = {
  inactif: 'aucun modèle',
  en_cours: 'chargement',
  pret: 'prêt',
  echoue: 'échec',
};

function lireThemeInitial(): Theme {
  try {
    const stocke = window.localStorage.getItem(CLE_THEME);
    return stocke === 'light' || stocke === 'dark' ? stocke : 'dark';
  } catch (cause) {
    // Stockage refusé (navigation privée, politique de site) : le thème sombre reste le défaut.
    console.warn('Préférence de thème illisible :', cause);
    return 'dark';
  }
}

function useTheme(): readonly [Theme, () => void] {
  const [theme, setTheme] = useState<Theme>(lireThemeInitial);
  useEffect(() => {
    document.documentElement.setAttribute('data-theme', theme);
    try {
      window.localStorage.setItem(CLE_THEME, theme);
    } catch (cause) {
      console.warn('Préférence de thème non enregistrée :', cause);
    }
  }, [theme]);
  const basculer = useCallback((): void => {
    setTheme((actuel) => (actuel === 'dark' ? 'light' : 'dark'));
  }, []);
  return [theme, basculer];
}

/** Sondage borné par le démontage du composant ; chaque requête porte en plus son propre délai. */
function useEtatInference(): readonly [StatutInference | null, () => void] {
  const [statut, setStatut] = useState<StatutInference | null>(null);
  // Incrémenté pour forcer un relevé hors du rythme de sondage — après une éjection, attendre
  // cinq secondes afficherait un état que l'utilisateur vient lui-même de rendre faux.
  const [reveil, setReveil] = useState(0);
  useEffect(() => {
    const controleur = new AbortController();
    let monte = true;
    const sonder = async (): Promise<void> => {
      try {
        const prochain = await lireEtatInference(controleur.signal);
        if (monte) setStatut(prochain);
      } catch (cause) {
        // Un backend injoignable rend l'état inconnu ; il ne doit pas faire tomber l'interface.
        if (monte) setStatut(null);
        console.warn("État d'inférence indisponible :", cause);
      }
    };
    void sonder(); // premier relevé immédiat, la promesse est volontairement non attendue ici
    const minuterie = window.setInterval(() => void sonder(), INTERVALLE_ETAT_MS);
    return () => {
      monte = false;
      window.clearInterval(minuterie);
      controleur.abort();
    };
  }, [reveil]);
  const resonder = useCallback((): void => setReveil((n) => n + 1), []);
  return [statut, resonder];
}

function Marque(): ReactElement {
  return (
    <div className="flex shrink-0 items-center gap-2 pr-2">
      <span className="text-md font-semibold tracking-tight">EchoHub</span>
      <span className="font-mono text-2xs text-text-3">v2</span>
    </div>
  );
}

interface OngletProps {
  readonly libelle: string;
  readonly actif: boolean;
  /** Barre basse : le trait se place du côté du bord partagé avec le contenu, donc en haut. */
  readonly indicateurEnHaut: boolean;
  readonly onClick: () => void;
}

function Onglet({ libelle, actif, indicateurEnHaut, onClick }: OngletProps): ReactElement {
  return (
    <button
      type="button"
      role="tab"
      aria-selected={actif}
      onClick={onClick}
      className={cn(
        'relative flex min-h-[44px] flex-1 items-center justify-center px-3 text-sm font-medium',
        'transition-colors duration-fast ease-out lg:h-12 lg:flex-none',
        'focus-visible:outline-none focus-visible:shadow-[inset_0_0_0_2px_var(--ring)]',
        actif ? 'text-text' : 'text-text-2 hover:text-text',
      )}
    >
      {libelle}
      {actif && (
        // Le trait suit l'onglet actif : la continuité du mouvement dit d'où l'on vient.
        <motion.span
          layoutId="onglet-actif"
          transition={transitionBase}
          className={cn('absolute inset-x-2 h-px bg-accent', indicateurEnHaut ? 'top-0' : 'bottom-0')}
        />
      )}
    </button>
  );
}

interface BarreOngletsProps {
  readonly ecran: Ecran;
  readonly enBas: boolean;
  readonly onChoisir: (ecran: Ecran) => void;
}

function BarreOnglets({ ecran, enBas, onChoisir }: BarreOngletsProps): ReactElement {
  return (
    <nav
      role="tablist"
      aria-label="Écrans"
      className={cn(
        'flex items-stretch',
        enBas && 'eh-marge-sure-bas shrink-0 border-t border-border bg-bg px-1 pt-1',
      )}
    >
      {ONGLETS.map((onglet) => (
        <Onglet
          key={onglet.cle}
          libelle={onglet.libelle}
          actif={onglet.cle === ecran}
          indicateurEnHaut={enBas}
          onClick={() => onChoisir(onglet.cle)}
        />
      ))}
    </nav>
  );
}

interface EtatInferenceProps {
  readonly statut: StatutInference | null;
  readonly onEjecter: () => void;
}

/*
 * Le GPU est exclusif : tant qu'un modèle l'occupe, aucun autre ne peut être chargé. L'éjection
 * appartient donc au bandeau, à côté de l'état — et pas à un écran, car elle est vraie partout.
 * Sans elle, un modèle chargé hors de cette page ne pouvait plus être libéré depuis l'interface.
 */
function EtatInference({ statut, onEjecter }: EtatInferenceProps): ReactElement {
  const etat: EtatChargement = statut?.etat ?? 'inactif';
  const modele = statut?.modele ?? null;
  const inconnu = statut === null;
  const [ejection, setEjection] = useState(false);

  const ejecter = useCallback((): void => {
    setEjection(true);
    void dechargerModele()
      .catch((cause: unknown) => console.warn('Éjection refusée :', cause))
      .finally(() => {
        setEjection(false);
        onEjecter();
      });
  }, [onEjecter]);

  return (
    <div className="flex min-w-0 items-center gap-2" title={statut?.message ?? undefined}>
      <span
        aria-hidden="true"
        className={cn('h-1.5 w-1.5 shrink-0 rounded-full', etat === 'en_cours' && 'animate-eh-pulse')}
        style={{ background: inconnu ? TONE_VAR.neutral : TONE_VAR[TONE_ETAT[etat]] }}
      />
      <span className="min-w-0 truncate text-xs text-text-2">
        {inconnu ? 'backend injoignable' : LIBELLE_ETAT[etat]}
      </span>
      {/* Le nom du modèle est un détail : sur téléphone il mangerait la place de l'éjection, qui
          elle doit rester atteignable partout. L'état, lui, ne disparaît jamais. */}
      {modele !== null && (
        <span className="hidden min-w-0 max-w-[14rem] truncate font-mono text-xs text-text-3 lg:inline">{modele}</span>
      )}
      {etat === 'pret' && (
        <Button variant="ghost" size="sm" onClick={ejecter} disabled={ejection} title="Libérer la VRAM">
          {ejection ? 'éjection…' : 'Éjecter'}
        </Button>
      )}
    </div>
  );
}

// Icônes monochromes, trait 1,5 px (DESIGN.md). Les rayons du soleil sont découpés en deux
// chemins pour rester lisibles dans la limite de longueur de ligne.
const TRAIT = { stroke: 'currentColor', strokeWidth: 1.5, strokeLinecap: 'round' } as const;
const RAYONS_CARDINAUX = 'M8 1.5v1.2M8 13.3v1.2M14.5 8h-1.2M2.7 8H1.5';
const RAYONS_DIAGONAUX = 'M12.6 3.4l-.8.8M4.2 11.8l-.8.8M12.6 12.6l-.8-.8M4.2 4.2l-.8-.8';

function IconeTheme({ theme }: { readonly theme: Theme }): ReactElement {
  return (
    <svg viewBox="0 0 16 16" className="h-4 w-4" fill="none" aria-hidden="true">
      {theme === 'dark' ? (
        <path d="M13 9.5A5.5 5.5 0 0 1 6.5 3a5.5 5.5 0 1 0 6.5 6.5Z" {...TRAIT} strokeLinejoin="round" />
      ) : (
        <>
          <circle cx="8" cy="8" r="3" {...TRAIT} />
          <path d={RAYONS_CARDINAUX} {...TRAIT} />
          <path d={RAYONS_DIAGONAUX} {...TRAIT} />
        </>
      )}
    </svg>
  );
}

/** Refus d'assemblage : une métadonnée manque. Affiché tel quel — l'utilisateur peut agir dessus. */
function BandeauRefus({ refus }: { readonly refus: string }): ReactElement {
  return (
    <div className="eh-marge-sure-x border-b border-border py-2 text-xs" style={{ color: TONE_VAR.caution }}>
      {refus}
    </div>
  );
}

interface FrontiereProps {
  /** Écran affiché. Il change → la panne appartenait au précédent, la frontière rend la main. */
  readonly ecran: Ecran;
  readonly children: ReactNode;
}

interface EtatFrontiere {
  readonly panne: string | null;
}

/*
 * Filet de dernier recours autour de la zone de contenu.
 *
 * Sans lui, une exception levée pendant un rendu ou un effet de layout démonte l'arbre entier :
 * React 18 laisse alors une page noire, sans message ni trace, et seul un rechargement manuel la
 * ramène. C'est exactement ce que la doctrine du projet interdit — une absence à la place d'un
 * fait. Ici l'exception devient un texte affiché et une sortie possible.
 *
 * La frontière vit dans App et non dans un domaine : elle est vraie pour les trois écrans, aucun
 * ne peut la porter sans que les deux autres importent son interne. Elle enveloppe l'AnimatePresence
 * plutôt que chaque écran, pour couvrir aussi les effets de layout de framer-motion, qui sont au-
 * dessus des écrans.
 */
// Au-delà, une sortie d'écran est tenue pour bloquée et l'écran est retiré quand même (fondu prévu : ~120 ms).
const SORTIE_MAX_MS = 400;

/*
 * Un écran dans la cellule partagée. Constaté le 2026-11-11 : quitter le chat pendant une génération pouvait laisser
 * sa sortie inachevée ; l'écran restait monté, invisible (opacité 0) mais AU-DESSUS du suivant, et captait tous les
 * clics — page Modèles inutilisable jusqu'au rechargement. Ici, dès que l'écran sort, il ne reçoit plus aucun
 * événement et passe dessous (c'est ce qui rend la page suivante utilisable quoi qu'il arrive) ; sa part de la
 * sortie est en plus déclarée finie après `SORTIE_MAX_MS`, pour ne pas dépendre de la seule animation.
 */
function EcranAnime({ children }: { children: ReactNode }): ReactElement {
  const [present, retirer] = usePresence();
  useEffect((): (() => void) | undefined => {
    if (present) {
      return undefined;
    }
    const minuterie = window.setTimeout((): void => retirer(), SORTIE_MAX_MS);
    return (): void => window.clearTimeout(minuterie);
  }, [present, retirer]);
  return (
    <motion.div
      variants={fadeUp}
      initial="hidden"
      animate="visible"
      exit="exit"
      aria-hidden={!present}
      className={cn(
        'col-start-1 row-start-1 h-full min-h-0 overflow-y-auto',
        present ? 'relative z-[1]' : 'pointer-events-none relative z-0',
      )}
    >
      {children}
    </motion.div>
  );
}

class FrontiereErreur extends Component<FrontiereProps, EtatFrontiere> {
  constructor(props: FrontiereProps) {
    super(props);
    this.state = { panne: null };
  }

  static getDerivedStateFromError(cause: unknown): EtatFrontiere {
    return { panne: cause instanceof Error ? cause.message : String(cause) };
  }

  override componentDidCatch(cause: Error, infos: ErrorInfo): void {
    console.error('Écran interrompu par une exception :', cause, infos.componentStack);
  }

  override componentDidUpdate(precedent: FrontiereProps): void {
    if (this.state.panne !== null && precedent.ecran !== this.props.ecran) {
      this.setState({ panne: null });
    }
  }

  override render(): ReactNode {
    if (this.state.panne === null) {
      return this.props.children;
    }
    return (
      <div className="flex h-full flex-col items-center justify-center gap-3 p-8 text-center">
        <p className="text-sm text-text">L’écran s’est interrompu.</p>
        <p className="max-w-lg break-words font-mono text-xs text-text-3">{this.state.panne}</p>
        <Button variant="primary" size="sm" onClick={() => window.location.reload()}>
          Recharger
        </Button>
      </div>
    );
  }
}

interface EnteteAppProps {
  readonly ecran: Ecran;
  readonly grandEcran: boolean;
  readonly statut: StatutInference | null;
  readonly theme: Theme;
  readonly onEjecter: () => void;
  readonly onBasculerTheme: () => void;
  readonly onChoisirEcran: (ecran: Ecran) => void;
}

function EnteteApp(props: EnteteAppProps): ReactElement {
  const { ecran, grandEcran, statut, theme, onEjecter, onBasculerTheme, onChoisirEcran } = props;
  return (
    <header
      className={cn(
        'eh-marge-sure-x flex min-h-[52px] shrink-0 items-center gap-1',
        'border-b border-border lg:h-12 lg:min-h-0',
      )}
    >
      <Marque />
      {grandEcran && <BarreOnglets ecran={ecran} enBas={false} onChoisir={onChoisirEcran} />}
      <div className="flex min-w-0 flex-1 items-center justify-end gap-2 lg:gap-3">
        <EtatInference statut={statut} onEjecter={onEjecter} />
        <Button
          variant="ghost"
          size="sm"
          onClick={onBasculerTheme}
          aria-label={theme === 'dark' ? 'Passer au thème clair' : 'Passer au thème sombre'}
        >
          <IconeTheme theme={theme} />
        </Button>
      </div>
    </header>
  );
}

export function App(): ReactElement {
  const [ecran, setEcran] = useState<Ecran>('modeles');
  const [theme, basculerTheme] = useTheme();
  const [statut, resonderEtat] = useEtatInference();
  const { cible, refus, erreur, choisir } = useCible();
  const grandEcran = useEstGrandEcran();
  useHauteurVisuelle();

  // Sélectionner un modèle amène sur le chat : c'est là que le plan est montré avant d'être appliqué.
  const surChoixModele = useCallback(
    (modele: Parameters<typeof choisir>[0]): void => {
      choisir(modele);
      setEcran('chat');
    },
    [choisir],
  );

  const rendreEcran = (): ReactElement => {
    switch (ecran) {
      case 'modeles':
        return <EcranModeles onCharger={surChoixModele} />;
      case 'chat':
        return <ChatEcran cible={cible} />;
      case 'systeme':
        return <EcranSysteme />;
    }
  };

  const alerte = refus === null ? erreur : `${refus.manquant} — ${refus.remediation}`;

  return (
    <div className="eh-hauteur-app flex flex-col overflow-x-hidden bg-bg text-text">
      <EnteteApp
        ecran={ecran}
        grandEcran={grandEcran}
        statut={statut}
        theme={theme}
        onEjecter={resonderEtat}
        onBasculerTheme={basculerTheme}
        onChoisirEcran={setEcran}
      />

      {alerte !== null && <BandeauRefus refus={alerte} />}

      {/* Une seule cellule de grille, partagée : les deux écrans s'y superposent le temps du
          fondu au lieu de s'empiler. C'est ce qui remplace `mode="wait"`, retiré parce qu'il
          laissait cette zone VIDE — donc noire — pendant la sortie de l'écran quitté, et
          définitivement vide si cette sortie ne s'achevait pas (démonter un arbre `layoutId`
          pendant la rafale de rendus d'une génération en cours). Le chevauchement dure 120 ms,
          le sortant déjà à `opacity: 0` : aucun risque de lire deux jeux de mesures à la fois. */}
      <main className="grid min-h-0 flex-1 grid-cols-1 grid-rows-1">
        <FrontiereErreur ecran={ecran}>
          <AnimatePresence initial={false}>
            <EcranAnime key={ecran}>{rendreEcran()}</EcranAnime>
          </AnimatePresence>
        </FrontiereErreur>
      </main>

      {!grandEcran && <BarreOnglets ecran={ecran} enBas onChoisir={setEcran} />}
    </div>
  );
}
