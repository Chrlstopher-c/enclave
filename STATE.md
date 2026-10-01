# STATE — EchoHub v2


## Session du 2026-10-02 — Autonomie de l'agent en mode projet (branche `agent-autonomie`)

Né de captures de Chris (projet `spoofer`) : boucle « I keep announcing… let me batch », lecture de
tous les fichiers pour une erreur, fichier recopié dans le chat au lieu d'écrit.
- **Plus de compte à rebours** : FORGE n'avertit plus « 1 appel restant » tous les 10 tours (cause de la
  boucle) ; le socle dit qu'il n'y a pas de petite borne. Seul le garde-fou absolu (200) est annoncé.
- **Outils** : `ecrire_fichiers` (groupé), `lire_fichier` avec `ligne_fin`, `suivre_taches` (liste de
  tâches ; le tour ne finit pas sur une tâche ouverte, 3 relances sans progrès), avis de syntaxe
  Python/JSON à chaque écriture.
- **Socle** : méthodes de travail — chercher (`chercher_dans_fichiers`/grep) avant de lire, corriger
  partout d'un coup, écrire groupé, relancer la même vérification, tout lancer soi-même.
- **Relances** : fichier recopié dans le chat (bloc de code ≥ 8 lignes, hors shell) relancé ; toute
  relance de mode projet cite le dernier appel et la fin de son erreur.
- **UI** : bouton « Fichiers » de l'en-tête (projet lié) → panneau repliable : arborescence, lecture,
  modifications depuis le dernier instantané avec diff coloré, relu toutes les 4 s.
- Radotage par similarité ESSAYÉ puis retiré : deux annonces consécutives se ressemblent toujours, la
  consigne de radotage (« dis ce qui bloque et arrête ») aurait remplacé les relances escaladées.
- Effet sur le modèle NON mesuré : l'essai est réservé à Chris.

## Session du 2026-10-01 — Mode projet : un dossier de l'hôte confié à une conversation

**Objectif (Chris).** Dans un chat, donner au modèle un accès RESTREINT à un dossier pour qu'il y
génère une application complète, avec des règles contre les dérapages.

**Construit.** Détails et contrats dans `ARCHITECTURE.md` (§ Le mode projet).
- Domaine `backend/projets/` : racine `ECHOHUB_PROJETS_RACINE` (tour : `/mnt/projects/echohub-projets`),
  projets = sous-dossiers directs au nom contraint, routes `/projets` (catalogue, création,
  instantanés, restauration). Liaison conversation ↔ projet : `chat_reglages.projet`,
  `GET/PATCH /chat/conversations/{id}/projet`.
- Instantanés git SÉPARÉS (`<projet>/.echohub/instantanes.git`) pris avant chaque tour ; restauration
  annulable (filet pris avant). Prouvé avec git réel (`projets/tests`).
- Garde-fous lexicaux `outils/garde_fous.py` sur toute commande / code / lancement de fond (35 cas).
- Outil `serveur_fond` + `atelier/processus.py` : serveurs de dev en arrière-plan, testables au curl.
- Outils : lecture par tranches (`ligne_debut`), listage élagué (node_modules, venv, dist…), pas de
  balayage ni de cartes en mode projet. Socle : bloc `_MODE_PROJET` (règles + méthode).
- Frontend : bouton dossier dans l'en-tête (nom du projet visible en permanence), `chat/projet/`
  (modale : confier/créer, règles affichées, instantanés avec restauration à confirmation).
- **Atelier opérationnel en natif** (il n'existait pas sur la tour : les outils d'exécution étaient
  inertes) : publié sur `127.0.0.1:37923`, démarré par `start.sh`, Node 22 + Bun ajoutés à l'image,
  `ATELIER_PROPRIETAIRE=1000:1000` rétrocède les fichiers créés par root.

**Corrections nécessaires en chemin.**
- Harnais FORGE : `extensions < None` levait TypeError au 10ᵉ tour d'outils — tuait toute tâche
  longue (`inference/__init__._restants_nuls`).
- `RequeteGeneration` ne portait pas `outils_actifs` : le moteur déclarait TOUS les outils quelle que
  soit la sélection (seul le socle la respectait). Corrigé avec le champ `projet`.
- Tests : `backend/conftest.py` neutralise le `.env` du poste (ses chemins réels fuyaient dans les
  tests) ; 3 tests figés sur le harnais d'origine ; 3 cas multimodaux sautés sans llama-cpp (CI).
