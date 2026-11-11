import { useCallback, useEffect, useRef, useState } from 'react';
import type {
  ChangeEvent,
  ClipboardEvent,
  DragEvent,
  KeyboardEvent,
  ReactElement,
  RefObject,
} from 'react';
import { AnimatePresence } from 'framer-motion';
import { Button } from '../../shared/design';
import type { FichierConversation } from '../api/contrats';
import { IndicationCommande, PaletteCommandes, useSaisieCommande, type SaisieCommande } from '../commandes';
import {
  BoutonPiece,
  EntreesFichier,
  IconeAppareilPhoto,
  IconeTrombone,
  RangeePieces,
  useDepotPieces,
  type PieceComposeur,
} from './pieces-jointes';
import { FileEnAttente } from './FileEnAttente';
import type { MessageEnAttente } from './useMessagesEnAttente';

/*
 * Saisie du message. Entrée envoie, Maj+Entrée passe à la ligne — la convention des interfaces de
 * chat, et la seule qui ne surprenne personne.
 *
 * Pendant une génération, le bouton devient « Arrêter » plutôt que de disparaître : l'annulation
 * doit être atteignable là où le regard est déjà, sans chercher un contrôle ailleurs dans l'écran.
 *
 * PIÈCES JOINTES — règle de l'opérateur (plan d'exécution, 2.4) : le composeur accepte une image
 * (collage, glisser-déposer, sélection) ou un fichier quelconque QUEL QUE SOIT le modèle chargé, y
 * compris si aucun n'est chargé. Il ne bloque jamais l'envoi et n'affiche jamais de message du type
 * « ce modèle ne prend pas en charge les images » — c'est au modèle chargé de répondre, avec ses
 * mots, s'il ne voit rien. Chaque pièce est déposée dans le magasin dès qu'elle est choisie ; seul
 * son identifiant part avec le message.
 *
 * AU DOIGT : le collage et le glisser-déposer n'existent pas sur un téléphone. Deux déclencheurs
 * explicites les remplacent — « Joindre un fichier » (sélecteur), et « Prendre une photo »
 * (`capture` sur une entrée image, donc l'appareil photo directement). Le second n'est proposé que
 * sous 1024 px, où il a un sens. Aucun des deux ne juge le modèle chargé : la règle de l'opérateur
 * tient, l'application transmet toujours et ne refuse jamais d'elle-même.
 *
 * COMMANDES — un « / » en tête de saisie ouvre la palette (`chat/commandes`) ; une commande
 * reconnue part par sa propre route au lieu d'un message, et pendant une commande longue
 * (`/compact`) l'envoi attend sa fin : la saisie reste ouverte pour préparer la suite.
 */

const HAUTEUR_MAX_PX = 200;
const PLACEHOLDER_GLISSER = 'Ajouter une consigne — lue à la fin de l’étape en cours…';
const PLACEHOLDER_COMMANDE = 'Compaction en cours… vous pourrez envoyer à sa fin.';
const PLACEHOLDER = 'Écrire un message, ou / pour les commandes…';

/*
 * Sous le seuil, la rangée passe à DEUX lignes : la saisie occupe la sienne, les boutons suivent.
 * Sur une seule ligne à 375 px, les trois boutons consommaient 156 px des 351 disponibles et ne
 * laissaient que 165 px pour écrire — mesuré le 2026-08-15, soit une vingtaine de caractères
 * visibles. Au-dessus du seuil, `lg:flex-nowrap` restaure la rangée unique.
 */
const CLASSE_CADRE =
  'flex flex-wrap items-end gap-1 rounded-md border border-border bg-surface px-2 py-1.5 ' +
  'focus-within:border-border-strong lg:flex-nowrap lg:gap-2 lg:px-3 lg:py-2';

/* `py-2.5` au doigt : la zone de saisie elle-même doit faire 44 px de haut à une ligne.
   `order-first basis-full` la place seule sur la première ligne tant qu'on est sous le seuil. */
const CLASSE_ZONE_SAISIE =
  'order-first w-full min-w-0 basis-full resize-none bg-transparent py-2.5 text-sm text-text ' +
  'outline-none placeholder:text-text-3 lg:order-none lg:w-auto lg:flex-1 lg:basis-auto lg:py-0';

