# Architecture — EchoHub v2

## Périmètre du MVP

**Dans le MVP :**

| Domaine | Ce qu'il fait |
|---|---|
| `system` | Détecte matériel et plateforme : GPU, VRAM, RAM, WSL2 ou Linux natif, pilote |
| `engines` | Installe et gère llama.cpp et vLLM, leurs versions et venvs |
| `models` | Cherche sur Hugging Face, télécharge, lit les métadonnées GGUF, tient le registre local |
| `inference` | **Planificateur de chargement** + pilotage des moteurs + génération |
| `chat` | Conversations, streaming des réponses, persistance |

**Hors MVP, volontairement** — à ne pas commencer, à ne pas préparer « au cas où » : RAG et
ChromaDB, skills MCP, connecteurs (Discord), fine-tuning, recherche web.

**Exception unique** : le service SearXNG figure dans `docker-compose.yml` sous un profil Docker
**inactif par défaut**. Il ne démarre pas, ne consomme rien, et évite d'avoir à retoucher
l'infrastructure quand la recherche web arrivera.

## Le cœur : le planificateur de chargement

C'est la raison d'être de la v2. Un module unique, **seule source de vérité**, qui répond à une
question : *comment charger ce modèle sur cette machine, maintenant ?*

```
plan = planifier(chemin_modele, preferences_utilisateur)
  → couches_gpu, contexte, batch, type_kv_cache, moteur, variables d'environnement
  → plus la justification de chaque valeur, affichable à l'utilisateur
```

Il **mesure** au lieu de supposer :

1. métadonnées réelles du GGUF — architecture, `block_count`, taille sur disque ;
2. VRAM et RAM réellement libres au moment du chargement ;
3. plateforme et ses contraintes (voir `COMPATIBILITE-GPU.md`) ;
4. préférences explicites de l'utilisateur, **plafonnées** par ce que la machine permet.

Trois règles qui viennent directement des défauts mesurés sur la v1 :

- **Aucune constante magique.** Pas de « 150 Mo par couche », pas de paliers de paramètres. Toute
  valeur vient d'une lecture ou d'une mesure.
- **Aucune duplication.** Le frontend affiche le plan, il ne le recalcule jamais. Un seul endroit
  décide, partout.
- **Dégradation, jamais escalade.** Un échec produit un plan plus conservateur, jusqu'à un mode
  minimal garanti de fonctionner.

Le planificateur doit être **testable sans GPU** : on lui injecte des métadonnées et un budget
mémoire, on vérifie le plan produit. C'était impossible en v1, d'où les défauts non détectés.

## Structure — par domaine, jamais par couche technique

```
backend/
  system/      détection matériel et plateforme
  engines/     installation et versions de llama.cpp et vLLM
  models/      recherche, téléchargement, métadonnées GGUF, registre
  inference/   planificateur, adaptateurs de moteurs, génération
  chat/        conversations et persistance
  outils/      outils du modèle (exécution, fichiers, recherche) + pont vers l'atelier + garde-fous
  projets/     mode projet : dossiers de l'hôte confiés à une conversation, instantanés git
  agent/       maison de l'agent PARTAGÉE entre ses conversations : SYSTEM.md, mémoire, skills,
               AWARENESS.md, mcp.json — stockage et index seulement ; les OUTILS qui s'en servent
               vivent dans outils/ (agent/ n'importe jamais outils/)
  core/        config, logging, erreurs, base de données
atelier/       conteneur d'exécution root persistant (Dockerfile, serveur HTTP, README)
frontend/src/
  models/      écrans de découverte et gestion des modèles
  chat/        écran de conversation
  system/      matériel, moteurs, réglages
  shared/      design system, composants, client API
```

Chaque domaine expose une interface publique. Un domaine n'importe jamais les internes d'un autre.

## L'atelier d'exécution — une frontière de conteneur, pas un bac dans le backend

