# Installation

## Core requirements

Manageroo core uses:

- Python 3.11 or newer;
- Git;
- a normal terminal or PowerShell environment.

The platform launcher checks these requirements and, in an interactive terminal, offers to install missing ones using a normal platform path. Windows uses winget. Linux supports Homebrew, apt, dnf, yum, pacman, and zypper. On macOS, the launcher first recognizes Homebrew in its standard Apple Silicon and Intel locations even when the current shell omits Homebrew from `PATH`. If Python is still missing, macOS uses an integrity-checked, release-pinned Python installer; if Git is missing, it uses Homebrew when available or opens Apple's Command Line Tools installer and tells the operator to rerun after Apple finishes.

For real AI work, at least one compatible agent path must also be available, such as Codex, Claude Code, Gemini, or a configured generic CLI. The installer detects the three built-in CLI paths. One detected tool requires no question; several detected tools produce a short preference choice; no detected tool produces an optional Codex install offer. Installing Codex also installs Node.js/npm through a supported platform package path when needed.

When Codex is detected or installed, Manageroo runs Codex's native sandbox helper
before recording it as configured. The helper is selected by the host platform:

- Linux and WSL2 use Codex's `bwrap` and seccomp sandbox. Linux must provide
  bubblewrap and usable unprivileged user namespaces; Ubuntu 24.04 may also need
  the `bwrap-userns-restrict` AppArmor profile.
- macOS uses the built-in Seatbelt sandbox. Linux setup commands never apply.
- native Windows uses the Windows sandbox from PowerShell; the elevated mode is
  preferred when available. WSL2 follows the Linux path, while WSL1 is not
  supported by current Codex releases.

A failed native sandbox preflight leaves Codex marked as needing action and prints
only the remediation for that platform. Manageroo never silently disables Codex
sandboxing. OpenAI's current platform setup is documented at
<https://learn.chatgpt.com/docs/sandboxing>.

Manageroo detects coding-agent command-line tools, not the person's subscription or private account details. The selected coding tool keeps control of its own login and model configuration.

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
On Windows, paths written into the generated command launcher cannot contain `%`, which batch files interpret as variable expansion.

If Manageroo is already cloned, rerun the platform installer from that existing folder. Do not run the clone command from inside the clone; that creates a nested repository copy.

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

Installing the pack does not make the operator choose skills manually. During a
run, Manageroo indexes available metadata locally and automatically gives each
worker only the relevant bounded capability capsule. The installer token-mode
question separately saves whether agent prose is normal, Caveman, or Caveman
Curse.

Manageroo installs a small portable core by default:

1. `uncle-matts-project-manageroo`
2. `use-installed-skills-first`
3. `skill-vetter`
4. `pimp-my-prompt`
5. `setup-matt-pocock-skills`
6. `to-spec`
7. `to-tickets`
8. `grill-me`
9. `grilling`
10. `grill-with-docs`
11. `domain-modeling`
12. `codebase-design`
13. `diagnosing-bugs`
14. `tdd`
15. `testing`
16. `security-review`
17. `handoff`
18. `writing-for-agents`
19. `edit-skill`
20. `skillify`
21. `caveman`
22. `uncle-matts-caveman-curse`

The repository may ship additional optional skill assets, but they are not Manageroo-owned default dependencies.

Installation inventories the standard `.agents/skills` and `.codex/skills`
roots before writing the portable core. An existing same-name skill is reused in
place, including a differing host-owned version; setup does not create a second
copy or a backup-file trail. Manageroo records ownership only for skill trees it
actually creates. A later install may update that owned tree only while its
digest still matches the last Manageroo install. If the operator edits it,
Manageroo preserves the edit and stops treating the tree as Manageroo-owned.
Known pre-ledger Manageroo bundle digests are migrated once so an upgrade from
an older Manageroo release does not become permanently stale. The complete pack
and its ownership ledger update transactionally: a later failure restores every
earlier tree. Existing trees are hashed under hard file, entry, and byte limits.

