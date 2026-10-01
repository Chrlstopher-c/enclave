# TODO — EchoHub v2

*Dernière mise à jour : 2026-10-01*

## En cours

Rien. Arbre git propre, application en ligne, accès distant opérationnel, 413 tests verts.

**Services vivants à connaître en reprenant** : conteneurs `echohub-v2` et `echohub-searxng`, plus un
processus `cloudflared` détaché qui porte le tunnel. Ce dernier meurt au redémarrage de la machine
et son URL change à chaque relance — la retrouver dans `%LOCALAPPDATA%\cloudflared\tunnel.log`.

## À faire (priorité)

- [ ] Téléchargements (`models/`) : `octets_recus` du mmproj huihui = 1,85 Go pour 0,90 Go attendus (2026-10-01) — compteur doublé ?

### Mode projet (2026-10-01) — suites

- [x] **Aperçu de l'app générée** (2026-10-01) : relais atelier sur 37924, section « Aperçu » de la modale.
- [ ] Aperçu : WebSocket (HMR Vite) non relayé ; un seul aperçu pour tout l'atelier ; joignable sur la
      tour seulement (127.0.0.1), comme le reste de l'UI.
- [ ] Exporter un projet fini : bouton/commande (rsync sans `.echohub/`, `.venv/`, `node_modules/`).
- [ ] **Dernière ligne droite du modèle** : relances sur annonce/pause/reste faisable en place
      (`fin_projet.py`), mais sur `todo-final` il finit à 8/9 en épuisant ses 6 relances en pauses sans
      appel. Pistes : consigne de relance qui NOMME le prochain appel attendu (dernier échec vu) ; modèle
      plus fort en agentique ; mesurer le quota optimal.
- [ ] Le choix du modèle « par défaut » reste le favori mudler dans l'UI : passer le huihui en favori.
- [x] **llama-server orphelin à chaque reload du backend natif** (corrigé : `_arreter_moteur` au shutdown) : le processus survit (re-parenté à
      systemd --user), garde le port 8081 et la VRAM, et le nouveau backend se croit « inactif ».
      Mesuré trois fois le 2026-10-01. Le stopper au `shutdown` du lifespan.
- [ ] **Reload natif qui gèle l'API** : `--reload` attend la fin de la génération en cours avant de
      redémarrer ; pendant ce temps l'API ne répond plus. Tests exclus du reload ; envisager
      `--timeout-graceful-shutdown` ou un mode sans reload pour l'usage réel.
- [ ] Garde-fous : analyse lexicale contournable par indirection (`X=/projets; rm -rf $X/b`). Piste
      sérieuse si besoin d'une vraie barrière : un utilisateur Unix par projet dans l'atelier.
- [ ] Projets imbriqués (`client/app`) non gérés : un projet = un sous-dossier direct de la racine.

### 0. Contrat réclamé par la refonte de la conversation (2026-08-26)

Le frontend est écrit et attend ces trois surfaces. Tant qu'elles n'existent pas, l'écran de
sélection d'outils affiche un mode dégradé ASSUMÉ (« sélection non persistée »), il ne simule rien.

- [x] ~~Outil `creer_artefact`~~ — **fait le 2026-08-26**. Sortie conforme au contrat. Le numéro de
      version est attribué par le backend et dérivé du MAGASIN DE FICHIERS (`<id>-vN.<ext>`), sans
      table d'artefacts : le magasin est la seule source qui survive à un redémarrage, là où un
      compteur en mémoire serait reparti à 1 en écrasant l'historique. L'`artefact_id` vient du
      modèle et finit dans un nom de fichier — il est donc normalisé avant tout usage
      (`../../etc/passwd` → `etc-passwd`, vérifié).
- [x] ~~`GET /chat/outils`~~ — **fait**. Coût mesuré avec le tokenizer du modèle chargé ; `null`
      quand aucun ne l'est, jamais 0 — un zéro se lirait « cet outil ne coûte rien », alors qu'un
      outil déclaré occupe la fenêtre à CHAQUE tour.
- [x] ~~`GET`/`PATCH /chat/conversations/{id}/outils`~~ — **fait**, persisté en base (colonne
      additive `chat_reglages.outils_actifs`). `null` = tous et `[]` = aucun restent distincts :
      les confondre priverait d'outils une conversation qui n'a jamais choisi, ou en rendrait à
      celle qui les a tous coupés. Le registre, le socle ET la déclaration au moteur respectent la
      sélection — un prompt qui annonce une capacité absente est le défaut que ce socle existe pour
      supprimer. Un nom inconnu est ignoré à l'usage, jamais refusé à l'enregistrement.
