import { useCallback, useMemo, useState } from 'react';
import type { ReactElement } from 'react';
import { cn, Feuille, Modal, useEstGrandEcran } from '../shared/design';
import { FournisseurActions, useActionsFil, type EtatActionsFil } from './actions';
import {
  FournisseurAtelier,
  PanneauArtefact,
  useAtelier,
  type CapacitesAtelier,
  type EtatAtelier,
  type VersionArtefact,
} from './artefacts';
import { PanneauContexte } from './contexte';
import { Composeur } from './conversation/Composeur';
import { FilMessages } from './conversation/FilMessages';
import { ListeConversations } from './conversation/ListeConversations';
import { PanneauOutils } from './conversation/PanneauOutils';
import { useSelectionOutils } from './conversation/useSelectionOutils';
import { EnTeteChat, type EnTeteChatProps } from './EnTeteChat';
import { ModaleProjet, PanneauFichiers, useProjetEcran } from './projet';
import { ModaleReglages } from './reglages';
import { PanneauPlan } from './plan/PanneauPlan';
import type { CibleChargement } from './plan/cible';
import { useEcranChat, type EtatEcranChat } from './useEcranChat';
import { useTiroirsChat, type EtatTiroirsChat } from './useTiroirsChat';

/*
 * Écran de conversation. Trois colonnes : les conversations, l'échange, et le plan de chargement.
 *
 * Le plan occupe une colonne permanente plutôt qu'une modale : ce n'est pas une étape qu'on
 * traverse avant de discuter, c'est l'état de la machine pendant qu'on discute. Le débit mesuré de
 * la dernière réponse remonte d'ailleurs du fil vers le plan — la conversation devient la mesure.
 *
 * Un artefact ouvert PREND LA PLACE du plan dans la colonne de droite, il ne s'y empile pas : le
 * plan dit l'état de la machine, l'artefact est ce qu'on regarde — deux moments différents, une
 * seule colonne, et la fermeture rend le plan tel qu'on l'avait laissé. Sous 1024 px, chacun des
 * trois panneaux latéraux devient un tiroir (`Feuille`) et l'échange prend tout l'écran.
 */

function FilVide({ cible }: { cible: CibleChargement | null }): ReactElement {
  return (
    <div className="mx-auto flex h-full max-w-md flex-col justify-center text-center">
      <p className="text-sm leading-relaxed text-text-2">
        {cible === null
          ? 'Sélectionnez un modèle pour voir le plan de chargement calculé pour cette machine.'
          : 'Le plan est calculé à droite. Chargez le modèle, puis écrivez votre premier message.'}
      </p>
    </div>
  );
}

/*
 * Le composeur (texte, pièces jointes) ne se bloque QUE faute de conversation : `!moteurPret` en
 * ferait une condition d'envoi, ce que la règle de l'opérateur interdit explicitement (Composeur.tsx)
 * — l'application transmet toujours, y compris sans modèle chargé ; c'est au modèle de répondre
 * qu'il ne voit rien, avec ses mots, jamais à l'interface de refuser à sa place.
 */
function empechementSaisie(conversationChoisie: boolean, moteurPret: boolean): string {
  if (!conversationChoisie) {
    return 'Créez une conversation pour commencer.';
  }
  if (!moteurPret) {
    // « à droite » n'existe plus sous 1024 px, où le plan est un tiroir : nommer le panneau, pas
    // sa position, sinon la remédiation désigne un endroit absent au doigt.
    return (
      'Aucun modèle chargé : la réponse ne pourra pas être générée tant que le panneau de plan '
      + 'n’en charge un.'
    );
  }
  return '';
}

interface ColonneProps {
  etat: EtatEcranChat;
  cible: CibleChargement | null;
}

interface ColonneEchangeProps extends ColonneProps {
  fil: EtatActionsFil;
  tiroirs: EtatTiroirsChat;
  capacites: CapacitesAtelier;
  onOutils: () => void;
  actionsProjet: ActionsProjetEntete;
}

