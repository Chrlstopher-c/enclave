import { useEffect, useState } from 'react';

/* Horloge qui avance chaque seconde tant que `actif` : ce qui dure se voit durer. */
export function useMaintenant(actif: boolean): number {
  const [maintenant, setMaintenant] = useState<number>(() => Date.now());
  useEffect((): (() => void) | undefined => {
    if (!actif) {
      return undefined;
    }
    setMaintenant(Date.now());
    const minuterie = window.setInterval((): void => setMaintenant(Date.now()), 1000);
    return (): void => window.clearInterval(minuterie);
  }, [actif]);
  return maintenant;
}