- `start.sh` : `--reload-exclude '*/tests/*'`. **Piège mesuré** : en natif, toute sauvegarde dans
  `backend/` déclenche un reload qui ATTEND la fin de la génération en cours — l'API ne répond plus
  pendant ce temps (« backend injoignable »). Ne pas éditer le backend pendant une génération.

**Harnais en mode projet** (`inference/fin_projet.py`, `harnais.py`, `reprise.py`) — mesuré sur des
essais réels (projet `todo-final`), chaque règle née d'un arrêt constaté :
- quota de 6 relances sur annonce, RÉARMÉ à chaque appel joué ; borne globale = `tours_absolus_max` ;
- pause sans bilan (< 400 car. visibles) après un appel, réussi OU échoué, relancée ;
- bilan dont le « reste à faire » contient une action jouable (bloc shell, curl, pytest, serveur_fond)
  relancé 2 fois max, sans réarmement ;
- fin au futur proche (« je vais… », « laissez-moi… », « let me… ») = annonce, quel que soit le verbe ;
- chemins `todo-final/main.py` ou `/projets/todo-final/main.py` ramenés au bac (`_relatif_au_bac`).

**Modèle.** `huihui-ai/Huihui-Qwen3.6-35B-A3B-Claude-4.7-Opus-abliterated-MTP-GGUF` Q5_K (+ mmproj),
même base que `mudler/…APEX` mais non censuré : 5 sondes de refus anodines → mudler 5/5 refus,
huihui 5/5 réponses. ~14 tok/s. Chargé via l'UI (Modèles → Sur le disque → 2ᵉ « Charger »).

**Résultat de bout en bout (honnête).** Le modèle travaille en autonomie (26 appels d'affilée,
pytest → lecture → correction → pytest), le projet est passé de 2/9 à 8/9 tests verts en 4 tours,
mais il n'a PAS fini seul : 1 test rouge, et l'app répond 500 (base SQLite `:memory:` partagée mal
initialisée). La chaîne `serveur_fond` → curl dans l'atelier → arrêt est vérifiée à la main. La limite
restante est le modèle sur la dernière ligne droite (il épuise ses relances en pauses sans appel).

**Recherche web en natif.** SearXNG publié sur `127.0.0.1:37925` (`SEARXNG_URL` du `.env`) : le
backend hors Docker ne résout pas `searxng`. Conteneur `restart: unless-stopped`.

**Relance nommée.** En mode projet, toute relance (pause, annonce, tour muet, reste faisable) cite le
dernier appel joué et, s'il a échoué, la fin de sa sortie (`DernierAppel`, `fin_projet.py`). Effet sur
le modèle pas encore mesuré.

**Tests.** 568 verts (`backend/.venv/bin/python -m pytest -q backend`), build frontend OK, CI verte.

*Dernière mise à jour : 2026-10-01*

## Session du 2026-08-28 — Atelier d'exécution persistant (branche `atelier`)

Remplacement du bac confiné (`setuid` + `rlimits` + PATH minimal) par un **conteneur atelier** de dev,
persistant et unique, où l'agent est root avec réseau, PATH complet et `apt`/`pip`. Motivation : le
confinement rendait l'outil inerte (mesuré le 2026-08-26 : `nasm: command not found`, pip sans droit
d'écriture). Le confinement vis-à-vis de l'hôte n'a pas disparu, il s'est déplacé vers la **frontière
du conteneur** (aucun chemin hôte monté, aucun `docker.sock`, ressources bornées par Compose).

