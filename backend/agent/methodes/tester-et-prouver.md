---
name: tester-et-prouver
description: Verify that work really works before calling it done — unit tests, running the program, checking an API or a web page — and report the proof.
---
# Testing and proving

A step is done when a command shows it works. "It should work" is not a proof.

## Pick the cheapest check that proves the claim
- Pure logic (parsing, calculation, rules) → a unit test.
- A script/CLI → run it on a real small input and look at the output.
- An API → start it (`serveur_fond`), then `curl -s -w '\n%{http_code}\n' localhost:PORT/route`.
- A web page/app → load it in the `playwright` browser at `http://echohub-atelier:<port>` (never
  localhost: the browser is another container; `mcp_appeler`: browser_navigate then browser_snapshot)
  and check the text/elements you expect; click through the main action.
  That browser is already there: never install one (`playwright install`, npm/pip playwright).
  Static page: serve it with the no-cache server of `serveur-et-interface`, or edits will not show.
  Smoke test done = page loads, 0 console errors, the main action works once. Then stop.
- A test fails on code you did not just change (a library, code someone else wrote): check the TEST
  first. Print the actual value on the smallest input and compare it to what the rule says; often the
  expectation or the test setup is what is wrong.

## The doctrine: decide apart, prove directly, smoke-test the edge
Applies to everything: script, API, CLI, page, game, data pipeline.
- What DECIDES (rules, calculations, parsing, state) lives in plain functions with no I/O inside.
  What TOUCHES the outside (screen, HTTP, files, terminal, clock) is a thin layer around them.
- The deciding part is proven by tests that call it with a CHOSEN input reaching the case you care about
  (the full row, the empty file, the bad date). Never wait for a real run to stumble on it.
- The outer layer gets ONE cheap smoke check: starts, answers, clean logs/console, main action works.
- Never prove logic by driving the outside for minutes (a bot playing, a script clicking, a long run
  retried until a random case appears): slow, flaky, and a pass proves less than a 5-line test.
- Before installing a tool (browser, server, test runner), check what is already provided.

## Python tests (pytest)
- Tests in `tests/test_<module>.py`, functions `test_<behaviour>`, one behaviour each, plain `assert`.
- For new logic, write the test FIRST from the requirement, see it fail, then write the code.
- Run quietly: `.venv/bin/python -m pytest -q -x 2>&1 | tail -20` (`-x` stops at the first failure).
- One test: `pytest tests/test_x.py::test_name -q`. Failures only: look at the `E ` lines.
- Install once: `.venv/bin/pip install -q pytest`.

## JS/TS
`bun test` or the project's `pnpm test`; type check with `pnpm tsc --noEmit` if TypeScript.

## Read the result honestly
Exit code 0 and "N passed" → proven. Anything else → it is not done: go to the `deboguer` method.
Never edit a test to make it pass unless the test itself is wrong — say so when you do.

## Report
Say what you ran and what it returned: "pytest -q: 14 passed", "curl /api/items → 200, 3 items",
"page shows the list and the Add button works". Say what you could NOT check.
