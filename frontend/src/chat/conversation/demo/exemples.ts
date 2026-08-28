/*
 * Données d'exemple de la page de démonstration (`/demo.html`) et des tests purs.
 *
 * Elles existent parce que les écrans doivent être vérifiables SANS modèle chargé ni backend :
 * une conversation réelle ne montrerait ni l'outil en cours, ni l'échec, ni les versions
 * d'artefact — précisément les cas que la refonte doit couvrir. Le balisage est celui que le
 * backend émet réellement (`harnais_outils.py`) : ces textes sont aussi les fixtures des tests.
 */

import type { MessageChat, ResumeConversation } from '../../api/contrats';

const MODELE = 'jackrong/qwen3.5::Qwen3.5-9B-Claude-Opus-Distilled.Q4_K_M.gguf';

type SocleMessage = Partial<MessageChat> & Pick<MessageChat, 'id' | 'role' | 'contenu'>;

function message(partiel: SocleMessage): MessageChat {
  return {
    conversation_id: 'demo',
    tokens_generes: null,
    tokens_par_seconde: null,
    cree_le: '2026-08-26T14:31:00Z',
    modele_id: null,
    interrompu: false,
    parent_id: null,
    compaction: null,
    ...partiel,
  };
}

/* ---------------------------------------------------------------- scène : conversation */

const REPONSE_COMPARAISON = `<think>L'utilisateur veut un arbitrage concret pour une 3060 12 Go.
Points décisifs : VRAM, quantification GGUF, débit mesuré, simplicité d'intégration.
vLLM brille en batch/serving multi-clients, hors sujet ici.</think>Pour une RTX 3060 sur EchoHub, \
**llama.cpp** est le bon choix. Voici l'arbitrage :

| Critère | llama.cpp | vLLM |
|---|---|---|
| Quantification | GGUF Q4_K_M natif | AWQ/GPTQ, moins de choix 9B |
| VRAM pour un 9B | ~6,2 Go | ~9,5 Go |
| Déport RAM | par couches, natif | non |
| Multi-clients | limité | excellent |

Deux raisons tranchent :

1. **Le déport par couches** : quand le contexte grandit, le planificateur peut garder 28 couches
   sur 41 en VRAM et déporter le reste — vLLM refuse simplement de charger.
2. **Un seul utilisateur** : le batching continu de vLLM, son vrai atout, ne sert à rien ici.

\`\`\`bash
# ce que le plan émet au chargement
llama-server -m qwen3.5-9b.Q4_K_M.gguf -ngl 41 -c 32768 -fa
\`\`\`

Le débit mesuré sur cette machine : 41 tok/s à 8k de contexte, 19,6 tok/s à 57k.`;

const REPONSE_CONTEXTE = `À 57k, deux choses changent, et le panneau de droite les montre déjà :

- le **KV cache passe à ~4,1 Go** en f16 — c'est lui qui pousse des couches hors VRAM ;
- le débit mesuré tombe à **19,6 tok/s** (−52 %), parce que 13 couches passent sur le CPU.

Si tu veux garder les 41 couches en VRAM, le cache en \`q8_0\` divise ce coût par deux pour une
perte de qualité négligeable sur ce modèle.`;

export const MESSAGES_CONVERSATION: MessageChat[] = [
  message({
    id: 'c1',
    role: 'user',
    contenu: 'Compare llama.cpp et vLLM pour servir un 9B sur ma RTX 3060, et dis-moi lequel choisir pour EchoHub.',
    cree_le: '2026-08-26T14:29:12Z',
  }),
  message({
    id: 'c2',
    role: 'assistant',
    contenu: REPONSE_COMPARAISON,
    tokens_generes: 512,
    tokens_par_seconde: 31.4,
    modele_id: MODELE,
    cree_le: '2026-08-26T14:29:41Z',
  }),
  message({
    id: 'c3',
    role: 'user',
    contenu: 'Et si je monte le contexte à 57k ?',
    cree_le: '2026-08-26T14:31:02Z',
  }),
  message({
    id: 'c4',
    role: 'assistant',
    contenu: REPONSE_CONTEXTE,
    tokens_generes: 187,
    tokens_par_seconde: 19.6,
    modele_id: MODELE,
    cree_le: '2026-08-26T14:31:19Z',
  }),
];

/* ---------------------------------------------------------------- scène : outils */

const SORTIE_RECHERCHE = `1. LDLC — GeForce RTX 5090 32 Go : 2 199 € (stock)
2. Materiel.net — RTX 5090 Founders : 2 329 €
3. TopAchat — RTX 5090 OC : 2 449 €
4. Reddit r/FranceHardware — « les prix redescendent depuis juillet »
5. Dealabs — alerte à 2 099 € le 18/08, expirée
6. NVIDIA.com — page produit, prix conseillé 2 099 €`;

const SORTIE_LECTURE = `# comparatif.md
| Boutique | Prix | Stock |
|---|---|---|
| LDLC | 2 199 € | oui |
| Materiel.net | 2 329 € | oui |
| TopAchat | 2 449 € | oui |`;

