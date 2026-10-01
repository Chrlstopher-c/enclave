# Atelier d'exécution

Conteneur de développement où s'exécutent les commandes et le code Python du modèle. Il remplace
l'ancien bac confiné par `setuid`/`rlimits` dans le backend : ce confinement rendait l'outil inerte
dès qu'il fallait installer un paquet (mesuré le 2026-08-26 : `nasm: command not found`, PATH réduit,
pip sans droit d'écriture).

## Ce que c'est

Un seul atelier, partagé par toutes les conversations. À l'intérieur, l'agent est **root**, avec le
réseau, un PATH complet et un toolchain de dev (bash, git, gcc, make, python3, node). Il installe ce
qui lui manque à l'exécution — `apt-get install`, `pip install` — et ce qu'il installe **persiste**.

L'isolation vis-à-vis de la machine de l'hôte ne vient pas de privilèges abaissés mais de la
**frontière du conteneur**, comme un environnement Docker de dev :

- aucun chemin de l'hôte n'est monté (pas de `/`, pas de home, pas de `docker.sock`) ;
- seul le volume nommé `echohub_ateliers` est visible, monté sur `/workspace`, partagé avec le
  backend ;
- les ressources sont bornées par Compose (`mem_limit`, `cpus`, `pids_limit`) ;
- aucun port n'est publié sur l'hôte : le service n'écoute que sur le réseau interne de la pile.

## Le service d'exécution (`serveur.py`)

Un petit serveur HTTP FastAPI, seul processus qui écoute dans le conteneur. Le backend lui envoie une
commande ou du code ; il l'exécute dans `/workspace/<sous_dossier>` et rend le résultat.

| Route | Corps | Réponse |
|---|---|---|
| `GET /sante` | — | `{"statut":"ok","jeton_configure":...}` (ouverte, sert au healthcheck) |
| `POST /executer/commande` | `{commande, sous_dossier, timeout_s}` | `{code_retour, sortie, erreur, duree_s, tue}` |
| `POST /executer/python` | `{code, sous_dossier, timeout_s}` | idem |
| `POST /processus/{lancer,journal,arreter,lister}` | `{sous_dossier, racine, nom, commande?, lignes?}` | état du processus (+ fin du journal) |

Chaque requête porte `racine` : `workspace` (dossier de conversation, `/workspace/<id>`) ou `projets`
(dossier de projet de l'hôte, `/projets/<nom>`, qui doit exister). Avec `ATELIER_PROPRIETAIRE=uid:gid`,
ce que root crée est rétrocédé à cet utilisateur après chaque exécution. En mode natif, le service est
publié sur `127.0.0.1:${ATELIER_PORT_HOTE:-37923}` uniquement. Toolchain : Node 22, Bun, Python 3,
gcc, git, ripgrep, sqlite3.

Les deux routes d'exécution exigent l'en-tête `X-Atelier-Jeton`, comparé à `ATELIER_JETON`. Repli
**fermé** : jeton absent de l'environnement = toute exécution refusée (jamais ouverte par défaut).

### Pourquoi HTTP et pas `docker exec` / `docker.sock`

Monter le socket Docker dans le backend donnerait à celui-ci root sur l'hôte — une surface d'attaque
majeure pour un backend qui exécute du texte produit par un modèle. Un service HTTP interne, non
publié et gardé par un jeton, obtient le même résultat sans jamais exposer l'hôte.

## Persistance — ce qui survit, ce qui ne survit pas

Le volume `echohub_ateliers` ne couvre que `/workspace` : fichiers des conversations et tout ce que
l'agent y dépose (un venv compris). Les paquets installés par `apt` vont dans `/usr`, **hors
volume** :

- ils survivent aux redémarrages (`docker compose restart`, `stop`/`start`) — le conteneur reste le
  même ;
- un **rebuild** de l'atelier (`docker compose build` / `down`) les efface. Refaire un `apt install`
  après un rebuild est acceptable ; les perdre à chaque message ne l'était pas, et ce n'est plus le
  cas.

## Démarrer / vérifier

```bash
docker compose up -d echohub-atelier
docker exec echohub-atelier bash -lc 'whoami; apt-get --version; curl --version'
docker exec echohub-atelier curl -fsS http://localhost:8080/sante
```

Le jeton partagé se génère avec `python3 -c "import secrets; print(secrets.token_urlsafe(32))"` et
se pose dans `.env` (`ATELIER_JETON=`), lu par le backend et par l'atelier via Compose.