function useHauteurAuto(valeur: string): RefObject<HTMLTextAreaElement> {
  const zone = useRef<HTMLTextAreaElement>(null);
  useEffect((): void => {
    const element = zone.current;
    if (element === null) {
      return;
    }
    // Remise à zéro avant mesure : sans elle, `scrollHeight` ne redescend jamais.
    element.style.height = 'auto';
    element.style.height = `${Math.min(element.scrollHeight, HAUTEUR_MAX_PX)}px`;
  }, [valeur]);
  return zone;
}

interface BarreSaisieProps {
  texte: string;
  genere: boolean;
  desactive: boolean;
  zone: RefObject<HTMLTextAreaElement>;
  onTexte: (evenement: ChangeEvent<HTMLTextAreaElement>) => void;
  onTouche: (evenement: KeyboardEvent<HTMLTextAreaElement>) => void;
  onColle: (evenement: ClipboardEvent<HTMLTextAreaElement>) => void;
  onEnvoyer: () => void;
  onAnnuler: () => void;
  /** Pendant une génération, l'envoi glisse le message à l'agent au lieu d'attendre. */
  peutGlisser: boolean;
  onChoisirFichier: () => void;
  onPrendrePhoto: () => void;
  saisie: SaisieCommande;
}

function BoutonEnvoi({
  genere,
  envoyable,
  peutGlisser,
  libelle,
  onEnvoyer,
  onAnnuler,
}: {
  genere: boolean;
  envoyable: boolean;
  peutGlisser: boolean;
  libelle: string;
  onEnvoyer: () => void;
  onAnnuler: () => void;
}): ReactElement {
  if (genere) {
    return (
      <>
        {peutGlisser && envoyable && (
          <Button variant="primary" size="sm" onClick={onEnvoyer} title="Lu par l'agent à la fin de son étape en cours">
            Glisser
          </Button>
        )}
        <Button variant="secondary" size="sm" onClick={onAnnuler}>
          Arrêter
        </Button>
      </>
    );
  }
  return (
    <Button variant="primary" size="sm" onClick={onEnvoyer} disabled={!envoyable}>
      {libelle}
    </Button>
  );
}

function BoutonsPieces({
  desactive,
  onChoisirFichier,
  onPrendrePhoto,
}: Pick<BarreSaisieProps, 'desactive' | 'onChoisirFichier' | 'onPrendrePhoto'>): ReactElement {
  return (
    <>
      <BoutonPiece libelle="Joindre un fichier" desactive={desactive} onClic={onChoisirFichier}>
        <IconeTrombone />
      </BoutonPiece>
      <BoutonPiece libelle="Prendre une photo" desactive={desactive} onClic={onPrendrePhoto} className="lg:hidden">
        <IconeAppareilPhoto />
      </BoutonPiece>
      {/* Pousse l'envoi à droite quand la rangée est repliée sur deux lignes ; sans effet une
          fois `lg:flex-nowrap` actif, où la zone de saisie occupe déjà tout l'espace libre. */}
      <span className="flex-1 lg:hidden" aria-hidden="true" />
    </>
  );
}

function placeholder(genere: boolean, peutGlisser: boolean, commandeEnCours: boolean): string {
  if (commandeEnCours) {
    return PLACEHOLDER_COMMANDE;
  }
  return genere && peutGlisser ? PLACEHOLDER_GLISSER : PLACEHOLDER;
}

/* Une commande reconnue s'EXÉCUTE : le bouton le dit, comme le badge au-dessus de la saisie. */
function libelleEnvoi(saisie: SaisieCommande): string {
  return saisie.analyse.type === 'commande' && saisie.analyse.definition !== null ? 'Exécuter' : 'Envoyer';
}

function Palette({ saisie }: { saisie: SaisieCommande }): ReactElement {
  return (
    <AnimatePresence>
      {saisie.palette !== null && (
        <PaletteCommandes palette={saisie.palette} onChoisir={saisie.choisir} onSurvol={saisie.survoler} />
      )}
    </AnimatePresence>
  );
}

