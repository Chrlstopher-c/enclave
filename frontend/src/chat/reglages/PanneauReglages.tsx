import type { ReactElement, ReactNode } from 'react';
import { cn } from '../../shared/design';
import type { MessageChat } from '../api/contrats';
import { ChampCurseur, ChampEntier, ChampEntierOptionnel, ChampTexte } from './Champs';
import type { Reglages } from './contrat';
import {
  GRAINE,
  MAX_TOKENS,
  MIN_P,
  PENALITE_PRESENCE,
  PENALITE_REPETITION,
  PROMPT_SYSTEME,
  TEMPERATURE,
  TOP_K,
  TOP_P,
} from './definitions';
import { BadgeEnregistrement, EchecEnregistrement } from './EtatEnregistrement';
import { PlafondReponses } from './PlafondReponses';
import { SequencesArret } from './SequencesArret';
import { useReglagesConversation, type PilotageReglages } from './useReglagesConversation';

/*
 * Panneau des réglages d'une conversation.
 *
 * L'ordre des sections suit la question que l'utilisateur se pose, pas la structure du modèle
 * pydantic : ce que le modèle doit savoir en permanence, comment il choisit ses mots, jusqu'où il a
 * le droit d'écrire, et quand il doit s'arrêter. Le plafond de réponse est la seule section adossée
 * à une mesure, parce que c'est la seule dont l'effet se constate dans les messages déjà produits.
 *
 * Aucun bouton « Enregistrer » : l'écriture est différée et automatique, et l'état d'enregistrement
 * est affiché en permanence. Un formulaire qui exige une validation finale perd la saisie de qui
 * ferme la modale — et rend l'échec silencieux, ce qui est le contraire du but ici.
 */

interface SectionProps {
  readonly pilotage: PilotageReglages;
}

function Section({ titre, children }: { titre: string; children: ReactNode }): ReactElement {
  return (
    <section className="min-w-0 space-y-3">
      <h3 className="text-xs font-medium text-text">{titre}</h3>
      {children}
    </section>
  );
}

function ChampTemperature({ pilotage }: SectionProps): ReactElement {
  return (
    <ChampCurseur
      id="reglage-temperature"
      definition={TEMPERATURE}
      valeur={pilotage.valeurs.parametres.temperature}
      onChanger={(temperature) => pilotage.modifierParametres({ temperature })}
    />
  );
}

function ChampTopP({ pilotage }: SectionProps): ReactElement {
  return (
    <ChampCurseur
      id="reglage-top-p"
      definition={TOP_P}
      valeur={pilotage.valeurs.parametres.top_p}
      onChanger={(top_p) => pilotage.modifierParametres({ top_p })}
    />
  );
}

function ChampPenalite({ pilotage }: SectionProps): ReactElement {
  return (
    <ChampCurseur
      id="reglage-penalite"
      definition={PENALITE_REPETITION}
      valeur={pilotage.valeurs.parametres.penalite_repetition}
      onChanger={(penalite_repetition) => pilotage.modifierParametres({ penalite_repetition })}
    />
  );
}

function ChampMinP({ pilotage }: SectionProps): ReactElement {
  return (
    <ChampCurseur
      id="reglage-min-p"
      definition={MIN_P}
      valeur={pilotage.valeurs.parametres.min_p}
      onChanger={(min_p) => pilotage.modifierParametres({ min_p })}
    />
  );
}

function ChampPresence({ pilotage }: SectionProps): ReactElement {
  return (
    <ChampCurseur
      id="reglage-presence"
      definition={PENALITE_PRESENCE}
      valeur={pilotage.valeurs.parametres.penalite_presence}
      onChanger={(penalite_presence) => pilotage.modifierParametres({ penalite_presence })}
    />
  );
}

function ChampTopK({ pilotage }: SectionProps): ReactElement {
  return (
    <ChampEntier
      id="reglage-top-k"
      definition={TOP_K}
      valeur={pilotage.valeurs.parametres.top_k}
      onChanger={(top_k) => pilotage.modifierParametres({ top_k })}
    />
  );
}

