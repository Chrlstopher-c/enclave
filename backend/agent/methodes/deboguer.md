---
name: deboguer
description: Something fails or behaves wrong (traceback, failing test, blank page, wrong output) — find the real cause and fix it without going in circles.
---
# Debugging

## 1. Reproduce with one command
Find the shortest command that shows the failure (`pytest tests/test_x.py::test_y -x -q`, `python app.py`,
`curl -s localhost:8000/api`). You will rerun exactly this after the fix.

## 2. Read the error from the BOTTOM
A Python traceback: the last line is the error, the last frame in YOUR code is where to look
(frames inside site-packages are rarely the cause). Keep the end: `cmd 2>&1 | tail -30`.
For a JS/browser error: the server log (`serveur_fond` journal) and the browser console.

## 3. Form ONE hypothesis, test it cheaply
State it in one sentence: "`config` is None because the file path is relative". Check it with one
command (print the value, `ls` the path, `python -c` the expression). Confirmed → fix. Refuted → next
hypothesis. Do not change code on a guess.

## 4. Fix the cause, rerun the same command
Then run the wider check (all tests, or the whole app) to see nothing else broke.

## Common causes, check first
- ImportError / ModuleNotFoundError: wrong venv (`which python`), package not installed, wrong module name.
- File not found: relative path vs current directory (`pwd`, `ls`), typo in the name (`rg --files | rg name`).
- Port already in use: an old server still runs (`serveur_fond` list / stop, or `ss -ltnp | grep :PORT`).
- Works in the shell, not in the app: different env variables or working directory.
- A library "lacks" a function: check the installed version (`pip show pkg`) and its real API before
  working around it.

## Going in circles?
Same error twice after two different fixes → stop editing. Re-read the error, list what you know for
sure, add one print at the boundary where the data becomes wrong. Third failure on the same point →
explain to the user what you tried and what you see, and ask.
