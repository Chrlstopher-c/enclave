---
name: serveur-et-interface
description: Run a web server, API or front-end in the workshop and check it like a user would — start in background, read logs, curl, test the page in the browser.
---
# Servers and web interfaces

## Start
- Anything that never exits (dev server, API, watcher) → `serveur_fond` `lancer`, never `executer_commande`.
- Listen on 0.0.0.0 and a port above 1023, not 8080 or 8090. Examples:
      .venv/bin/uvicorn app:app --host 0.0.0.0 --port 8000
      bun run dev --host 0.0.0.0 --port 5173
      # a static page: this server sends no-store, so the browser never runs a stale script after an edit
      python3 -c "import http.server as h;H=h.SimpleHTTPRequestHandler;f=H.end_headers;H.end_headers=lambda s:(s.send_header('Cache-Control','no-store'),f(s));h.test(HandlerClass=H,port=8100,bind='0.0.0.0')"
- Wait (`sleep 3` in `executer_commande`), then read the `journal`: an error there is the first thing to fix.

## Check from the shell
    curl -s -o /dev/null -w '%{http_code}\n' localhost:8000/
    curl -s localhost:8000/api/items | head -c 600
    curl -s -X POST localhost:8000/api/items -H 'Content-Type: application/json' -d '{"name":"x"}'

## Check the page like a user (`playwright` MCP, via `mcp_appeler`)
The browser reaches the workshop at `http://echohub-atelier:<port>`.
1. `browser_navigate` to the page. 2. `browser_snapshot`: an accessibility tree in TEXT, with `ref`s.
3. `browser_click` / `browser_type` with those refs; snapshot again to see the result.
4. Errors: `browser_console_messages`. You cannot see images or colours: check text and structure.
5. STOP there once the page loads with 0 console errors and the main action does what it should (one key or
   click, one snapshot). That is the smoke test; the logic is already proven by unit tests. Do not chase
   canvas pixels, timings or animations in the browser.
Fetch a tool's argument schema once with `mcp_outils` before its first call.

## Port taken / server will not start
`ss -ltnp | grep :8000` shows who holds it. Stop your old one with `serveur_fond` `arreter`, or use
another port. Never start the same server twice.

## Finish
Leave running what the user should open; give the port. Stop the rest.
