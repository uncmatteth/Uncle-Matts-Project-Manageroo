# Uncle Matt's Project Manageroo

## Install in one command

**Linux / macOS:**

```bash
git clone https://github.com/uncmatteth/Uncle-Matts-Project-Manageroo.git && cd Uncle-Matts-Project-Manageroo && ./install.sh
```

**Windows PowerShell:**

```powershell
git clone https://github.com/uncmatteth/Uncle-Matts-Project-Manageroo.git; Set-Location Uncle-Matts-Project-Manageroo; .\install.ps1
```

The installer walks you through the optional stack and setup choices. Requirements: Python 3.11+ and Git.

Use `manageroo` at the terminal. The name is incredibly super serious.

Manageroo is a local control plane for AI coding agents working on real Git repositories.

```text
ONE PLAIN-ENGLISH BRIEF
        ↓
MANAGEROO CONTROLLER
        ↓
DISCOVERY + BOUNDED WORKER JOBS
        ↓
REAL CHECKS + INDEPENDENT REVIEW
        ↓
REPAIR IF NEEDED
        ↓
PATCH + REPORT + EVIDENCE
```

The point is simple: stop relying on one giant AI chat to remember everything, make every change correctly, review itself, and confidently say “done.”

Manageroo keeps durable truth on disk. Workers are disposable.

## What Manageroo owns

Manageroo:

- reads a Git repository;
- captures the requested outcome, must-not rules, and proof expectations;
- maps and analyzes the repository before implementation;
- creates bounded worker assignments;
- launches compatible coding-agent CLIs;
- records every job and retry;
- verifies changed-file scope and repository state;
- runs deterministic checks;
- performs independent review;
- repairs failed work within budgets;
- blocks completion when required proof is missing;
- produces a final patch, report, and evidence trail.

Manageroo is **not** an IDE, model host, memory database, code graph database, cloud scheduler, or deployment platform.

## Architecture

```text
Manageroo controller
    ↓
universal worker / adapter protocol
    ↓
Codex / Claude Code / Gemini / compatible future agents
    ↓
normalized structured responses
    ↓
Manageroo-owned verification / review / evidence / completion
```

The controller is the authority. Workers do not certify their own work.

Every run stores controller-owned truth under:

```text
.manageroo/runs/<run-id>/
```

That includes controller state, phase journals, jobs, attempts, prompts, planning artifacts, verification evidence, review evidence, and final delivery output.

`manageroo run --continue <run-id>` resumes from those durable artifacts. It does not pretend a dead process kept running.

## Source isolation

Manageroo works from a run-owned isolated repository. Coding agents do not need direct write access to the operator's source repository.

After successful delivery, Manageroo:

1. generates a binary-capable Git patch;
2. verifies the original source repository still matches its starting manifest;
3. runs `git apply --check`;
4. applies the patch only when `--apply` or project policy allows it;
5. records whether source application actually happened.

Concurrent source changes block application instead of being guessed around.

## Proof before “done”

Completion requires Manageroo to reconcile:

- requested outcomes;
- bound proof gates;
- changed-file scope;
- review state;
- verification results;
- required demonstration evidence.

Observable browser flows, authentication behavior, security claims, deployment claims, visual outcomes, and user journeys remain unknown unless matching evidence exists.

## Discovery and unknown unknowns

Before implementation, Manageroo's discovery preflight reviews areas the operator may not know to ask about, including:

- failure, interruption, rollback, and recovery;
- proof strength;
- scope and non-goals;
- authentication and authorization;
- payments and reconciliation;
- migrations and data preservation;
- deployment and rollback;
- target-project hardware or local-AI assumptions;
- external services, rate limits, cost, and degraded mode;
- accessibility and user-facing states.

High-impact unresolved choices become explicit blocking decisions:

```bash
manageroo decisions show RUN_ID --repo /path/to/repo
manageroo decisions answer RUN_ID --repo /path/to/repo
manageroo run --continue RUN_ID --repo /path/to/repo --apply
```

## Hardware compatibility

Manageroo core is **hardware-agnostic**.

It does not require a GPU, a particular VRAM amount, a CPU tier, or a RAM class.

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

The hardware profile is development context only. Manageroo does not automatically increase or reduce worker concurrency from detected CPU, RAM, GPU, or VRAM.

A target project or explicitly selected local AI tool may still have its own hardware requirements.

## Agent support

The default agent mode is provider-neutral `auto`.

Built-in paths cover:

- Codex;
- Claude Code;
- Gemini;
- a generic CLI adapter.