function BarreSaisie(props: BarreSaisieProps): ReactElement {
  const { texte, genere, desactive, zone, onTexte, onTouche, onColle, saisie } = props;
  const occupe = saisie.enCours !== null || saisie.envoi;
  return (
    <div className="relative">
      <Palette saisie={saisie} />
      <div className={CLASSE_CADRE}>
        <BoutonsPieces
          desactive={desactive}
          onChoisirFichier={props.onChoisirFichier}
          onPrendrePhoto={props.onPrendrePhoto}
        />
        <textarea
          ref={zone}
          rows={1}
          value={texte}
          disabled={desactive}
          onChange={onTexte}
          onKeyDown={onTouche}
          onPaste={onColle}
          placeholder={placeholder(genere, props.peutGlisser, saisie.enCours !== null)}
          className={CLASSE_ZONE_SAISIE}
        />
        <BoutonEnvoi
          genere={genere}
          peutGlisser={props.peutGlisser}
          envoyable={!desactive && !occupe && texte.trim() !== ''}
          libelle={libelleEnvoi(saisie)}
          onEnvoyer={props.onEnvoyer}
          onAnnuler={props.onAnnuler}
        />
      </div>
    </div>
  );
}

export interface ComposeurProps {
  genere: boolean;
  desactive: boolean;
  /** Raison de l'indisponibilité, affichée sous la zone de saisie. Vide quand tout est prêt. */
  empechement: string;
  /** Conversation courante — nécessaire pour déposer une pièce jointe dans le bon dossier. */
  conversationId: string | null;
  onEnvoyer: (contenu: string, fichierIds: string[]) => void;
  onAnnuler: () => void;
  /** Message écrit pendant une génération : lu par l'agent à la fin de son étape en cours. */
  onGlisser?: (texte: string) => void;
  /** Messages glissés pas encore lus par l'agent. */
  enAttente?: readonly MessageEnAttente[];
}

interface GestesComposeur {
  envoyer: () => void;
  surTouche: (evenement: KeyboardEvent<HTMLTextAreaElement>) => void;
  surCollage: (evenement: ClipboardEvent<HTMLTextAreaElement>) => void;
  surDepot: (evenement: DragEvent<HTMLDivElement>) => void;
  surSelectionFichier: (evenement: ChangeEvent<HTMLInputElement>) => void;
}

interface EntreesGestes {
  texte: string;
  genere: boolean;
  desactive: boolean;
  pieces: PieceComposeur[];
  onEnvoyer: (contenu: string, fichierIds: string[]) => void;
  onGlisser: ((texte: string) => void) | undefined;
  setTexte: (texte: string) => void;
  deposer: (fichiers: File[]) => void;
  vider: () => void;
  saisie: SaisieCommande;
}

type Deposer = (fichiers: File[]) => void;

function collerFichiers(deposer: Deposer, evenement: ClipboardEvent<HTMLTextAreaElement>): void {
  const fichiers = Array.from(evenement.clipboardData?.files ?? []);
  if (fichiers.length === 0) {
    return;
  }
  evenement.preventDefault();
  deposer(fichiers);
}

function deposerGlisse(deposer: Deposer, evenement: DragEvent<HTMLDivElement>): void {
  evenement.preventDefault();
  deposer(Array.from(evenement.dataTransfer.files));
}

function choisirFichiers(deposer: Deposer, evenement: ChangeEvent<HTMLInputElement>): void {
  deposer(Array.from(evenement.target.files ?? []));
  evenement.target.value = '';
}

function envoyerTouche(
  saisie: SaisieCommande,
  envoyer: () => void,
  evenement: KeyboardEvent<HTMLTextAreaElement>,
): void {
  if (saisie.intercepter(evenement)) {
    return;
  }
  if (evenement.key === 'Enter' && !evenement.shiftKey) {
    evenement.preventDefault();
    envoyer();
  }
}

/*
 * Ce qui part comme MESSAGE, ou `null` : saisie vide, commande en cours, ou commande reconnue —
 * celle-ci part par sa propre route. « //texte » revient ramené à « /texte ».
 */
function contenuAEnvoyer(texte: string, desactive: boolean, saisie: SaisieCommande): string | null {
  if (texte.trim() === '' || desactive || saisie.enCours !== null) {
    return null;
  }
  const decision = saisie.soumettre(texte.trim());
  return decision.type === 'message' && decision.contenu !== '' ? decision.contenu : null;
}

