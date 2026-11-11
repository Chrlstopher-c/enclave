/*
 * Progression d'une commande longue (`/compact`) DANS le fil, là où le regard attend la suite.
 *
 * Elle répond aux trois questions qu'une compaction de quinze minutes laissait sans réponse :
 * où en est-on (étapes, détail), qui travaille et à quel rythme (résumeur, jetons écrits, débit,
 * état du moteur), depuis quand (temps écoulé qui avance à la seconde). Et elle rassure sur la
 * seule chose qui inquiétait : fermer la page n'annule rien. Un silence du serveur se DIT.
 */

import { motion } from 'framer-motion';
import type { ReactElement } from 'react';
import { Badge, Button, cn, fadeUp } from '../../shared/design';
import type { EtatCommande } from './contrats';
import { EtapesProgression } from './EtapesProgression';
import type { CommandeRecue } from './magasin';
import {
  debit,
  dureeEcoulee,
  etatMoteur,
  formaterDuree,
  jetonsEcrits,
  libelleResumeur,
  SILENCE_MS,
  titreCommande,
} from './progression';
import { useMaintenant } from './useMaintenant';

function Mesures({ commande }: { commande: EtatCommande }): ReactElement | null {
  const resumeur = libelleResumeur(commande.resumeur);
  const morceaux = [jetonsEcrits(commande.tokens), debit(commande.tokens_par_seconde)].filter(
    (m): m is string => m !== null,
  );
  if (resumeur === null && morceaux.length === 0 && commande.moteur === null) {
    return null;
  }
  const moteur = commande.moteur === null ? null : etatMoteur(commande.moteur);
  return (
    <p className="flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1 text-2xs text-text-3">
      {resumeur !== null && (
        <span>
          Résumé par <span className="font-medium text-text-2">{resumeur}</span>
        </span>
      )}
      {morceaux.map((morceau) => (
        <span key={morceau} className="font-mono tabular-nums text-text-2">
          · {morceau}
        </span>
      ))}
      {moteur !== null && commande.moteur !== null && (
        <Badge tone={moteur.tone} dot>
          {moteur.libelle}
          {commande.moteur.modele !== '' && <span className="font-normal opacity-80"> · {commande.moteur.modele}</span>}
        </Badge>
      )}
    </p>
  );
}

function Entete({ recue, maintenant }: { recue: CommandeRecue; maintenant: number }): ReactElement {
  const { commande } = recue;
  const enCours = commande.etat === 'en_cours';
  const silence = enCours && maintenant - recue.recueMs > SILENCE_MS;
  const ecoule = dureeEcoulee(commande.duree_ms, recue.recueMs, maintenant, enCours);
  return (
    <div className="flex min-w-0 items-center justify-between gap-3">
      <Badge tone={enCours ? (silence ? 'caution' : 'accent') : 'caution'} dot pulse={enCours && !silence}>
        {titreCommande(commande)}
      </Badge>
      <span className="shrink-0 font-mono text-2xs tabular-nums text-text-2" title="Temps écoulé depuis le lancement">
        {formaterDuree(ecoule)}
      </span>
    </div>
  );
}

function Pied({ recue, maintenant }: { recue: CommandeRecue; maintenant: number }): ReactElement {
  const silenceS = Math.floor((maintenant - recue.recueMs) / 1000);
  if (silenceS * 1000 > SILENCE_MS) {
    return (
      <p className="text-2xs text-caution">
        Aucune nouvelle du serveur depuis {silenceS} s. La commande continue côté serveur ; la carte se remet à jour
        dès qu’il répond.
      </p>
    );
  }
  return (
    <p className="text-2xs text-text-3">
      Vous pourrez écrire dès la fin. Quitter ou recharger la page n’interrompt pas la commande.
    </p>
  );
}

export interface CarteCommandeProps {
  recue: CommandeRecue;
  onFermer: () => void;
}

export function CarteCommande({ recue, onFermer }: CarteCommandeProps): ReactElement {
  const { commande } = recue;
  const enCours = commande.etat === 'en_cours';
  const maintenant = useMaintenant(enCours);
  return (
    <motion.section
      variants={fadeUp}
      initial="hidden"
      animate="visible"
      exit="exit"
      aria-live="polite"
      aria-label={titreCommande(commande)}
      className={cn(
        'min-w-0 space-y-2.5 rounded-md border bg-surface px-3 py-2.5',
        enCours ? 'border-border' : 'border-[var(--caution)]',
      )}
    >
      <Entete recue={recue} maintenant={maintenant} />
      <EtapesProgression etapes={commande.etapes} echec={!enCours} />
      {commande.detail !== '' && <p className="text-xs text-text-2">{commande.detail}</p>}
      <Mesures commande={commande} />
      {enCours ? (
        <Pied recue={recue} maintenant={maintenant} />
      ) : (
        <Echec erreur={commande.erreur} nom={commande.nom} onFermer={onFermer} />
      )}
    </motion.section>
  );
}

function Echec({ erreur, nom, onFermer }: { erreur: string | null; nom: string; onFermer: () => void }):
ReactElement {
  return (
    <div className="flex min-w-0 flex-wrap items-end justify-between gap-2">
      <p className="min-w-0 flex-1 text-xs text-text">
        {erreur ?? 'La commande a échoué sans donner de raison.'}{' '}
        <span className="text-text-3">Le contexte est inchangé : relancez /{nom} depuis la saisie.</span>
      </p>
      <Button variant="ghost" size="sm" onClick={onFermer}>
        Fermer
      </Button>
    </div>
  );
}