Les outils `executer_commande` et `executer_python` (domaine `outils`) n'exécutent plus rien dans le
backend. L'exécution vit dans un **conteneur de dev séparé et persistant**, `echohub-atelier`
(dossier `atelier/` à la racine : `Dockerfile`, `serveur.py`, `README.md`). L'agent y est **root**,
avec réseau, PATH complet et toolchain ; il installe ce qui lui manque (`apt`, `pip`), et fichiers
comme paquets **persistent**.

Pourquoi ce déplacement : l'ancien confinement (`setuid` + `rlimits` + PATH minimal, dans
`bac_a_sable.py`) protégeait l'hôte au prix de rendre l'outil inerte dès qu'il fallait installer quoi
que ce soit (mesuré : `nasm: command not found`). Le confinement n'a pas disparu, il s'est **déplacé
vers la frontière du conteneur** : aucun chemin de l'hôte monté, aucun `docker.sock`, ressources
bornées par Compose (`mem_limit`, `cpus`, `pids_limit`).

**Mécanisme d'exécution — HTTP interne, pas `docker.sock`.** Le backend parle à l'atelier par un
petit service HTTP (`atelier/serveur.py`, FastAPI), sur le réseau interne de la pile (port **jamais
publié**), gardé par un jeton partagé (`ATELIER_JETON`). Le client backend est
`backend/outils/atelier.py` ; `backend/outils/bac_a_sable.py` n'est plus qu'un pont qui traduit le
`racine_bac` d'une conversation en dossier de l'atelier et délègue. Monter `docker.sock` dans le
backend aurait donné root sur l'hôte à un backend qui exécute du texte de modèle — écarté pour cette
raison.

**Workspace partagé.** Un volume nommé (`echohub_ateliers`) est monté dans le backend
(`/data/ateliers`, = `settings.atelier_workspace`) **et** dans l'atelier (`/workspace`). Le `racine_bac`
d'une conversation est `atelier_workspace/<conversation_id>` ; l'atelier le voit sous
`/workspace/<conversation_id>`. C'est le même dossier : un fichier écrit par `ecrire_fichier` (backend)
est vu du shell de l'atelier, et un fichier produit par une commande de l'atelier est balayé
(`balayage_bac.py`) et rattaché à la conversation comme pièce jointe (`origine='modele'`).

**Repli.** Atelier injoignable → les outils rendent un message actionnable (« démarrer avec
`docker compose up -d echohub-atelier` »), journalisé (loguru), jamais un timeout muet ni un crash.

## Le mode projet — un dossier de l'hôte confié à une conversation

Une conversation peut recevoir un **projet** : un sous-dossier direct de la racine
`ECHOHUB_PROJETS_RACINE` (dossier de l'hôte, monté dans l'atelier sous `/projets`). Le modèle y
construit une application complète — fichiers, dépendances, build, tests, serveur de dev — au lieu de
travailler dans son bac de conversation.

- **Liaison** : colonne `chat_reglages.projet` (NULL = conversation ordinaire), routes
  `GET/PATCH /chat/conversations/{id}/projet`. Le nom est validé par `projets.chemin_projet` (motif
  `[a-z0-9][a-z0-9._-]*`, sous-dossier DIRECT de la racine, lien symbolique sortant refusé).
- **Exécution** : `RequeteGeneration.projet` → `inference._contexte_execution` pose `racine_bac` sur le
  dossier du projet. `bac_a_sable.emplacement_atelier` reconnaît un bac sous la racine des projets et
  l'envoie à l'atelier en `racine="projets"`. En mode projet, ni balayage ni dépôt dans le magasin :
  le projet sur disque EST le livrable (un `bun install` ne doit pas produire 30 000 cartes).
