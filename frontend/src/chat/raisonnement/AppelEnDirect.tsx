/*
 * L'appel d'outil PENDANT que le modèle l'écrit : quel outil, sur quoi, et le texte qui arrive.
 *
 * Demandé le 2026-11-10 : la ligne d'activité disait « Commande · 12 Ko » sans montrer la commande.
 * Comme dans Claude Code, la carte de l'outil apparaît dès le premier fragment et son contenu
 * (commande, fichier en cours d'écriture, requête) défile en direct ; la carte définitive, avec son
 * résultat, la remplace à l'exécution.
 */

import { useEffect, useRef } from 'react';
import type { ReactElement } from 'react';
import { Badge } from '../../shared/design';
import type { OutilEnDirect } from '../api/contrats';
import { IconeDeCarte } from './icones-outils';
import { OUTILS_CONNUS } from './lecture-appel';

const NOMBRE = new Intl.NumberFormat('fr-FR');

/* L'argument qui porte le gros du texte : c'est lui qui défile. */
const CORPS = ['contenu', 'content', 'code', 'source', 'commande', 'command', 'nouveau', 'texte', 'requete', 'query'];

function cibleDe(nom: string, parametres: Record<string, string>): string | null {
  const cles = OUTILS_CONNUS[nom]?.cles ?? [];
  const cle = cles.find((candidate) => (parametres[candidate] ?? '').trim() !== '');
  const valeur = cle === undefined ? null : (parametres[cle] ?? null);
  return valeur === null ? null : (valeur.split('\n')[0] ?? '').slice(0, 160);
}

function corpsDe(parametres: Record<string, string>, cible: string | null): string {
  const cle = CORPS.find((candidate) => parametres[candidate] !== undefined);
  if (cle !== undefined) {
    return parametres[cle] ?? '';
  }
  const valeurs = Object.values(parametres).filter((valeur) => valeur.split('\n')[0] !== cible);
  return valeurs.sort((a, b) => b.length - a.length)[0] ?? '';
}

/* Un argument non textuel (nombre, liste) s'affiche tel qu'il serait écrit, au lieu de faire tomber l'écran. */
function enTexte(parametres: Record<string, unknown>): Record<string, string> {
  return Object.fromEntries(
    Object.entries(parametres).map(([cle, valeur]) => [
      cle,
      typeof valeur === 'string' ? valeur : (JSON.stringify(valeur) ?? ''),
    ]),
  );
}

export interface AppelEnDirectProps {
  readonly outil: OutilEnDirect;
}

export function AppelEnDirect({ outil }: AppelEnDirectProps): ReactElement {
  const descripteur = OUTILS_CONNUS[outil.nom];
  const parametres = enTexte(outil.parametres ?? {});
  const cible = cibleDe(outil.nom, parametres) ?? outil.chemin;
  const corps = corpsDe(parametres, cible);
  const defilement = useRef<HTMLPreElement | null>(null);
  useEffect((): void => {
    const zone = defilement.current;
    if (zone !== null) {
      zone.scrollTop = zone.scrollHeight;
    }
  }, [corps]);
  return (
    <section className="max-w-full rounded-sm bg-surface">
      <div className="flex min-h-[44px] flex-wrap items-center gap-x-2 gap-y-1 px-2.5 py-2 lg:min-h-0 lg:py-1.5">
        <span className="text-text-3">
          <IconeDeCarte icone={descripteur?.icone ?? 'code'} />
        </span>
        <span className="shrink-0 text-xs font-medium text-text-2">{descripteur?.libelle ?? outil.nom}</span>
        {cible !== null && (
          <span className="min-w-0 flex-1 truncate font-mono text-2xs text-text-3" title={cible}>
            {cible}
          </span>
        )}
        <span className="shrink-0 font-mono text-2xs tabular-nums text-text-3">
          {NOMBRE.format(outil.caracteres)} car.
        </span>
        <Badge tone="accent" dot pulse>
          écrit
        </Badge>
      </div>
      {corps !== '' && (
        <pre
          ref={defilement}
          className="max-h-64 overflow-auto overscroll-contain whitespace-pre-wrap break-words border-t
            border-border px-2.5 py-2 font-mono text-2xs leading-relaxed text-text-2"
        >
          {corps}
        </pre>
      )}
    </section>
  );
}
