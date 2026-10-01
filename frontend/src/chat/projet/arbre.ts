/*
 * Arborescence d'un projet reconstruite depuis la liste plate des chemins rendue par le backend.
 * Fonction pure : les dossiers viennent avant les fichiers, chacun trié par nom.
 */

export interface NoeudArbre {
  readonly nom: string;
  readonly chemin: string;
  readonly enfants: readonly NoeudArbre[] | null;
  readonly taille: number;
}

interface NoeudMutable {
  nom: string;
  chemin: string;
  enfants: Map<string, NoeudMutable> | null;
  taille: number;
}

function figer(noeud: NoeudMutable): NoeudArbre {
  if (noeud.enfants === null) {
    return { nom: noeud.nom, chemin: noeud.chemin, enfants: null, taille: noeud.taille };
  }
  const enfants = [...noeud.enfants.values()].map(figer).sort((a, b) => {
    const dossierA = a.enfants !== null;
    const dossierB = b.enfants !== null;
    return dossierA === dossierB ? a.nom.localeCompare(b.nom) : dossierA ? -1 : 1;
  });
  return { nom: noeud.nom, chemin: noeud.chemin, enfants, taille: noeud.taille };
}

export function construireArbre(fichiers: readonly { chemin: string; taille: number }[]): readonly NoeudArbre[] {
  const racine: NoeudMutable = { nom: '', chemin: '', enfants: new Map(), taille: 0 };
  for (const fichier of fichiers) {
    const parties = fichier.chemin.split('/');
    let courant = racine;
    parties.forEach((partie, rang) => {
      const feuille = rang === parties.length - 1;
      const enfants = courant.enfants ?? new Map<string, NoeudMutable>();
      courant.enfants = enfants;
      const existant = enfants.get(partie);
      const chemin = parties.slice(0, rang + 1).join('/');
      const suivant = existant ?? { nom: partie, chemin, enfants: feuille ? null : new Map(), taille: 0 };
      if (feuille) {
        suivant.taille = fichier.taille;
      }
      enfants.set(partie, suivant);
      courant = suivant;
    });
  }
  return figer(racine).enfants ?? [];
}
