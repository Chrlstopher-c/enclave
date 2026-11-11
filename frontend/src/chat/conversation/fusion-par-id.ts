/*
 * Fusion par identifiant d'une liste relue du serveur. Un élément inchangé garde son ancienne
 * identité d'objet, et une liste identique garde son ancien tableau : une relecture périodique ne
 * provoque donc aucun rendu, et les nœuds ne sont ni recréés ni rejoués.
 */

export function memeContenu(a: unknown, b: unknown): boolean {
  return JSON.stringify(a) === JSON.stringify(b);
}

export function fusionnerParId<T extends { readonly id: string }>(actuels: T[], recus: T[]): T[] {
  const anciens = new Map<string, T>(actuels.map((element): [string, T] => [element.id, element]));
  const fusion = recus.map((recu): T => {
    const ancien = anciens.get(recu.id);
    return ancien !== undefined && memeContenu(ancien, recu) ? ancien : recu;
  });
  const identique = fusion.length === actuels.length && fusion.every((element, i) => element === actuels[i]);
  return identique ? actuels : fusion;
}
