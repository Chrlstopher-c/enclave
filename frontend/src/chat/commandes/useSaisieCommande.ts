/*
 * Ce que la saisie fait d'un « / » : palette, clavier, et décision à l'envoi.
 *
 * Clavier quand la palette est ouverte (référence Claude Code, Linear) : ↑↓ choisissent, Tab
 * complète, Entrée complète — ou exécute si la saisie est déjà exactement la commande choisie —,
 * Échap ferme jusqu'à la prochaine frappe. Le composeur ne garde que l'envoi d'un message.
 */

import { useCallback, useEffect, useState } from 'react';
import type { KeyboardEvent } from 'react';
import { analyserSaisie, completion, estComplete, filtrerCommandes, nomEnFrappe, refusArguments } from './analyse';
import type { AnalyseSaisie } from './analyse';
import type { DefinitionCommande } from './contrats';
import { commandeEnCours, useEtatCommandes, type CommandeRecue } from './magasin';
import { useCatalogue, useExecution, type EtatCatalogue } from './useCommandes';

export interface EtatPalette {
  choix: readonly DefinitionCommande[];
  index: number;
  etat: EtatCatalogue;
  recharger: () => void;
}

/** `message` : la saisie part comme un message ordinaire, avec ce contenu (« //x » devient « /x »). */
export type Decision = { type: 'traite' } | { type: 'message'; contenu: string };

export interface SaisieCommande {
  analyse: AnalyseSaisie;
  /** Tant que le catalogue n'est pas lu, une commande ne peut pas être jugée inconnue. */
  catalogue: EtatCatalogue;
  palette: EtatPalette | null;
  /** Commande longue en cours sur cette conversation : l'envoi attend sa fin. */
  enCours: CommandeRecue | null;
  envoi: boolean;
  erreur: string | null;
  intercepter: (evenement: KeyboardEvent<HTMLTextAreaElement>) => boolean;
  choisir: (definition: DefinitionCommande) => void;
  survoler: (index: number) => void;
  soumettre: (texte: string) => Decision;
}

interface EntreesSaisie {
  texte: string;
  setTexte: (texte: string) => void;
  conversationId: string | null;
  genere: boolean;
}

function usePalette(texte: string): { palette: EtatPalette | null; fermer: () => void; setIndex: (i: number) => void;
  commandes: readonly DefinitionCommande[]; etat: EtatCatalogue } {
  const catalogue = useCatalogue();
  const [fermeePour, setFermeePour] = useState<string | null>(null);
  const [index, setIndex] = useState<number>(0);
  const prefixe = nomEnFrappe(texte);
  useEffect((): void => setIndex(0), [prefixe]);
  const choix = prefixe === null ? [] : filtrerCommandes(catalogue.commandes, prefixe);
  // Aucune correspondance une fois le catalogue lu : pas de liste vide, l'indication prend le relais.
  const visible = prefixe !== null && fermeePour !== texte && (choix.length > 0 || catalogue.etat !== 'pret');
  const palette = visible
    ? { choix, index: Math.min(index, Math.max(0, choix.length - 1)), etat: catalogue.etat,
      recharger: catalogue.recharger }
    : null;
  const fermer = (): void => setFermeePour(texte);
  return { palette, fermer, setIndex, commandes: catalogue.commandes, etat: catalogue.etat };
}

function deplacer(palette: EtatPalette, sens: number): number {
  const total = palette.choix.length;
  return total === 0 ? 0 : (palette.index + sens + total) % total;
}