export const MESSAGE_OUTILS: MessageChat = message({
  id: 'o1',
  role: 'assistant',
  contenu:
    `<think>Trois sources suffisent ; je vérifie d'abord les prix, puis je consigne le comparatif.</think>` +
    `Je cherche les prix actuels.<outil><entree>recherche_web(requete : prix RTX 5090 France août 2026)` +
    `</entree><sortie>${SORTIE_RECHERCHE}</sortie></outil>\n<etape-fin/>` +
    `Six résultats cohérents, j'écris le comparatif puis je tente la compilation du script de veille.` +
    `<outil><entree>ecrire_fichier(chemin : comparatif.md, contenu : # comparatif\n| Boutique | Prix |…)` +
    `</entree><sortie>Fichier écrit : comparatif.md (312 octets).</sortie></outil>` +
    `<outil><entree>executer_commande(commande : cargo build --release)</entree>` +
    `<sortie>Échec de l'outil : commande introuvable : cargo</sortie></outil>\n<etape-fin/>` +
    `<outil><entree>lire_fichier(chemin : comparatif.md)</entree><sortie>${SORTIE_LECTURE}</sortie></outil>` +
    `\n<etape-fin/>` +
    `\n\nLes prix se tiennent entre **2 199 €** et **2 449 €** ; LDLC est le mieux placé avec du stock.` +
    `\n\nLa compilation du script de veille a échoué : \`cargo\` n'est pas installé dans le bac — je peux` +
    ` le réécrire en Python si tu veux une alerte de prix.`,
  tokens_generes: 264,
  tokens_par_seconde: 28.7,
  modele_id: MODELE,
  cree_le: '2026-08-26T15:02:44Z',
});

export const MESSAGES_OUTILS: MessageChat[] = [
  message({
    id: 'o0',
    role: 'user',
    contenu: 'Trouve le prix actuel de la RTX 5090 en France et prépare un comparatif.',
    cree_le: '2026-08-26T15:02:12Z',
  }),
  MESSAGE_OUTILS,
  message({
    id: 'o2',
    role: 'user',
    contenu: 'Vas-y pour la version Python.',
    cree_le: '2026-08-26T15:04:01Z',
  }),
];

/** Brouillon de streaming : un appel dont la sortie n'est pas refermée — l'outil travaille. */
export const BROUILLON_OUTIL_EN_COURS =
  `<think>Je réécris la veille en Python avec urllib, sans dépendance.</think>` +
  `J'écris puis j'exécute le script.` +
  `<outil><entree>executer_python(code : import urllib.request\nimport json\n` +
  `PRIX_CIBLE = 2100\nurl = "https://…")</entree><sortie>`;

/* ---------------------------------------------------------------- scène : artefact */

export const CONTENUS_ARTEFACTS: Readonly<Record<string, string>> = {
  'fic-pong-v1': `<!doctype html><html><head><meta charset="utf-8"><style>
  body{margin:0;background:#e8e8f0;display:grid;place-items:center;height:100vh;font-family:monospace}
  canvas{background:#f8f8ff;border:1px solid #99a}
  h1{position:fixed;top:8px;color:#334}</style></head>
<body><h1>PONG</h1><canvas id="c" width="480" height="300"></canvas>
<script>const c=document.getElementById('c'),x=c.getContext('2d');let bx=240,by=150,dx=3,dy=2,p=130;
function t(){x.clearRect(0,0,480,300);x.fillStyle='#334';x.fillRect(10,p,8,60);x.fillRect(bx,by,10,10);
bx+=dx;by+=dy;if(by<0||by>290)dy=-dy;if(bx>470)dx=-dx;if(bx<18&&by>p&&by<p+60)dx=-dx;
if(bx<0){bx=240;by=150}requestAnimationFrame(t)}t();
addEventListener('mousemove',e=>{p=e.clientY-c.getBoundingClientRect().top-30});</script></body></html>`,
  'fic-pong-v2': `<!doctype html><html><head><meta charset="utf-8"><style>
  body{margin:0;background:#0b0b10;display:grid;place-items:center;height:100vh;font-family:monospace}
  canvas{background:#12121a;border:1px solid #2de2a3;box-shadow:0 0 24px #2de2a366}
  h1{position:fixed;top:8px;color:#2de2a3;text-shadow:0 0 8px #2de2a3}</style></head>
<body><h1>PONG</h1><canvas id="c" width="480" height="300"></canvas>
<script>const c=document.getElementById('c'),x=c.getContext('2d');let bx=240,by=150,dx=3,dy=2,p=130;
function t(){x.clearRect(0,0,480,300);x.fillStyle='#2de2a3';x.fillRect(10,p,8,60);x.fillRect(bx,by,10,10);
bx+=dx;by+=dy;if(by<0||by>290)dy=-dy;if(bx>470)dx=-dx;if(bx<18&&by>p&&by<p+60)dx=-dx;
if(bx<0){bx=240;by=150}requestAnimationFrame(t)}t();
addEventListener('mousemove',e=>{p=e.clientY-c.getBoundingClientRect().top-30});</script></body></html>`,
  'fic-notes-v1':
    '# Veille RTX 5090\n\n## Prix relevés (26/08)\n\n- LDLC : **2 199 €**\n- Materiel.net : 2 329 €\n\n' +
    '> Les prix redescendent depuis juillet — r/FranceHardware\n\nProchaine étape : automatiser le relevé.',
};

