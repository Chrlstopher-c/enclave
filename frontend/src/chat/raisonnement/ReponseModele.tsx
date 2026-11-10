/*
 * Une réponse de modèle telle qu'elle doit se lire : le travail intermédiaire d'abord — replié ou
 * en carte —, puis la réponse rendue en Markdown.
 *
 * C'est ici que chaque segment reçoit sa forme, et UNIQUEMENT ici — une seule table de routage
 * pour un même balisage, sinon deux détections finissent par produire deux affichages :
 *   - segment `outil` : artefact créé → carte d'atelier ; fichier présenté → carte cliquable ;
 *     sinon carte d'outil lisible d'un coup d'œil (`CarteOutil`) ;
 *   - segment `outil` illisible (balisage inattendu) : bloc replié générique, jamais du vide ;
 *   - raisonnement, note de travail, appel brut du modèle : bloc replié discret.
 *
 * Le cas « rien hors du raisonnement » est nommé au lieu d'être laissé vide. Il arrive pour de bon
 * sur les modèles de raisonnement dont le budget s'épuise avant la réponse ; un message blanc
 * laisserait croire à une panne d'affichage.
 */

import { useMemo } from 'react';
import type { ReactElement } from 'react';
import { CarteArtefact, CarteVersionArtefact, artefactDepuisSegment, versionDepuisSegment } from '../artefacts';
import { RenduMarkdown } from '../markdown';
import { BlocRaisonnement } from './BlocRaisonnement';
import { CarteOutil } from './CarteOutil';
import { lireAppel } from './lecture-appel';
import { segmenterReponse, type ReponseSegmentee, type SegmentRaisonnement } from './extraction';

interface SansReponseProps {
  segmentee: ReponseSegmentee;
  actif: boolean;
}

function SansReponse({ segmentee, actif }: SansReponseProps): ReactElement | null {
  // Pendant la génération, « pas encore de réponse » n'est pas une information : le bloc de
  // raisonnement affiche déjà son activité.
  if (actif || segmentee.raisonnements.length === 0) {
    return null;
  }
  const dernier = segmentee.raisonnements[segmentee.raisonnements.length - 1];
  const coupe = dernier !== undefined && !dernier.complet;
  return (
    <p className="text-xs text-caution">
      {coupe
        ? "La génération s'est arrêtée en plein raisonnement : aucune réponse n'a été écrite."
        : "Le modèle n'a rien écrit en dehors de son raisonnement."}
    </p>
  );
}

interface SegmentProps {
  segment: SegmentRaisonnement;
  rang: number | null;
  actif: boolean;
  /** `true` dès qu'un outil a été appelé plus haut dans la réponse. Voir `SegmentRendu`. */
  apresOutil: boolean;
}

/*
 * Commentaire intermédiaire : ce que le modèle écrit ENTRE deux actions.
 *
 * Rendu en clair, sans surface ni chevron, parce que ce n'est pas du raisonnement à replier — c'est
 * le fil de la réponse. « J'ai les résultats, je synthétise », « la recherche a échoué, je change
 * d'approche » : le lecteur a besoin de le voir pour suivre, exactement comme il suit un
 * collaborateur qui commente ce qu'il fait.
 *
 * La distinction est POSITIONNELLE et non textuelle : le premier bloc, avant tout appel, est une
 * délibération privée — le modèle pèse sa décision, et cela se replie. Ceux qui suivent un appel
 * commentent un travail en cours, et cela se lit.
 */
function CommentaireIntermediaire({ texte }: { texte: string }): ReactElement | null {
  const propre = texte.trim();
  if (propre === '') {
    return null;
  }
  return (
    <div className="min-w-0 border-l-2 border-border pl-3 text-text-2">
      <RenduMarkdown source={propre} />
    </div>
  );
}