- [x] ~~Porter l'issue d'un appel dans le balisage~~ — **fait le 2026-08-26**. Le harnais écrit
      `<sortie etat="echec">` quand l'appel a échoué, `<sortie>` sinon ; il tient ce fait de
      l'exécution même de l'outil. Côté frontend, l'issue déclarée PRIME et le repli par préfixe ne
      sert plus qu'aux messages enregistrés avant cette date — ce qui permettra de le supprimer un
      jour sans rien casser. La forme sans attribut reste émise pour un succès : un historique relu
      ne doit pas changer d'apparence parce que le format a évolué.
- [ ] Dépendance npm `mermaid` pour le rendu des diagrammes (repli actuel : source colorée).

### 0 bis. Né de la session du 2026-08-26, consigné le 2026-08-27

- [ ] **Le modèle demande la permission d'utiliser un outil qu'il possède.** Mesuré sur un fil réel :
      il écrit « Si tu veux, je peux réécrire le script en utilisant httpx (déjà présent) » et rend
      la main, deux fois de suite. Le harnais relance bien (journal : 1/3, 2/3, 3/3 puis extension
      de budget) mais une demande de permission est une phrase BIEN FORMÉE — elle n'est ni une
      promesse en l'air ni un tour muet, donc elle passe à travers les trois détections.
      À MESURER D'ABORD : ce fil précis échouait parce que `requests` manquait au bac (corrigé
      depuis). Vérifier si le réflexe survit au correctif avant d'ajouter une règle au socle —
      empiler une consigne sur un problème disparu, c'est du contexte payé à chaque tour pour rien.
- [ ] **Message de clôture trompeur.** Quand le harnais clôt sur une promesse non tenue, il
      journalise « Borne de 10 tours d'outils atteinte » alors que ce n'est pas le motif. Purement
      cosmétique aujourd'hui, et c'est exactement le genre de ligne qui enverra sur une fausse piste
      dans six mois. `_cloturer` doit dire POURQUOI il clôt.
- [ ] **Artefact affiché d'un bloc, sans progression.** L'utilisateur voit un écran vide pendant
      toute la génération, puis l'artefact apparaît d'un coup. Proposition non tranchée : afficher
      la carte dès que le NOM de l'outil est connu — au premier fragment — avec une progression,
      comme le fait Claude AI. Le contenu, lui, ne peut pas être diffusé au fil de l'eau sans casser
      l'accumulation des arguments (cf. `_Accumulateur`, corrigé le 2026-08-26).

### 1. Reconnexion de l'interface après une veille

La génération survit désormais au départ du client et se persiste seule (2026-08-16). Il reste la
moitié visible, et c'est ce que l'utilisateur constate en premier :

- [ ] **Au retour de veille, le fil ne se rafraîchit pas** : la réponse est complète en base, mais il
      faut recharger la page pour la voir. C'est le point le plus visible à l'usage mobile.
- [ ] Aucune indication qu'une génération tourne encore quand on revient. `annulation.est_active()`
      le sait déjà côté serveur ; il manque la route et l'affichage.
- [ ] Se rebrancher sur le FLUX d'une génération en cours — et non attendre sa fin — demanderait de
      diffuser vers plusieurs abonnés : la file actuelle n'en sert qu'un.

### 2. Deux habitudes du modèle, à traiter dans le socle

Mesurées sur des appels enregistrés, pas supposées :

- [ ] Le modèle écrit parfois ses fichiers via `executer_python(code=...)` avec un `open().write()` —
      donc avec le double échappement que `ecrire_fichier` existe pour supprimer.
- [ ] Il cite des sources HORS SUJET sans le voir : sur une question de prix, la recherche a ramené
      des articles sur le café, et il les a cités tels quels. La règle d'honnêteté est respectée à la
      lettre — il cite ce que l'outil a rendu — mais rien ne lui fait vérifier la pertinence.

- [ ] Reprendre le scénario exact qui a échoué : « écris-moi une page HTML avec un simulateur »,
      puis « ça ne rend pas bien, corrige ». Ce que la correction doit produire :
      l'appel avec `nom` au lieu de `chemin` **écrit le fichier** ; l'erreur suivante est corrigée
      par `modifier_fichier` et non par une réécriture complète ; aucune annonce de fichier ou de
      carte qui n'existe pas.
- [ ] Vérifier que le bloc « Appel d'outil » affiche un aperçu de cinq lignes et non 12 000 caractères.
- [ ] Si un appel vide réapparaît malgré tout : le journal dit maintenant ce qui a été normalisé et
      ce qui a été refusé comme redite (`logger.info` dans `registre.executer`, `logger.warning` dans
      `_executer_appels`). Lire le journal AVANT de toucher au code.

### 3. Très long contexte — ce que la carte permet vraiment

