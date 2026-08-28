/*
 * Écran de démonstration — la composition de `ChatEcran` nourrie par les données d'exemple, sans
 * un seul appel réseau. Il sert deux choses : produire les captures (aucun modèle chargé, aucun
 * backend requis), et vérifier les états que la production ne montre qu'au bon moment (outil en
 * cours, échec, versions d'artefact).
 *
 * La scène se choisit par `?scene=conversation|outils|artefact|liste|selection`. Les composants
 * rendus sont EXACTEMENT ceux de la production ; seul l'état est en dur — un écart visuel entre
 * cette page et l'application serait un bug de la page, jamais une excuse.
 */

import { useEffect, useMemo, useState } from 'react';
import type { ReactElement } from 'react';
import { Card, Feuille, Modal, cn, useEstGrandEcran } from '../../../shared/design';
import {
  FournisseurAtelier,
  PanneauArtefact,
  useAtelier,
  type CapacitesAtelier,
  type EtatAtelier,
} from '../../artefacts';
import { EnTeteChat } from '../../EnTeteChat';
import { useTiroirsChat, type EtatTiroirsChat } from '../../useTiroirsChat';
import { Composeur } from '../Composeur';
import { FilMessages } from '../FilMessages';
import { ListeConversations } from '../ListeConversations';
import { PanneauOutils } from '../PanneauOutils';
import { CATALOGUE_OUTILS } from '../outils-catalogue';
import type { MessageChat } from '../../api/contrats';
import {
  ARCHIVEES_DEMO,
  BROUILLON_OUTIL_EN_COURS,
  CONTENUS_ARTEFACTS,
  CONVERSATIONS_DEMO,
  MESSAGES_ARTEFACT,
  MESSAGES_CONVERSATION,
  MESSAGES_OUTILS,
} from './exemples';

export type SceneDemo = 'conversation' | 'outils' | 'artefact' | 'liste' | 'selection';

interface DonneesScene {
  titre: string;
  messages: MessageChat[];
  brouillon: string | null;
  ouvrirArtefact: boolean;
}

const SCENES: Readonly<Record<SceneDemo, DonneesScene>> = {
  conversation: {
    titre: 'llama.cpp ou vLLM sur 3060',
    messages: MESSAGES_CONVERSATION,
    brouillon: null,
    ouvrirArtefact: false,
  },
  outils: {
    titre: 'Veille prix RTX 5090',
    messages: MESSAGES_OUTILS,
    brouillon: BROUILLON_OUTIL_EN_COURS,
    ouvrirArtefact: false,
  },
  artefact: {
    titre: 'Pong néon en HTML',
    messages: MESSAGES_ARTEFACT,
    brouillon: null,
    ouvrirArtefact: true,
  },
  liste: {
    titre: 'llama.cpp ou vLLM sur 3060',
    messages: MESSAGES_CONVERSATION,
    brouillon: null,
    ouvrirArtefact: false,
  },
  selection: {
    titre: 'Veille prix RTX 5090',
    messages: MESSAGES_OUTILS,
    brouillon: null,
    ouvrirArtefact: false,
  },
};

/** Sert les contenus d'artefact depuis les exemples — le contrat du chargeur, sans réseau. */
function chargerContenuDemo(fichierId: string): Promise<string> {
  const contenu = CONTENUS_ARTEFACTS[fichierId];
  return contenu === undefined
    ? Promise.reject(new Error(`Contenu d'exemple absent : ${fichierId}`))
    : Promise.resolve(contenu);
}

function PlanFictif(): ReactElement {
  return (
    <div className="p-3">
      <Card title="Plan de chargement">
        <p className="text-xs leading-relaxed text-text-2">
          Page de démonstration : le vrai panneau de plan vit ici, nourri par le planificateur.
        </p>
      </Card>
    </div>
  );
}

function ColonneDroiteDemo({ atelier }: { atelier: EtatAtelier }): ReactElement {
  return (
    <aside
      className={cn(
        'hidden h-full w-full min-w-0 flex-col lg:flex',
        'lg:w-[26rem] lg:shrink-0 lg:border-l lg:border-border',
      )}
    >
      {atelier.ouvert !== null ? (
        <div className="min-h-0 flex-1 p-3">
          <PanneauArtefact
            artefact={atelier.ouvert.artefact}
            version={atelier.ouvert.version}
            onChoisirVersion={atelier.choisirVersion}
            onFermer={atelier.fermer}
            chargerContenu={chargerContenuDemo}
          />
        </div>
      ) : (
        <PlanFictif />
      )}
    </aside>
  );
}

function TiroirArtefactDemo({ atelier, tiroirs }: { atelier: EtatAtelier; tiroirs: EtatTiroirsChat }):
  ReactElement | null {
  if (atelier.ouvert === null) {
    return null;
  }
  return (
    <Feuille ouverte={tiroirs.tiroir === 'artefact'} onFermer={tiroirs.fermer} cote="droite" titre="Artefact">
      <div className="h-full min-h-0 p-3">
        <PanneauArtefact
          artefact={atelier.ouvert.artefact}
          version={atelier.ouvert.version}
          onChoisirVersion={atelier.choisirVersion}
          onFermer={tiroirs.fermer}
          chargerContenu={chargerContenuDemo}
        />
      </div>
    </Feuille>
  );
}