/** Message glissé par l'utilisateur pendant le travail, montré là où l'agent l'a lu. */
function ConsigneGlissee({ texte }: { texte: string }): ReactElement {
  const message = texte.replace(/^id:[\w-]+\n/, '');
  return (
    <div className="ml-auto max-w-[92%] rounded-md bg-surface-2 px-3.5 py-2.5 lg:max-w-[80%]">
      <p className="mb-1 text-2xs text-text-3">Ton message, lu pendant le travail</p>
      <p className="whitespace-pre-wrap break-words text-sm leading-relaxed text-text">{message}</p>
    </div>
  );
}

function SegmentRendu({ segment, rang, actif, apresOutil }: SegmentProps): ReactElement | null {
  // L'appel émis par le modèle n'est plus montré : il n'apprend rien au lecteur, qui voit déjà
  // l'outil et son résultat juste après. Il doublait chaque action d'une ligne « Appel du modèle »
  // sans contenu utile — et sur un tour à quatre outils, cela faisait huit blocs pour quatre gestes.
  // Le texte reste dans le message enregistré : c'est l'AFFICHAGE qui change, pas la trace.
  if (segment.convention === 'appel') {
    return null;
  }
  if (segment.convention === 'consigne') {
    return <ConsigneGlissee texte={segment.texte} />;
  }
  if (apresOutil && segment.convention !== 'outil') {
    return <CommentaireIntermediaire texte={segment.texte} />;
  }
  if (segment.convention === 'outil') {
    // L'ordre compte : la forme la plus spécifique d'abord. Un artefact créé porte aussi la forme
    // d'un appel réussi — le tester après `lireAppel` le ferait retomber en carte générique.
    const versionCreee = versionDepuisSegment(segment);
    if (versionCreee !== null) {
      return <CarteVersionArtefact version={versionCreee} />;
    }
    const artefact = artefactDepuisSegment(segment);
    if (artefact !== null) {
      return <CarteArtefact artefact={artefact} />;
    }
    const appel = lireAppel(segment.texte, actif && !segment.complet);
    if (appel !== null) {
      return <CarteOutil appel={appel} />;
    }
  }
  return <BlocRaisonnement segment={segment} rang={rang} actif={actif && !segment.complet} />;
}

export interface ReponseModeleProps {
  source: string;
  /**
   * `true` pendant le streaming. Sert uniquement à distinguer un bloc qui grandit d'un bloc figé :
   * l'analyse du texte ne peut pas le savoir, et une animation le prétendrait à tort.
   */
  actif?: boolean;
}

export function ReponseModele({ source, actif = false }: ReponseModeleProps): ReactElement {
  // Le streaming remplace `source` à chaque fragment : la séparation est mémoïsée sur le texte reçu.
  const segmentee = useMemo(() => segmenterReponse(source), [source]);
  // Les blancs qui encadrent la réponse (après `</think>`, typiquement deux sauts de ligne) ne
  // portent rien : les retirer distingue une réponse vide d'une réponse faite de deux retours.
  const visible = segmentee.visible.trim();
  const multiples = segmentee.raisonnements.length > 1;
  // Rang du premier appel d'outil : c'est lui qui sépare la délibération initiale — repliée — des
  // commentaires de travail qui suivent, affichés en clair. `-1` quand aucun outil n'a été appelé,
  // auquel cas tout reste replié : une réponse sans action n'a pas de « pendant ».
  const premierOutil = segmentee.raisonnements.findIndex((s) => s.convention === 'outil');
  return (
    <div className="min-w-0 space-y-1.5">
      {segmentee.raisonnements.map((segment, index) => (
        <SegmentRendu
          key={index}
          segment={segment}
          rang={multiples ? index + 1 : null}
          actif={actif}
          apresOutil={index > premierOutil && premierOutil >= 0}
        />
      ))}
      {visible !== '' ? (
        <RenduMarkdown source={visible} />
      ) : (
        <SansReponse segmentee={segmentee} actif={actif} />
      )}
    </div>
  );
}
