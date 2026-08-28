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
  outils/      outils du modèle (exécution, fichiers, recherche) + pont vers l'atelier
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

## L'auto-compaction du contexte — non destructive, réduit ce qui part AU MOTEUR

Prérequis d'un futur mode agent longue durée : sans elle, une session longue tronque en silence son
contexte et perd sa tâche. La discipline est celle du harnais d'outils — **ce que l'utilisateur voit
et ce qui est enregistré en base ne sont JAMAIS touchés** ; seul le flux envoyé au moteur est réduit.

**Déclenchement.** Avant chaque génération (`backend/chat/generation.py::_compacter_si_besoin`), on
mesure l'occupation de la fenêtre pour ce qui partirait au moteur (socle d'outils + définitions
d'outils + historique). Si `tokens_mesures >= SEUIL_COMPACTION × contexte_total` — **une seule
constante nommée, `SEUIL_COMPACTION = 0.90`** dans `backend/chat/compaction.py` — une compaction se
déclenche. Une occupation non mesurable (pas de tokenizer, moteur occupé) ne déclenche rien.

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
