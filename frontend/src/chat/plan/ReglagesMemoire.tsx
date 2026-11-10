import type { ReactElement } from 'react';
import { Badge } from '../../shared/design';
import type { PlanDeChargement, TypeCacheKV } from '../api/contrats';

/*
 * Les deux leviers qui décident combien de VRAM le contexte consomme, rendus manipulables.
 *
 * Ils existaient déjà dans `PreferencesLocales` et partaient bien au planificateur — mais aucun
 * écran ne les exposait, si bien que le défaut `f16` était le seul réglage atteignable. Sur une
 * carte de 12 Go et un contexte large, ce défaut décide de tout : le cache mange la VRAM, il ne
 * reste plus de place pour les couches, et le débit s'effondre sans que rien ne le nomme.
 *
 * Mesure du 2026-08-26 sur un 35B-A3B, contexte 152576 : plan à 3 couches GPU sur 40 en `f16`,
 * pour 5,6 tok/s observés. La même carte, servie en `q4_0` par un llama-server réglé à la main,
 * tenait les 40 couches — c'est un facteur quatre sur le poids de chaque token de contexte.
 *
 * Le composant suit la règle du panneau : il exprime une DEMANDE, et affiche à côté ce que le
 * plan a réellement retenu. Quand les deux diffèrent, c'est visible plutôt que silencieux.
 */

interface OptionCache {
  valeur: TypeCacheKV;
  libelle: string;
  /* Poids relatif d'un token de cache, par rapport à f16. Ce n'est pas une estimation : c'est le
     nombre d'octets par élément du type, tel que le planificateur le calcule. */
  facteur: string;
  detail: string;
}

const CACHE_F16: OptionCache = {
  valeur: 'f16',
  libelle: 'f16',
  facteur: '×1',
  detail: 'Aucune compression. Le contexte coûte le plus cher en VRAM.',
};

const OPTIONS_CACHE: readonly OptionCache[] = [
  CACHE_F16,
  {
    valeur: 'q8_0',
    libelle: 'q8_0',
    facteur: '×½',
    detail: 'Moitié moins de VRAM par token, qualité quasi intacte.',
  },
  {
    valeur: 'q4_0',
    libelle: 'q4_0',
    facteur: '×¼',
    detail: 'Quatre fois moins de VRAM par token : ce qui est libéré repart aux couches.',
  },
] as const;

interface ChoixCacheProps {
  valeur: TypeCacheKV;
  retenu: TypeCacheKV;
  desactive: boolean;
  onChanger: (valeur: TypeCacheKV) => void;
}

function ChoixCache({ valeur, retenu, desactive, onChanger }: ChoixCacheProps): ReactElement {
  const actif = OPTIONS_CACHE.find((option) => option.valeur === valeur) ?? CACHE_F16;
  return (
    <div className="min-w-0 space-y-1.5">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <span className="text-2xs text-text-2">Cache KV</span>
        {retenu !== valeur && <Badge tone="caution">plan : {retenu}</Badge>}
      </div>
      <div role="radiogroup" aria-label="Type de cache KV" className="flex gap-1">
        {OPTIONS_CACHE.map((option) => {
          const selectionne = option.valeur === valeur;
          return (
            <button
              key={option.valeur}
              type="button"
              role="radio"
              aria-checked={selectionne}
              disabled={desactive}
              onClick={() => onChanger(option.valeur)}
              className={[
                'min-w-0 flex-1 rounded-sm border px-2 py-1.5 text-center transition-colors',
                'disabled:cursor-not-allowed disabled:opacity-50',
                selectionne
                  ? 'border-border-strong bg-surface-2 text-text'
                  : 'border-border bg-transparent text-text-2 hover:border-border-strong hover:text-text',
              ].join(' ')}
            >
              <span className="block font-mono text-xs tabular-nums">{option.libelle}</span>
              <span className="block font-mono text-2xs tabular-nums text-text-3">{option.facteur}</span>
            </button>
          );
        })}
      </div>
      <p className="text-2xs leading-relaxed text-text-3">{actif.detail}</p>
    </div>
  );
}

interface ChoixFlashProps {
  valeur: boolean;
  retenu: boolean;
  desactive: boolean;
  onChanger: (valeur: boolean) => void;
}