**Ce qui a été construit :**
- `atelier/` : service HTTP FastAPI (`serveur.py`) + `Dockerfile` (Ubuntu 24.04, toolchain, sans
  `nasm` — c'est le cas de preuve) + `README.md`. Service non publié, gardé par jeton `ATELIER_JETON`
  (repli fermé : sans jeton, exécution refusée).
- `docker-compose.yml` : service `echohub-atelier` (`restart: unless-stopped`, `mem_limit 4g`,
  `cpus 4`, `pids_limit 512`), volume partagé `echohub_ateliers` monté dans le backend
  (`/data/ateliers`) et l'atelier (`/workspace`).
- Backend : `outils/atelier.py` (client HTTP), `bac_a_sable.py` réduit à un pont (traduit
  `racine_bac`→`sous_dossier`, délègue, repli propre), `config.py` (réglages `atelier_*`),
  `_contexte_execution` pointe `racine_bac` sur le workspace partagé. Descriptions d'outils + socle +
  `LIMITES_REELLES_TEXTE` disent la vérité (root, persistance, install).

**Choix du mécanisme :** HTTP interne + jeton plutôt que `docker.sock` — le socket Docker = root sur
l'hôte, surface d'attaque inacceptable pour un backend qui exécute du texte de modèle.

**Persistance :** le volume couvre `/workspace` (fichiers + venv). Les paquets `apt` (dans `/usr`)
survivent aux `restart`/`stop`/`start`, sont perdus à un `build`/`down` (refaire un `apt install`
alors est acceptable).

**Preuve de bout en bout (chemin de chat réel) :** génération sur la conversation
`4ec18f4d-…` avec le modèle `Qwen3.6-35B-A3B-…APEX-I-Nano.gguf`. Le modèle a émis
`ecrire_fichier hello.asm` → `executer_commande: apt-get update && apt-get install -y nasm`
(`Code de retour : 0`) → `nasm -f elf64 … && ld …` → `./hello` affichant `Hello, world!`. Le binaire
`hello` (ELF 8872 o) atterrit dans `/data/ateliers/<conv>/` (vu du backend via le volume partagé).
Balayage : `hello.asm` et un `.txt` de commande (`echo > rapport_commande.txt`) rattachés à la
conversation (`origine=modele`). Le binaire ELF est filtré par la liste blanche MIME du magasin
(politique préexistante, inchangée). Repli vérifié : atelier arrêté → message actionnable, pas de
crash. nasm persiste après stop/start.

**Tests :** 12 tests de contrat neufs verts (`test_bac_a_sable.py` réécrit, `test_atelier.py` neuf,
mock à la frontière `atelier`). `test_contexte_execution_outil` adapté au nouveau `racine_bac`.
Aucune régression (suite : 369 passés vs 360 sur `main`). *Réserve* : ~95 erreurs de suite
préexistantes et identiques sur `main` — bug d'ordre dans `core/db.py` (`init_db` ALTER
`chat_reglages` avant que la table chat existe) ; hors scope atelier, non corrigé.

## Résumé de l'état antérieur (2026-08-17)

L'application tourne, en Docker, sur RTX 5080 16 Go / WSL2. On charge un modèle GGUF depuis un plan
calculé, on discute avec, il appelle réellement des outils, exécute du Python confiné, écrit et
édite des fichiers dans son bac, et les présente dans le fil en artefacts cliquables.

**8 domaines backend montés**, **413 tests Python verts**, typage TypeScript strict sans `any`.
Accès local, LAN (`http://10.0.0.6:37820`) et **distant** depuis le 2026-08-16 : authentification
HTTP dans nginx, tunnel Cloudflare sans droits administrateur. L'interface est utilisable au
téléphone depuis le 2026-08-15, et une génération y survit désormais à la mise en veille.

Six outils sont déclarés au modèle, dans l'ordre de la boucle de travail : `recherche_web`,
`ecrire_fichier`, `lire_fichier`, `modifier_fichier`, `executer_python`, `presenter_fichier`.

## Contexte non-évident

**Quatre hypothèses réfutées le même jour, toutes par la même erreur de raisonnement.** J'ai
supposé que `q2_0` libérerait la VRAM (il tue le processus), que les couches sur CPU coûtaient la
vitesse (+1 % entre 26 et 29 couches), que le modèle tournait à 10–20 tok/s (28–35 mesurés), et que
l'imatrix serait un gain quasi gratuit (−25 % de vitesse, gain non démontré). Cause commune : je
raisonnais sur une architecture DENSE alors que ce modèle est un MoE **A3B**, 3 milliards de
paramètres actifs par token. Une couche restée sur CPU n'y active presque aucun expert, donc elle ne
coûte presque rien — et c'est aussi ce qui rendrait coûteux le passage à un 27B dense.

**Un type ggml qui existe n'est pas pour autant servable comme cache KV.** `q2_0` et `q1_0` sont
exposés par le binaire, mais CUDA n'implémente pas `SET_ROWS` pour eux : le chargement meurt en
`ggml_abort()`, SIGABRT non rattrapable. La table de quatre types n'était pas un oubli, c'était une
liste de types VALIDÉS — élargie parce qu'ils « existaient », elle a tué le backend. Un type ne s'y
ajoute qu'après un chargement ET une génération réels.

**Le harnais peut coûter plus cher que le modèle.** Mesure du 2026-08-16 : le modèle émet
`ecrire_fichier` avec le contenu entier du fichier — 12 173 caractères de HTML valide — et un
argument `nom` au lieu de `chemin`. Le harnais répond « Aucun chemin fourni » et jette tout. Le
modèle réémet alors un appel VIDE, trois tours de suite, puis annonce à l'utilisateur un fichier
inexistant et une carte qui n'est pas affichée. Un seul refus de synonyme a produit toute la
cascade. Règle qui en découle : quand l'intention d'un appel est lisible, le harnais la sert.