function sortieArtefact(id: string, version: number, titre: string, type: string, fichier: string): string {
  return JSON.stringify({
    artefact_id: id,
    version,
    titre,
    type,
    langage: null,
    fichier_id: fichier,
    taille_octets: (CONTENUS_ARTEFACTS[fichier] ?? '').length,
  });
}

export const MESSAGES_ARTEFACT: MessageChat[] = [
  message({
    id: 'a0',
    role: 'user',
    contenu: 'Fais-moi un petit Pong jouable en HTML, un seul fichier.',
    cree_le: '2026-08-26T16:10:05Z',
  }),
  message({
    id: 'a1',
    role: 'assistant',
    contenu:
      `<think>Canvas seul, zéro dépendance, raquette à la souris.</think>` +
      `<outil><entree>creer_artefact(titre : Pong néon, type : html, contenu : <!doctype html>…)` +
      `</entree><sortie>${sortieArtefact('art-pong', 1, 'Pong néon', 'html', 'fic-pong-v1')}</sortie></outil>` +
      `\n<etape-fin/>\n\nLe Pong est prêt — raquette à la souris, balle qui accélère. Dis-moi si le` +
      ` rendu te va.`,
    tokens_generes: 402,
    tokens_par_seconde: 30.1,
    modele_id: MODELE,
    cree_le: '2026-08-26T16:10:38Z',
  }),
  message({
    id: 'a2',
    role: 'user',
    contenu: 'Le fond est trop clair — passe-le en sombre, avec un accent néon.',
    cree_le: '2026-08-26T16:11:20Z',
  }),
  message({
    id: 'a3',
    role: 'assistant',
    contenu:
      `<outil><entree>creer_artefact(titre : Pong néon, type : html, contenu : <!doctype html>…)` +
      `</entree><sortie>${sortieArtefact('art-pong', 2, 'Pong néon', 'html', 'fic-pong-v2')}</sortie></outil>` +
      `\n<etape-fin/>\n\nFond sombre, raquette et balle en vert néon avec un halo léger. La v1 reste` +
      ` consultable dans le sélecteur de versions.`,
    tokens_generes: 385,
    tokens_par_seconde: 29.4,
    modele_id: MODELE,
    cree_le: '2026-08-26T16:11:52Z',
  }),
  message({
    id: 'a4',
    role: 'assistant',
    contenu:
      `<outil><entree>creer_artefact(titre : Veille RTX 5090, type : markdown, contenu : # Veille…)` +
      `</entree><sortie>${sortieArtefact('art-notes', 1, 'Veille RTX 5090', 'markdown', 'fic-notes-v1')}` +
      `</sortie></outil>\n<etape-fin/>\n\nJ'ai aussi consigné la veille de prix en document séparé.`,
    tokens_generes: 118,
    tokens_par_seconde: 30.8,
    modele_id: MODELE,
    cree_le: '2026-08-26T16:12:30Z',
  }),
];

/* ---------------------------------------------------------------- scène : liste */

function conversation(partiel: Partial<ResumeConversation> & Pick<ResumeConversation, 'id' | 'titre'>):
  ResumeConversation {
  return {
    modele_id: MODELE,
    cree_le: '2026-08-20T09:00:00Z',
    maj_le: '2026-08-26T12:00:00Z',
    archivee: false,
    nb_messages: 6,
    ...partiel,
  };
}

const RECENT = Date.now();
const iso = (ilYaMs: number): string => new Date(RECENT - ilYaMs).toISOString();

export const CONVERSATIONS_DEMO: ResumeConversation[] = [
  conversation({ id: 'v1', titre: 'Pong néon en HTML', nb_messages: 5, maj_le: iso(4 * 60_000) }),
  conversation({ id: 'v2', titre: 'llama.cpp ou vLLM sur 3060', nb_messages: 4, maj_le: iso(2 * 3_600_000) }),
  conversation({ id: 'v3', titre: 'Veille prix RTX 5090', nb_messages: 12, maj_le: iso(26 * 3_600_000) }),
  conversation({ id: 'v4', titre: 'Refonte du prompt système', nb_messages: 9, maj_le: iso(4 * 86_400_000) }),
];

export const ARCHIVEES_DEMO: ResumeConversation[] = [
  conversation({
    id: 'v9',
    titre: 'Tests quantification Q3',
    nb_messages: 22,
    archivee: true,
    maj_le: iso(12 * 86_400_000),
  }),
  conversation({
    id: 'v10',
    titre: 'Migration WSL2 → natif',
    nb_messages: 7,
    archivee: true,
    maj_le: iso(30 * 86_400_000),
  }),
];
