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

- GBrain: installed with `bun install -g github:garrytan/gbrain`, then initialized with `gbrain init --pglite` when possible.
- GitNexus: installed with `npm install -g gitnexus`; run `gitnexus setup` afterward for MCP wiring.
- AUTOREVIEW: installed from `openclaw/agent-skills` into `~/.agents/skills/autoreview`.
- Clawpatch: installed with `pnpm add -g clawpatch`; the installer can install `pnpm` with npm when needed.
- Loop Library: installed with `npx --yes skills add Forward-Future/loop-library --skill loop-library ...` for the selected agent.
- Obsidian: installed through a detected package manager when possible, otherwise the installer prints the official install path.

Interactive installs ask whether to run this lane. Non-interactive installs skip
it unless `--install-stack` is passed.

The installer writes a stack summary into `install-lock.json`. It lists what was
installed, what was skipped, what still needs action, and the next command for
each unfinished piece.

## Validate

```bash
umsmfburasbofe --version
umsmfburasbofe banner --no-animation
umsmfburasbofe self-test
umsmfburasbofe token-mode status
umsmfburasbofe stack-status
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
umsmfburasbofe init --agent codex
umsmfburasbofe doctor
```

Use `--agent codex` only when this tool should launch Codex itself. Use
`--agent generic` for another CLI and configure `[agent].argv_template` in
`.umsmfburasbofe/config.toml`.

If an AI IDE can read the repo and run commands, it does not need a special
vendor build. Give it the installed command plus the repo-local skill.

No IDE-specific directory is created.

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
controller profile for a loop. Loop Library itself is not installed unless the
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


## Source checkout versus release archive

A GitHub checkout and an extracted release archive use the same installer. The GitHub repository is the source of truth; a release archive is a versioned convenience copy for end users.
