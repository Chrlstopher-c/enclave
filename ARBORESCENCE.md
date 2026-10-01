# ARBORESCENCE — EchoHub v2

*Dernière mise à jour : 2026-08-17 — 170 fichiers Python, 179 fichiers frontend*

Organisation **par domaine métier**, jamais par couche technique : la structure dit ce que le
produit fait, pas avec quoi il est bâti. Un domaine expose son interface publique (`__init__.py`
côté Python, `index.ts` côté TypeScript) et n'est jamais atteint par ses internes.

## Racine

| Fichier | Rôle |
|---|---|
| `ARCHITECTURE.md` | Carte des domaines et définition non ambiguë de chaque dossier |
| `COMPATIBILITE-GPU.md` | Contraintes GPU payées en pannes réelles — CUDA, WSL2, débits mesurés |
| `DESIGN.md` | Langage visuel : palette sémantique, typographie, mouvement |
| `MESURES-MOE.md` | Relevés sur les modèles à experts |
| `PREUVES-MULTIMODAL.md` | Preuves du coût en tokens d'une image et du repli sans vision |
| `PLAN-EXECUTION.md` | Plan des lots, avec les sections référencées depuis le code |
| `STATE.md` | État courant, décisions et leurs raisons |
| `TODO.md` | Ce qui reste, par priorité |
| `README.md` | Lancement manuel, stack, ports |
| `Dockerfile` | Image GPU — CUDA 12.8 devel, recompilation de llama-cpp-python |
| `docker-compose.yml` | Orchestration ; syntaxe GPU **inversée** entre WSL2 et Linux natif |
| `.gitattributes` | `* text=auto eol=lf` — sans lui, un checkout Windows casse l'entrypoint |
| `start.sh` `stop.sh` `restart.sh` | Cycle de vie, PID et journaux |
| `acces-distant.ps1` | Accès distant par Tailscale — réseau privé, rien d'exposé. Demande les droits administrateur |
| `.env.example` | Variables attendues, sans valeurs sensibles. **Le port réel vient du `.env`** |

## backend/ — 164 fichiers

### `core/` (5) — socle partagé, aucun métier

`config.py` réglages pydantic · `db.py` SQLite WAL, schéma et migrations additives idempotentes ·
`errors.py` erreurs métier portant code, statut HTTP et remédiation · `logging.py` loguru.

### `system/` (9) — ce que la machine offre

Mesure réelle : GPU par NVML avec repli `nvidia-smi`, mémoire, contraintes de plateforme. Une valeur
non mesurable vaut `null`, jamais une estimation.

### `models/` (23) — trouver, télécharger, **connaître** les modèles

`gguf_reader.py` analyse binaire de l'en-tête · `gguf_metadata.py` interprétation et poids réel des
tenseurs · `safetensors_reader.py` index des poids · `coherence.py` confronte le déclaré au présent ·
`discovery.py` recherche Hub · `capacites.py` capacités **déduites** des annonces, tracées ·
`registry.py` index local · `disque.py` inventaire de ce qui occupe, y compris le non chargeable ·
`storage.py` dont `fichiers_projecteurs()` (détection `mmproj*.gguf`) · `download*.py` transferts,
reprise, parts multiples · `api.py` routes.

### `inference/` (44) — décider, appliquer, générer

| Fichier | Rôle |
|---|---|
| `planner/` | **Pur et testable sans GPU** : budget mémoire, paliers, plan justifié, dégradation strictement conservatrice, experts MoE |
| `engines_adapters/` | Application réelle : adaptateurs llama.cpp et vLLM, superviseur (un modèle à la fois), diagnostic qualifié, journal, mesure VRAM, pont flux bloquant → asynchrone |
| `__init__.py` | Interface publique **et boucle d'outils** — tours, redites bornées, clôture honnête |
| `harnais_outils.py` | Mise en forme du flux d'outils : balises affichées, aperçus d'arguments, compaction de l'historique, retrait du balisage d'appel avant renvoi au moteur |
| `reprise.py` | Ce qui gouverne la reprise d'une réponse coupée : bornes, marge, consignes, avertissement |
| `api.py` | Routes — dont `/contexte`, qui compacte avant de compter |

### `chat/` (19) — conversations, branches, génération

`depot.py` persistance · `branches.py` arbre de messages, édition non destructive · `generation.py`
assemblage du contexte et du prompt système · `port_inference.py` contrat attendu du moteur, défini
côté consommateur · `adaptation_inference.py` branchement du domaine voisin · `flux_sse.py` ·
`routes.py`.

### `outils/` (22) — le harnais

