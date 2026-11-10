import { useEffect, useState } from 'react';
import type { ReactElement } from 'react';
import { Badge, cn } from '../../shared/design';
import type { Tone } from '../../shared/design';
import type { ActiviteMoteur, OutilEnDirect } from '../api/contrats';
import { AppelEnDirect } from '../raisonnement/AppelEnDirect';
import { OUTILS_CONNUS } from '../raisonnement/lecture-appel';
import type { ActiviteRecue } from './useGeneration';

/*
 * Ce que le moteur fait EN CE MOMENT, sous la réponse en cours.
 *
 * Demandé le 2026-11-10 : une écriture groupée de plusieurs minutes ne montrait rien, et rien ne
 * distinguait « il écrit à 46 tok/s » de « il est bloqué ». La ligne dit la phase, le débit mesuré
 * sur les trois dernières secondes, le fichier en cours et ceux déjà sauvés sur le disque. Sans
 * nouvelle du moteur depuis `SILENCE_MS`, elle le dit aussi : un silence se voit, il ne se devine pas.
 */

const SILENCE_MS = 4000;

const PHASES: Record<ActiviteMoteur['phase'], { libelle: string; tone: Tone }> = {
  reflexion: { libelle: 'Réflexion', tone: 'neutral' },
  texte: { libelle: 'Rédaction', tone: 'accent' },
  outil: { libelle: 'Écrit un appel', tone: 'accent' },
  execution: { libelle: 'Exécute', tone: 'caution' },
};

function useMaintenant(actif: boolean): number {
  const [maintenant, setMaintenant] = useState<number>(() => Date.now());
  useEffect((): (() => void) | undefined => {
    if (!actif) {
      return undefined;
    }
    const minuterie = window.setInterval((): void => setMaintenant(Date.now()), 1000);
    return (): void => window.clearInterval(minuterie);
  }, [actif]);
  return maintenant;
}

function formaterTaille(caracteres: number): string {
  return caracteres < 1024 ? `${caracteres} car.` : `${(caracteres / 1024).toFixed(1).replace('.', ',')} Ko`;
}

function formaterDebit(debit: number): string {
  return debit > 0 ? `${debit.toFixed(1).replace('.', ',')} tok/s` : '…';
}

function LigneOutil({ outil, execution }: { outil: OutilEnDirect; execution: boolean }): ReactElement {
  const libelle = OUTILS_CONNUS[outil.nom]?.libelle ?? outil.nom;
  return (
    <div className="min-w-0 space-y-1">
      <p className="flex min-w-0 items-baseline gap-1.5 text-2xs text-text-2">
        <span className="shrink-0 font-medium text-text">{libelle}</span>
        {outil.chemin !== null && <span className="truncate font-mono text-text-2">{outil.chemin}</span>}
        {!execution && outil.caracteres > 0 && (
          <span className="shrink-0 tabular-nums text-text-3">· {formaterTaille(outil.caracteres)}</span>
        )}
      </p>
      {outil.fichiers_sauves.length > 0 && (
        <p className="flex min-w-0 flex-wrap items-center gap-1 text-2xs text-text-3">
          <span className="shrink-0">Déjà sur le disque :</span>
          {outil.fichiers_sauves.map((chemin) => (
            <Badge key={chemin} tone="ok">
              {chemin}
            </Badge>
          ))}
        </p>
      )}
    </div>
  );
}

export interface ActiviteEnDirectProps {
  activite: ActiviteRecue | null;
}

export function ActiviteEnDirect({ activite }: ActiviteEnDirectProps): ReactElement | null {
  const maintenant = useMaintenant(activite !== null);
  if (activite === null) {
    return null;
  }
  const { phase, tokens, tokens_par_seconde: debit, outil } = activite.activite;
  const silenceS = Math.floor((maintenant - activite.recueMs) / 1000);
  const silencieux = maintenant - activite.recueMs > SILENCE_MS && phase !== 'execution';
  const repere = silencieux ? { libelle: 'Aucune nouvelle du moteur', tone: 'caution' as Tone } : PHASES[phase];
  const enEcriture = phase === 'outil' && outil != null;
  return (
    <div className="min-w-0 space-y-2">
      {enEcriture && <AppelEnDirect outil={outil} />}
      <div
        className={cn(
          'min-w-0 space-y-1.5 rounded-sm border px-2.5 py-2',
          silencieux ? 'border-[var(--caution)]' : 'border-border',
        )}
        aria-live="polite"
      >
        <p className="flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1 text-2xs">
          <Badge tone={repere.tone} dot pulse={!silencieux}>
            {repere.libelle}
          </Badge>
          {silencieux ? (
            <span className="tabular-nums text-text-3">depuis {silenceS} s</span>
          ) : (
            <span className="tabular-nums text-text-2">{formaterDebit(debit)}</span>
          )}
          <span className="tabular-nums text-text-3">· {tokens.toLocaleString('fr-FR')} tokens</span>
        </p>
        {outil != null && (!enEcriture || outil.fichiers_sauves.length > 0) && (
          <LigneOutil outil={outil} execution={phase === 'execution'} />
        )}
      </div>
    </div>
  );
}
