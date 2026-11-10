/*
 * « Charger comme la dernière fois » : le dernier plan qui a RÉELLEMENT chargé ce modèle, rejoué tel quel.
 *
 * Demandé par Chris le 2026-11-10 : Ornith refusait de se charger depuis le panneau, alors que le même
 * modèle chargé avec des réglages forcés tenait. Un plan réussi est une mesure ; il se rejoue d'un clic.
 */

import { useEffect, useState } from 'react';
import type { ReactElement } from 'react';
import { Button } from '../../shared/design';
import type { PlanEprouve } from '../api/contrats';
import { lirePlanEprouve } from '../api/inference-api';
import type { EtatChargementModele } from './useChargement';

function resume(plan: PlanEprouve): string {
  const contexte = plan.contexte >= 1024 ? `${Math.round(plan.contexte / 1024)}K` : String(plan.contexte);
  const morceaux = [contexte, plan.type_kv_cache ?? 'cache par défaut', plan.mode_eager ? 'sans graphes' : 'graphes'];
  if (plan.fraction_vram !== null) {
    morceaux.push(`VRAM ${Math.round(plan.fraction_vram * 100)} %`);
  }
  return morceaux.join(' · ');
}

function usePlanEprouve(identifiant: string, etat: string | undefined): PlanEprouve | null {
  const [plan, setPlan] = useState<PlanEprouve | null>(null);
  useEffect((): (() => void) => {
    const controle = new AbortController();
    void lirePlanEprouve(identifiant, controle.signal).then((lu): void => {
      if (!controle.signal.aborted) {
        setPlan(lu);
      }
    });
    return (): void => controle.abort();
    // Relu quand un chargement aboutit : c'est lui qui enregistre le plan éprouvé.
  }, [identifiant, etat]);
  return plan;
}

export function ChargementEprouve({
  identifiant,
  chargement,
}: {
  identifiant: string;
  chargement: EtatChargementModele;
}): ReactElement | null {
  const plan = usePlanEprouve(identifiant, chargement.statut?.etat);
  if (plan === null) {
    return null;
  }
  return (
    <Button
      variant="secondary"
      size="sm"
      disabled={chargement.statut?.etat === 'en_cours'}
      title="Rejoue exactement le dernier chargement réussi de ce modèle"
      onClick={() => void chargement.demarrerEprouve(identifiant)}
    >
      Comme la dernière fois · {resume(plan)}
    </Button>
  );
}
