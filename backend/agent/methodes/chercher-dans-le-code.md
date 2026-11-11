---
name: chercher-dans-le-code
description: Find where something lives in a codebase (function, error text, config key, route) or get to know an unknown project — without reading files one by one.
---
# Finding things in code

Goal: reach the exact file and line in 2-3 calls. Reading files one after another to "look for it" is the
slowest way and floods your context. Search first, read only the range that matters.

## 1. Unknown project — get the map (one call)
`executer_commande`:
    tree -L 2 -I 'node_modules|.venv|venv|__pycache__|dist|build|.git' | head -60
Then read ONLY: README.md, the manifest (`pyproject.toml`, `package.json`, `requirements.txt`), STATE.md /
TODO.md if present, and the entry point (`main.py`, `app.py`, `src/main.ts`, `index.html`).

## 2. Find a name, a text, an error
Use `rg` (ripgrep) in `executer_commande`. It is recursive, fast, skips .git and node_modules.
    rg -n "def load_config" --type py           # a definition
    rg -n -w "load_config"                       # every use of the name (whole word)
    rg -n "Connection refused" -g '!*.log'       # an error message
    rg -l "TODO|FIXME"                           # only the file names
    rg -n -C 3 "class User\b"                    # with 3 lines of context
    rg --files | rg -i "config"                  # files whose PATH contains a word
Useful flags: `-i` ignore case, `-w` whole word, `-t py|js|ts` by language, `-g '*.tsx'` by glob,
`-l` file names only, `-c` count per file, `--max-count 5`, `| head -40` to cap output.
`chercher_dans_fichiers` does the same without a shell; prefer `rg` for anything with flags.

## 3. Read just what you found
- File under ~150 lines: `lire_fichier` whole.
- Bigger: `plan_fichier` (functions/classes with line ranges), then `lire_fichier` with
  `ligne_debut`/`ligne_fin` around the line `rg` gave you (about 20 lines before, 40 after).

## 4. Follow the thread
From a function: who calls it → `rg -n -w name`. What it calls → read its body, then search those names.
From an error: search the exact message text, then the function that raises it.

## Never
- Never `cat` a whole big file or read a file in successive ranges to scan it: search instead.
- Never repeat a search with the same pattern: change the pattern (shorter, `-i`, a different word).
- Two searches with no hit → the thing may not exist: say so, or list files (`rg --files`) to check names.
