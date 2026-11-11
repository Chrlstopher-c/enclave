import type { ReactElement } from 'react';
import { Badge, cn } from '../../shared/design';
import type { ActiviteMoteur, OutilEnDirect } from '../api/contrats';
import {
  debit,
  depuisDebut,
  EtapesProgression,
  etapesDepuisCle,
  formaterDuree,
  jetonsEcrits,
  libelleResumeur,
  repereActivite,
  SILENCE_MS,
  useMaintenant,
  type CompactionEnDirect,
  type RepereActivite,
} from '../commandes';
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
 *
 * 2026-11-11 : le compteur s'appelle « jetons écrits » (ce que le moteur a GÉNÉRÉ depuis le début de
 * la réponse) et ne s'affiche que quand le moteur écrit ; une compaction en cours de tâche montre ses
 * étapes ; « au travail depuis » avance à la seconde quand le backend date le début du tour.
 */

function formaterTaille(caracteres: number): string {
  return caracteres < 1024 ? `${caracteres} car.` : `${(caracteres / 1024).toFixed(1).replace('.', ',')} Ko`;
}

function formaterLecture(lecture: { faits: number; total: number } | null | undefined): string {
  if (lecture == null || lecture.total === 0) {
    return '…';
  }
  const nombre = (n: number): string => n.toLocaleString('fr-FR');
  return `${nombre(lecture.faits)} / ${nombre(lecture.total)} jetons relus`;
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

/* Compaction pendant la tâche : mêmes étapes et mêmes mesures que la carte de `/compact`. */
function BlocCompaction({ compaction }: { compaction: CompactionEnDirect }): ReactElement {
  const resumeur = libelleResumeur(compaction.resumeur);
  const mesures = [jetonsEcrits(compaction.tokens), debit(compaction.tokens_par_seconde)].filter(
    (m): m is string => m !== null,
  );
  return (
    <div className="min-w-0 space-y-1.5">
      <EtapesProgression etapes={etapesDepuisCle(compaction.etape)} />
      {compaction.detail !== '' && <p className="text-2xs text-text-2">{compaction.detail}</p>}
      <p className="flex min-w-0 flex-wrap gap-x-2 text-2xs text-text-3">
        {resumeur !== null && <span>Résumé par <span className="font-medium text-text-2">{resumeur}</span></span>}
        {mesures.map((m) => (
          <span key={m} className="font-mono tabular-nums text-text-2">· {m}</span>
        ))}
        <span className="font-mono tabular-nums">· {formaterDuree(compaction.duree_ms)}</span>
      </p>
    </div>
  );
}

function Mesure({ activite, silenceS, mesure }: {
  activite: ActiviteMoteur;
  silenceS: number;
  mesure: RepereActivite['mesure'];
}): ReactElement | null {
  if (mesure === 'silence') {
    return <span className="tabular-nums text-text-3">depuis {silenceS} s</span>;
  }
  if (mesure === 'lecture') {
    return <span className="tabular-nums text-text-2">{formaterLecture(activite.lecture)}</span>;
  }
  if (mesure === 'compaction') {
    return null;
  }
  return <span className="tabular-nums text-text-2">{debit(activite.tokens_par_seconde) ?? '…'}</span>;
}

const TITRE_JETONS = 'Jetons générés par le moteur depuis le début de la réponse';

function LigneRepere({ activite, repere, silenceS, depuis }: {
  activite: ActiviteMoteur;
  repere: RepereActivite;
  silenceS: number;
  depuis: string | null;
}): ReactElement {
  return (
    <p className="flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1 text-2xs">
      <Badge tone={repere.tone} dot pulse={repere.mesure !== 'silence'}>
        {repere.libelle}
      </Badge>
      <Mesure activite={activite} silenceS={silenceS} mesure={repere.mesure} />
      {repere.montrerJetons && (
        <span className="tabular-nums text-text-3" title={TITRE_JETONS}>
          · {jetonsEcrits(activite.tokens)}
        </span>
      )}
      {depuis !== null && (
        <span className="ml-auto font-mono tabular-nums text-text-3" title="Depuis le début de ce tour">
          au travail depuis {depuis}
        </span>
      )}
    </p>
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
  const { phase, outil, compaction } = activite.activite;
  const silenceS = Math.floor((maintenant - activite.recueMs) / 1000);
  const repere = repereActivite(activite.activite, maintenant - activite.recueMs > SILENCE_MS);
  const silencieux = repere.mesure === 'silence';
  const enEcriture = phase === 'outil' && outil != null && repere.montrerOutil;
  const depuis = depuisDebut(activite.activite.debut, maintenant);
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
        <LigneRepere activite={activite.activite} repere={repere} silenceS={silenceS} depuis={depuis} />
        {compaction != null && <BlocCompaction compaction={compaction} />}
        {outil != null && repere.montrerOutil && (!enEcriture || outil.fichiers_sauves.length > 0) && (
          <LigneOutil outil={outil} execution={phase === 'execution'} />
        )}
      </div>
    </div>
  );
}
