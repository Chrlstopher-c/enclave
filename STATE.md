# STATE — EchoHub v2

*Dernière mise à jour : 2026-08-28*

## Session du 2026-08-28 — Auto-compaction du contexte (branche `auto-compact`)

**Ce qui a été construit.** Compaction automatique et NON DESTRUCTIVE du contexte à 90 % de la
fenêtre du modèle chargé (`SEUIL_COMPACTION = 0.90`, `backend/chat/compaction.py`). Avant chaque
génération, on mesure l'occupation (socle + définitions d'outils + historique) ; au franchissement du
seuil, les tours anciens sont remplacés — **dans le seul flux moteur** — par un résumé cumulatif
orienté agent (objectif, état, fichiers, décisions, reste à faire) produit par le modèle chargé
(`backend/inference/resume_compaction.py`). La base et l'API rendent toujours l'intégral. Balise en
direct (`EvenementCompaction`) et au rechargement (`MessageChat.compaction`), table additive
`chat_compactions`. Décision pure et testée sans DB ni moteur : `backend/chat/tests/test_compaction.py`
(10 tests verts — seuil, coupe dichotomique, résumé cumulatif). Rendu web :
`frontend/src/chat/conversation/BaliseCompaction.tsx` (marqueur système repliable). **Contrat de
balise figé dans `ARCHITECTURE.md`** pour l'app mobile.

**Deux corrections nécessaires à ce que la feature fonctionne sur le modèle réel :**
- `compter_tokens` implémenté sur l'adaptateur `llama-server` via `/tokenize` : sans lui, tout modèle
  MoE à experts déportés rendait la fenêtre « non mesurable » — panneau d'occupation vide ET
  compaction inerte.
- L'occupation compte désormais les **définitions d'outils** (envoyées à chaque tour, ~1500 tokens) :
  sans elles, le prompt réel franchissait la fenêtre AVANT le seuil (mesuré : réel 8766 vs mesure 7259,
  llama-server en 400).

**Watchdog d'inactivité (commit distinct).** `DELAI_INACTIVITE_S` 180 s → configurable
`ECHOHUB_DELAI_INACTIVITE_S`, défaut **900 s**. Un préremplissage lourd (35B, experts déportés) peut
dépasser plusieurs minutes avant le premier token sans réarmer le compteur : 180 s coupait une
génération vivante. Les watchdogs chat et flux moteur in-process lisent le même délai.

**Preuve d'intégration (chemin de chat réel, modèle `Huihui-Qwen3.6-35B-A3B-…Q3_K_S`).** Rechargé à
contexte 12288 (le seuil de 90 % de 262144 étant irréaliste à remplir). Conversation remplie par
`POST …/generer` : occupation **11492 → seuil 11059 franchi → compaction → 7603 tokens**, événement
`compaction` émis, balise persistée et rendue au rechargement (`GET …/messages`), et **la génération
du même tour a réussi** (580 caractères, le modèle répond avec le contexte réduit). Seconde compaction
observée, **cumulative** (`nb_messages_resumes` 5 → 11, coupe avancée, 708 c. générés). Sous le seuil,
aucune compaction, aucun événement parasite. **35B restauré à 262144** (q4_0, 40 couches GPU, flash
attn — vérifié `GET /inference/etat` → `pret`, contexte 262144 ; experts déportés 27 vs 24 d'origine,
décision live du planificateur sur la VRAM courante).

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

## Session du 2026-08-28 — CDI stale après reboot, zombie llama-server, plan appliqué sans revérification

Panne : « Aucun moteur installé ne sait charger un modèle gguf » côté web, chargement accepté mais
génération infinie côté mobile.

### Cause racine, environnementale — majeur `nvidia_uvm` figé dans un CDI spec vieux de 18 jours

