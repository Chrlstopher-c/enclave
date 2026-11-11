---
name: apprendre-une-librairie
description: Use a library, framework or CLI you are unsure about — get its real API from the installed version (`doc`), then official docs from real links; never guess URLs, never tinker blind.
---
# Learning a library

Your memory of an API may be from an older version, and guessing wastes turns. Follow this order and
stop as soon as you have the answer. Each step is ONE call.

## 1. Installed? Which version? Where is its official doc? — `doc`
    doc httpx                    # version, official links (Documentation, Source), public classes/functions
Not installed → install it first (`.venv/bin/pip install -q httpx` / `pnpm add zod`), then `doc` again.
JS: `doc npm:zod`.

## 2. The exact thing you need — still `doc`, no web
    doc httpx.AsyncClient        # signature + docstring + methods
    doc httpx.AsyncClient.get    # full docstring of one method
    doc httpx --find timeout     # every definition whose name contains the word, with file:line
A typo → `doc` lists the close names. To see real code: `sed -n 'START,ENDp' <file>` from the --find result.
This answers most questions in 1-3 calls and costs little context.

## 3. Usage examples, guides — the official site, from REAL links
- The links printed by `doc` (Documentation / Homepage / Source) are real: fetch those.
- Not installed and no link? `recuperer_page https://pypi.org/pypi/<package>/json` returns the package's
  official links (npm: `https://registry.npmjs.org/<package>/latest`).
- Otherwise `recherche_web "<package> <the exact need>"`, and fetch a URL FROM the results.
- Never type a URL from memory or build path variants: a 404 means that page does not exist.

## 4. When a fetch fails, read WHY — the message tells you
- 404 / no such domain → the address is wrong. Permanent. Take another URL from the results.
- 403 / login → that site refuses tools. Permanent. Same content elsewhere (GitHub README, PyPI page).
- 5xx / timeout → their side, temporary. Use another source now.
- "no Internet connection" → the web is down for everything: work locally (`doc`, `--help`, source).
A failure concerns ONLY that address: the next site, even a similar one, may work fine — keep using the
web when you need it. The harness refuses an identical failed call: change the address or the source.

## 5. Then build on it
Write the smallest snippet that uses what you found, run it, then build. Note a surprise (renamed
function, changed default) in STATE.md or memory so you do not hit it twice.
