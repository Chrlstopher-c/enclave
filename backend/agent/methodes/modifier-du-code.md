---
name: modifier-du-code
description: Change existing code safely — fix, rename, add a feature to files you did not just write — and prove nothing else broke.
---
# Changing existing code

## Steps
1. Locate: `rg -n -w <name>` lists the definition AND every use. Note them all now: a change to a
   function signature, a field or a route must be applied to every use in the same pass.
2. Read the exact range you will change with `lire_fichier` (`ligne_debut`/`ligne_fin`). Your memory of
   the file is not the file.
3. Baseline: run the existing check BEFORE editing (tests, or running the program) so you know what
   already failed. `pytest -q 2>&1 | tail -15`.
4. Edit with `modifier_fichier`: copy the old fragment verbatim (indentation included), a few lines
   that appear once. Several separate spots = several `modifier_fichier` calls.
5. Same check again. Compare with the baseline. Then `rg -n -w <old_name>` must return nothing after a rename.

## Choosing the tool
- A few lines → `modifier_fichier`.
- More than half the file changes, or the file is small (< 80 lines) → `ecrire_fichier` with the whole new
  content (read it first so you lose nothing).
- The same mechanical replacement in many files → one shell command, then verify:
      rg -l -w old_name | xargs sed -i 's/\bold_name\b/new_name/g' && rg -n -w old_name
- `modifier_fichier` says the fragment is not found → `lire_fichier` that range again and copy exactly;
  do not retry with the same text.

## Rules
- Fix the cause, not the symptom: if a value is wrong, find where it is produced (`rg`), fix it there.
- Change only what the task needs. No unrelated renames or reformatting.
- A file growing past ~400 lines → move a cohesive part to a new module instead of adding more.
