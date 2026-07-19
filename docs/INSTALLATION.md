# Installation

## Core requirements

Manageroo core requires:

- Python 3.11 or newer;
- Git;
- a normal terminal or PowerShell environment.

For real AI work, at least one compatible agent path must also be available, such as Codex, Claude Code, Gemini, or a configured generic CLI.

Manageroo does **not** require a particular GPU, VRAM amount, CPU tier, or RAM class. The selected target project or an explicitly chosen local AI tool may have separate requirements.

## Install

Unix-like systems:

```bash
./install.sh
```

Windows PowerShell:

```powershell
.\install.ps1
```

The launchers install the same Manageroo product.

## Hardware profile

After installation:

```bash
manageroo capacity
manageroo capacity --json
```

This reports the current host's CPU, RAM, detectable NVIDIA GPU/VRAM, and free disk as **informational development context only**.

It does not:

- decide whether Manageroo is allowed to run;
- turn Tommy's workstation into the minimum requirement;
- require a GPU;
- automatically increase or reduce Manageroo worker concurrency.

Concurrency comes from the project orchestration configuration because a configured agent may be cloud-backed, remote, local, or a custom CLI.

## Portable core skill pack

Manageroo installs a small portable core by default:

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

The repository may ship additional skill assets as an optional library, but they are not Manageroo-owned default dependencies.

Inspect what the current host already has without changing anything:

```bash
manageroo host-skills
manageroo host-skills --json
```

`use-installed-skills-first` lets compatible workers use relevant host/tOS skills when present. Manageroo does not copy, delete, upgrade, or claim ownership of the whole host skill environment.

Reconcile the Manageroo core later if needed:

```bash
manageroo skills reconcile --apply
```

## Optional local stack

Manageroo can coexist with and optionally integrate with:

- GBrain;
- GitNexus;
- Obsidian;
- AUTOREVIEW;
- Clawpatch.

These are surrounding tools, not requirements for the Manageroo core controller.

Inspect them:

```bash
manageroo stack-status
manageroo stack-doctor
```

Preview supported updates without changing anything:

```bash
manageroo stack-update
```

Explicitly apply supported updates to already-installed components:

```bash
manageroo stack-update --apply
```

The updater does not use absence as permission to install every optional component.

## Installer controls

Common options include:

```bash
./install.sh --no-music
./install.sh --no-animation
./install.sh --install-codex
./install.sh --install-stack
./install.sh --skip-stack
./install.sh --skill-pack install
./install.sh --skill-pack skip
./install.sh --project-discovery add
./install.sh --project-discovery pick
./install.sh --project-discovery skip
./install.sh --token-mode caveman
./install.sh --token-mode curse
./install.sh --skip-tests
```

PowerShell exposes equivalent parameters.

## First project

Discover existing Git projects:

```bash
manageroo projects --add
```

Start Manageroo in an existing repo:

```bash
manageroo solo /absolute/path/to/product
```

Create a new missing or empty repo:

```bash
manageroo solo /absolute/path/to/new-product \
  --create \
  --want "Describe what should be built first"
```

Use the default provider-neutral worker pool unless you need to force a specific agent.

## Validate the install

```bash
manageroo --version
manageroo banner --no-animation
manageroo self-test
manageroo skills list
manageroo host-skills
manageroo token-mode status
manageroo stack-status
manageroo repair-install --no-apply
```

## Release proof

The repository intentionally does not use GitHub Actions. The fail-closed release command is:

```bash
python3 scripts/release.py
```

It must complete product proof, source verification, packaging, checksum generation, and a clean-install ZIP smoke before the release is considered shippable.

A passing smoke on one operating system proves that operating system only.

## Truth boundary

Manageroo is the controller. Optional host tools, local skills, tOS, and the developer's hardware are context and capabilities around it.

```text
Manageroo core = portable controller
Host/tOS = optional extra capabilities
Target repo = may have its own runtime and hardware requirements
```

Do not collapse those three layers into one system requirement.
