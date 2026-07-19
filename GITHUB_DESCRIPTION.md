# GitHub Description Copy

## Repository Description

```text
A very serious local CLI that keeps AI coding agents on task: one brief in, repo-aware build or repair work, checks, review, and proof out.
```

## Plain-English About Text

- The command is `manageroo`.
- Manageroo is a portable project controller for AI coding agents working on real Git repositories.
- It is **hardware-agnostic**. Manageroo core does not require a particular GPU, VRAM amount, CPU tier, or RAM class.
- `manageroo capacity` records the current development host's CPU, RAM, detectable GPU/VRAM, and free disk as context only. It does not auto-tune worker concurrency or turn one developer workstation into a minimum system requirement.
- A target project or explicitly selected local AI tool may have its own hardware requirements. Those belong to that project/tool, not to Manageroo.
- The core software requirements are Python 3.11+, Git, and at least one usable agent path for real AI work.
- Give Manageroo an existing Git repo, or use `solo --create` to start a missing or empty one.
- You write the brief. Manageroo maps the repo, creates bounded worker jobs, runs real checks, performs independent review, repairs failures, and saves evidence.
- Before implementation, the unknown-unknowns preflight reviews failure/recovery, proof strength, scope, and relevant signals such as auth, payments, migrations, deployment, target-project hardware, external services, accessibility, and user-facing states.
- Manageroo answers questions from repository evidence when it can and surfaces only genuinely high-impact unresolved choices as blocking decisions.
- `manageroo decisions show RUN_ID` displays those decisions; `manageroo decisions answer RUN_ID` records answers and lets the same durable run continue.
- The Python controller is the boss. Codex, Claude Code, Gemini, generic compatible CLIs, and future workers are disposable adapters; workers do not certify their own completion.
- The default `auto` worker pool can use compatible installed agents without making Manageroo vendor-specific.
- Manageroo's durable state, intent lock, project memory, proof bindings, transactional attempts, rollback, budgets, review, and completion evidence stay controller-owned.
- Manageroo installs only its small portable core skill pack by default.
- `use-installed-skills-first` lets workers use relevant host/tOS skills when present without Manageroo copying, deleting, upgrading, or claiming ownership of the host environment.
- `manageroo host-skills` inventories that boundary read-only.
- Optional integrations such as GBrain, GitNexus, Obsidian, AUTOREVIEW, and Clawpatch can add context or review lanes but do not become the source of truth for Manageroo completion.
- `manageroo stack-update` is dry-run by default and only updates already-installed optional components when `--apply` is explicit.
- `manageroo capacity` is informational; concurrency comes from project orchestration configuration because an arbitrary agent command may be cloud-backed, remote, or local.
- `manageroo next` prints one next operator action instead of dumping a giant workflow.
- `release-ready` is the final operator gate; it does not deploy.
- The release process is local and fail-closed. This repository does not use GitHub Actions.
- Credit to Matthew Berman / Forward Future's public loop-engineering work, including Loop Library, for clarifying bounded action, independent verification, budgets, stop rules, and evidence. Manageroo implements those ideas natively and does not connect to or depend on Loop Library.
- Credit to Peter Yang's public skill-writing advice for the skill-hygiene direction.
- Manageroo is not a replacement for tests, backups, security review, production monitoring, or human judgment.

## Core Boundary

```text
Manageroo portable core
    -> owns controller state, jobs, proof, review, repair, and completion
    -> installs only its small portable core skill pack
    -> works with different host hardware and different compatible agent providers

Host / tOS environment
    -> may contain extra skills and optional tools
    -> remains independently owned and maintained
    -> can be used when relevant without becoming Manageroo's public product definition
```