```bash
manageroo agent list
```

## Recommended full stack

Manageroo is the controller, but the intended full installation can also set up a first-class surrounding tool stack:

```text
Manageroo
├── GitNexus   → repository/code-graph intelligence
├── GBrain     → external durable knowledge when explicitly relevant
├── AUTOREVIEW → external review lane
├── Clawpatch  → external review/repair lane
└── Obsidian   → human-readable knowledge lane
```

These tools add capabilities without becoming authorities over Manageroo completion.

**GitNexus is a first-class recommended repository-intelligence integration.** When selected during installation, Manageroo installs it and completes `gitnexus setup`. Manageroo still degrades gracefully when GitNexus is unavailable.

Inspect the surrounding stack with:

```bash
manageroo stack-status
manageroo stack-doctor
```

Preview updates:

```bash
manageroo stack-update
```

Apply supported updates explicitly:

```bash
manageroo stack-update --apply
```

## Portable core skills

Manageroo installs a small portable default core:

1. `uncle-matts-project-manageroo`
2. `use-installed-skills-first`
3. `skill-vetter`
4. `pimp-my-prompt`
5. `to-prd`
6. `to-issues`
7. `grill-me`
8. `grill-with-docs`
9. `diagnose`
10. `tdd`
11. `testing`
12. `security-review`
13. `handoff`
14. `write-a-skill`
15. `edit-skill`
16. `skillify`
17. `caveman`
18. `uncle-matts-caveman-curse`

The source distribution may contain additional optional skill assets, but they are not installed as Manageroo-owned defaults.

`skill-vetter` provides a security-first review lane for third-party skills before installation or adoption.

## Host skill boundary

A user's host environment may contain additional skills and tools that are not part of Manageroo itself.

```text
Manageroo portable core
    -> owns controller state, runs, evidence, review, repair, completion
    -> owns only the small portable core skill pack

Host environment
    -> may contain additional skills and tools
    -> remains independently owned and maintained
    -> can expose relevant capabilities to Manageroo workers
```

Inspect that boundary without modifying anything:

```bash
manageroo host-skills
manageroo host-skills --json
```

`use-installed-skills-first` is the bridge. Relevant host-installed skills may be used when appropriate, but Manageroo does not copy, delete, upgrade, or claim ownership of the whole host skill environment.

An installed competing orchestrator does not replace Manageroo's controller during a Manageroo run.

## Install

The recommended **first install is human-first**. Run the installer yourself so you can see what is happening and choose optional components intentionally.

Unix-like systems:

```bash
./install.sh
```

Windows PowerShell:

```powershell
.\install.ps1
```

Useful installer controls:

```bash
./install.sh --no-music
./install.sh --no-animation
./install.sh --skill-pack skip
./install.sh --install-stack
./install.sh --skip-stack
```

An AI or IDE agent may assist with installation, but it should surface meaningful choices before selecting them on the user's behalf.

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

External memory systems are not required for ordinary project continuity.

## Release gate for managed projects

Before a production release of a project managed by Manageroo:

```bash
manageroo release-ready \
  --target "Production deploy path" \
  --rollback "Rollback steps" \
  --approved-by "Your name"
```

This is an operator gate. It does not deploy.

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

## Credits

Credit where it is due: Matthew Berman / Forward Future's public loop-engineering work, including Loop Library, helped clarify the pattern of bounded action, independent verification, budgets, stop conditions, and evidence. Manageroo implements those ideas natively and does not connect to or depend on Loop Library.

Peter Yang's public skill-writing advice influenced the skill-hygiene direction: clear triggers, reusable procedures, and edit passes that remove duplicate or stale instructions.

GBrain, GitNexus, OpenClaw Agent Skills/AUTOREVIEW, Clawpatch, Obsidian, and the OpenAI Codex skill ecosystem influenced integration and workflow ideas around the controller.

## Documentation

- [`LOCAL_SETUP.md`](LOCAL_SETUP.md)
- [`PUBLISH_TO_GITHUB.md`](PUBLISH_TO_GITHUB.md)
- [`docs/00_START_HERE.md`](docs/00_START_HERE.md)
- [`docs/INSTALLATION.md`](docs/INSTALLATION.md)
- [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md)
- [`docs/DISCOVERY_AND_CAPACITY.md`](docs/DISCOVERY_AND_CAPACITY.md)
- [`docs/HOST_INTEGRATION.md`](docs/HOST_INTEGRATION.md)
- [`docs/LIMITATIONS.md`](docs/LIMITATIONS.md)