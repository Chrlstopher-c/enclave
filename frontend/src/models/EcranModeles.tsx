import { useEffect, useRef, useState, type ReactElement } from 'react';
import { Badge, Button, cn } from '../shared/design';
import { useProfilMachine } from '../system';
import type { ModeleEnregistre, ResultatRecherche } from './api/types';
import { budgetDepuis, type BudgetMemoire } from './faisabilite/evaluation';
import { enGoUnite } from './format';
import { ModelesLocaux } from './locaux/ModelesLocaux';
import { useModelesLocaux, type EtatModelesLocaux } from './locaux/useModelesLocaux';
import { ModaleTelechargement } from './recherche/ModaleTelechargement';
import { PanneauDecouverte } from './recherche/PanneauDecouverte';
import { CarteStrata } from './strata/CarteStrata';
import { useRecherche, type EtatRecherche } from './recherche/useRecherche';
import { Telechargements } from './telechargements/Telechargements';
import { useTelechargements, type EtatTelechargements } from './telechargements/useTelechargements';

/*
 * Écran Modèles — découvrir, télécharger, gérer ce qui est sur le disque.
 *
 * Le budget mémoire est affiché en haut et jamais loin d'un chiffre de taille : c'est lui qui donne
 * son sens à tout le reste. Il vient du domaine `system`, par son interface publique ; le domaine
 * `models` ne mesure aucun matériel lui-même.
 */

type Onglet = 'decouvrir' | 'locaux' | 'transferts';

function BudgetMachine({ budget }: { budget: BudgetMemoire }): ReactElement {
  if (!budget.mesure) {
    return <Badge tone="caution">mémoire non mesurée — aucune faisabilité affichable</Badge>;
  }
  return (
    <div className="flex flex-wrap items-center gap-x-3 gap-y-0.5 font-mono text-xs tabular-nums">
      <span className="text-mem-vram">{enGoUnite(budget.vramLibreOctets)} VRAM libre</span>
      <span className="text-text-3">·</span>
      <span className="text-mem-ram">{enGoUnite(budget.ramDisponibleOctets)} RAM disponible</span>
    </div>
  );
}

function EnTete({ budget }: { budget: BudgetMemoire }): ReactElement {
  return (
    <header className="mb-4 flex flex-wrap items-end justify-between gap-2 lg:mb-6 lg:gap-3">
      <div className="min-w-0">
        <h1 className="text-xl font-semibold text-text">Modèles</h1>
        <p className="mt-1 text-xs text-text-2">
          Ce que le Hub annonce, confronté à ce que cette machine peut réellement tenir.
        </p>
      </div>
      <BudgetMachine budget={budget} />
    </header>
  );
}

interface EntreeOnglet {
  cle: Onglet;
  libelle: string;
  compte?: number;
}

function Onglets({
  actif,
  entrees,
  onChoisir,
}: {
  actif: Onglet;
  entrees: readonly EntreeOnglet[];
  onChoisir: (onglet: Onglet) => void;
}): ReactElement {
  // Trois onglets tiennent à 390 px, mais un libellé plus long ne doit jamais pousser la page :
  // le ruban défile dans son propre conteneur plutôt que d'élargir le corps.
  return (
    <div role="tablist" className="flex max-w-full items-center gap-1 overflow-x-auto">
      {entrees.map((entree) => (
        <button
          key={entree.cle}
          type="button"
          role="tab"
          aria-selected={actif === entree.cle}
          onClick={(): void => onChoisir(entree.cle)}
          className={cn(
            'shrink-0 rounded-sm px-3 text-sm font-medium transition-colors duration-fast ease-out',
            'min-h-[44px] min-w-[44px] lg:min-h-0 lg:min-w-0 lg:h-8',
            actif === entree.cle ? 'bg-surface-2 text-text' : 'text-text-2 hover:text-text',
          )}
        >
          {entree.libelle}
          {entree.compte !== undefined && entree.compte > 0 && (
            <span className="ml-1.5 font-mono text-2xs tabular-nums text-text-3">{entree.compte}</span>
          )}
        </button>
      ))}
    </div>
  );
}