**Retirer ses outils au modèle après un tour l'empêchait de finir sa tâche.** Renversement du
2026-08-16, imposé par la mesure. Les outils n'étaient déclarés qu'au PREMIER tour (L10-b), pour
qu'un modèle ne redemande pas sans fin un outil dont il a déjà le résultat. Mesuré sur le MoE 35B,
contexte servi de 131 072 tokens dont 18 835 occupés — donc sans aucune contrainte de fenêtre : le
modèle appelle `lire_fichier`, apprend que le fichier n'existe pas, annonce « je repars de zéro,
voici la nouvelle version »… et s'arrête. Il n'avait pas renoncé : `ecrire_fichier` ne lui était
plus déclaré. C'est le symptôme « ça coupe alors que le contexte est large ».

La boucle que le socle DEMANDE compte plusieurs appels enchaînés — écrire, exécuter, relire,
corriger, présenter. `TOURS_OUTILS_MAX` passe donc de 3 à 6, et les outils restent déclarés à chaque
tour. Mesure avant/après sur la MÊME demande, même modèle, même conversation : 758 caractères et un
seul outil, contre **19 469 caractères et trois outils enchaînés** — le modèle écrit désormais ses
deux fichiers, les relit, et termine sa réponse. Ce que L10-b protégeait est couvert ailleurs et mieux ciblé : cette borne, l'anti-redite sur
les appels échoués, et le retrait du balisage d'appel de l'historique.

**Tout format que le harnais laisse dans le contexte finit imité.** Deux fois : le préfixe
`[outil nom — résultat]`, puis le balisage `<function=…>` d'un appel raté. Ce qui revient au modèle
comme étant son propre texte lui sert d'exemple de ce qu'il a « bien » fait.

**La fenêtre saturait, et c'était la cause.** MESURÉ le 2026-08-16 sur la conversation réelle :
48 461 tokens d'historique brut pour une fenêtre de 32 768 — un dépassement de 15 000 tokens, donc
presque aucune place pour répondre. La compaction livrée le même jour ramène ce même historique à
9 562 tokens, soit 23 000 tokens libres. C'est le correctif décisif du symptôme « ça coupe ».

**Une réponse coupée par la fenêtre est désormais reprise.** `finish_reason` existait sur le morceau
de fin de l'adaptateur et n'était lu par personne : la chaîne ne rendait que `texte`,
`tokens_generes` et `tokens_par_seconde`. Mesuré à 1 973 tokens puis `length` sur un contexte de
2 048. La reprise repart du texte déjà produit, bornée à quatre essais, et annonce la fenêtre pleine
quand elle ne peut plus rien produire. Un plafond `max_tokens` demandé par l'utilisateur, lui, est
respecté : `length` recouvre les deux causes, et le moteur ne les distingue pas.

**Les réponses courtes ne viennent pas de l'application.** Mesuré le 2026-08-16 sur quatre cellules :
6 389 à 7 904 caractères, la chaîne complète avec harnais donnant la plus longue. Rien dans le code
ne raccourcit. Les leviers restants sont le prompt système de la conversation, l'échantillonnage
Qwen3 (+14 % mesuré, non appliqué) et la quantification Q3_K_S du modèle chargé.

**La v1 était calibrée pour une autre machine.** RTX 3060, Linux natif. Nombre de couches codé en
dur, heuristique de 150 Mo par couche (436 Mo mesurés), et mémoire unifiée CUDA — inutilisable sous
WSL2, qui laisse les poids en RAM hôte avec la VRAM figée à 2 Go. Première hypothèse à tester devant
tout symptôme mémoire inexpliqué.

**`GGML_CUDA_FORCE_CUBLAS=ON` n'est pas cosmétique.** Sans lui, nvcc de CUDA 12.8 segfaute en
compilant les kernels MMQ de ggml pour `compute_120a`. Bug du compilateur. Détail dans
COMPATIBILITE-GPU.md.

**La syntaxe GPU de Docker est inversée entre plateformes.** `deploy.resources.reservations` sur
Windows/WSL2, CDI `nvidia.com/gpu=all` sur Linux natif. Les deux formes sont dans
docker-compose.yml, une seule active — **`main` porte aujourd'hui la forme Windows.**

**Le port réel est 37820, pas celui du compose.** Le défaut du compose est 37920 ; un `.env` non
suivi par git le surcharge. Lire le `.env`, pas le compose.

