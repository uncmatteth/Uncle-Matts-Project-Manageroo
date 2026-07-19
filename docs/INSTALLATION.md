# Installation

## Core requirements

Manageroo core requires:

- Python 3.11 or newer;
- Git;
- a normal terminal or PowerShell environment.

For real AI work, at least one compatible agent path must also be available, such as Codex, Claude Code, Gemini, or a configured generic CLI.

Manageroo does **not** require a particular GPU, VRAM amount, CPU tier, or RAM class. A selected target project or explicitly chosen local AI tool may have separate requirements.

## Human-first first install

The recommended first install is interactive and human-run. This lets the operator see what Manageroo is doing and make intentional choices about optional components.

Unix-like systems:

```bash
./install.sh
```

Windows PowerShell:

```powershell
.\install.ps1
```

The launchers install the same Manageroo product.

An AI or IDE agent can assist, but it should surface meaningful installer choices before selecting them on the user's behalf.

## Hardware profile

After installation:

```bash
manageroo capacity
manageroo capacity --json
```

This reports the current host's CPU, RAM, detectable NVIDIA GPU/VRAM, and free disk as **informational development context only**.

It does not:

- decide whether Manageroo is allowed to run;
- require a GPU;
- turn one developer machine into a minimum system requirement;
- automatically increase or reduce Manageroo worker concurrency.

Concurrency comes from project orchestration configuration because a configured agent may be cloud-backed, remote, local, or a custom CLI.

## Portable core skill pack

Manageroo installs a small portable core by default:

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

The repository may ship additional optional skill assets, but they are not Manageroo-owned default dependencies.

Inspect what the current host already has without changing anything:

```bash
manageroo host-skills
manageroo host-skills --json
```

`use-installed-skills-first` lets compatible workers use relevant host-installed skills when present. Manageroo does not copy, delete, upgrade, or claim ownership of the whole host skill environment.

Reconcile the Manageroo core later if needed:

```bash
manageroo skills reconcile --apply
```

## Recommended full stack

Manageroo can install and integrate with a recommended surrounding stack:

- **GitNexus** for repository and code-graph intelligence;
- **GBrain** for external durable knowledge when explicitly relevant;
- **AUTOREVIEW** for an external review lane;
- **Clawpatch** for an external review/repair lane;
- **Obsidian** for human-readable Markdown knowledge.

These tools add capabilities around Manageroo. They do not become authorities over Manageroo completion.

GitNexus is a first-class recommended integration. When the installer selected and installed GitNexus, the platform launcher completes `gitnexus setup` and updates the install lock to reflect whether configuration succeeded. A selected GitNexus setup failure fails the installation instead of being silently reported as complete.

Manageroo itself can still run without GitNexus when the operator intentionally skips the surrounding stack or GitNexus is unavailable.

Inspect the stack:

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
  --want "Describe the result"
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
manageroo stack-doctor
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

```text
Manageroo core
    = portable controller and its small core skill pack

Recommended surrounding stack
    = GitNexus, GBrain, AUTOREVIEW, Clawpatch, Obsidian when selected

Host environment
    = additional independently owned skills and tools

Target repository
    = may have its own runtime and hardware requirements
```

Do not collapse those layers into one system requirement, and do not let surrounding tools replace Manageroo's controller authority.
