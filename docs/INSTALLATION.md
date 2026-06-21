# Installation

## Requirements

- Python 3.11 or newer
- Git
- Internet access only if installing or updating a selected external agent/tool

Install Python 3.11+ and Git first. The installer is supposed to be the easy
part, not a treasure hunt.

## Install

```bash
./install.sh
```

Same installer, same behavior. Use `./install.sh` from a normal Unix-style
terminal, or `.\install.ps1` from PowerShell. Those are launchers, not separate
products.

## Installer controls

```bash
./install.sh --no-music
./install.sh --no-animation
./install.sh --install-codex
./install.sh --install-stack
./install.sh --skip-stack
./install.sh --loop-library-agent codex
./install.sh --loop-library-agent YOUR_AGENT
./install.sh --token-mode caveman
./install.sh --token-mode curse
./install.sh --skip-tests
```

Normal users should not need these.

## Recommended stack

The installer can install or guide the surrounding stack that makes the whole
thing useful:

- GBrain: installed with `bun install -g github:garrytan/gbrain` when missing. If it already exists, the installer inspects config/status and does not reinitialize it.
- GitNexus: installed with `npm install -g gitnexus`; run `gitnexus setup` afterward for MCP wiring.
- AUTOREVIEW: detected in `~/.agents/skills/autoreview` or `~/.codex/skills/autoreview`; installed from `openclaw/agent-skills` only when missing.
- Clawpatch: installed with `pnpm add -g clawpatch`; the installer can install `pnpm` with npm when needed.
- Loop Library: installed with `npx --yes skills add Forward-Future/loop-library --skill loop-library ...` for the selected agent.
- Obsidian: installed through a detected package manager when possible, otherwise the installer prints the official install path.

Interactive installs ask whether to run this lane. Non-interactive installs skip
it unless `--install-stack` is passed.

The installer writes a stack summary into `install-lock.json`. It lists what was
installed, what was skipped, what still needs action, and the next command for
each unfinished piece.

For an existing GBrain install, the lock records the detected engine, embedding
model, schema pack, source count, unembedded chunks, and coverage summary. It
also includes safe mapping commands:

```bash
gbrain sources list
gbrain sources add YOUR_SOURCE_ID --path /absolute/path/to/folder
gbrain sync --source YOUR_SOURCE_ID --json --yes
gbrain status --json --section sync
```

The installer does not choose broad personal folders for you.

## Bundled helper skills

Normal install writes these local skills under `~/.agents/skills`:

- `pimp-my-prompt`: turns rough requests into exact scope, acceptance criteria,
  fallback rules, and runnable product briefs.
- `write-a-skill`: creates a concise reusable skill when a workflow keeps
  coming back.
- `edit-skill`: tightens existing skills by removing duplicate instructions,
  stale rules, vague wording, and AI slop.
- `skillify`: checks whether a repeated workflow deserves a skill, then makes
  sure it has triggers and proof.

They are available even when token mode is off. Reinstall them later with:

```bash
umsmfburasbofe skills install
```

## Validate

```bash
umsmfburasbofe --version
umsmfburasbofe banner --no-animation
umsmfburasbofe self-test
umsmfburasbofe skills list
umsmfburasbofe token-mode status
umsmfburasbofe stack-status
umsmfburasbofe repair-install --no-apply
```

## Token reduction

The package includes both token-reduction skills:

- `caveman`: terse, clean output.
- `uncle-matts-caveman-curse`: terse output plus profanity.

Switch later:

```bash
umsmfburasbofe token-mode set off
umsmfburasbofe token-mode set caveman
umsmfburasbofe token-mode set curse
```

If a different local `SKILL.md` already exists for one of those names, the tool
backs it up before installing the bundled copy.

## Initialize a Git-backed project

```bash
cd /absolute/path/to/product
umsmfburasbofe setup
```

Bare `setup` is the first-run wizard. It asks:

- what AI you are using;
- what repo should be initialized;
- whether to check GBrain, GitNexus, Obsidian, or Loop Library.

Use `--agent codex` only when this tool should launch Codex itself. Use
`umsmfburasbofe agent list` to see starter presets:

```bash
umsmfburasbofe agent list
umsmfburasbofe agent preset gemini
umsmfburasbofe agent preset generic
```

The non-Codex presets are command templates. If your CLI needs different flags,
edit `[agent].argv_template` in `.umsmfburasbofe/config.toml`.

If an AI IDE can read the repo and run commands, it does not need a special
vendor build. Give it the installed command plus the repo-local skill.

No IDE-specific directory is created.

Create a normal-language brief:

```bash
umsmfburasbofe brief \
  --want "Say exactly what should be built or fixed" \
  --outcome "The result that must be true" \
  --must-not "Anything the agent must not touch" \
  --proof "The check or demo that proves it worked" \
  --force
```

Check whether it is ready to run:

```bash
umsmfburasbofe ready
```

If GBrain should know this repo, inspect first and map only the selected folder:

```bash
umsmfburasbofe gbrain-setup
umsmfburasbofe gbrain-setup --source-id my-product --path "$PWD" --apply --sync
```

Run the default build flow:

```bash
umsmfburasbofe run --apply
```

For already-broken code:

```bash
umsmfburasbofe run --mode repair --apply
```

## Use a Loop Library loop

Matthew Berman / Forward Future's Loop Library can be used as the source of a
job pattern:

```bash
umsmfburasbofe loop-library search docs
umsmfburasbofe loop-library show overnight-docs-sweep
umsmfburasbofe loop-library profile overnight-docs-sweep
umsmfburasbofe loop-library brief overnight-docs-sweep --output .umsmfburasbofe/PRODUCT-BRIEF.md --force
```

UMSMFBURASBOFE reads the catalog and turns the selected loop into a repo-local
brief. It also caches the catalog for offline fallback and can print a structured
controller profile for a loop. That profile calls out whether the pattern is a
`goal`, `loop`, or `routine`, then adds budget/caps, verifier, anti-spin, and
completion-contract fields. Loop Library itself is not installed unless the
operator separately asks for that exact tool.

## Uninstall

Print the plan first:

```bash
umsmfburasbofe uninstall-plan
```

The plan does not delete anything. It names the core files and reminds you that
third-party tools are separate.

```bash
rm -rf "$HOME/.local/share/umsmfburasbofe"
rm -f "$HOME/.local/bin/umsmfburasbofe" "$HOME/.local/bin/umsmfburasbofe.cmd"
```

If the launcher or helper skills get damaged, run:

```bash
umsmfburasbofe repair-install --no-apply
umsmfburasbofe repair-install
```


## Source checkout versus release archive

A GitHub checkout and an extracted release archive use the same installer. The GitHub repository is the source of truth; a release archive is a versioned convenience copy for end users.