`docker exec echohub-v2 python -c "import llama_cpp; ...llama_supports_gpu_offload()"` rendait
`False` avec `ggml_cuda_init: failed to initialize CUDA: unknown error` en journal, alors que
`nvidia-smi` (NVML) répondait normalement dans le même conteneur — c'est ce qui a orienté vers un
problème propre à `cuInit`, pas au pilote.

Artefact : `/dev/nvidia-uvm` s'ouvrait `Operation not permitted` (puis `ENXIO` après un simple
`docker restart`, qui ne change rien au cgroup device figé à la création). Comparaison des majors :

| device | host (ce boot) | conteneur (avant correctif) |
|---|---|---|
| `/dev/nvidia-uvm` | major 234 | major 235 (`/etc/cdi/nvidia.yaml`, généré il y a 18 jours) |
| `/dev/nvidia-uvm-tools` | major 234 | major 235 |

Le major du module `nvidia_uvm` est alloué dynamiquement à chaque chargement du module — il a
changé au dernier boot (27/08 21:08). Le spec CDI (`/etc/cdi/nvidia.yaml`) fige ce major au moment
de sa génération et Docker construit les nœuds du conteneur avec ces valeurs figées, pas par un
`stat()` live de l'hôte. Un `docker restart`/`--force-recreate` seuls ne suffisent pas tant que le
spec lui-même n'est pas régénéré.

**Correctif appliqué** : `sudo nvidia-ctk cdi generate --output=/etc/cdi/nvidia.yaml`, puis
`docker compose up -d --force-recreate echohub`. Vérifié : `llama_supports_gpu_offload()` → `True`,
`ggml_cuda_init: found 1 CUDA devices`. **À refaire après chaque reboot de la machine** tant que rien
n'automatise la régénération (candidat : hook `nvidia-ctk cdi generate` dans un service systemd
post-boot, ou dans `start.sh` avant `docker compose up`, hors scope de cette session).

### Correctifs de code, branche `correctif-moteur`

1. **Zombie `llama-server` non récolté sur annulation** (`superviseur.py`) — `_demarrer()` lance le
   sous-processus puis attend sa santé ; une annulation de tâche pendant cette attente traversait
   `adaptateur.charger()` sans jamais atteindre son propre `poll()`. Mesuré : PID 337338, zombie
   depuis plusieurs heures, PPID le backend. `_executer()` appelle désormais
   `adaptateur.decharger()` (idempotent) dans le handler `CancelledError` — seul point qui voit
   passer cette exception pour tous les moteurs. Test : `test_annulation_chargement.py`.
2. **`/inference/charger` ne revérifiait jamais la santé du moteur sur un plan déjà construit**
   (`api.py`) — `RequeteChargement.plan` (le chemin qui applique un plan déjà affiché, pour ne pas
   replanifier sur une VRAM qui a bougé) ne repassait jamais par `choisir_moteur()`. Un plan devenu
   caduc entre `/planifier` et `/charger` (moteur tombé entre les deux) pouvait être accepté (202)
   et ne jamais aboutir — piste retenue pour l'état « chargé » menteur côté mobile.
   `_verifier_moteur_disponible()` sonde `backend.engines.service` avant de dispatcher, refuse avec
   `MoteurIndisponible` (503) sinon. Test : `test_verification_moteur_avant_charger.py`.

### Preuve, chemin réel (API HTTP, pas les bindings)

`/inference/planifier` → `/inference/charger` → poll `/inference/etat` → `curl -N` SSE sur
`/inference/generer` :

| modèle | couches GPU | contexte | chargement | TTFT | flux |
|---|---|---|---|---|---|
| Qwen3-4B-Instruct-2507 Q8_0 | 36/36 | 8192 | 38,2 s | 0,40 s | 6 morceaux, « Bonjour ! 😊 » |
| Qwen3.6-35B-A3B (IQ2_XXS, MoE, 7 groupes d'experts déportés) | 40/40 | 8192 | ~0 s (déjà chaud) | 0,63 s | 151 morceaux en 3,9 s |

Backend redémarré deux fois pendant l'investigation (`docker restart`, puis
`--force-recreate` après régénération du spec CDI) — les deux fois annoncées et vérifiées revenues
avant de continuer. Modèle déchargé en fin de session, `etat=inactif`.