- **Garde-fous** (`outils/garde_fous.py`, pur, testé) : appliqués à toute commande, tout code Python
  et tout lancement de fond, avec ou sans projet. Refusent : sortie du dossier (`..`, `/projets/autre`,
  `/workspace/autre`, `cd / && rm …`), suppressions globales (`rm -rf .`/`*`/`/`), le dossier réservé
  `.echohub`, la publication (`git push`, `npm publish`), `ssh`/`scp`, `pkill`/`killall`/`kill 1`,
  `shutdown`, `mkfs`, `dd of=/dev`, `docker`/`systemctl`. **Limite assumée** : analyse lexicale, une
  indirection (`X=/projets; rm -rf $X/b`) passe. La frontière dure reste le conteneur (il ne voit que
  son volume et la racine des projets) ; le filet, ce sont les instantanés.
- **Instantanés** (`projets/instantanes.py`) : dépôt git SÉPARÉ `<projet>/.echohub/instantanes.git`
  (le `.git` du projet n'est jamais touché), commit pris par le harnais **avant chaque tour**
  (`chat.generation._instantane_projet`), dépendances et builds exclus. Restaurer prend d'abord un
  instantané de l'état courant : une restauration s'annule.
- **Processus de fond** (`atelier/processus.py`, outil `serveur_fond`) : serveurs de dev détachés dans
  leur groupe de processus, journal hors du dossier de travail, 5 par dossier au plus.
- **Aperçu** (`atelier/apercu.py`, `backend/projets/apercu.py`, `chat/projet/SectionApercu.tsx`) : un
  relais dans l'atelier écoute sur 8090 (publié `127.0.0.1:${ATELIER_APERCU_PORT_HOTE:-37924}`) et
  sert À LA RACINE le port qu'on lui désigne — les chemins absolus d'une SPA marchent. Le backend
  ne relaie aucun octet : il pointe le relais (`POST /projets/{nom}/apercu`) et rend l'URL
  (`ATELIER_APERCU_URL`). Un seul aperçu pour tout l'atelier ; pas de WebSocket (HMR de Vite absent).
- **Socle** : bloc `_MODE_PROJET` (règles + méthode de travail : regarder, planifier en tâches
  `suivre_taches`, CHERCHER avant de lire, corriger partout, écrire groupé, étapes VÉRIFIÉES, tout lancer
  soi-même, commandes non interactives, README, bilan honnête, et NOS NORMES DE CODE : fichier < 500
  lignes, fonction < 35, par domaine et non par couche, types obligatoires, try/except journalisé, venv/Bun,
  tests unitaires). Le socle dit aussi qu'il n'y a pas de
  petite borne d'appels : sous FORGE, aucun compte à rebours (`budget_outils`), seul le garde-fou absolu
  (200 tours) est annoncé.
- **Conduite de fin de tour** (`inference/fin_projet.py`, `suivi_taches.py`) : un tour sans appel est
  relancé s'il est une pause, une annonce, un faux bilan, un fichier recopié dans le chat, ou s'il
  laisse une tâche ouverte ; chaque relance en mode projet cite le dernier appel et son erreur.
- **Panneau Fichiers** (`backend/projets/contenu.py`, `instantanes.modifications/diff`,
  `chat/projet/PanneauFichiers.tsx`) : arborescence et lecture lues sur le disque de l'hôte ;
  modifications et diff calculés dans l'atelier contre le dernier instantané (donc le tour courant).
- **Propriétaire** : l'agent est root dans l'atelier ; `ATELIER_PROPRIETAIRE=uid:gid` rétrocède ce
  qu'il crée (`find ! -user … -exec chown`) pour que le backend natif et l'utilisateur gardent la main.

**Mode natif.** Même en natif, l'exécution passe par le conteneur atelier, publié sur `127.0.0.1`
seulement (`ATELIER_URL=http://127.0.0.1:37923`, jeton obligatoire) et démarré par `start.sh`.
Workspace et projets y sont des chemins de l'hôte (`ECHOHUB_ATELIERS_HOTE`, `ECHOHUB_PROJETS_HOTE`).

## L'auto-compaction du contexte — non destructive, réduit ce qui part AU MOTEUR

Prérequis d'un futur mode agent longue durée : sans elle, une session longue tronque en silence son
contexte et perd sa tâche. La discipline est celle du harnais d'outils — **ce que l'utilisateur voit
et ce qui est enregistré en base ne sont JAMAIS touchés** ; seul le flux envoyé au moteur est réduit.

**Déclenchement (règle de Quart, 2026-10-02, `backend/core/politique_compaction.py`, source unique).**
Seuil d'ÉTAPE min(120 k, 40 % de la fenêtre), seuil DUR min(350 k, 70 %). Deux points d'application :
- au départ d'un message (`chat/generation.py::_compacter_si_besoin`) — un nouveau message suit un tour
  terminé, donc le seuil d'étape s'applique ;
- PENDANT une tâche d'agent (`inference/compaction_boucle.py`), après chaque tour d'outil : seuil
  d'étape quand une tâche `suivre_taches` vient de se fermer, seuil dur sinon. Socle, demande (repérée
  par identité, jamais une relance) et queue récente (coupée sur un tour d'assistant) restent intacts ;
  la liste de tâches est réinjectée dans le résumé.
Une occupation non mesurable ne déclenche rien. L'ancien seuil (90 %) ne se déclenchait jamais avant
« fenêtre pleine » sur une fenêtre de 262 k.

**Mesure.** Passe par le port d'inférence (`mesurer_occupation`), qui délègue à
`superviseur.compter_contexte` : le tokenizer du modèle réellement chargé, jamais un ratio
caractères/tokens. Le décompte inclut les définitions d'outils, envoyées à chaque tour. Le chemin
`llama-server` (MoE à experts déportés) expose son tokenizer via `/tokenize` — sans quoi la fenêtre
serait « non mesurable » et la compaction inerte.

**Résumé cumulatif orienté agent.** Produit par le modèle chargé
(`backend/inference/resume_compaction.py`) : il préserve OBJECTIF, ÉTAT, FICHIERS, DÉCISIONS, RESTE À
FAIRE — pas un résumé littéraire —, dans la langue de la conversation. Un résumé antérieur est
**englobé**, jamais oublié (`resume_precedent` passé au modèle). Le point de coupe est choisi par
dichotomie pour ramener la queue conservée intacte bien sous le seuil ; on garde toujours au moins
les 2 derniers messages.

**Ce qui part au moteur après compaction** = socle + un message système portant le résumé + les
messages récents gardés. Les messages compactés **restent en base** et dans ce que l'API rend.

**Persistance + événement.** Une balise est persistée (`chat_compactions`, additive) et émise :
- **en direct** dans le flux SSE via `EvenementCompaction` (`type: "compaction"`) ;
- **au rechargement**, portée par `MessageChat.compaction` du message assistant déclencheur, à sa
  place dans le fil — le rechargement montre la même chose que le direct.

### Contrat de la balise — figé, consommé par le web ET le mobile (`echo-centre` / `EchoHubNoyau`)

Événement SSE : `event: compaction`, charge JSON `{ "type": "compaction", "compaction": InfoCompaction }`.
`InfoCompaction` (identique dans `MessageChat.compaction` au rechargement) porte, noms de champs
**stables** :

| champ | type | sens |
|---|---|---|
| `id` | string | identifiant de la compaction |
| `conversation_id` | string | conversation |
| `message_id` | string | message assistant AU-DESSUS duquel la balise se pose |
| `coupe_message_id` | string | dernier message d'historique replié ; tout ce qui suit reste envoyé intact |
| `nb_messages_resumes` | int | nombre de messages du fil que le résumé remplace côté moteur (cumulatif) |
| `tokens_avant` | int | occupation juste avant la compaction |
| `tokens_apres` | int | occupation juste après |
| `contexte_total` | int | fenêtre servie par le moteur |
| `resume` | string | résumé cumulatif (repliable côté UI) |
| `cree_le` | datetime ISO | horodatage |

Le front pose la balise **juste avant** le message assistant `message_id`. La balise n'est PAS un
message assistant : c'est un événement de système, rendu distinct et sobre
(`frontend/src/chat/conversation/BaliseCompaction.tsx`).

## L'agent maison — ce qui l'encadre comme Claude Code (2026-10-02)

- **Maison** (`backend/agent/`, `ECHOHUB_AGENT_DIR`, Docker : `/data/agent` monté depuis l'hôte) :
  `SYSTEM.md` (ses instructions permanentes, éditées par Chris, injectées bornées), `memoire/` (un fait
  par fichier, en-tête `name`/`description`, index injecté), `skills/<nom>/SKILL.md` (liste injectée,
  corps lu à la demande), `AWARENESS.md` (régénéré depuis ce qui existe : outils, MCP, skills,
  projets, environnement ; JAMAIS injecté, lu par section), `mcp.json` (format Claude Code).
- **Accès** : préfixe `~agent/` dans `resoudre_dans_bac` (même confinement) ; écriture limitée à
  `memoire/`, `skills/`, `notes/` ; fichiers rendus à `ECHOHUB_AGENT_PROPRIETAIRE` (backend root).
- **Lecture structurée** : `plan_fichier` (sections + lignes), puis `lire_fichier` par plage.
- **MCP** (`outils/mcp_client.py`, `mcp_registre.py`) : client HTTP/stdio maison ; deux outils fixes
  `mcp_outils` / `mcp_appeler` (outils « différés » : coût de prompt constant). Service
  `echohub-navigateur` (Playwright MCP officiel) pour les tests e2e, snapshots texte.
- **Socle** : bloc `HOW YOU WORK` (penser bref puis agir, contexte d'abord, preuves, finir) commun à
  tous les modes outillés ; bloc maison ; bloc projet.
- **Modèle** : défauts Qwen3.6 (top_k 20, min_p 0, rep 1.0, temp 0.6, presence 0.5) ; dans la
  boucle, seule la réflexion du dernier tour est gardée (le gabarit purgeait tout à chaque relance).

## Stack

- **Backend** : Python 3.10, FastAPI, uvicorn, pydantic, loguru. Python est imposé par
  `llama-cpp-python` et vLLM, pas choisi.
- **Frontend** : React 18, TypeScript strict, Tailwind, Framer Motion.
- **Livraison** : Docker, nginx sert le frontend statique et proxifie `/api`.
- **Typage** : zéro `any`, types de retour explicites sur toute fonction publique.

`tsc` doit passer. La v1 avait trois erreurs TypeScript jamais vues parce que `bun run dev`
n'exécute pas `tsc` — le build de production les contournait au lieu de les corriger.

## Interface — exigence de niveau

L'interface est un livrable de premier plan, pas un habillage. Référence : Apple et Anthropic —
sobre, dense en information sans être chargée, cohérente jusque dans les détails.

- Thème sombre, palette sémantique : chaque couleur porte un sens, aucune couleur décorative.
- Typographie distinctive — ni Inter, ni Roboto.
- Le plan de chargement est **rendu lisible** : l'utilisateur voit pourquoi 28 couches et pas 41,
  ce que coûte un contexte de 57k. C'est la valeur qui distingue EchoHub d'un lanceur de modèles.
- Animations au service de la compréhension : transitions d'état, progression réelle. Jamais
  d'effet gratuit.

## Ce qui est repris de la v1

Le `Dockerfile` et son savoir de compilation CUDA — voir `COMPATIBILITE-GPU.md`. À **réintégrer
en comprenant chaque ligne**, pas à copier tel quel : la v1 vise une RTX 5090 32 Go, la machine
réelle est une 5080 16 Go.
