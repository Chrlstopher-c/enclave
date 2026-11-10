/*
 * Mesure de l'occupation du contexte, rafraîchie au rythme de la conversation.
 *
 * Deux garanties tenues ici, pas ailleurs :
 *
 * 1. **Anti-rebond, pas un appel par token.** Pendant un flux, l'entrée change à chaque fragment
 *    reçu ; le minuteur est relancé à chaque fois et la requête ne part qu'une fois le flux calmé.
 *    La mesure ne bouge de toute façon qu'à la fin du message.
 * 2. **Rien ne survit au démontage.** Le minuteur est nettoyé par l'effet, et le contrôleur
 *    d'annulation est avorté séparément — il vit plus longtemps que l'effet qui l'a créé, un
 *    nettoyage rangé dans le seul effet de dépendance le laisserait courir.
 */

import { useEffect, useRef, useState } from 'react';
import type { MessageMoteur, OccupationContexte } from '../../shared/api';
// `shared/api/index.ts` réexporte déjà les TYPES de ce domaine, mais pas encore cette fonction.
// Import direct assumé le temps que la ligne d'export y soit ajoutée (cf. rapport de livraison).
import { mesurerOccupationContexte } from '../../shared/api/inference';
import { getJson } from '../api/client';

/*
 * Assez long pour absorber un flux de tokens sans jamais laisser passer une requête, assez court
 * pour que le chiffre suive la fin d'un message sans attente perceptible.
 */
const DELAI_ANTI_REBOND_MS = 500;

export interface EntreeOccupation {
  /**
   * Conversation affichée : la mesure porte alors sur ce que la génération enverrait VRAIMENT (socle,
   * outils, historique budgété, compaction) — l'ancienne mesure ne voyait ni le socle ni les outils.
   */
  readonly conversationId?: string | null;
  readonly promptSysteme: string;
  readonly messages: readonly MessageMoteur[];
  /** Modèle chargé : sa bascule relance la mesure, la fenêtre servie changeant avec lui. */
  readonly modeleCharge: string | null;
  /** Faux quand le panneau n'est pas affiché : aucune requête n'est alors émise. */
  readonly actif: boolean;
}

export interface EtatOccupation {
  readonly occupation: OccupationContexte | null;
  /** Une mesure est demandée mais pas encore rendue : le chiffre affiché date d'avant. */
  readonly enAttente: boolean;
  readonly erreur: string | null;
}

/**
 * Empreinte de ce qui change le décompte, réduite à des primitives : l'effet ne dépend pas de
 * l'identité du tableau de messages, qu'un parent non mémoïsé renouvellerait à chaque rendu.
 *
 * Limite assumée : une retouche qui conserverait la longueur exacte de chaque message ne
 * relancerait pas la mesure. Dans cet écran les messages ne sont qu'ajoutés ou allongés pendant
 * un flux, jamais réécrits à longueur constante.
 */
function empreinte(entree: EntreeOccupation): string {
  const messages = entree.messages.map((message) => `${message.role}:${message.content.length}`);
  const tete = `${entree.conversationId ?? ''}#${entree.modeleCharge ?? ''}#${entree.promptSysteme.length}`;
  return `${tete}#${messages.join('|')}`;
}

function messageDe(cause: unknown): string {
  return cause instanceof Error ? cause.message : String(cause);
}

export function useOccupationContexte(entree: EntreeOccupation): EtatOccupation {
  const [occupation, setOccupation] = useState<OccupationContexte | null>(null);
  const [enAttente, setEnAttente] = useState<boolean>(false);
  const [erreur, setErreur] = useState<string | null>(null);
  const controleur = useRef<AbortController | null>(null);
  const derniere = useRef<EntreeOccupation>(entree);

  // L'entrée courante est lue à l'échéance du minuteur, pas à sa pose : la requête porte donc
  // toujours l'état le plus récent, sans que l'effet ait à dépendre de l'objet lui-même.
  useEffect((): void => {
    derniere.current = entree;
  });

  const cle = entree.actif ? empreinte(entree) : null;

  useEffect((): (() => void) | undefined => {
    if (cle === null) {
      return undefined;
    }
    setEnAttente(true);
    const attente = window.setTimeout((): void => {
      controleur.current?.abort();
      const controle = new AbortController();
      controleur.current = controle;
      const { promptSysteme, messages, conversationId } = derniere.current;
      const mesure =
        conversationId !== null && conversationId !== undefined
          ? getJson<OccupationContexte>(`/chat/conversations/${conversationId}/contexte`, controle.signal)
          : mesurerOccupationContexte({ prompt_systeme: promptSysteme, messages }, controle.signal);
      // Promesse volontairement non attendue : le hook n'est pas asynchrone, l'issue passe par
      // l'état React. Le rejet est traité dans `catch`, il n'y a pas d'échec silencieux.
      void mesure
        .then((resultat): void => {
          if (controle.signal.aborted) {
            return;
          }
          setOccupation(resultat);
          setErreur(null);
        })
        .catch((cause: unknown): void => {
          if (controle.signal.aborted) {
            return;
          }
          setErreur(messageDe(cause));
        })
        .finally((): void => {
          if (!controle.signal.aborted) {
            setEnAttente(false);
          }
        });
    }, DELAI_ANTI_REBOND_MS);
    return (): void => window.clearTimeout(attente);
  }, [cle]);

  // Démontage : le contrôleur survit à l'effet qui l'a posé, il s'avorte donc à part.
  useEffect((): (() => void) => (): void => controleur.current?.abort(), []);

  return { occupation, enAttente, erreur };
}
