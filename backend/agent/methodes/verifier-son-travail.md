---
name: verifier-son-travail
description: After writing or changing files — check in ONE command that they run, pass lint, respect size rules, are wired into the project, have no dead functions and pass their tests.
---
# Checking your work: the `verifier` command

You just wrote or changed something. Do not check it by eye, do not reread the file: run
`verifier` in `executer_commande` (from the project folder).

    verifier app/scanner.py              # the files you touched (several allowed)
    verifier                             # every file git sees as modified or new
    verifier --projet                    # + the project's organisation (docs, venv, layout, big files)
    verifier --tout --sans-tests         # every source file, quick (tests skipped)

For each file it reports OK / FAIL / WARN on:
- syntax (Python compile, bun/node for JS/TS, bash -n, JSON);
- lint (ruff for Python: unused imports, undefined names, bugs; eslint if the project has it; tsc for TS);
- size rules (file ≤ 500 lines, function ≤ 35, line ≤ 120);
- integration: which file imports/loads it — or that NOTHING does (your new module is not wired in);
- dead code: top-level functions/classes defined but used nowhere;
- tests: runs the tests that mention the file and gives the result.
Exit code 1 while any FAIL remains. One call costs about a second.

## Reading it and fixing — one FAIL at a time, top to bottom
- `syntax` → fix that line first; nothing else is reliable until it parses.
- `lint` → `F821 undefined name` and `F401 unused import` are real bugs or leftovers. `[*]` ones:
  `ruff check --fix <file>`. Then fix the rest by hand.
- `size rules` → extract a part of the long function into a named helper; split a big file by responsibility.
- `NOT integrated` → the code exists but nothing uses it: add the import / route / script tag where the
  feature belongs, or delete the file if it is not needed. "mentioned but never imported" = probably a
  wrong import path or name.
- `defined but never used` → wire it in, or delete it. Never leave dead code "for later".
- `tests FAIL` → read the `E ` lines; go to the `deboguer` method. `no test mentions this file` on real
  logic → write one (`tester-et-prouver`).
Rerun `verifier` on the same files after the fixes. Done = no FAIL; WARN only with a reason you state.

## Then
`verifier` proves the code is sound, not that the feature works: still run the real thing once
(the command, the page, the API call) before saying it is done.
