---
name: organiser-une-tache
description: Plan and drive a task of more than a few steps (build an app, a feature, a migration) — split it, track it, keep context small, finish it.
---
# Organising a long task

## Before the first call
1. Restate the goal in one sentence and what "done" looks like (what the user will run or see).
2. Resuming a project: read STATE.md and TODO.md first, then the files they point to.
3. Split into 4-8 steps, each ending in something you can check. Write them with `suivre_taches`.
   Good step: "API /items returns the list (curl)". Bad step: "work on the backend".

## While working
- One step `en_cours` at a time. Finish it (proof) before starting the next.
- Each step: find (search) → change (write/edit) → check (run) → mark `fait` with the proof.
- Unexpected problem bigger than the step → add a step to the list rather than drifting silently.
- Decide yourself on implementation details (names, library, file layout). Ask the user only what only
  the user can answer (a business choice, a credential, a taste), in ONE precise question.

## Keep your context light
- Short outputs: `| tail -20`, `| head -40`, `-q`. Never print a whole log or a large file.
- Do not re-read what is already above in the conversation.
- Long task (several sessions, many modules): keep STATE.md up to date (what works, what is next,
  decisions and why). After a compaction, it is how you find your way back.
- Save to `~agent/memoire/` a fact a FUTURE conversation will need (a user preference, a pitfall and its fix).

## Finishing
Run the whole thing once more end to end. Report: what was built, how to run it, what you verified
(with results), what remains. Leave servers the user needs running and give the address.
