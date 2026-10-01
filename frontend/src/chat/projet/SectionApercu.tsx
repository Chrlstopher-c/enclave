/*
 * Section « Aperçu » de la modale projet : ouvrir dans un onglet l'app que l'agent fait tourner.
 *
 * Les ports listés sont ceux en écoute dans l'atelier (un serveur lancé par `serveur_fond`).
 * L'app est servie à la racine d'un port dédié : ses chemins absolus fonctionnent tels quels.
 */

import { useEffect, type ReactElement } from 'react';
import { Button } from '../../shared/design';
import { useApercuProjet } from './useApercuProjet';

export function SectionApercu({ projet }: { readonly projet: string }): ReactElement {
  const { apercu, erreur, chercher, ouvrir } = useApercuProjet(projet);
  useEffect((): void => chercher(), [chercher]);
  const ports = apercu?.ports ?? [];
  return (
    <section className="space-y-2">
      <div className="flex items-center justify-between gap-2">
        <h3 className="text-xs font-semibold text-text">Aperçu de l’app</h3>
        <Button size="sm" variant="ghost" onClick={chercher}>
          Actualiser
        </Button>
      </div>
      {erreur !== null && <p className="text-2xs text-critical">{erreur}</p>}
      {ports.length === 0 ? (
        <p className="text-2xs text-text-3">
          Aucun serveur en écoute. Demande à l’agent de lancer l’app avec serveur_fond.
        </p>
      ) : (
        <div className="flex flex-wrap gap-2">
          {ports.map((port) => (
            <Button key={port} size="sm" variant={port === apercu?.port ? 'primary' : 'secondary'}
              onClick={() => ouvrir(port)}>
              Ouvrir le port {port}
            </Button>
          ))}
        </div>
      )}
    </section>
  );
}
