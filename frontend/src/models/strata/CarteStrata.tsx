import type { ReactElement } from 'react';

import { Badge, Button, Card } from '../../shared/design';
import { useStrata, type SondeStrata } from './useStrata';

function Etat({ sonde }: { sonde: SondeStrata | null }): ReactElement {
  if (sonde === null) {
    return <Badge>sonde…</Badge>;
  }
  if (!sonde.joignable) {
    return <Badge tone="caution">serveur arrêté</Badge>;
  }
  return sonde.charge ? <Badge tone="ok">chargé</Badge> : <Badge tone="neutral">prêt à charger</Badge>;
}

/** Strata ne passe pas par le planificateur : il place lui-même ses experts (VRAM, RAM, SSD). */
export function CarteStrata(): ReactElement {
  const { sonde, envoi, erreur, charger } = useStrata();
  const contexte = sonde?.contexte ? `${Math.round(sonde.contexte / 1024)} k tokens` : '—';

  return (
    <Card title="Strata · Qwen3.8-Flash-Next" actions={<Etat sonde={sonde} />} className="mb-4">
      <p className="text-sm text-text-2">
        Moteur dédié, servi sur l'hôte : cache d'experts en VRAM, tête MTP, prompt lu par blocs de 8 k.
        Charger remplace le modèle actif.
      </p>
      <div className="mt-3 flex flex-wrap items-center justify-between gap-3 text-sm">
        <span className="text-text-3">
          {sonde?.modele ?? 'modèle inconnu'} · contexte {contexte}
        </span>
        <Button
          variant="primary"
          size="sm"
          loading={envoi}
          disabled={!sonde?.joignable || sonde.charge}
          onClick={charger}
        >
          Charger
        </Button>
      </div>
      {sonde !== null && !sonde.joignable && <p className="mt-2 text-xs text-text-3">{sonde.detail}</p>}
      {erreur !== null && <p className="mt-2 text-xs text-critical">{erreur}</p>}
    </Card>
  );
}
