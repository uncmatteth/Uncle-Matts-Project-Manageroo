# Uncle Matt's Project Manageroo

Use `manageroo` at the terminal. The name is incredibly super serious.

Manageroo is a local control plane for AI coding agents working on real Git repositories.

```text
ONE PLAIN-ENGLISH BRIEF
        ↓
MANAGEROO CONTROLLER
        ↓
BOUNDED WORKER JOBS
        ↓
REAL CHECKS + REVIEW
        ↓
REPAIR IF NEEDED
        ↓
PATCH + REPORT + EVIDENCE
```

The point is simple: stop relying on one giant AI chat to remember everything, make every change correctly, review itself, and confidently say “done.”

Manageroo keeps the durable truth on disk. Workers are disposable.

## What Manageroo is

Manageroo:

- reads a Git repository;
- captures the requested outcome, must-not rules, and proof expectations;
- creates bounded worker assignments;
- launches compatible coding-agent CLIs;
- records every job and retry;
- verifies scope and repository state;
- runs deterministic checks;
- performs independent review;
- repairs failed work within budgets;
- blocks completion when required proof is missing;
- produces a final patch, report, and evidence trail.

Manageroo is **not** an IDE, model host, memory database, code graph, cloud scheduler, or deployment platform.

## Hardware compatibility

Manageroo core is **hardware-agnostic**.

It does not require:

- Tommy's workstation specs;
- a GPU;
- a particular VRAM amount;
- a CPU tier;
- a RAM class.

The core software requirements are:

- Python 3.11+;
- Git;
- a usable terminal or PowerShell environment.

For real AI work, at least one compatible agent path must also be available.

Inspect the current host with:

```bash
manageroo capacity
manageroo capacity --json
```

That command records CPU, RAM, detectable GPU/VRAM, and free disk as **development context only**.

Manageroo does **not** automatically increase or reduce worker concurrency from detected hardware. A worker can be cloud-backed, remote, local, or a custom CLI, so Manageroo cannot truthfully infer the cost of one agent call from host CPU/RAM/GPU.

A target project or explicitly selected local AI tool can still have its own hardware requirements. Those belong to that project or tool, not to Manageroo.

## Agent support

The default agent mode is provider-neutral `auto`.

Built-in paths cover:

- Codex;
- Claude Code;
- Gemini;
- a generic CLI adapter.

If a compatible AI IDE or CLI can read files and run commands in the repo, it does not need a special Manageroo build.

```bash
manageroo agent list
```

## Durable runs

Every run stores controller-owned truth under:

```text
.manageroo/runs/<run-id>/
```

That includes:

- controller state;
- phase journal;
- worker jobs;
- worker attempts;
- prompts;
- agent outputs;
- planning artifacts;
- verification evidence;
- review evidence;
- delivery output.

`manageroo run --continue <run-id>` resumes from durable saved state. It does not pretend a dead OS process kept running.

## Proof before “done”

Manageroo does not let a worker certify its own work.

Completion requires the controller to reconcile:

- requested outcomes;
- bound proof gates;
- changed-file scope;
- review state;
- verification results;
- required demonstration evidence.

Observable browser flows, authentication behavior, security claims, deployment claims, visual outcomes, and user journeys remain unknown unless matching evidence exists.

## Discovery and unknown unknowns

Before implementation, the product analyst receives a deterministic preflight that reviews things the operator may not know to ask about, including:

- failure and recovery;
- proof strength;
- scope and non-goals;
- authentication and authorization;
- payments and reconciliation;
- migrations and data preservation;
- deployment and rollback;
- target-project hardware or local-AI assumptions;
- external services and rate limits;
- accessibility and user-facing states.

High-impact unresolved decisions can be answered with:

```bash
manageroo decisions show RUN_ID --repo /path/to/repo
manageroo decisions answer RUN_ID --repo /path/to/repo
manageroo run --continue RUN_ID --repo /path/to/repo --apply
```

The development host's hardware profile is never turned into a Manageroo minimum requirement.

## Portable core skills

Manageroo installs a small portable default core:

1. `uncle-matts-project-manageroo`
2. `use-installed-skills-first`
3. `pimp-my-prompt`
4. `to-prd`
5. `to-issues`
6. `grill-me`
7. `grill-with-docs`
8. `diagnose`
9. `tdd`
10. `testing`
11. `security-review`
12. `handoff`
13. `write-a-skill`
14. `edit-skill`
15. `skillify`
16. `caveman`
17. `uncle-matts-caveman-curse`

The source distribution may contain additional optional skill assets. They are not installed as Manageroo-owned defaults.

## tOS and host skills

Tommy's tOS is a host environment, not the public Manageroo product definition.

```text
Manageroo portable core
    -> owns controller state, runs, evidence, review, repair, completion
    -> owns only the small core skill pack

Host / tOS
    -> may contain many extra skills and tools
    -> remains independently owned and maintained
    -> can expose relevant capabilities to Manageroo workers
```

