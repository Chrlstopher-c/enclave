/*
 * Modale du mode projet : confier un dossier à la conversation, en créer un, revenir à un instantané.
 *
 * Les règles sont AFFICHÉES, pas seulement appliquées : l'utilisateur doit savoir ce que le modèle
 * peut faire dans ce dossier — tout, sauf en sortir, publier, ou détruire en masse — et qu'un
 * instantané précède chaque tour.
 */

import { useEffect, useState, type ReactElement } from 'react';
import { Badge, Button, Modal, cn } from '../../shared/design';
import { MOTIF_NOM_PROJET, type Instantane, type Projet } from './api-projet';
import type { EtatProjetConversation } from './useProjetConversation';

const DATE = new Intl.DateTimeFormat('fr-FR', { dateStyle: 'short', timeStyle: 'short' });

const CLASSE_CHAMP =
  'min-h-[44px] w-full flex-1 rounded-sm border border-border bg-surface-2 px-2 py-1 font-mono text-xs '
  + 'text-text outline-none focus:border-border-strong lg:min-h-0';

function Regles(): ReactElement {
  return (
    <ul className="space-y-1 rounded-sm border border-border bg-surface-2 p-3 text-2xs leading-relaxed text-text-2">
      <li>Le modèle travaille uniquement dans ce dossier : fichiers, commandes, dépendances, serveurs de dev.</li>
      <li>Refusé par le harnais : sortir du dossier, git push / publication, ssh, suppressions globales.</li>
      <li>Un instantané est pris avant chaque tour : tout ce qu’il fait peut être annulé ci-dessous.</li>
    </ul>
  );
}

function LigneProjet({ projet, actif, onChoisir }: {
  readonly projet: Projet;
  readonly actif: boolean;
  readonly onChoisir: () => void;
}): ReactElement {
  return (
    <li>
      <button
        type="button"
        onClick={onChoisir}
        className={cn(
          'flex min-h-[44px] w-full items-center justify-between gap-2 rounded-sm px-2 py-1 text-left',
          'transition-colors duration-fast hover:bg-surface-2 lg:min-h-0',
          actif && 'bg-surface-2',
        )}
      >
        <span className="truncate font-mono text-xs text-text">{projet.nom}</span>
        <span className="shrink-0 text-2xs text-text-3">
          {actif ? 'confié' : DATE.format(new Date(projet.modifie_le * 1000))}
        </span>
      </button>
    </li>
  );
}

function NouveauProjet({ occupe, onCreer }: {
  readonly occupe: boolean;
  readonly onCreer: (nom: string) => void;
}): ReactElement {
  const [nom, setNom] = useState<string>('');
  const valide = MOTIF_NOM_PROJET.test(nom);
  return (
    <form
      className="flex flex-col gap-2 lg:flex-row"
      onSubmit={(evenement) => {
        evenement.preventDefault();
        if (valide) {
          onCreer(nom);
          setNom('');
        }
      }}
    >
      <input
        value={nom}
        onChange={(evenement) => setNom(evenement.target.value.toLowerCase())}
        placeholder="nouveau-projet"
        aria-label="Nom du nouveau projet"
        className={CLASSE_CHAMP}
      />
      <Button type="submit" size="sm" disabled={!valide || occupe}>
        Créer et confier
      </Button>
    </form>
  );
}

function LigneInstantane({ instantane, occupe, onRestaurer }: {
  readonly instantane: Instantane;
  readonly occupe: boolean;
  readonly onRestaurer: () => void;
}): ReactElement {
  const [confirmer, setConfirmer] = useState<boolean>(false);
  return (
    <li className="flex items-center justify-between gap-2 py-1">
      <span className="min-w-0">
        <span className="block truncate text-xs text-text">{instantane.message}</span>
        <span className="font-mono text-2xs text-text-3">
          {instantane.sha.slice(0, 8)} · {DATE.format(new Date(instantane.date * 1000))}
        </span>
      </span>
      <Button
        size="sm"
        variant={confirmer ? 'danger' : 'ghost'}
        disabled={occupe}
        onClick={() => (confirmer ? onRestaurer() : setConfirmer(true))}
        onBlur={() => setConfirmer(false)}
      >
        {confirmer ? 'Confirmer' : 'Restaurer'}
      </Button>
    </li>
  );
}

function SectionInstantanes({ etat }: { readonly etat: EtatProjetConversation }): ReactElement {
  return (
    <section className="space-y-1">
      <h3 className="text-xs font-semibold text-text">Instantanés</h3>
      {etat.instantanes.length === 0 ? (
        <p className="text-2xs text-text-3">Aucun pour l’instant : le premier sera pris au prochain tour.</p>
      ) : (
        <ul className="max-h-56 divide-y divide-border overflow-y-auto">
          {etat.instantanes.map((instantane) => (
            <LigneInstantane
              key={instantane.sha}
              instantane={instantane}
              occupe={etat.occupe}
              onRestaurer={() => etat.restaurer(instantane.sha)}
            />
          ))}
        </ul>
      )}
    </section>
  );
}

function ProjetConfie({ etat }: { readonly etat: EtatProjetConversation }): ReactElement | null {
  if (etat.projet === null) {
    return null;
  }
  return (
    <div className="flex items-center justify-between gap-2">
      <Badge tone="accent" dot>
        {etat.projet}
      </Badge>
      <Button size="sm" variant="ghost" disabled={etat.occupe} onClick={() => etat.confier(null)}>
        Retirer le projet
      </Button>
    </div>
  );
}

function ContenuActif({ etat }: { readonly etat: EtatProjetConversation }): ReactElement {
  const projets = etat.catalogue?.projets ?? [];
  return (
    <div className="space-y-4">
      <ProjetConfie etat={etat} />
      <Regles />
      <section className="space-y-2">
        <h3 className="text-xs font-semibold text-text">Projets</h3>
        {projets.length > 0 && (
          <ul className="max-h-56 overflow-y-auto">
            {projets.map((projet) => (
              <LigneProjet
                key={projet.nom}
                projet={projet}
                actif={projet.nom === etat.projet}
                onChoisir={() => etat.confier(projet.nom)}
              />
            ))}
          </ul>
        )}
        <NouveauProjet occupe={etat.occupe} onCreer={etat.creerEtConfier} />
        <p className="font-mono text-2xs text-text-3">{etat.catalogue?.racine}</p>
      </section>
      {etat.projet !== null && <SectionInstantanes etat={etat} />}
    </div>
  );
}

export interface ModaleProjetProps {
  readonly etat: EtatProjetConversation;
  readonly ouvert: boolean;
  readonly onFermer: () => void;
}

export function ModaleProjet({ etat, ouvert, onFermer }: ModaleProjetProps): ReactElement {
  const { rafraichir } = etat;
  useEffect((): void => {
    if (ouvert) {
      rafraichir();
    }
    // Recharger à l'ouverture seulement : `rafraichir` change avec le projet, qu'il recharge lui-même.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ouvert]);
  return (
    <Modal open={ouvert} onClose={onFermer} title="Projet de la conversation" size="md">
      {etat.erreur !== null && <p className="mb-3 text-2xs text-critical">{etat.erreur}</p>}
      {etat.catalogue === null ? (
        <p className="text-2xs text-text-3">Chargement…</p>
      ) : etat.catalogue.actif ? (
        <ContenuActif etat={etat} />
      ) : (
        <p className="text-2xs leading-relaxed text-caution">
          Mode projet non configuré : définir ECHOHUB_PROJETS_RACINE (dossier de l’hôte) puis redémarrer.
        </p>
      )}
    </Modal>
  );
}
