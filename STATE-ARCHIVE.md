# STATE — archive (sessions antérieures au 2026-08-28 « CDI stale »)

Archivé le 2026-10-01 depuis STATE.md (limite de 300 lignes). Toujours valable comme historique.

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