function ChampPlafond({ pilotage }: SectionProps): ReactElement {
  return (
    <ChampEntierOptionnel
      id="reglage-max-tokens"
      definition={MAX_TOKENS}
      valeur={pilotage.valeurs.parametres.max_tokens}
      etiquetteVide="aucun plafond"
      onChanger={(max_tokens) => pilotage.modifierParametres({ max_tokens })}
    />
  );
}

function ChampGraine({ pilotage }: SectionProps): ReactElement {
  return (
    <ChampEntierOptionnel
      id="reglage-graine"
      definition={GRAINE}
      valeur={pilotage.valeurs.parametres.graine}
      etiquetteVide="aléatoire"
      onChanger={(graine) => pilotage.modifierParametres({ graine })}
    />
  );
}

function Entete({ pilotage }: SectionProps): ReactElement {
  return (
    <div className="space-y-2">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-2xs text-text-3">Enregistré au fil de la saisie.</p>
        <BadgeEnregistrement etat={pilotage.etat} />
      </div>
      <EchecEnregistrement
        etat={pilotage.etat}
        modifies={pilotage.modifies}
        onReessayer={pilotage.enregistrerMaintenant}
      />
    </div>
  );
}

function SectionTirage({ pilotage }: SectionProps): ReactElement {
  return (
    <Section titre="Choix du prochain jeton">
      <ChampTemperature pilotage={pilotage} />
      <ChampTopP pilotage={pilotage} />
      <ChampTopK pilotage={pilotage} />
      <ChampMinP pilotage={pilotage} />
      <ChampPenalite pilotage={pilotage} />
      <ChampPresence pilotage={pilotage} />
    </Section>
  );
}

interface SectionPlafondProps extends SectionProps {
  readonly messages: readonly MessageChat[];
}

function SectionPlafond({ pilotage, messages }: SectionPlafondProps): ReactElement {
  return (
    <Section titre="Longueur de la réponse">
      <ChampPlafond pilotage={pilotage} />
      <PlafondReponses plafond={pilotage.enregistre.parametres.max_tokens} messages={messages} />
    </Section>
  );
}

function SectionArret({ pilotage }: SectionProps): ReactElement {
  return (
    <Section titre="Arrêt et reproductibilité">
      <SequencesArret
        valeurs={pilotage.valeurs.parametres.sequences_arret}
        onChanger={(sequences_arret) => pilotage.modifierParametres({ sequences_arret })}
      />
      <ChampGraine pilotage={pilotage} />
    </Section>
  );
}

export interface PanneauReglagesProps {
  readonly conversationId: string;
  /** Réglages tels que le backend les a servis. Ils font autorité à l'ouverture. */
  readonly reglages: Reglages;
  /** Messages persistés de la conversation : ce qui adosse le plafond à des mesures réelles. */
  readonly messages?: readonly MessageChat[];
  /** Réglages confirmés par le backend, pour que l'écran appelant reste à jour sans les relire. */
  readonly onEnregistre?: (reglages: Reglages) => void;
  readonly className?: string;
}

export function PanneauReglages({
  conversationId,
  reglages,
  messages = [],
  onEnregistre,
  className,
}: PanneauReglagesProps): ReactElement {
  const pilotage = useReglagesConversation(conversationId, reglages, onEnregistre);
  return (
    <div className={cn('min-w-0 space-y-5', className)}>
      <Entete pilotage={pilotage} />
      <Section titre="Instructions permanentes">
        <ChampTexte
          id="reglage-prompt"
          definition={PROMPT_SYSTEME}
          valeur={pilotage.valeurs.prompt_systeme}
          lignes={5}
          exemple="Instructions envoyées au modèle avant chaque échange."
          onChanger={pilotage.modifierPrompt}
        />
      </Section>
      <SectionTirage pilotage={pilotage} />
      <SectionPlafond pilotage={pilotage} messages={messages} />
      <SectionArret pilotage={pilotage} />
    </div>
  );
}
