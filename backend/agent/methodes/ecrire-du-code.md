---
name: ecrire-du-code
description: Write new code — a script, a module, the files of a new feature — so that it runs the first time and stays small and readable.
---
# Writing new code

## The rhythm: one file, then run it
1. Decide the files before writing: one responsibility each, under ~300 lines, named after what they do
   (`scanner.py`, `report.py`), grouped by feature, not by layer.
2. Write ONE file completely with `ecrire_fichier` (the whole content in the call, no placeholders, no
   "..." or "rest unchanged").
3. Run it at once: `python -c "import module"` catches syntax and import errors; then a tiny real call,
   or its test. Fix before writing the next file.
4. Next file. Never write five files and test at the end: errors then pile up and hide each other.

## Inside a file
- Top: imports, constants. Then small functions (under ~35 lines) with type hints and a one-line docstring.
- Every call to the outside (file, network, subprocess, DB) is wrapped: catch the specific exception,
  log it, return or raise something meaningful.
- No dead code, no commented-out blocks, no TODO left without telling the user.
- Script entry point: `if __name__ == "__main__": main()`.

## Dependencies
- Python: a venv in the project (`python3 -m venv .venv && .venv/bin/pip install -q <pkg>`), and a
  `requirements.txt`. Run with `.venv/bin/python`.
- JS/TS: pnpm (`corepack enable pnpm` once if `pnpm` is missing). Never npm.
- Install the latest version unless the project pins one; never guess a version number from memory.

## Large content (HTML page, long file)
Write the structure first (a minimal page that loads), check it, then add sections with
`modifier_fichier`. A file over ~400 lines is split (CSS and JS in their own files).