| Fichier | Rôle |
|---|---|
| `contrat.py` | Forme d'un outil, de son résultat, `EchecOutil`, et **normalisation des alias d'arguments** |
| `registre.py` | Outils disponibles, ordre de présentation, exécution d'un appel |
| `socle.py` | Prompt système posé **avant** celui de la conversation — en anglais |
| `recherche_web.py` | Recherche, adossée au domaine `recherche` |
| `fichiers_bac.py` | `ecrire_fichier`, `lire_fichier`, `modifier_fichier` — la boucle de travail |
| `ecriture_groupee.py` | `ecrire_fichiers` : plusieurs fichiers indépendants en un appel |
| `verif_syntaxe.py` | Avis de syntaxe Python / JSON rendu à l'écriture même |
| `suivre_taches.py` | `suivre_taches` : la liste de tâches de l'agent, remplacée en entier |
| `executer_python.py` | Exécution réelle, par `fichier` de préférence, par `code` pour un jetable |
| `bac_a_sable.py` | Lanceur confiné : rlimits → setgid → setuid, résolution de chemin bornée au bac |
| `balayage_bac.py` | Enregistre dans le magasin `fichiers` ce que le bac contient de nouveau |
| `presenter_fichier.py` | Le modèle désigne un fichier, l'utilisateur le voit en carte cliquable |
| `api.py` | Routes du harnais |

### `fichiers/` (17) — magasin des pièces jointes et des productions

`politique.py` quotas et types acceptés · `stockage.py` racines par conversation · `depot.py`
persistance · `service.py` dépôt, liaison au message, et `resoudre_reference()` qui accepte un
identifiant **ou** un nom affiché, borné à la conversation · `routes.py`.

### `engines/` (14) — installation et santé des moteurs

Sondes réelles (importable ET capable de toucher le GPU), venvs vLLM versionnés, flux d'installation
en SSE.

### `recherche/` (10) — recherche web locale

Client SearXNG, analyse, service, sonde de disponibilité.

## frontend/src/ — 179 fichiers

| Dossier | Rôle |
|---|---|
| `App.tsx` | Navigation, bandeau d'état, éjection — seul point de rencontre des domaines |
| `cible/` | Croise métadonnées lues, profil machine et moteurs pour bâtir une cible de chargement |
| `chat/` | `ChatEcran.tsx` · `EnTeteChat.tsx` et `useTiroirsChat.ts` (tiroirs mobiles) · `conversation/` fil et composeur · `markdown/` analyseur maison, aucun HTML injecté · `raisonnement/` extraction et repli · `artefacts/` détection et cartes cliquables · `actions/` survol, branches, édition · `reglages/` · `plan/` · `contexte/` occupation de la fenêtre · `api/` |
| `models/` | `recherche/` Hub et filtres de capacités · `locaux/` registre, favoris, inventaire disque · `telechargements/` · `faisabilite/` verdict VRAM |
| `system/` | Matériel, contraintes, moteurs, installation vLLM |
| `shared/design/` | Primitives et tokens · `Modal.tsx` et `Feuille.tsx` (modale et tiroir, sans débordement) · `BoutonActions.tsx` · `MenuContextuel.tsx` · `useEstGrandEcran.ts` et `useHauteurVisuelle.ts` (points de rupture et clavier mobile) · polices IBM Plex versionnées |
| `shared/api/` | Client unique, SSE, types miroirs du backend |

## docker/

`nginx.conf` sert le build statique et proxifie `/api` en retirant le préfixe · `entrypoint.sh`
lance uvicorn et nginx, neutralise la mémoire unifiée sous WSL2, **appose une empreinte de version
aux assets** · `preuves_bac_a_sable.py` preuves d'isolation exécutées en conteneur ·
`outils-acces.py` engendre les identifiants web (mot de passe affiché une fois, seule l'empreinte
crypt salée est conservée) · `searxng/settings.yml` configuration de la recherche.

## Tests — 413 verts, sans GPU ni réseau

