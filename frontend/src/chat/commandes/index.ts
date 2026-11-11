/* Interface publique du domaine des commandes du chat (`/compact`, `/clear`). */

export type {
  CompactionEnDirect,
  DefinitionCommande,
  EtatCommande,
  EvenementCommande,
  InfoEffacement,
} from './contrats';
export { CarteCommande } from './CarteCommande';
export { EtapesProgression } from './EtapesProgression';
export { IndicationCommande } from './IndicationCommande';
export { PaletteCommandes } from './PaletteCommandes';
export { SeparateurEffacement } from './SeparateurEffacement';
export { masquerEfface, type VueEffacee } from './masquage';
export {
  ecarterCommande,
  finDeFlux,
  recevoirCommande,
  recevoirCompaction,
  useEtatCommandes,
  type CommandeRecue,
  type EtatCommandes,
} from './magasin';
export {
  debit,
  dureeEcoulee,
  etapesDepuisCle,
  formaterDuree,
  jetonsEcrits,
  libelleResumeur,
  repereActivite,
  SILENCE_MS,
  type RepereActivite,
} from './progression';
export { useEffacements, type EtatEffacements } from './useEffacements';
export { useMaintenant } from './useMaintenant';
export { useSaisieCommande, type SaisieCommande } from './useSaisieCommande';
export { depuisDebut, dureeGeneration, horodatageLisible } from './horodatage';
