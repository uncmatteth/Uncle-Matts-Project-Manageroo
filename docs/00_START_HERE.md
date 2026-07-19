# Start here

## What Manageroo is

**Uncle Matt's Project Manageroo** is a local CLI that makes AI coding agents follow a bounded, evidence-driven job.

```text
You explain what should be built or fixed.
Manageroo captures the brief and intent.
Manageroo reads the repo and creates bounded worker jobs.
Compatible AI agents do the code work.
Manageroo runs checks, reviews the result, repairs failures, and keeps the receipts.
```

The controller, not the worker, decides whether the job is complete.

## Hardware

Manageroo core is hardware-agnostic.

It does not require a GPU, a VRAM tier, or a particular RAM/CPU class.

```bash
manageroo capacity
```

That command reports the current development host as context only. It does not auto-tune worker concurrency or decide whether Manageroo is supported.

A target project or explicitly selected local AI tool may still have its own hardware requirements.

## Install

The recommended first install is human-first so the operator can see what is happening and choose optional components intentionally.

Unix-like systems:

```bash
./install.sh
```

Windows PowerShell:

```powershell
.\install.ps1
```

Then validate:

```bash
manageroo --version
manageroo self-test
manageroo skills list
manageroo host-skills
manageroo token-mode status
manageroo stack-status
manageroo stack-doctor
```

## Portable core skills

Manageroo installs 18 core skills by default:

- `uncle-matts-project-manageroo`
- `use-installed-skills-first`
- `skill-vetter`
- `pimp-my-prompt`
- `to-prd`
- `to-issues`
- `grill-me`
- `grill-with-docs`
- `diagnose`
- `tdd`
- `testing`
- `security-review`
- `handoff`
- `write-a-skill`
- `edit-skill`
- `skillify`
- `caveman`
- `uncle-matts-caveman-curse`

Additional host skills remain host-owned and optional.

Inspect them without changing anything:

```bash
manageroo host-skills
manageroo host-skills --json
```

## Recommended surrounding stack

Manageroo's full recommended setup can include:

- GitNexus for repository/code-graph intelligence;
- GBrain for external durable knowledge when explicitly relevant;
- AUTOREVIEW for external review;
- Clawpatch for external review and repair;
- Obsidian for human-readable knowledge.

GitNexus is a first-class recommended integration. When selected during installation, Manageroo installs it and completes `gitnexus setup`.

These tools add capabilities without replacing Manageroo's controller authority.

```bash
manageroo stack-status
manageroo stack-doctor
manageroo stack-update
```

`stack-update` is a dry run unless `--apply` is explicit. You can also target specific installed tools, for example:

```bash
manageroo stack-update gitnexus
manageroo stack-update gitnexus --apply
```

## Start a project

Discover existing Git repos:

```bash
manageroo projects --add
```

Existing repo:

```bash
manageroo solo /absolute/path/to/product
```

New missing or empty repo:

```bash
manageroo solo /absolute/path/to/new-product \
  --create \
  --want "Describe what should be built first"
```

Useful starter:

```bash
manageroo solo /absolute/path/to/new-site \
  --create \
  --starter static-site \
  --want "Build a simple product homepage"
```

## What Solo Operator Mode does

`solo` prepares:

- the Manageroo project configuration;
- the product brief;
- project memory;
- the intent lock;
- readiness checks;
- one next action.

When unsure:

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

Continue a durable interrupted run:

```bash
manageroo run --continue RUN_ID --repo . --apply
```

## Blocking decisions

When Manageroo cannot safely infer a genuinely high-impact decision:

```bash
manageroo decisions show RUN_ID --repo .
manageroo decisions answer RUN_ID --repo .
manageroo run --continue RUN_ID --repo . --apply
```

## Memory and intent

```bash
manageroo memory show
manageroo intent show
manageroo compact audit --summary SUMMARY.md
```

Manageroo stores durable project truth on disk instead of trusting a long chat transcript. External memory systems are optional unless a task explicitly needs them.

## Release gate for a managed project

```bash
manageroo release-ready \
  --target "Production deploy path" \
  --rollback "Rollback steps" \
  --approved-by "Your name"
```

This is an operator gate, not a deployment command.

## Manageroo's own release proof

```bash
python3 scripts/release.py
```

That fail-closed command must pass product proof, regressions, packaging, checksums, and clean-install ZIP smoke before Manageroo itself is considered shippable.

## Boundary

```text
Manageroo core
    portable controller + 18 core skills

Recommended surrounding stack
    GitNexus + GBrain + AUTOREVIEW + Clawpatch + Obsidian when selected

Host environment
    independently owned additional skills and tools

Target repo
    its own runtime, build, deployment, and possible hardware requirements
```

Keep those layers separate.