Le facteur limitant n'est pas le modèle mais le cache KV, et il se calcule à partir du nombre de
couches à **attention pleine** : les architectures hybrides (Qwen3.5/3.8, `linear_attention`) n'en
paient qu'une sur quatre. Chiffres établis sur les `config.json` réels, avec les types de cache que
le binaire chargé sait servir (`q2_0` débloqué le 2026-08-16) :

| cible | modèle | total sur 16 Go |
|---|---|---|
| 262 144 (natif) | Qwen3.8-27B Q3_K_S + KV q2_0 | 15,9 Go — tient |
| 500 000 (YaRN) | Qwen3.5-4B Q8_0 + KV q2_0 | 8,1 Go — large |
| 500 000 | Qwen3.8-27B Q2_K + KV q2_0 | 16,8 Go — dépasse |
| 1 000 000 | aucun modèle correct | — |

- [ ] Trancher : `Qwen3.8-27B` abliterated pour la qualité à 262 k, ou `Qwen3.5-4B` pour aller
      au-delà avec un modèle nettement plus faible. Au-dessus de 262 144, on quitte le contexte
      natif des deux et on extrapole.
- [ ] Exposer le choix du type de cache KV dans les réglages de chargement : `q2_0` divise le cache
      par six par rapport à `f16` et c'est lui qui rend ces fenêtres tenables.

### 4. Défauts moteur mesurés le 2026-08-16

- [x] **Le verrou du moteur restait tenu après déconnexion** (12+ min). Réglé indirectement le
      2026-08-16 : la génération n'étant plus interrompue par le départ du client, elle s'achève
      normalement et libère le verrou.
- [ ] **`/inference/decharger` pendant une génération active fait tomber le backend**, et 15,4 Go de
      VRAM ne sont pas rendus. Récupéré par `wsl --shutdown`. Le déchargement doit refuser tant
      qu'une génération tient le verrou, ou l'interrompre proprement — jamais planter.

### 5. Longueur des réponses — leviers restants

Mesuré : **rien dans l'application ne raccourcit les réponses** (quatre cellules, 6 389 à 7 904
caractères, la chaîne complète avec harnais donnant la plus longue). Les hypothèses « c'est
l'échantillonnage » puis « c'est le harnais » ont toutes deux été réfutées par la mesure.

- [x] Reprise d'une réponse coupée par la fenêtre — `finish_reason` était perdu par la chaîne
- [ ] Aligner l'échantillonnage par défaut sur les recommandations Qwen3 (temp 0.6 / top_p 0.95 /
      top_k 20, sans pénalité de répétition) — **+14 % mesuré**, modeste mais gratuit.
- [ ] Regarder le prompt système de la conversation : c'est le levier non mesuré qui reste.
- [ ] Considérer une quantification supérieure à Q3_K_S pour le modèle utilisé.

### 6. Captures d'écran et fichiers dans les conversations

- [ ] Joindre un fichier non-image à un message (les images passent depuis le 2026-08-15)
- [ ] Transmettre au modèle chargé dès qu'il sait les lire, quel que soit le modèle

**La règle demandée, et elle est structurante** : l'application **ne bloque pas** et **n'affiche
aucun message générique** du type « ce modèle ne prend pas en charge les images ». Elle transmet. Si
le modèle chargé n'a pas de tour de vision, c'est **lui** qui répond qu'il ne voit rien, avec ses
mots. Une interface qui refuse à sa place se trompera tôt ou tard sur ce dont le modèle est capable.

### 7. Charger un MoE en conditions réelles

- [ ] Charger le 35B-A3B et mesurer : VRAM occupée, RAM, débit
- [ ] Comparer au plan calculé — le déport des experts récupère-t-il les 6 Go inutilisés ?

Planifiable depuis le 2026-08-15 (`largeur_ffn_active` sérialisée), **jamais chargé**. Tout le code
de déport existe et est couvert par des tests unitaires ; aucune mesure ne l'a validé.

### 8. Vérifications restées en suspens

- [ ] GGUF en plusieurs parts : correctif écrit et poussé, **jamais éprouvé** sur un vrai
      téléchargement découpé
- [ ] Sondage du profil machine ramené de 2 s à 10–15 s (appel NVML à chaque passage)

### 9. Dette de style relevée par le linter

- [ ] **`superviseur.compter_contexte` fait 43 lignes** (max 35) —
      `backend/inference/engines_adapters/superviseur.py:306`. Relevé le 2026-08-26 en linterant le
      fichier pour une autre raison ; la fonction est antérieure et n'a pas été touchée depuis, donc
      ce n'est pas une régression. Extraire les helpers plutôt que relever la borne.
- [x] ~~`inference/harnais.py` non câblé~~ — fait le 2026-08-26 : la conduite (état de boucle,
      relances, budget) a été déplacée dans `harnais.py`, le transport reste dans `__init__.py`.