/* Ce que l'en-tête montre du projet confié : le bouton de la modale et celui du panneau de fichiers. */
type ActionsProjetEntete = Pick<EnTeteChatProps, 'projet' | 'onProjet' | 'onFichiers' | 'fichiersOuverts'>;

function ColonneEchange(props: ColonneEchangeProps): ReactElement {
  const { etat, cible, fil, tiroirs, capacites, onOutils } = props;
  const { courante, moteurPret } = etat;
  // Deux flux peuvent alimenter le fil : le composeur et un rejeu lancé depuis un message. Le
  // moteur n'en sert qu'un à la fois (le backend refuse le second), donc l'écran n'en montre qu'un.
  const genere = courante.genere || fil.genere;
  return (
    <section className="flex min-h-0 min-w-0 flex-1 flex-col">
      <EnTeteChat
        titre={courante.detail?.conversation.titre ?? 'Conversation'}
        modele={etat.chargement.statut?.modele ?? cible?.nomModele ?? null}
        pret={moteurPret}
        onReglages={() => etat.ouvrirReglages(true)}
        onOutils={onOutils}
        {...props.actionsProjet}
        onOuvrirConversations={() => tiroirs.ouvrir('conversations')}
        onOuvrirPlan={() => tiroirs.ouvrir('plan')}
      />
      <LigneErreur texte={courante.erreur ?? fil.erreur} />
      {/* `fil.messages` est le chemin de branche servi par le serveur ; tant qu'il n'est pas
          arrivé il vaut `null` et l'historique déjà chargé fait foi — aucun chemin n'est déduit. */}
      <FournisseurActions valeur={fil.actions}>
        <FournisseurAtelier valeur={capacites}>
          <FilMessages
            messages={fil.messages ?? courante.messages}
            brouillon={fil.brouillon ?? courante.brouillon}
            compactionEnCours={courante.compactionEnCours}
            vide={<FilVide cible={cible} />}
          />
        </FournisseurAtelier>
      </FournisseurActions>
      <ComposeurEchange etat={etat} fil={fil} genere={genere} />
    </section>
  );
}

function ComposeurEchange({
  etat,
  fil,
  genere,
}: {
  etat: EtatEcranChat;
  fil: EtatActionsFil;
  genere: boolean;
}): ReactElement {
  const { courante, conversationActive, moteurPret } = etat;
  return (
    <Composeur
      genere={genere}
      desactive={conversationActive === null}
      empechement={empechementSaisie(conversationActive !== null, moteurPret)}
      conversationId={conversationActive}
      onEnvoyer={(contenu, fichierIds) => envoyer(courante, fil, contenu, fichierIds)}
      onAnnuler={() => interrompre(courante, fil)}
    />
  );
}

function LigneErreur({ texte }: { texte: string | null }): ReactElement | null {
  if (texte === null) {
    return null;
  }
  return <p className="shrink-0 border-b border-border px-3 py-2 text-xs text-critical lg:px-6">{texte}</p>;
}

/*
 * L'envoi est signalé aux deux états. Le fil de branche affiche le chemin servi par le serveur : il
 * ignore l'optimisme local de `useConversation`, et sans ce signal le message parti resterait
 * invisible jusqu'à la fin de la génération.
 */
function envoyer(
  courante: EtatEcranChat['courante'],
  fil: EtatActionsFil,
  contenu: string,
  fichierIds: string[],
): void {
  fil.noterEnvoi(contenu);
  void courante.envoyer(contenu, fichierIds);
}

/* L'arrêt vise le tour réellement en cours ; chaque flux ignore la demande s'il n'a rien à couper. */
function interrompre(courante: EtatEcranChat['courante'], fil: EtatActionsFil): void {
  void courante.annuler();
  void fil.annuler();
}

