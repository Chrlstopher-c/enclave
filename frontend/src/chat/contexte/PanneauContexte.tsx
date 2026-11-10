/*
 * Panneau d'occupation de la fenêtre de contexte, en temps réel dans la conversation.
 *
 * Règle qui commande tout l'affichage : tant qu'aucun modèle n'est chargé, il n'existe aucun
 * tokenizer, donc aucune mesure. Le panneau le DIT — il n'affiche pas une barre vide, qui
 * laisserait croire à une fenêtre entièrement libre alors que rien n'a été mesuré.
 *
 * Le total de référence est le contexte réellement servi par le moteur, jamais le contexte natif
 * du modèle : 262 144 déclarés contre 32 768 appliqués, confondre les deux rendrait la barre fausse
 * d'un facteur huit.
 */

import type { ReactElement } from 'react';
import type { MessageMoteur, OccupationContexte, PartContexte } from '../../shared/api';
import { Badge, Card, cn } from '../../shared/design';
import { BarreContexte } from './BarreContexte';
import { formaterTokens } from './postes';
import { useOccupationContexte } from './useOccupationContexte';

/** Mesure complète et non ambiguë : tous les champs chiffrés présents, aucun défaut inventé. */
interface MesureFermee {
  readonly utilises: number;
  readonly total: number;
  readonly depassement: number;
  readonly postes: readonly PartContexte[];
  readonly avertissements: readonly string[];
}

/**
 * Ne rend une mesure que si elle est complète. Un champ chiffré manquant vaut « pas de mesure » et
 * bascule le panneau sur son état d'indisponibilité — jamais sur un zéro d'apparence mesurée.
 */
function fermer(occupation: OccupationContexte | null): MesureFermee | null {
  if (occupation === null || !occupation.mesurable) {
    return null;
  }
  const utilises = occupation.tokens_mesures;
  const total = occupation.contexte_total;
  if (utilises === null || total === null) {
    return null;
  }
  return {
    utilises,
    total,
    // `null` ne peut venir que d'un backend antérieur à ce champ : zéro est alors la seule valeur
    // qui n'affiche rien de faux (aucun cadre rouge, aucun dépassement annoncé).
    depassement: occupation.depassement_tokens ?? 0,
    postes: occupation.postes,
    avertissements: occupation.avertissements,
  };
}

/** Occupation de la tâche en cours, rapportée par la boucle d'outils pendant la génération. */
export interface OccupationDirecte {
  readonly tokens: number;
  readonly total: number;
}

/**
 * Pendant une tâche, la mesure du prochain message ne dit rien de ce que le modèle porte MAINTENANT
 * (24K affichés pour 58K réels, 2026-11-10) : la boucle rapporte son occupation, on l'affiche telle quelle.
 */
function mesureDirecte(direct: OccupationDirecte): MesureFermee {
  const tokens = Math.min(direct.tokens, direct.total);
  const postes: PartContexte[] = [
    { poste: 'assistant', tokens, part: tokens / direct.total, segments: 0 },
    { poste: 'libre', tokens: direct.total - tokens, part: (direct.total - tokens) / direct.total, segments: 0 },
  ];
  return {
    utilises: tokens,
    total: direct.total,
    depassement: Math.max(0, direct.tokens - direct.total),
    postes,
    avertissements: ['En direct : contexte complet de la tâche en cours (socle, outils, historique, travail).'],
  };
}

function Entete({ mesure, enAttente }: { mesure: MesureFermee | null; enAttente: boolean }): ReactElement | null {
  if (mesure === null) {
    return null;
  }
  return (
    <span className="flex flex-wrap items-baseline justify-end gap-x-2">
      {mesure.depassement > 0 && (
        <Badge tone="critical">{`+${formaterTokens(mesure.depassement)} hors fenêtre`}</Badge>
      )}
      {mesure.depassement === 0 && mesure.utilises === mesure.total && (
        <Badge tone="caution">Fenêtre pleine</Badge>
      )}
      <span className="font-mono text-xs tabular-nums text-text">
        {`${formaterTokens(mesure.utilises)} / ${formaterTokens(mesure.total)}`}
      </span>
      {/* Pas de pouls : une mesure différée n'est pas une activité, seulement un chiffre qui date. */}
      {enAttente && <span className="text-2xs text-text-3">en attente</span>}
    </span>
  );
}

interface IndisponibleProps {
  occupation: OccupationContexte | null;
  erreur: string | null;
}

/** Aucune barre dans cet état : une jauge vide se lirait comme une fenêtre libre. */
function Indisponible({ occupation, erreur }: IndisponibleProps): ReactElement {
  if (erreur !== null) {
    return (
      <div className="space-y-1.5">
        <Badge tone="critical">Mesure indisponible</Badge>
        <p className="text-2xs text-text-2">{erreur}</p>
      </div>
    );
  }
  if (occupation === null) {
    return <p className="text-2xs text-text-3">Mesure en cours…</p>;
  }
  return (
    <div className="space-y-1.5">
      <Badge tone="neutral" dot>
        Rien à mesurer
      </Badge>
      <p className="text-2xs text-text-2">{occupation.raison}</p>
    </div>
  );
}

/** Ce que le décompte ne couvre pas. Affiché, jamais comblé par une estimation. */
function Notes({ lignes }: { lignes: readonly string[] }): ReactElement | null {
  if (lignes.length === 0) {
    return null;
  }
  return (
    <ul className="space-y-1 border-t border-border pt-2">
      {lignes.map((ligne) => (
        <li key={ligne} className="text-2xs leading-snug text-text-3">
          {ligne}
        </li>
      ))}
    </ul>
  );
}

export interface PanneauContexteProps {
  /** Conversation affichée : la mesure suit alors exactement ce que la génération enverrait. */
  conversationId?: string | null;
  /** Occupation rapportée par la tâche en cours ; prioritaire tant qu'elle est là. */
  direct?: OccupationDirecte | null;
  /** Prompt système de la conversation, tel qu'il repart au modèle à chaque tour. */
  promptSysteme?: string;
  /** Messages au format moteur (`role` / `content`), dans l'ordre d'envoi. */
  messages: readonly MessageMoteur[];
  /** Modèle actuellement chargé : sa bascule relance la mesure. */
  modeleCharge?: string | null;
  /** Faux quand le panneau est masqué : plus aucune requête n'est émise. */
  actif?: boolean;
  className?: string;
}

export function PanneauContexte({
  conversationId = null,
  direct = null,
  promptSysteme = '',
  messages,
  modeleCharge = null,
  actif = true,
  className,
}: PanneauContexteProps): ReactElement {
  const entree = { conversationId, promptSysteme, messages, modeleCharge, actif };
  const { occupation, enAttente, erreur } = useOccupationContexte(entree);
  const mesure = direct !== null && direct.total > 0 ? mesureDirecte(direct) : fermer(occupation);
  return (
    <Card
      level="surface"
      padding="sm"
      title="Fenêtre de contexte"
      actions={<Entete mesure={mesure} enAttente={enAttente} />}
      className={cn('min-w-0', className)}
    >
      {mesure === null ? (
        <Indisponible occupation={occupation} erreur={erreur} />
      ) : (
        <div className="space-y-3">
          <BarreContexte postes={mesure.postes} depassement={mesure.depassement} />
          <Notes lignes={mesure.avertissements} />
        </div>
      )}
    </Card>
  );
}
