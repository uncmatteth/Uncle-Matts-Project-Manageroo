# Research conclusions

## What already exists

The ecosystem already contains strong individual components:

- GStack: opinionated product, engineering, QA, review, and release skills.
- OpenSpec and Spec Kit: durable specification-driven planning.
- GitNexus: code graph and impact analysis.
- GBrain: durable agent memory and retrieval.
- Clawpatch and AUTOREVIEW: review and repair workflows.
- Matthew Berman / Forward Future's Loop Library and the loop-engineering
  discussion: clear language for goals, loops, routines, independent
  verification, budgets, anti-spin stops, completion contracts, and evidence.
- Peter Yang's public skill-writing advice: long-running threads work better
  when reusable skills have clear triggers and get periodically edited down
  instead of growing duplicate, stale, or vague instructions.
- Codex, Claude Code, OpenClaw, Gemini CLI, Cursor, and others: capable coding runtimes.
- Git worktrees, containers, CI, linters, type systems, and tests: mechanical engineering controls.

## What MANAGEROO contributes

MANAGEROO does not attempt to replace those systems. Its distinct role is the operator-facing control contract:

- one product intake;
- rough request cleanup through the bundled `pimp-my-prompt` skill;
- reusable skill creation through the bundled `write-a-skill` and `skillify` skills;
- externalized durable state;
- reversible decision defaults;
- reuse gate;
- bounded context compilation;
- pre-code plan review;
- task scope enforcement;
- controller-owned verification commands;
- isolated author/reviewer contexts;
- evidence-validated findings;
- bounded repair;
- explicit budget and anti-spin controls for loop-shaped work;
- skill hygiene through the bundled `edit-skill` skill;
- product-level final report.

## Why the architecture is intentionally smaller

An earlier design risked becoming a new IDE, memory service, graph database, workflow marketplace, and multi-agent platform simultaneously. The final architecture removes those ambitions. It is a thin local controller with explicit adapters. Optional tools can improve it without becoming hidden dependencies.