function ChoixFlash({ valeur, retenu, desactive, onChanger }: ChoixFlashProps): ReactElement {
  return (
    <div className="min-w-0 space-y-1.5">
      <label className="flex items-center justify-between gap-3">
        <span className="min-w-0 text-2xs text-text-2">Flash attention</span>
        <span className="flex shrink-0 items-center gap-2">
          {retenu !== valeur && <Badge tone="caution">plan : {retenu ? 'active' : 'inactive'}</Badge>}
          <input
            type="checkbox"
            checked={valeur}
            disabled={desactive}
            onChange={(evenement) => onChanger(evenement.target.checked)}
            className="h-4 w-4 cursor-pointer rounded-sm border border-border bg-surface-2
              accent-[var(--tone-accent)] disabled:cursor-not-allowed disabled:opacity-50"
          />
        </span>
      </label>
      <p className="text-2xs leading-relaxed text-text-3">
        Réduit la mémoire d’attention et accélère les longs contextes. Le moteur peut la refuser :
        le plan dit alors ce qui s’applique réellement.
      </p>
    </div>
  );
}

interface ChoixGraphesProps {
  valeur: boolean;
  retenu: boolean;
  desactive: boolean;
  onChanger: (valeur: boolean) => void;
}

/* Le plan peut refuser les graphes faute de VRAM : la demande et ce qui est retenu restent distincts. */
function ChoixGraphes({ valeur, retenu, desactive, onChanger }: ChoixGraphesProps): ReactElement {
  return (
    <div className="min-w-0 space-y-1.5">
      <label className="flex items-center justify-between gap-3">
        <span className="min-w-0 text-2xs text-text-2">Graphes CUDA</span>
        <span className="flex shrink-0 items-center gap-2">
          {retenu !== valeur && <Badge tone="caution">plan : {retenu ? 'actifs' : 'inactifs'}</Badge>}
          <input
            type="checkbox"
            checked={valeur}
            disabled={desactive}
            onChange={(evenement) => onChanger(evenement.target.checked)}
            className="h-4 w-4 cursor-pointer rounded-sm border border-border bg-surface-2
              accent-[var(--tone-accent)] disabled:cursor-not-allowed disabled:opacity-50"
          />
        </span>
      </label>
      <p className="text-2xs leading-relaxed text-text-3">
        Environ trois fois plus rapide en génération, pour quelques centaines de Mo de VRAM. Sans eux,
        tout va au contexte.
      </p>
    </div>
  );
}

/* Ce que le plan applique réellement : vLLM le dit (`mode_eager`), llama.cpp suit la demande. */
function graphesRetenus(plan: PlanDeChargement, demande: boolean): boolean {
  return plan.moteur.valeur === 'vllm' ? !(plan.mode_eager ?? false) : demande;
}

export interface ReglagesMemoireProps {
  plan: PlanDeChargement;
  typeCacheKv: TypeCacheKV;
  flashAttention: boolean;
  graphesCuda: boolean;
  desactive: boolean;
  onChangerCache: (valeur: TypeCacheKV) => void;
  onChangerFlash: (valeur: boolean) => void;
  onChangerGraphes: (valeur: boolean) => void;
}

export function ReglagesMemoire({
  plan,
  typeCacheKv,
  flashAttention,
  graphesCuda,
  desactive,
  onChangerCache,
  onChangerFlash,
  onChangerGraphes,
}: ReglagesMemoireProps): ReactElement {
  return (
    <div className="min-w-0 space-y-3 border-t border-border pt-3">
      <ChoixCache
        valeur={typeCacheKv}
        retenu={plan.type_cache_kv.valeur}
        desactive={desactive}
        onChanger={onChangerCache}
      />
      <ChoixFlash
        valeur={flashAttention}
        retenu={plan.flash_attention.valeur}
        desactive={desactive}
        onChanger={onChangerFlash}
      />
      <ChoixGraphes
        valeur={graphesCuda}
        retenu={graphesRetenus(plan, graphesCuda)}
        desactive={desactive}
        onChanger={onChangerGraphes}
      />
    </div>
  );
}