/*
 * Le plan dit ce que le chargement a COÛTÉ ; le contexte dit ce que la conversation CONSOMME.
 * Les deux répondent à la même question — « pourquoi ça coince » — à deux instants différents,
 * d'où leur voisinage dans la même colonne.
 *
 * La conversion `contenu` -> `content` est nécessaire et non cosmétique : le domaine `chat`
 * persiste en français, le contrat des moteurs est en anglais. Compter les tokens exige la forme
 * qui repart réellement au modèle.
 */
function ColonnePlan({ etat, cible }: ColonneProps): ReactElement {
  const messagesMoteur = etat.courante.messages.map((message) => ({
    role: message.role,
    content: message.contenu,
  }));
  return (
    // Dans le tiroir, la largeur vient du panneau : une largeur fixe y déborderait à 390 px.
    <div className="flex w-full min-w-0 max-w-full flex-col gap-3 overflow-y-auto overflow-x-hidden p-3">
      <PanneauPlan
        cible={cible}
        etatPlan={etat.etatPlan}
        chargement={etat.chargement}
        debitObserve={etat.courante.debitObserve}
      />
      <PanneauContexte
        promptSysteme={etat.courante.detail?.reglages.prompt_systeme ?? ''}
        messages={messagesMoteur}
        modeleCharge={cible?.demande.metadonnees.identifiant ?? null}
        // Une génération en cours fait varier le décompte à chaque fragment : mesurer alors
        // coûterait une tokenisation par token reçu, sur le verrou du moteur qui génère.
        actif={!etat.courante.genere}
      />
    </div>
  );
}

/*
 * La colonne de droite n'a qu'un occupant à la fois : l'artefact ouvert, sinon le plan. L'aside
 * garde SA largeur dans les deux cas — un panneau qui redimensionne le fil à chaque ouverture
 * ferait sauter le texte qu'on est en train de lire ; « agrandir » existe pour le reste. Les
 * classes `lg:` sont inertes dans un tiroir : le même élément sert les deux mises en page.
 */
function ColonneDroite({ etat, cible, atelier }: ColonneProps & { atelier: EtatAtelier }): ReactElement {
  return (
    <aside
      className={cn(
        'flex h-full w-full min-w-0 max-w-full flex-col',
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
          />
        </div>
      ) : (
        <ColonnePlan etat={etat} cible={cible} />
      )}
    </aside>
  );
}

/* Le tiroir d'artefact n'existe que sous le seuil ; au-dessus, la colonne de droite l'affiche. */
function TiroirArtefact({ atelier, tiroirs }: { atelier: EtatAtelier; tiroirs: EtatTiroirsChat }): ReactElement | null {
  if (atelier.ouvert === null) {
    return null;
  }
  return (
    <Feuille
      ouverte={tiroirs.tiroir === 'artefact'}
      onFermer={tiroirs.fermer}
      cote="droite"
      titre="Artefact"
    >
      <div className="h-full min-h-0 p-3">
        <PanneauArtefact
          artefact={atelier.ouvert.artefact}
          version={atelier.ouvert.version}
          onChoisirVersion={atelier.choisirVersion}
          onFermer={() => {
            atelier.fermer();
            tiroirs.fermer();
          }}
        />
      </div>
    </Feuille>
  );
}

/*
 * Modale de sélection des outils. Une modale et non un volet des réglages : les réglages vivent
 * dans `chat/reglages/` (hors du périmètre de cette refonte), et la sélection d'outils est un
 * choix de CAPACITÉS qui mérite d'être atteignable en un geste depuis l'entête — voir le rapport
 * pour la fusion éventuelle des deux surfaces.
 */