**Les identifiants contiennent des `/`.** `<depot>::<fichier>`, encodé `%2F` par le navigateur :
toute route les recevant a besoin de `:path`, routes suffixées déclarées **avant** la route nue.

**Pydantic ne sérialise pas les `@property`.** `computed_field` est obligatoire dès qu'une valeur
dérivée doit voyager. C'est ce qui bloquait tous les MoE.

**Aucune authentification.** Le port 37820 est ouvert sur le LAN : n'importe qui sur le réseau peut
lire les conversations, charger ou éjecter un modèle, et désormais **exécuter du Python dans le bac**.
À traiter avant toute exposition hors du réseau domestique.

**Sécurité, à ne pas perdre de vue.** Un jeton GitHub `ghp_…` collé en clair le 2026-08-14 doit être
considéré comme compromis et révoqué (https://github.com/settings/tokens). Le jeton OAuth de
`gh auth login --web` est dans le gestionnaire d'identifiants Windows de cette machine — qui n'est
pas celle de Chris. `gh auth logout` avant de la rendre.

## Prochaines étapes

Ordonnées dans TODO.md. En tête : **la reconnexion côté interface** — au retour de veille, le fil ne
se rafraîchit pas seul, alors que la réponse est complète en base.

## Points en suspens

- **Le harnais corrigé n'a pas encore été éprouvé en génération réelle.** 382 tests couvrent les
  mécanismes ; aucun modèle n'a été chargé depuis (Chris s'en charge lui-même).
- **Le MoE n'a jamais été chargé en conditions réelles.** Planifiable depuis le 2026-08-15, aucune
  mesure. C'est le test qui dira si les 6 Go de VRAM inutilisés sont récupérés.
- **Qwen3-Coder-30B en plusieurs parts** : correctif écrit, jamais éprouvé sur un vrai
  téléchargement découpé.
- **Compose par plateforme** : un découpage `docker-compose.windows.yml` / `.linux.yml` piloté par
  `COMPOSE_FILE` dans le `.env` a été proposé, non tranché. En attendant, le va-et-vient reste sur
  `main`.
- **ccremote** (`../ccremote`, branche `local-models`) : l'orchestrateur exige des identifiants
  Claude. Trois voies proposées, aucune tranchée.

## Mesures de référence sur cette machine

| Modèle | Contexte | Débit |
|---|---|---|
| Qwen2.5-0.5B Q4_K_M | 32 768 | 113–120 tok/s |
| Qwen3.6-27B PHILADELPHIA Q3_K_M | 32 768 | ~72 tok/s |
| Qwen3.6-35B-A3B IQ4_XS (29/41 couches GPU) | 32 768 | 41 tok/s |
| idem | 57 344 | 19,6 tok/s |
| Huihui-Qwen3.6-35B-A3B-Claude-4.7-Opus-abliterated Q3_K_S | 262 144 | 28–35 tok/s |
| idem, i1-IQ3_M (imatrix, 15,4 Go) | 262 144 | 21 tok/s |

Les 10–20 tok/s relevés le 2026-08-16 sur capture d'écran étaient une mesure de conversation chargée,
pas du modèle : mesuré en conditions contrôlées, il rend 28 à 35 tok/s selon le cache KV.

**Le cache KV ne commande pas la vitesse sur un MoE.** Mesuré : `q8_0` place 26 couches sur GPU et
rend 34,9 tok/s, `q4_0` en place 29 et rend 35,3 — soit +1 %. Sur un modèle à 3 milliards de
paramètres actifs, une couche restée sur CPU n'active presque aucun expert et ne coûte donc presque
rien. Le cache commande la place en VRAM, pas le débit.

**`q2_0` et `q1_0` sont inutilisables comme cache KV.** Ils existent dans ggml et le binaire les
expose, mais CUDA n'implémente pas `SET_ROWS` pour ces types : le chargement meurt en `ggml_abort()`
— SIGABRT non rattrapable, backend tué. Vérifié en le provoquant. Un type de cache ne s'ajoute
qu'après un chargement ET une génération réels.

**L'imatrix ne s'est pas montré meilleur ici.** `i1-IQ3_M` (15,44 Go) contre `Q3_K_S` (15,18 Go) sur
la même demande : 4 appels d'outils contre 2, un fichier de 12,4 Ko contre 7,6 Ko — mais 21 tok/s
contre 28, les i-quants étant plus coûteux à déquantifier que les k-quants. Un échantillon chacun,
sur un modèle dont la variance est forte : l'écart de comportement n'est pas une preuve, l'écart de
vitesse l'est.