Inspect the boundary without modifying anything:

```bash
manageroo host-skills
manageroo host-skills --json
```

`use-installed-skills-first` is the bridge. Relevant installed host skills may be used when appropriate, but Manageroo does not copy, delete, upgrade, or claim ownership of the whole host skill environment.

An installed competing orchestrator does not replace Manageroo's controller during a Manageroo run.

## Optional integrations

Manageroo can coexist with and optionally use:

- GBrain;
- GitNexus;
- Obsidian;
- AUTOREVIEW;
- Clawpatch.

These are surrounding lanes, not authorities over Manageroo completion.

Inspect them:

```bash
manageroo stack-status
manageroo stack-doctor
```

Preview updates:

```bash
manageroo stack-update
```

Explicitly apply supported updates to already-installed components:

```bash
manageroo stack-update --apply
```

## Install

Unix-like systems:

```bash
./install.sh
```

Windows PowerShell:

```powershell
.\install.ps1
```

The installer includes the Manageroo terminal banner and generated chiptune music. Music is generated at a reduced default level, and the banner is resize-safe: it animates once and then behaves like normal terminal output instead of repainting fixed screen rows.

Useful installer controls:

```bash
./install.sh --no-music
./install.sh --no-animation
./install.sh --skill-pack skip
./install.sh --install-stack
./install.sh --skip-stack
```

## First project

Discover existing projects:

```bash
manageroo projects --add
```

Start in an existing repo:

```bash
manageroo solo /absolute/path/to/product
```

Create a new missing or empty repo:

```bash
manageroo solo /absolute/path/to/new-product \
  --create \
  --want "Describe what should be built first"
```

Use a starter:

```bash
manageroo solo /absolute/path/to/new-site \
  --create \
  --starter static-site \
  --want "Build a simple product homepage"
```

When unsure what to do next:

```bash
manageroo next
```

## Run

Build:

```bash
manageroo run --apply
```

Repair:

```bash
manageroo run --mode repair --apply
```

Inspect:

```bash
manageroo status RUN_ID --repo .
manageroo report RUN_ID --repo .
```

## Project memory and intent

Manageroo keeps small repo-local continuity files instead of trusting chat history:

```text
.manageroo/PROJECT-MEMORY.md
.manageroo/intent/INTENT-LOCK.json
.manageroo/intent/INTENT-LOCK.md
```

Useful commands:

```bash
manageroo memory show
manageroo intent show
manageroo compact audit --summary SUMMARY.md
```

## Release gate for managed projects

Before a production release of a project managed by Manageroo:

```bash
manageroo release-ready \
  --target "Production deploy path" \
  --rollback "Rollback steps" \
  --approved-by "Your name"
```

This does not deploy. It is an operator gate.

## Manageroo's own release proof

This repository intentionally does **not** use GitHub Actions.

The fail-closed release command is:

```bash
python3 scripts/release.py
```

That command must complete:

1. adversarial Manageroo product proof;
2. regression and structural verification;
3. packaging and checksums;
4. clean-install end-user ZIP smoke testing;
5. release drop assembly.

A release is not honestly certified until that command passes on a real machine. A passing smoke on one operating system proves only that operating system.

## Architecture principle

```text
Manageroo
    ↓
universal worker/adapter protocol
    ↓
Codex / Claude / Gemini / compatible future agents
    ↓
normalized structured responses
    ↓
Manageroo-owned verification / review / evidence / completion
```

The controller is the product. The surrounding tools are optional capabilities.

## Credits

Credit where it is due: Matthew Berman / Forward Future's public loop-engineering work, including Loop Library, helped clarify the pattern: bounded action, independent verification, a budget, a stop condition, and evidence. MANAGEROO implements those ideas natively and does not connect to or depend on Loop Library.

Peter Yang's public skill-writing advice influenced the skill-hygiene direction: clear triggers, reusable procedures, and edit passes that remove duplicate or stale instructions.

GBrain, GitNexus, OpenClaw Agent Skills/AUTOREVIEW, Clawpatch, Obsidian, and the OpenAI Codex skill ecosystem all influenced optional integration or workflow ideas around the controller.

## Documentation

- [`LOCAL_SETUP.md`](LOCAL_SETUP.md)
- [`PUBLISH_TO_GITHUB.md`](PUBLISH_TO_GITHUB.md)
- [`docs/00_START_HERE.md`](docs/00_START_HERE.md)
- [`docs/INSTALLATION.md`](docs/INSTALLATION.md)
- [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md)
- [`docs/DISCOVERY_AND_CAPACITY.md`](docs/DISCOVERY_AND_CAPACITY.md)
- [`docs/HOST_AND_TOS_INTEGRATION.md`](docs/HOST_AND_TOS_INTEGRATION.md)
- [`docs/LIMITATIONS.md`](docs/LIMITATIONS.md)