function ModaleOutils({
  conversationId,
  ouvert,
  onFermer,
}: {
  conversationId: string | null;
  ouvert: boolean;
  onFermer: () => void;
}): ReactElement {
  const selection = useSelectionOutils(conversationId);
  return (
    <Modal open={ouvert} onClose={onFermer} title="Outils du modèle" size="md">
      <PanneauOutils
        catalogue={selection.catalogue}
        actifs={selection.actifs}
        persistee={selection.persistee}
        onBasculer={selection.basculer}
        onBasculerGroupe={selection.basculerGroupe}
      />
    </Modal>
  );
}

/*
 * Modale de réglages complète : prompt système, échantillonnage, plafond de réponse, séquences
 * d'arrêt. Elle remplace l'ancien panneau en lecture partielle — c'est elle qui adosse le plafond
 * de réponse aux mesures réelles de la conversation, ce que réclamait la troncature systématique
 * des réponses des modèles de raisonnement.
 */
function PanneauDeReglages({ etat }: { etat: EtatEcranChat }): ReactElement | null {
  const detail = etat.courante.detail;
  if (detail === null || etat.conversationActive === null) {
    return null;
  }
  return (
    <ModaleReglages
      ouvert={etat.reglagesOuverts}
      conversationId={etat.conversationActive}
      reglages={detail.reglages}
      messages={etat.courante.messages}
      onFermer={() => etat.ouvrirReglages(false)}
    />
  );
}

/*
 * Ouvrir ou créer une conversation change l'écran DERRIÈRE le voile : garder le tiroir ouvert
 * masquerait le résultat de l'action qu'on vient de déclencher. Au-dessus du seuil, `fermer` porte
 * sur un état déjà nul — le comportement de la colonne en flux est inchangé.
 */
function TiroirConversations({ etat, tiroirs }: { etat: EtatEcranChat; tiroirs: EtatTiroirsChat }): ReactElement {
  return (
    <Feuille
      ouverte={tiroirs.tiroir === 'conversations'}
      onFermer={tiroirs.fermer}
      cote="gauche"
      titre="Conversations"
    >
      <ListeConversations
        conversations={etat.liste.conversations}
        archivees={etat.liste.archivees}
        conversationActive={etat.conversationActive}
        erreur={etat.liste.erreur}
        onOuvrir={(id) => {
          etat.choisirConversation(id);
          tiroirs.fermer();
        }}
        onCreer={() => {
          etat.creerConversation();
          tiroirs.fermer();
        }}
        onSupprimer={etat.supprimerConversation}
        onRenommer={etat.renommerConversation}
        // L'archivage passe directement par l'état de liste : `useEcranChat` n'a pas à connaître
        // un geste qui ne change ni la conversation courante ni le moteur.
        onArchiver={(id, archivee) => void etat.liste.archiver(id, archivee)}
        onChargerArchivees={() => void etat.liste.chargerArchivees()}
      />
    </Feuille>
  );
}

/*
 * Deux tiroirs distincts à droite plutôt qu'un tiroir à contenu variable : le tiroir de plan
 * montre TOUJOURS le plan, celui d'artefact toujours l'artefact — fermer l'un ne fait pas surgir
 * l'autre. Au-dessus du seuil, la Feuille est un passe-plat et la colonne de droite arbitre seule
 * entre les deux occupants.
 */
function CoteDroit({
  etat,
  cible,
  atelier,
  tiroirs,
  grandEcran,
}: ColonneProps & { atelier: EtatAtelier; tiroirs: EtatTiroirsChat; grandEcran: boolean }): ReactElement {
  return (
    <>
      <Feuille
        ouverte={tiroirs.tiroir === 'plan'}
        onFermer={tiroirs.fermer}
        cote="droite"
        titre="Plan de chargement"
      >
        {grandEcran ? (
          <ColonneDroite etat={etat} cible={cible} atelier={atelier} />
        ) : (
          <ColonnePlan etat={etat} cible={cible} />
        )}
      </Feuille>
      {!grandEcran && <TiroirArtefact atelier={atelier} tiroirs={tiroirs} />}
    </>
  );
}