## Session du 2026-08-26 — le harnais d'agent-forge, et llama.cpp servi autrement

Six chantiers, tous décidés sur une mesure. Ce qui suit est l'état courant ; le résumé d'origine
suit plus bas, inchangé.

### 1. Quatre outils portés depuis agent-forge

`executer_commande` (shell réel confiné : gcc, as, ld, make, curl, git — vérifiés présents sous le
PATH du bac), `recuperer_page` (la seconde moitié de `recherche_web` : un extrait de deux lignes
sert à choisir une source, jamais à répondre), `lister_fichiers` et `chercher_dans_fichiers` (le
socle exigeait « your memory of what you wrote is not the file » sans donner le moyen d'obéir).

Le confinement est PARTAGÉ, pas dupliqué : `executer_commande` passe par le même lanceur que
`executer_python`. Deux réglages diffèrent, mesurés — le temps processeur (une compilation en
consomme) et le filet en temps réel (un `curl` attend sans consommer de CPU).

### 2. Le planificateur voyait 3 couches sur 40 — bug de transmission, pas de calcul

Le backend mesure `octets_experts_par_bloc` correctement (346 Mo d'experts sur 369 Mo par bloc,
**93,7 %**), l'API les envoie, et `cible/conversion.ts` ne les faisait pas suivre. Sans elles,
`mesures_experts()` rend `None` et le planificateur retombe sur la coupe par couches entières — son
repli documenté, correct en soi, déclenché pour rien.

Sept champs rétablis. Mesuré avant/après, à VRAM identique :

| ctx demandé | cache | sans les mesures | avec |
|---|---|---|---|
| 131072 | f16 | 18/40 GPU | **40/40** |
| 131072 | q4_0 | 27/40 GPU | **40/40** |
| 262144 | q4_0 | 23/40 GPU | **40/40** |

Le type TS `MesuresTenseurs` ne déclarait même pas le champ : la dette de transcription que
`conversion.ts` signale lui-même — deux transcriptions parallèles du contrat pydantic qui ont divergé.

### 3. llama.cpp est servi par son binaire natif, plus par les bindings

Mesuré sur le 35B-A3B, en conversation qui s'allonge :

    llama-cpp-python  tour 1 : 1162 tokens réévalués · tour 2 : 1188 · tour 3 : 1211
                      TTFT 5,94 s À CHAQUE MESSAGE
    llama-server      TTFT 5,96 s au premier, puis 0,15 s

Le journal donne la cause : `partial kv removal not supported`. Le préfixe EST trouvé (1161 tokens),
mais l'architecture est hybride — un bloc sur quatre porte un cache KV, les autres un état récurrent,
et un état récurrent ne se tronque pas. Enchaîner un tour sur le précédent l'exige. `swa_full=True`
essayé : sans effet.

Le débit de génération était comparable (26 contre 27-35 tok/s). Ce que l'interface affichait à
10 tok/s divisait les tokens par le temps TOTAL, prefill compris : la lenteur ressentie était
entièrement du TTFT.

**Ce n'est PAS un troisième moteur.** Le plan reste `moteur: llama.cpp` ; le choix de
l'implémentation vit dans le superviseur. Une troisième valeur de `Moteur` aurait obligé
planificateur, capacités et frontend à connaître une distinction qui ne change rien à ce qu'ils
décident — et aurait rendu les deux chemins incomparables. Repli : binaire absent → bindings ;
`ECHOHUB_CHEMIN_LLAMA=serveur|bindings` pour forcer. Les bindings restent le seul chemin qui expose
le tokenizer et le découpage multimodal dans ce processus.

Le binaire est **compilé dans l'image** pour sm_86 : celui de `ghcr.io/ggml-org/llama.cpp` est lié à
la glibc d'Ubuntu 24.04 et l'image est sur 22.04 (« GLIBC_2.38 not found »). Monté depuis
`/mnt/models/echohub-bin` pour ne pas repayer 10 min de CUDA à chaque reconstruction.

### 4. Deux régressions introduites ce soir avec ce chemin, et corrigées

**La réflexion fuyait.** llama-server extrait les pensées vers `reasoning_content` et les retire du
contenu ; l'adaptateur les concaténait SANS balise, et la réflexion — en anglais — coulait dans la
réponse visible. Correctif : `--reasoning-format none`, qui les laisse balisées dans le contenu,
comme le faisait le chemin bindings.

**Les arguments d'appel étaient détruits.** llama-server envoie les arguments caractère par
caractère (`{"`, `\"requete\":\"`, `met`, `eo`, …). L'adaptateur lisait chaque fragment comme un
JSON complet, échouait, et émettait un `<tool_call>` VIDE par fragment. L'utilisateur a vu six
appels identiques sans arguments et un modèle qui s'excuse — alors qu'il avait parfaitement produit
`{"requete": "meteo Paris demain"}` à chaque tentative. **Un harnais qui détruit l'appel puis lui
reproche son absence est pire qu'un harnais qui échoue : il accuse.** `_Accumulateur` recompose les
fragments par index et ne les lit qu'une fois le flux clos.

### 5. La conduite est réglable, et le budget d'outils avertit au lieu de couper

`inference/harnais.py` porte deux conduites. `forge` est le DÉFAUT depuis ce jour, sur un cas
mesuré : à une recherche web ordinaire, la borne de six tours était atteinte, le modèle se
retrouvait au tour de clôture SANS outils déclarés, écrivait « Laisse-moi chercher autrement » et
s'arrêtait. Il ne pouvait pas savoir qu'on venait de lui retirer ses moyens.

La limite n'est plus un quota mais un compte de tours CONSÉCUTIFS qui PRÉVIENT : à l'avant-dernier
tour, une consigne dit combien de tours sont faits, combien restent, et quoi faire pour continuer.
Le modèle qui rappelle un outil après l'avertissement est prolongé, sans plafond de prolongations.
Quand plus aucune extension n'est possible, l'avertissement CHANGE de texte — annoncer une extension
qui ne viendra pas ferait organiser une suite que le harnais n'accordera pas.

Reste un garde-fou à 200 tours, et c'en est un, pas un budget : le franchir se journalise comme une
boucle suspectée. Le cas n'est pas théorique — le même jour, six appels identiques d'affilée.

`echohub` (6 tours, couperet) est conservée inchangée comme point de comparaison : à outils et
modèle constants, la seule variable est la conduite.

### 6. Identité, issue des appels, et refonte de la conversation

Le modèle sait désormais **où il tourne et quel modèle il est** (+595 caractères sur un socle de
10 255). À « présente-toi », il répondait « je fonctionne sur un modèle d'inférence générique — pas
le tien en particulier ». À la question la plus fréquente qu'on lui pose, un modèle sans identité
n'admet pas son ignorance : il invente.

L'**issue d'un appel voyage dans la balise** : `<sortie etat="echec">`. Le frontend la devinait par
préfixe de texte, ce qui ne survit ni à une reformulation ni à un `EchecOutil` au texte libre.

La **conversation a été refondue** (desktop et mobile) : affichage des outils repensé — une ligne
qui dit tout, détail au dépliage —, artefacts versionnés avec panneau dédié, archivage et renommage
des conversations, écran de sélection d'outils. Captures dans `frontend/captures/`.

### 7. Le contrat réclamé par la refonte est tenu (matin du 26/08)

`creer_artefact` (11e outil), `GET /chat/outils`, `GET`/`PATCH /chat/conversations/{id}/outils`.
La sélection est persistée par une colonne additive et respectée par le registre, le socle et la
déclaration au moteur. Reste côté frontend : brancher `api-outils.ts` et `outils-catalogue.ts` sur
ces routes — ils tournent aujourd'hui en mode dégradé assumé (« sélection non persistée »).

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

## Ce qui a été fait — session des 2026-08-16 et 17

**Le sujet de la journée : le harnais d'outils, corrigé sur transcripts réels.** Chaque correctif
part d'une conversation relue en base, jamais d'une hypothèse. Deux fois dans la session, une
hypothèse documentée mais non mesurée a été réfutée par un test contrôlé — l'échantillonnage
d'abord, les outils ensuite.

- **Fins de ligne forcées en LF** (`.gitattributes`). Un `git pull` sous Windows réécrivait
  `docker/entrypoint.sh` en CRLF et le conteneur sortait en 127 à chaque démarrage.
- **Interface mobile** : composeur, tiroirs, écran Modèles. La carte de modèle débordait de 629 px,
  cause réelle `min-width: auto` sur les enfants de grille.
- **Le harnais n'abandonne plus un appel ni la réponse.** La condition de sortie de boucle portait
  aussi sur les outils *déclarés*, devenus nuls au second tour : l'appel était détecté puis jamais
  exécuté, et le `<tool_call>` restait affiché en XML brut. Et quand les trois tours demandaient un
  outil, la conversation restait sans un mot — il y a désormais un tour de clôture.
- **Socle et schémas d'outils réécrits en anglais**, parsing des deux dialectes rendu tolérant aux
  balises fermantes manquantes.
- **Modale d'artefact** : ne déborde plus, ni en largeur ni en hauteur. Même cause que la carte de
  modèle.
- **Trois outils de fichier** (`ecrire_fichier`, `lire_fichier`, `modifier_fichier`). Avant, le seul
  moyen de produire un fichier était `executer_python` : le modèle emballait son contenu dans du
  source Python, doublement échappé, et **réécrivait tout à la moindre erreur**.
- **Les résultats d'outils repartent en rôle `tool`**, contenu nu. L'ancienne forme — rôle
  `assistant` préfixé `[outil nom — résultat]` — était un format inventé par nous, que le modèle a
  fini par imiter en prose au lieu d'appeler l'outil.
- **Aperçu des appels et compaction de l'historique.** Écrire un fichier passe son contenu entier en
  argument : le bloc affiché pesait 7 261 caractères. Cinq lignes à l'affichage, huit lignes pour
  les blocs d'outils des tours passés qui repartent au moteur.
- **Un synonyme d'argument ne fait plus jeter le travail du modèle** (voir « Contexte non-évident »).
- **Les outils restent déclarés à chaque tour** (L10-b abandonné). Renversement imposé par la mesure :
  758 → 19 469 caractères, 1 → 3 outils enchaînés sur la même demande.
- **Une réponse coupée par la fenêtre est reprise** — `finish_reason` remontait jusqu'au contrat et
  n'était lu par personne. Et un appel JSON incomplet est réparé au lieu d'être perdu.
- **Le socle interdit d'affirmer sans vérifier**, de revendiquer une action non faite, et de finir
  sur une promesse. Mesuré ensuite : le modèle cherche sur le web et cite ses sources.
- **Une réponse close sur une annonce sans suite est relancée**, une fois, et le compteur se remet à
  zéro dès qu'un outil aboutit — la seconde promesse passait sinon.
- **Accès distant sans droits administrateur** : authentification HTTP dans nginx (activée par le
  `.env`, absente = comportement d'origine), plus un tunnel Cloudflare en binaire portable. Vérifié
  depuis Internet : 401 sans identifiants sur la page comme sur l'API, 200 avec.
- **La génération survit au départ du client.** Elle vivait dans le générateur du flux SSE : une mise
  en veille du téléphone la tuait et l'utilisateur retrouvait une réponse vide. Elle vit désormais
  dans une tâche que la déconnexion ne touche pas, et c'est elle qui persiste.

## Décisions prises — 2026-08-16

| Décision | Raison | Date |
|---|---|---|
| Alias d'arguments déclarés par outil | Le modèle a envoyé 12 173 caractères de HTML valide avec `nom` au lieu de `chemin` : tout a été jeté. Une correspondance déclarée et testée, jamais un appariement au jugé des arguments inattendus | 2026-08-16 |
| L'échec d'un outil porté par le TYPE (`EchecOutil`) | Un outil rendait « Échec : … » avec `succes=True` ; le harnais ne pouvait pas savoir qu'un tour n'avait rien produit, et laissait annoncer un fichier inexistant. Le deviner sur le préfixe du texte cassait au premier message reformulé | 2026-08-16 |
| Le balisage d'appel du modèle ne repart pas au moteur | Un appel raté qu'on lui remontre est un gabarit qu'on lui propose : l'appel vide se rejouait à l'identique, y compris au premier tour du message suivant | 2026-08-16 |
| Anti-redite sur les ÉCHECS seulement, effacée par le premier succès | Borner toute répétition aurait cassé `lire → modifier → relire`, c'est-à-dire la boucle que ces outils existent pour permettre. Attrapé par les tests existants | 2026-08-16 |
| Résultats d'outils en rôle `tool`, contenu nu | Canal natif des gabarits (`<tool_response>`), que le modèle ne confond pas avec sa propre prose. Vérifié dans les en-têtes GGUF des 8 modèles présents | 2026-08-16 |
| Socle et schémas d'outils rédigés en anglais | Ces modèles raisonnent en anglais — visible dans chaque bloc de raisonnement — et suivent mieux une consigne de forme dans cette langue. La sortie reste en français, la première ligne du socle l'exige | 2026-08-16 |
| Écrire dans un fichier plutôt que dans `code` | Le fichier survit à l'appel : une erreur se corrige avec `modifier_fichier` au lieu de tout retaper | 2026-08-16 |
| Compaction des blocs d'outils dans le seul flux vers le moteur | Le contenu d'un outil n'a de valeur pleine que pendant le tour qui l'a demandé. L'affiché et l'enregistré restent entiers : économie de contexte, pas perte d'information | 2026-08-16 |
| `.gitattributes` avec `* text=auto eol=lf` | Sans lui, chaque checkout Windows recasse l'entrypoint du conteneur. `git add --renormalize` ne corrige que l'index | 2026-08-16 |

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

## Historique

**2026-08-15 — Lots L2 à L10.** Exécution Python confinée avec un bac par conversation ; artefacts
dans le fil (présentation, modale agrandissable, aperçu HTML cloisonné) ; coût en tokens d'une image
mesuré via mtmd et repli sans tour de vision ; correction d'un plantage natif SIGABRT au premier
comptage d'image ; réglage de désactivation des CUDA graphs ; arrêt de la réémission des outils
après un tour avec résultats.

**2026-08-14 au 2026-08-15 — Reconstruction complète.** La v1 (`../echohub-master`) abandonnée après
plusieurs heures de correctifs, ses constantes étant calibrées pour une RTX 3060 sur Linux natif. La
v2 bâtie par un workflow de 15 agents, puis assemblée et corrigée à la main : planificateur de
chargement, chat complet avec branches, harnais d'outils et recherche web SearXNG, panneau
d'occupation du contexte, écran Modèles.

**2026-08-14 — Journée v1.** Lancement sous Windows, Docker Desktop et WSL2, quatre correctifs pour
démarrer. Puis diagnostic du MoE : plusieurs heures perdues à supposer un manque de VRAM avant de
tester un modèle connu-bon de 490 Mo, qui a généré immédiatement et disculpé toute la chaîne.

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