Inspect what the current host already has without changing anything:

```bash
manageroo host-skills
manageroo host-skills --json
```

Automatic selection is controller-owned during Manageroo runs. `use-installed-skills-first` remains useful compatibility guidance for supported agents working outside a Manageroo run. Manageroo does not copy, delete, upgrade, or claim ownership of the whole host skill environment.

Reconcile the Manageroo core later if needed:

```bash
manageroo skills reconcile --apply
```

## Recommended full stack

Manageroo can install and integrate with a recommended surrounding stack:

- **GitNexus** for repository and code-graph intelligence;
- **GBrain** for external durable knowledge when explicitly relevant;
- **TruffleHog** for the local secret scan required by AUTOREVIEW;
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

`stack-status` rechecks each recorded executable by its path or command name instead of
treating the install lock as current installation proof.

Preview supported updates without changing anything:

```bash
manageroo stack-update
```

Explicitly apply supported updates to already-installed components:

```bash
manageroo stack-update --apply
```

The updater does not use absence as permission to install every optional component.

The recommended installer is the exception for TruffleHog because current AUTOREVIEW cannot run without it. Manageroo first reuses an existing command. If none exists, it selects the official pinned release asset for Linux, macOS, or Windows and the current CPU architecture, verifies its SHA-256 checksum, installs only the binary beside the Manageroo launcher, and records that exact path as Manageroo-owned.

## Installer controls

Common options include:

```bash
./install.sh --no-music
./install.sh --no-animation
./install.sh --install-codex
./install.sh --agent auto
./install.sh --agent codex
./install.sh --agent claude-code
./install.sh --agent gemini
./install.sh --install-stack
./install.sh --skip-stack
./install.sh --skill-pack install
./install.sh --skill-pack skip
./install.sh --token-mode caveman
./install.sh --token-mode curse
./install.sh --skip-tests
./install.sh --run-developer-tests
```

PowerShell exposes equivalent parameters.

A normal install runs the short source compile check and the installed product self-test. It does not run Manageroo's complete developer test suite. `--run-developer-tests` is the explicit contributor and release-validation option; `--skip-tests` skips the source compile check as well.

## First request

The interactive installer finishes by discovering projects read-only and opening Manageroo:

```text
Hi! I'm Manageroo! Let's do!
>
```

Type the work you want done. Manageroo matches the request to discovered projects and asks which project only when necessary. Installation never initializes every discovered repository.

To bypass automatic matching and name an existing repository explicitly:

```bash
manageroo solo /absolute/path/to/product
```

`solo` creates or updates the repo's `AGENTS.md`, `CONTEXT.md`, `.manageroo/PROJECT-MEMORY.md`, `.manageroo/PRODUCT-BRIEF.md`, intent lock, configuration, and repo-local Manageroo skill from plain-English answers. Existing human-written instruction and context content is preserved; the operator does not need to remember or hand-fill these files.

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
manageroo uninstall-plan
```

`uninstall-plan` emits removal commands only for an absolute, non-root prefix whose
ownership is proven by a matching resolved install lock and the installer's random
ownership marker bound into that lock with SHA-256. Python package and virtual-environment
files by themselves never prove ownership. Installs made before the ownership marker
remain supported only when the legacy lock's product, resolved prefix, installed-app
digest, exact generated launcher, Python executable, and virtual-environment marker all
match the current files.
It includes a launcher only when the file has Manageroo's versioned ownership marker and
matches the complete generated POSIX or Windows launcher structure.

## Release proof

This repository does not use GitHub Actions. The fail-closed release command is:

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
    = GitNexus, GBrain, TruffleHog, AUTOREVIEW, Clawpatch, Obsidian when selected

Host environment
    = additional independently owned skills and tools

Target repository
    = may have its own runtime and hardware requirements
```

Do not collapse those layers into one system requirement, and do not let surrounding tools replace Manageroo's controller authority.
