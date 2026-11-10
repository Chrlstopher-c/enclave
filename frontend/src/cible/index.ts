/*
 * Interface publique du module d'assemblage. Seule `App` l'utilise — c'est la seule couche qui a
 * le droit de connaître `models`, `system` et `chat` en même temps.
 */

export { useCible, type EtatCible } from './useCible';
export {
  construireCible,
  construireCibleSafetensors,
  modelesCharges,
  moteursUtilisables,
  versMetadonneesPlan,
  versMetadonneesPlanSafetensors,
  versProfilPlan,
  type RefusCible,
  type ResultatCible,
} from './conversion';
