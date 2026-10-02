/*
 * Accès HTTP du domaine retours. Client minimal propre au domaine : il ne dépend pas des internes
 * du chat, qui peuvent changer sans prévenir.
 */

export type Verdict = 'positif' | 'negatif' | 'correction' | 'meilleure' | 'pire';

/** Défauts qu'aucun contrôle automatique ne voit (CTA, longueur, interdits, recopie : mesurés à l'export). */
export type Raison =
  | 'accroche_faible'
  | 'ton'
  | 'fait_invente'
  | 'cliche_ia'
  | 'francais'
  | 'generique'
  | 'hors_brief'
  | 'structure';

export interface ResumeRetours {
  total: number;
  positifs: number;
  negatifs: number;
  corrections: number;
  comparaisons: number;
  par_message: Record<string, Verdict>;
  raisons_par_message: Record<string, Raison[]>;
  /** Verdicts posés par Claude via le MCP accroche, affichés à part : ils ne remplacent jamais ceux de Chris. */
  claude_par_message: Record<string, Verdict>;
  par_source: Record<string, number>;
}

export interface DemandeRetour {
  conversation_id: string;
  message_id: string;
  verdict: Verdict;
  correction?: string;
  raisons?: Raison[];
}

async function lire<T>(reponse: Response): Promise<T> {
  if (!reponse.ok) {
    const corps = await reponse.text();
    throw new Error(`Retour refusé (${reponse.status}) : ${corps.slice(0, 200)}`);
  }
  return (await reponse.json()) as T;
}

export async function lireRetours(conversationId: string): Promise<ResumeRetours> {
  const reponse = await fetch(`/api/retours?conversation_id=${encodeURIComponent(conversationId)}`);
  return lire<ResumeRetours>(reponse);
}

export async function envoyerRetour(demande: DemandeRetour): Promise<void> {
  const reponse = await fetch('/api/retours', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(demande),
  });
  await lire<unknown>(reponse);
}

export async function retirerRetour(messageId: string): Promise<void> {
  const reponse = await fetch(`/api/retours/${encodeURIComponent(messageId)}`, { method: 'DELETE' });
  await lire<unknown>(reponse);
}