`backend/inference/planner/tests/` · `backend/inference/tests/` (contexte d'exécution, pièces
jointes, réémission d'outils, compaction de l'historique, **boucle d'appels ratés**) ·
`backend/inference/engines_adapters/tests/` (dont dialectes d'appel d'outil, multimodal) ·
`backend/models/tests/` · `backend/chat/tests/` (dont **survie de la génération sans client**) ·
`backend/fichiers/tests/` (dont résolution de
référence) · `backend/outils/tests/` (bac à sable, balayage, outils de fichier, socle, présentation,
**alias d'arguments**) · `backend/recherche/tests/` · `frontend/src/chat/markdown/tests/` ·
`frontend/src/chat/raisonnement/tests/`

**Lancer la suite sans toucher au conteneur en service** — le venv vit dans `backend/.venv`, monter
tout `backend` l'écraserait :

```bash
docker run --rm --gpus all --entrypoint /app/backend/.venv/bin/python \
  -v "$PWD/backend/inference:/app/backend/inference" \
  -v "$PWD/backend/outils:/app/backend/outils" \
  echohub:v2 -m pytest backend -q
```

## Ajouts du 2026-08-26

| Fichier | Rôle |
|---|---|
| `backend/outils/executer_commande.py` | Outil `executer_commande` — une commande shell réelle, confinée dans le bac |
| `backend/outils/recuperer_page.py` | Outil `recuperer_page` — lit une page web dont on a l'adresse |
| `backend/outils/explorer_bac.py` | Outils `lister_fichiers` et `chercher_dans_fichiers` |
| `backend/inference/fin_projet.py` | Mode projet : pause, faux bilan, code montré, fin au futur proche, rappel du dernier appel |
| `backend/inference/budget_outils.py` | Budget de tours d'outils : borne, avertissements, prolongations |
| `backend/inference/suivi_taches.py` | Relance d'un tour qui finit sur une tâche ouverte |
| `backend/inference/pre_remplissage.py` | Relance d'une annonce en rouvrant le tour sur `<tool_call>` (llama-server) |
| `backend/inference/harnais.py` | Conduite de la boucle d'outils : tours, relances, budget, radotage |
| `backend/inference/engines_adapters/processus_llama_server.py` | Pilotage du sous-processus `llama-server` |
| `backend/inference/engines_adapters/adaptateur_llama_server.py` | Adaptateur `llama-server` — même plan, HTTP au lieu de bindings |
| `frontend/src/chat/plan/ReglagesMemoire.tsx` | Cache KV et flash attention, dans le panneau de plan |

Le frontend a par ailleurs été refondu sur la conversation (`chat/conversation/`,
`chat/raisonnement/`, `chat/artefacts/`) : voir `STATE.md`, section du 2026-08-26.

## Ajouts du 2026-10-01 — mode projet

| Fichier | Rôle |
|---|---|
| `backend/conftest.py` | Isole les tests du `.env` du poste (les chemins réels fuyaient dans les tests) |
| `backend/projets/__init__.py` | Interface publique du domaine `projets` |
| `backend/projets/modeles.py` | Projet, catalogue, instantané, liaison |
| `backend/projets/racine.py` | Racine des projets : lister, créer, résoudre sans jamais en sortir |
| `backend/projets/apercu.py` | Aperçu : pointer le relais de l'atelier sur un port, rendre l'URL |
| `backend/projets/contenu.py` | Arborescence et lecture d'un fichier du projet (lecture seule, disque de l'hôte) |
| `backend/projets/instantanes.py` | Instantanés git séparés, restauration annulable, modifications et diff depuis le dernier |
| `backend/projets/routes.py` | `/projets` : catalogue, création, instantanés, restauration |
| `backend/projets/tests/test_apercu.py` | Aperçu : pointage, port réservé, atelier injoignable |
| `backend/projets/tests/test_projets.py` | Racine confinée, git réel, restauration |
| `backend/outils/garde_fous.py` | Refus lexical des commandes dangereuses ou hors dossier |
| `backend/outils/serveur_fond.py` | Outil `serveur_fond` : serveurs de dev en arrière-plan |
| `backend/outils/tests/test_garde_fous.py` | Ce qui passe, ce qui est refusé |
| `backend/outils/tests/test_ecriture_groupee.py` | Écriture groupée, lecture par plage, avis de syntaxe |
| `backend/outils/tests/test_suivre_taches.py` | Liste de tâches : rendu, ouvertes, raison exigée |
| `backend/outils/tests/test_mode_projet.py` | Outils dans le dossier du projet, élagage, lecture par tranches |
| `atelier/apercu.py` | Relais d'aperçu (port 8090) vers le serveur de dev choisi, servi à la racine |
| `atelier/processus.py` | Processus de fond de l'atelier (lancer, journal, arrêter, lister) |
| `frontend/src/chat/projet/api-projet.ts` | Client des routes projet |
| `frontend/src/chat/projet/useProjetConversation.ts` | Liaison, catalogue, instantanés, gestes |
| `frontend/src/chat/projet/SectionApercu.tsx` | Section « Aperçu de l'app » : ports en écoute, ouvrir |
| `frontend/src/chat/projet/useApercuProjet.ts` | Hook : lire les ports, pointer et ouvrir l'onglet |
| `frontend/src/chat/projet/PanneauFichiers.tsx` | Panneau « Fichiers » du chat : onglets arborescence / modifications, lecture |
| `frontend/src/chat/projet/ArbreFichiers.tsx` | Arborescence repliable, fichiers colorés selon leur modification |
| `frontend/src/chat/projet/VueFichier.tsx` | Contenu numéroté d'un fichier, ou son diff coloré |
| `frontend/src/chat/projet/arbre.ts` | Arbre reconstruit depuis la liste plate des chemins |
| `frontend/src/chat/projet/useFichiersProjet.ts` | Hook : arbre, modifications et sélection, relus toutes les 4 s |
| `frontend/src/chat/projet/useProjetEcran.ts` | Câblage projet de l'écran : modale, panneau, actions d'en-tête |
| `frontend/src/chat/projet/ModaleProjet.tsx` | Modale : confier / créer un projet, règles, restaurer |
| `frontend/src/chat/projet/index.ts` | Exports du module |