/* Panneau des fichiers du projet : colonne en flux sur grand écran, tiroir en dessous du seuil. */
function TiroirFichiers({ projet, onFermer }: { projet: string | null; onFermer: () => void }): ReactElement | null {
  if (projet === null) {
    return null;
  }
  return (
    <Feuille ouverte onFermer={onFermer} cote="droite" titre="Fichiers du projet">
      <PanneauFichiers key={projet} projet={projet} onFermer={onFermer} />
    </Feuille>
  );
}

export interface ChatEcranProps {
  /**
   * Modèle sélectionné et entrées mesurées du planificateur, fournis par les domaines `models` et
   * `system`. La référence doit être stable entre deux rendus : elle déclenche la replanification.
   */
  cible: CibleChargement | null;
}

/*
 * Câblage de l'atelier sur l'écran : mêmes messages que le fil, et ouverture qui déclenche le
 * tiroir sous le seuil — la carte cliquée doit MONTRER l'artefact, pas seulement changer un état.
 */
function useAtelierEcran(
  etat: EtatEcranChat,
  fil: EtatActionsFil,
  tiroirs: EtatTiroirsChat,
  grandEcran: boolean,
): { atelier: EtatAtelier; capacites: CapacitesAtelier } {
  // L'atelier lit le MÊME chemin que le fil : une version créée dans une branche abandonnée
  // n'existe pas ici, et une version tout juste fermée dans le brouillon est déjà ouvrable.
  const atelier = useAtelier(fil.messages ?? etat.courante.messages, fil.brouillon ?? etat.courante.brouillon);
  const ouvrirVersion = useCallback(
    (version: VersionArtefact): void => {
      atelier.ouvrir(version);
      if (!grandEcran) {
        tiroirs.ouvrir('artefact');
      }
    },
    [atelier, grandEcran, tiroirs],
  );
  const capacites = useMemo(
    () => ({ ouvrirVersion, artefactOuvert: atelier.ouvert?.artefact.artefact_id ?? null }),
    [ouvrirVersion, atelier.ouvert],
  );
  return { atelier, capacites };
}

export function ChatEcran({ cible }: ChatEcranProps): ReactElement {
  const etat = useEcranChat(cible);
  const [outilsOuverts, setOutilsOuverts] = useState<boolean>(false);
  const projet = useProjetEcran(etat.conversationActive);
  // `courante.genere` est passé au fil de branche : c'est le seul signal qui dit qu'un tour occupe
  // déjà le moteur, et sa fin est le moment où la feuille active a pu changer sans qu'on l'ait
  // demandé — donc le moment où la vue de branche doit être relue.
  const fil = useActionsFil(etat.conversationActive, etat.courante.genere);
  const tiroirs = useTiroirsChat();
  const grandEcran = useEstGrandEcran();
  const { atelier, capacites } = useAtelierEcran(etat, fil, tiroirs, grandEcran);
  return (
    <div className="flex h-full min-h-0 overflow-x-hidden bg-bg">
      <TiroirConversations etat={etat} tiroirs={tiroirs} />
      <ColonneEchange
        etat={etat}
        cible={cible}
        fil={fil}
        tiroirs={tiroirs}
        capacites={capacites}
        onOutils={() => setOutilsOuverts(true)}
        actionsProjet={projet.actions}
      />
      <TiroirFichiers projet={projet.projetPanneau} onFermer={projet.fermerPanneau} />
      <CoteDroit etat={etat} cible={cible} atelier={atelier} tiroirs={tiroirs} grandEcran={grandEcran} />
      <ModaleOutils
        conversationId={etat.conversationActive}
        ouvert={outilsOuverts}
        onFermer={() => setOutilsOuverts(false)}
      />
      <ModaleProjet etat={projet.liaison} ouvert={projet.modaleOuverte} onFermer={projet.fermerModale} />
      <PanneauDeReglages etat={etat} />
    </div>
  );
}