function useIntercepteur(
  texte: string,
  palette: EtatPalette | null,
  choisir: (definition: DefinitionCommande) => void,
  outils: { fermer: () => void; setIndex: (i: number) => void },
): (evenement: KeyboardEvent<HTMLTextAreaElement>) => boolean {
  return (evenement): boolean => {
    if (palette === null) {
      return false;
    }
    const choisie = palette.choix[palette.index];
    const touche = evenement.key;
    if (touche === 'Escape') {
      outils.fermer();
    } else if ((touche === 'ArrowDown' || touche === 'ArrowUp') && palette.choix.length > 0) {
      outils.setIndex(deplacer(palette, touche === 'ArrowDown' ? 1 : -1));
    } else if ((touche === 'Tab' || touche === 'Enter') && !evenement.shiftKey && choisie !== undefined) {
      if (touche === 'Enter' && estComplete(texte, choisie)) {
        return false;
      }
      choisir(choisie);
    } else {
      return false;
    }
    evenement.preventDefault();
    return true;
  };
}

interface Lancement {
  envoi: boolean;
  erreur: string | null;
  setErreur: (erreur: string | null) => void;
  lancer: (nom: string, args: string) => void;
}

/* Le texte n'est vidé qu'une fois la commande ACCEPTÉE : un refus laisse la saisie à corriger. */
function useLancement(conversationId: string | null, texte: string, setTexte: (texte: string) => void): Lancement {
  const executer = useExecution(conversationId);
  const [envoi, setEnvoi] = useState<boolean>(false);
  const [erreur, setErreur] = useState<string | null>(null);
  useEffect((): void => setErreur(null), [texte, conversationId]);
  const lancer = useCallback(
    (nom: string, args: string): void => {
      setEnvoi(true);
      void executer(nom, args).then((echec): void => {
        setEnvoi(false);
        if (echec === null) {
          setTexte('');
        } else {
          setErreur(echec);
        }
      });
    },
    [executer, setTexte],
  );
  return { envoi, erreur, setErreur, lancer };
}

const CATALOGUE_ABSENT = 'Liste des commandes pas encore lue : réessayez (« // » envoie le texte tel quel).';

interface Contexte {
  genere: boolean;
  /** Ni envoi en vol ni commande longue en cours. */
  libre: boolean;
  cataloguePret: boolean;
}

function decider(analyse: AnalyseSaisie, contenu: string, contexte: Contexte, lancement: Lancement): Decision {
  if (analyse.type === 'litteral') {
    return { type: 'message', contenu: analyse.contenu.trim() };
  }
  if (analyse.type !== 'commande' || (analyse.definition === null && contexte.cataloguePret)) {
    return { type: 'message', contenu };
  }
  // Avant la lecture du catalogue, « inconnue » n'est pas établi : on retient plutôt que d'envoyer.
  const refus = analyse.definition === null
    ? CATALOGUE_ABSENT
    : contexte.genere ? 'Les commandes attendent la fin de la réponse en cours.' : refusArguments(analyse);
  if (refus !== null) {
    lancement.setErreur(refus);
  } else if (analyse.definition !== null && contexte.libre) {
    lancement.lancer(analyse.definition.nom, analyse.arguments);
  }
  return { type: 'traite' };
}

export function useSaisieCommande({ texte, setTexte, conversationId, genere }: EntreesSaisie): SaisieCommande {
  const { palette, fermer, setIndex, commandes, etat: catalogue } = usePalette(texte);
  const etat = useEtatCommandes(conversationId);
  const lancement = useLancement(conversationId, texte, setTexte);
  const { envoi, erreur } = lancement;
  const analyse = analyserSaisie(texte, commandes);
  const choisir = useCallback((definition: DefinitionCommande): void => setTexte(completion(definition)), [setTexte]);
  const contexte = { genere, libre: !envoi && !commandeEnCours(etat), cataloguePret: catalogue === 'pret' };
  return {
    analyse, catalogue, palette, envoi, erreur,
    enCours: commandeEnCours(etat) ? etat.commande : null,
    intercepter: useIntercepteur(texte, palette, choisir, { fermer, setIndex }),
    choisir,
    survoler: setIndex,
    soumettre: (contenu) => decider(analyse, contenu, contexte, lancement),
  };
}