/**
 * Un transfert qui s'achève inscrit une entrée au registre côté backend : le disque a changé, la
 * liste affichée doit être relue plutôt que corrigée à la main.
 */
function useRelireApresTransfert(actifs: number, relire: () => void): void {
  const precedents = useRef<number>(0);
  useEffect(() => {
    if (precedents.current > 0 && actifs === 0) {
      relire();
    }
    precedents.current = actifs;
  }, [actifs, relire]);
}

interface BarreProps {
  onglet: Onglet;
  locaux: EtatModelesLocaux;
  actifs: number;
  onChoisir: (onglet: Onglet) => void;
}

function BarreOnglets({ onglet, locaux, actifs, onChoisir }: BarreProps): ReactElement {
  return (
    <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
      <Onglets
        actif={onglet}
        onChoisir={onChoisir}
        entrees={[
          { cle: 'decouvrir', libelle: 'Découvrir' },
          { cle: 'locaux', libelle: 'Sur le disque', compte: locaux.liste.length },
          { cle: 'transferts', libelle: 'Transferts', compte: actifs },
        ]}
      />
      {onglet === 'locaux' && (
        <Button
          size="sm"
          className="w-full lg:w-auto"
          loading={locaux.synchronisation}
          onClick={locaux.synchroniser}
        >
          Synchroniser avec le disque
        </Button>
      )}
    </div>
  );
}

interface PanneauProps {
  onglet: Onglet;
  budget: BudgetMemoire;
  recherche: EtatRecherche;
  locaux: EtatModelesLocaux;
  transferts: EtatTelechargements;
  onChoisirDepot: (resultat: ResultatRecherche) => void;
  onCharger?: (modele: ModeleEnregistre) => void;
}

function Panneau(props: PanneauProps): ReactElement {
  if (props.onglet === 'decouvrir') {
    return (
      <PanneauDecouverte recherche={props.recherche} budget={props.budget} onChoisir={props.onChoisirDepot} />
    );
  }
  if (props.onglet === 'locaux') {
    return (
      <>
        <CarteStrata />
        <ModelesLocaux etat={props.locaux} budget={props.budget} onCharger={props.onCharger} />
      </>
    );
  }
  return <Telechargements etat={props.transferts} />;
}

interface Sources {
  budget: BudgetMemoire;
  recherche: EtatRecherche;
  locaux: EtatModelesLocaux;
  transferts: EtatTelechargements;
}

/** Les quatre sources de l'écran, dont le budget mémoire emprunté au domaine `system`. */
function useSources(): Sources {
  const profil = useProfilMachine();
  const recherche = useRecherche();
  const transferts = useTelechargements();
  const locaux = useModelesLocaux();
  useRelireApresTransfert(transferts.actifs, locaux.rafraichir);
  return { budget: budgetDepuis(profil.donnee), recherche, locaux, transferts };
}

export interface EcranModelesProps {
  /** Délégué au domaine `inference` : cet écran ne construit aucun plan de chargement. */
  onCharger?: (modele: ModeleEnregistre) => void;
}

export function EcranModeles({ onCharger }: EcranModelesProps): ReactElement {
  const [onglet, setOnglet] = useState<Onglet>('decouvrir');
  const [depotChoisi, setDepotChoisi] = useState<ResultatRecherche | null>(null);
  const { budget, recherche, locaux, transferts } = useSources();

  const lance = (): void => {
    setOnglet('transferts');
    transferts.rafraichir();
  };

  return (
    <div className="mx-auto max-w-5xl px-4 py-5 lg:px-6 lg:py-8">
      <EnTete budget={budget} />
      <BarreOnglets onglet={onglet} locaux={locaux} actifs={transferts.actifs} onChoisir={setOnglet} />
      <Panneau
        onglet={onglet}
        budget={budget}
        recherche={recherche}
        locaux={locaux}
        transferts={transferts}
        onChoisirDepot={setDepotChoisi}
        onCharger={onCharger}
      />
      <ModaleTelechargement
        depot={depotChoisi}
        budget={budget}
        onFermer={(): void => setDepotChoisi(null)}
        onLance={lance}
      />
    </div>
  );
}
