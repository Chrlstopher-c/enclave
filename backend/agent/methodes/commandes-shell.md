---
name: commandes-shell
description: Quick, reliable shell recipes for the workshop — inspect files and folders, count, filter, JSON, archives, processes, disk — with short output.
---
# Shell recipes (`executer_commande`)

Always: non-interactive (`-y`, `--yes`, `-q`), output capped (`| head -40`, `| tail -20`), and check the exit code.

## Look around
    pwd; ls -la                      # where am I, what is here
    tree -L 2 -I 'node_modules|.venv|.git' | head -60
    rg --files | head -50            # all tracked-looking files
    wc -l src/*.py | sort -n | tail  # biggest files
    du -sh * | sort -h | tail        # what takes space

## Read part of a file without the file tools
    sed -n '120,160p' file.py        # lines 120-160
    head -30 file; tail -30 file
    rg -n "pattern" file             # line numbers to target

## Filter and transform
    rg -n "ERROR" app.log | tail -20
    jq '.items | length' data.json ; jq -r '.items[].name' data.json | head
    sort | uniq -c | sort -rn | head  # frequencies
    python3 -c 'import json; d = json.load(open("data.json")); print(len(d))'
    # longer logic: write a .py file with ecrire_fichier and run it (heredocs break on indentation)

## Several files at once
    rg -l old | xargs sed -i 's/old/new/g'
    for f in *.csv; do echo "$f: $(wc -l < "$f")"; done

## Archives
    tar -tzf a.tar.gz | head ; tar -xzf a.tar.gz -C out/ ; unzip -q a.zip -d out/

## Processes, ports, network
    ps aux | rg -i python | head
    ss -ltnp | head -20              # listening ports
    curl -sS -m 10 URL | head -c 800

## Packages
    apt-get install -y -q <pkg>      # system tool (persists)
    python3 -m venv .venv && .venv/bin/pip install -q <pkg>
    corepack enable pnpm && pnpm install --silent

## Avoid
Interactive programs (vim, less, top, a REPL) in `executer_commande` — use the `pty` MCP if truly needed.
`cd` chains that you forget: use paths. Printing big files or binary content.