- [ ] **`inference/__init__.py` reste au-dessus de 500 lignes**, avec `_diffuser_complet` à 44 et
      `_boucle_outils` à 46 (contre 62 avant le découpage). Ce qui reste à sortir relève du
      transport, pas de la conduite.
- [ ] **`chat/generation.py` fait 541 lignes** (max 500), avec `preparer` et `diffuser` à 36 lignes
      et `_construire_contexte` à 45. Relevé le 2026-08-26 en y remplaçant une seule ligne ; aucune
      de ces fonctions n'a été touchée.

## Backlog

- [ ] **Compose par plateforme** : `docker-compose.windows.yml` / `docker-compose.linux.yml` choisis
      par `COMPOSE_FILE` dans le `.env` non suivi. Proposé, non tranché — en attendant, la syntaxe
      GPU fait le va-et-vient sur `main` à chaque pull, et `main` porte la forme Windows.
- [x] **Authentification HTTP** posée dans nginx (2026-08-16), activée par `ECHOHUB_AUTH_USER` et
      `ECHOHUB_AUTH_HASH` dans le `.env`. Vérifiée à travers le tunnel : 401 sans identifiants sur
      la page comme sur l'API, 200 avec. Seul `127.0.0.1` en est exempté — le healthcheck du
      conteneur, qui échouerait sinon en permanence.
- [ ] **Authentification APPLICATIVE** : celle de nginx protège l'accès, pas les données. Elle est
      globale (un seul compte), sans session ni révocation, et le mot de passe voyage à chaque
      requête. Suffisante pour un accès personnel distant, insuffisante dès qu'il y a plusieurs
      utilisateurs ou un partage.
- [ ] **Le tunnel « quick » Cloudflare change d'URL à chaque redémarrage** et meurt avec le
      processus. Pour une adresse stable : tunnel nommé (compte Cloudflare + domaine), ou Tailscale
      via `acces-distant.ps1` une fois l'accès physique à la machine retrouvé.
- [ ] `_boucle_outils` fait 44 lignes au lieu des 35 de la norme. La découper imposerait de faire
      transiter trois valeurs à travers un générateur ; écart assumé, à revoir si la fonction grossit.
- [ ] Option de désactivation des CUDA graphs : livrée le 2026-08-15, jamais utilisée en pratique.
- [ ] ccremote (`../ccremote`, branche `local-models`) : l'orchestrateur exige des identifiants
      Claude. Trois voies proposées, aucune tranchée.
- [ ] Nettoyage disque : ~57 Go récupérables (image v1, volumes, venv vLLM 0.21.0 non transposable —
      ses shebangs portent des chemins absolus).

## Terminé — session du 2026-08-16

- [x] Fins de ligne forcées en LF (`.gitattributes`) — un pull Windows cassait le conteneur
- [x] Interface utilisable au téléphone : composeur, tiroirs, écran Modèles
- [x] Le harnais n'abandonne plus un appel d'outil détecté au second tour
- [x] Un tour de clôture garantit une réponse quand les trois tours ont demandé un outil
- [x] Socle et schémas d'outils en anglais ; parsing tolérant aux balises fermantes manquantes
- [x] Modale d'artefact : plus de débordement, en largeur comme en hauteur
- [x] Trois outils de fichier — écrire, lire, modifier — au lieu de tout passer par `executer_python`
- [x] Résultats d'outils en rôle `tool`, contenu nu, au lieu d'un préfixe inventé et imitable
- [x] Aperçu de cinq lignes à l'écriture, compaction à huit lignes dans l'historique renvoyé au moteur
- [x] Alias d'arguments : un synonyme ne fait plus jeter le travail du modèle
- [x] `EchecOutil` : l'échec d'un outil est porté par le type, plus deviné sur un préfixe de texte
- [x] Le balisage d'appel du modèle ne repart plus au moteur dans son propre texte
- [x] Un appel déjà échoué n'est pas rejoué à l'identique tant que rien d'autre n'a abouti
- [x] `harnais_outils.py` extrait, `_resoudre_outils` (code mort, 44 lignes) supprimé

## Terminé — sessions précédentes

- [x] L2 : exécution Python confinée, un bac à sable par conversation (2026-08-15)
- [x] L3 : artefacts dans le fil — présentation, modale agrandissable, aperçu HTML cloisonné
- [x] L5+L6 : coût en tokens d'une image mesuré via mtmd, repli sans tour de vision
- [x] L10 : outils cessés d'être repassés au moteur après un tour avec résultats ; langue imposée
- [x] Reconstruction complète de l'application (v1 abandonnée), planificateur, chat, harnais,
      panneau de contexte, écran Modèles (2026-08-14 au 2026-08-15)
