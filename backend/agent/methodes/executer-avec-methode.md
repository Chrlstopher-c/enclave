---
name: executer-avec-methode
description: How to think while working so you are fast AND meticulous — zoom on one point, define the proof, take the smallest step, check it, move on. Read it when a task feels big or you start going in circles.
---
# Being executive and meticulous

The usual failure is not a lack of knowledge: it is staying GLOBAL. You look at the whole project,
change several things at once, check nothing precisely, and loop. Work the other way.

## Plan globally, execute locally
The global view is only for the plan (`suivre_taches`). Execution always happens at ONE point:
one file, one function, one error. Before each tool call you can say in one sentence:
"I am doing X in <file/function>, and <this command> will prove it."
If you cannot name the point and the proof, you are not ready to call a tool: search first.

## The micro-cycle (repeat until the step is done)
1. Locate — `rg` / `plan_fichier` gives the exact file and line. (`chercher-dans-le-code`)
2. Read — only that range.
3. Change — only that, the smallest change that moves the step forward.
4. Check — `verifier <file>`, then run the real thing (test, command, curl). (`verifier-son-travail`)
5. Decide from the RESULT, not from your plan: OK → next point; FAIL → this is now the point.

## Rules that save the most time
- Fast path first: the tool that answers in one call (`rg`, `verifier`, `--help`, the error's last line)
  beats reading. Reading is for after you know where.
- One change, one check. Two unchecked changes = when it fails you don't know which one broke it.
- An error is information: read its exact text and line before touching code. Never "try something".
- Same symptom twice → stop; your model of the problem is wrong. Write down what you KNOW (facts from
  outputs) vs what you ASSUME, and test the assumption with one command.
- Finish what you start: a step is closed by a proof, then marked done. Never leave a half-wired file
  (`verifier` says NOT integrated) to go do something else.
- Don't polish what was not asked; don't stop before what was asked works end to end.

## Before saying "done"
`verifier` with no FAIL on every file you touched, the real feature run once, and in your report: what
you ran and what it returned. If something could not be checked, say it.
