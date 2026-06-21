# Local setup

This is the straight path from the ZIP to a working local install.

## 1. Extract the end-user release archive

The archive contains one folder named `Uncle-Matts-Super-Mega-Forward-Build-Ultimate-Remix-All-Star-Booty-of-Fire-Edition`.

## 2. Run the installer

```bash
cd /path/to/Uncle-Matts-Super-Mega-Forward-Build-Ultimate-Remix-All-Star-Booty-of-Fire-Edition
./install.sh
```

Same installer, same behavior. Use `./install.sh` from a normal Unix-style
terminal, or `.\install.ps1` from PowerShell. Those are launchers, not separate
products.

Token-reduction mode is optional:

```bash
./install.sh --token-mode caveman
./install.sh --token-mode curse
```

`caveman` is clean. `curse` is Uncle Matt's Caveman Curse, the funny profane
version.

The recommended stack lane is optional:

```bash
./install.sh --install-stack --loop-library-agent codex
```

Use a different `--loop-library-agent` value when your skills-compatible agent
is not Codex.

That covers GBrain, GitNexus, AUTOREVIEW, Clawpatch, Obsidian, and Matthew
Berman / Forward Future's Loop Library skill when the needed package managers
are available. If something is missing, the installer prints the exact next
command instead of claiming that piece is done.

When the shell cannot find `umsmfburasbofe` immediately afterward:

```bash
export PATH="$HOME/.local/bin:$PATH"
```

Persist that line in the shell profile used on the machine, such as `~/.zshrc` or `~/.bashrc`.

Core install also installs bundled helper skills under `~/.agents/skills`:

- `pimp-my-prompt` for turning a rough request into exact scope, proof, and stop rules.
- `edit-skill` for tightening local skills when they get duplicated, stale, or bloated.

They can be reinstalled later with:

```bash
umsmfburasbofe skills install
```

## 3. Confirm the core installation

```bash
umsmfburasbofe --version
umsmfburasbofe self-test
umsmfburasbofe skills list
umsmfburasbofe token-mode status
umsmfburasbofe stack-status
umsmfburasbofe repair-install --no-apply
```

The self-test must return `"ok": true` and `"status": "COMPLETE"`.

## 4. Choose how agents will use it

For Codex, install/authenticate Codex and initialize with `--agent codex`:

```bash
codex
```

For another CLI that this tool should launch itself, use a preset:

```bash
umsmfburasbofe agent list
```

The non-Codex presets are command templates. If your CLI needs different flags,
edit `[agent].argv_template` in `.umsmfburasbofe/config.toml`.

For an AI IDE that is already running in the repo, do not make this harder than
it is. Give it `GIVE-THIS-TO-YOUR-IDE-AGENT.md` or the repo-local skill created
by `umsmfburasbofe setup`.

Switch token-reduction mode later:

```bash
umsmfburasbofe token-mode set off
umsmfburasbofe token-mode set caveman
umsmfburasbofe token-mode set curse
```

## 5. Initialize an existing product repository

The target must already be a Git repository.

```bash
cd /absolute/path/to/product
umsmfburasbofe setup
```

Bare `setup` asks what AI you are using, which repo to initialize, and whether
to check GBrain, GitNexus, Obsidian, or Loop Library.

Use `--agent codex` only when Codex is the selected runtime. Use
`umsmfburasbofe agent preset generic` for another CLI and configure
`[agent].argv_template`.

Do not continue until `umsmfburasbofe ready` reports `READY TO RUN`. If no
verification gates were detected, add explicit `[[verification.gates]]` entries
to `.umsmfburasbofe/config.toml` using the project's real test, lint,
type-check, or build commands.

## 6. Write the product request

Create the first brief:

```bash
umsmfburasbofe brief \
  --want "Describe what should be built or fixed" \
  --outcome "The result that must be true" \
  --must-not "Anything the agent must not touch" \
  --proof "The check or demo that proves it worked" \
  --force
```

You can still hand-edit `.umsmfburasbofe/PRODUCT-BRIEF.md` afterward.

If GBrain should know this repo, map only the chosen folder:

```bash
umsmfburasbofe gbrain-setup --source-id my-product --path "$PWD" --apply --sync
```

Then:

```bash
umsmfburasbofe ready
```

## 7. Run UMSMFBURASBOFE

New product or feature:

```bash
umsmfburasbofe run --apply
```

Repair existing code:

```bash
umsmfburasbofe run --mode repair --apply
```

## 8. Read the result

The command returns a run ID. Use:

```bash
umsmfburasbofe status RUN_ID --repo .
umsmfburasbofe report RUN_ID --repo .
```

Run artifacts and evidence are stored under `.umsmfburasbofe/runs/RUN_ID/`.

## Important boundary

The package tests pass, but that is not the same as proving your real repo and
your real AI tool are ready. Do the first live run on a backup, clone, branch, or
disposable copy.