function ListeDemo({ onOuvrir }: { onOuvrir: (id: string) => void }): ReactElement {
  const [archiveesVisibles, setArchiveesVisibles] = useState<typeof ARCHIVEES_DEMO | null>(null);
  return (
    <ListeConversations
      conversations={CONVERSATIONS_DEMO}
      archivees={archiveesVisibles}
      conversationActive="v2"
      erreur={null}
      onOuvrir={onOuvrir}
      onCreer={() => undefined}
      onSupprimer={() => undefined}
      onRenommer={() => undefined}
      onArchiver={() => undefined}
      onChargerArchivees={() => setArchiveesVisibles(ARCHIVEES_DEMO)}
    />
  );
}

/* La modale porte SA sélection : partielle d'entrée, pour que la capture montre une paire cassée
 * (recuperer_page sans recherche_web) et un groupe incomplet — l'état par défaut ne raconte rien. */
function ModaleSelectionDemo({ ouverte, onFermer }: { ouverte: boolean; onFermer: () => void }): ReactElement {
  const [actifs, setActifs] = useState<ReadonlySet<string>>(
    () =>
      new Set(
        CATALOGUE_OUTILS.map((o) => o.nom).filter((n) => n !== 'recherche_web' && n !== 'executer_commande'),
      ),
  );
  const basculerGroupe = (noms: readonly string[], activer: boolean): void => {
    const prochains = new Set(actifs);
    for (const nom of noms) {
      if (activer) prochains.add(nom);
      else prochains.delete(nom);
    }
    setActifs(prochains);
  };
  return (
    <Modal open={ouverte} onClose={onFermer} title="Outils du modèle" size="md">
      <PanneauOutils
        catalogue={CATALOGUE_OUTILS}
        actifs={actifs}
        persistee
        onBasculer={(nom) => basculerGroupe([nom], !actifs.has(nom))}
        onBasculerGroupe={basculerGroupe}
      />
    </Modal>
  );
}

function useCapacitesDemo(atelier: EtatAtelier, tiroirs: EtatTiroirsChat, grandEcran: boolean): CapacitesAtelier {
  return useMemo(
    () => ({
      ouvrirVersion: (version) => {
        atelier.ouvrir(version);
        if (!grandEcran) {
          tiroirs.ouvrir('artefact');
        }
      },
      artefactOuvert: atelier.ouvert?.artefact.artefact_id ?? null,
    }),
    [atelier, grandEcran, tiroirs],
  );
}

/* Ouvre la dernière version du premier artefact du catalogue, une seule fois, pour la scène
 * `artefact` : la capture doit montrer le panneau ET son sélecteur sans clic préalable. */
function useOuvertureScenario(atelier: EtatAtelier, voulu: boolean): void {
  const { catalogue, ouvert, ouvrir } = atelier;
  useEffect((): void => {
    if (!voulu || ouvert !== null) {
      return;
    }
    const premier = [...catalogue.values()][0];
    const derniere = premier?.versions[premier.versions.length - 1];
    if (derniere !== undefined) {
      ouvrir(derniere);
    }
  }, [voulu, ouvert, catalogue, ouvrir]);
}

interface EchangeDemoProps {
  donnees: DonneesScene;
  tiroirs: EtatTiroirsChat;
  capacites: CapacitesAtelier;
  onOutils: () => void;
}

function EchangeDemo({ donnees, tiroirs, capacites, onOutils }: EchangeDemoProps): ReactElement {
  return (
    <section className="flex min-h-0 min-w-0 flex-1 flex-col">
      <EnTeteChat
        titre={donnees.titre}
        modele="Qwen3.5-9B-Claude-Opus-Distilled.Q4_K_M"
        pret
        onReglages={() => undefined}
        onOutils={onOutils}
        onOuvrirConversations={() => tiroirs.ouvrir('conversations')}
        onOuvrirPlan={() => tiroirs.ouvrir('plan')}
      />
      <FournisseurAtelier valeur={capacites}>
        <FilMessages
          messages={donnees.messages}
          brouillon={donnees.brouillon}
          compactionEnCours={null}
          vide={<p className="text-sm text-text-2">Scène vide.</p>}
        />
      </FournisseurAtelier>
      <Composeur
        genere={donnees.brouillon !== null}
        desactive={false}
        empechement=""
        conversationId={null}
        onEnvoyer={() => undefined}
        onAnnuler={() => undefined}
      />
    </section>
  );
}

export function EcranDemo({ scene }: { readonly scene: SceneDemo }): ReactElement {
  const donnees = SCENES[scene];
  const tiroirs = useTiroirsChat();
  const grandEcran = useEstGrandEcran();
  const [selectionOuverte, setSelectionOuverte] = useState<boolean>(scene === 'selection');
  const atelier = useAtelier(donnees.messages, donnees.brouillon);
  useOuvertureScenario(atelier, donnees.ouvrirArtefact);
  const capacites = useCapacitesDemo(atelier, tiroirs, grandEcran);
  return (
    <div className="flex h-dvh min-h-0 overflow-x-hidden bg-bg">
      <Feuille ouverte={tiroirs.tiroir === 'conversations'} onFermer={tiroirs.fermer} cote="gauche"
        titre="Conversations">
        <ListeDemo onOuvrir={tiroirs.fermer} />
      </Feuille>
      <EchangeDemo
        donnees={donnees}
        tiroirs={tiroirs}
        capacites={capacites}
        onOutils={() => setSelectionOuverte(true)}
      />
      <ColonneDroiteDemo atelier={atelier} />
      {!grandEcran && <TiroirArtefactDemo atelier={atelier} tiroirs={tiroirs} />}
      <ModaleSelectionDemo ouverte={selectionOuverte} onFermer={() => setSelectionOuverte(false)} />
    </div>
  );
}