/* Les gestes du composeur, sortis du composant : chacun tient en quelques lignes et se lit seul. */
function useGestesComposeur(entrees: EntreesGestes): GestesComposeur {
  const { texte, genere, desactive, pieces, onEnvoyer, onGlisser, setTexte, deposer, vider, saisie } = entrees;
  const envoyer = useCallback((): void => {
    const contenu = contenuAEnvoyer(texte, desactive, saisie);
    if (contenu === null || (genere && onGlisser === undefined)) {
      return;
    }
    if (genere && onGlisser !== undefined) {
      onGlisser(contenu);
      setTexte('');
      return;
    }
    // Les pièces encore en cours de dépôt sont exclues plutôt que d'attendre : le texte part sans
    // délai, et une pièce arrivée trop tard reste simplement une pièce que ce message n'aura pas.
    const fichierIds = pieces.filter((p) => p.fichier !== null).map((p) => (p.fichier as FichierConversation).id);
    onEnvoyer(contenu, fichierIds);
    setTexte('');
    vider();
  }, [texte, genere, desactive, pieces, onEnvoyer, onGlisser, setTexte, vider, saisie]);

  return {
    envoyer,
    surTouche: (evenement) => envoyerTouche(saisie, envoyer, evenement),
    surCollage: (evenement) => collerFichiers(deposer, evenement),
    surDepot: (evenement) => deposerGlisse(deposer, evenement),
    surSelectionFichier: (evenement) => choisirFichiers(deposer, evenement),
  };
}

interface CorpsComposeurProps {
  texte: string;
  setTexte: (texte: string) => void;
  genere: boolean;
  desactive: boolean;
  zone: RefObject<HTMLTextAreaElement>;
  pieces: PieceComposeur[];
  retirer: (cle: string) => void;
  gestes: GestesComposeur;
  onAnnuler: () => void;
  peutGlisser: boolean;
  saisie: SaisieCommande;
}

function CorpsComposeur(props: CorpsComposeurProps): ReactElement {
  const { texte, genere, desactive, zone, gestes } = props;
  // Les entrées de fichier n'existent que pour ce corps : leurs refs vivent ici, pas au-dessus.
  const entreeFichier = useRef<HTMLInputElement>(null);
  const entreePhoto = useRef<HTMLInputElement>(null);
  return (
    <div className="mx-auto max-w-3xl">
      <EntreesFichier fichier={entreeFichier} photo={entreePhoto} onChoisir={gestes.surSelectionFichier} />
      <RangeePieces pieces={props.pieces} onRetirer={props.retirer} />
      <IndicationCommande saisie={props.saisie} />
      <BarreSaisie
        texte={texte}
        genere={genere}
        desactive={desactive}
        zone={zone}
        onTexte={(evenement) => props.setTexte(evenement.target.value)}
        onTouche={gestes.surTouche}
        onColle={gestes.surCollage}
        onEnvoyer={gestes.envoyer}
        onAnnuler={props.onAnnuler}
        peutGlisser={props.peutGlisser}
        onChoisirFichier={() => entreeFichier.current?.click()}
        onPrendrePhoto={() => entreePhoto.current?.click()}
        saisie={props.saisie}
      />
    </div>
  );
}

export function Composeur(props: ComposeurProps): ReactElement {
  const { genere, desactive, conversationId, onEnvoyer, onGlisser } = props;
  const [texte, setTexte] = useState<string>('');
  const zone = useHauteurAuto(texte);
  const [pieces, deposer, retirer, vider] = useDepotPieces(conversationId);
  const saisie = useSaisieCommande({ texte, setTexte, conversationId, genere });
  const gestes = useGestesComposeur({
    texte, genere, desactive, pieces, onEnvoyer, onGlisser, setTexte, deposer, vider, saisie,
  });
  return (
    <div
      className="eh-marge-sure-bas shrink-0 border-t border-border px-3 py-3 lg:px-6 lg:py-4"
      onDragOver={(evenement) => evenement.preventDefault()}
      onDrop={gestes.surDepot}
    >
      <FileEnAttente messages={props.enAttente ?? []} />
      <CorpsComposeur
        peutGlisser={onGlisser !== undefined}
        texte={texte}
        setTexte={setTexte}
        genere={genere}
        desactive={desactive}
        zone={zone}
        pieces={pieces}
        retirer={retirer}
        gestes={gestes}
        onAnnuler={props.onAnnuler}
        saisie={saisie}
      />
      <Empechement
        texte={saisie.enCours !== null ? 'Compaction en cours : l’envoi reprend dès sa fin.' : props.empechement}
      />
    </div>
  );
}

function Empechement({ texte }: { texte: string }): ReactElement | null {
  if (texte === '') {
    return null;
  }
  return <p className="mx-auto mt-1.5 max-w-3xl text-2xs text-text-3">{texte}</p>;
}
