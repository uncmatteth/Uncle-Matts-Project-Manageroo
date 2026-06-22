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
- `write-a-skill` for packaging repeated work as a reusable skill.
- `edit-skill` for tightening local skills when they get duplicated, stale, or bloated.
- `skillify` for deciding whether a painful repeated workflow deserves a real skill.

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
by `umsmfburasbofe solo`.

Switch token-reduction mode later:

```bash
umsmfburasbofe token-mode set off
umsmfburasbofe token-mode set caveman
umsmfburasbofe token-mode set curse
```

## 5. Start Solo Operator Mode

For an existing Git repository:

```bash
cd /absolute/path/to/product
umsmfburasbofe solo
```

For a brand-new missing or empty folder:

```bash
umsmfburasbofe solo /absolute/path/to/new-product \
  --create \
  --want "Describe what should be built first"
```

`--create` initializes Git, writes a small `README.md` and `.gitignore`, and
creates the first scaffold commit. It refuses to absorb a non-empty non-Git
folder or create a nested repo inside another Git repo, so it does not
accidentally commit personal files, secrets, or a random archive.

Bare `solo` asks what AI you are using, what should be built or fixed, what
must not break, what proof should pass, and whether to check GBrain, GitNexus,
Obsidian, or Loop Library. It initializes the repo, writes the product brief,
runs readiness, and prints exactly one next command.

Use `--agent codex` only when Codex is the selected runtime. Use
`umsmfburasbofe agent preset generic` for another CLI and configure
`[agent].argv_template`.

If you want the lower-level flow instead, run:

```bash
umsmfburasbofe setup
umsmfburasbofe brief --want "Describe what should be built or fixed" --force
umsmfburasbofe ready
```

Do not continue until `umsmfburasbofe ready` reports `READY TO RUN`. If no
verification command was detected, add one real check command:

```bash
umsmfburasbofe checks add smoke -- npm test
umsmfburasbofe checks list
umsmfburasbofe ready
```

If GBrain should know this repo, map only the chosen folder:

```bash
umsmfburasbofe gbrain-setup --source-id my-product --path "$PWD" --apply --sync
```

## 6. Run UMSMFBURASBOFE

New product or feature:

```bash
umsmfburasbofe run --apply
```

Repair existing code:

```bash
umsmfburasbofe run --mode repair --apply
```

You can also combine intake and run in one first command when you already know
readiness is green:

```bash
umsmfburasbofe solo --want "Describe what should be built or fixed" --run --apply --force
```

## 7. Read the result

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
