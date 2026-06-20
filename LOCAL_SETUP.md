# Local setup

This is the straight path from the ZIP to a working local install.

## 1. Extract the end-user release archive

The archive contains one folder named `Uncle-Matts-Super-Mega-Forward-Build-Ultimate-Remix-All-Star-Booty-of-Fire-Edition`.

## 2. Run the installer

```bash
cd /path/to/Uncle-Matts-Super-Mega-Forward-Build-Ultimate-Remix-All-Star-Booty-of-Fire-Edition
./install.sh
```

PowerShell users can run `.\install.ps1`; it starts the same installer.

Token-reduction mode is optional:

```bash
./install.sh --token-mode caveman
./install.sh --token-mode curse
```

`caveman` is clean. `curse` is Uncle Matt's Caveman Curse, the funny profane
version.

When the shell cannot find `umsmfburasbofe` immediately afterward:

```bash
export PATH="$HOME/.local/bin:$PATH"
```

Persist that line in the shell profile used on the machine, such as `~/.zshrc` or `~/.bashrc`.

## 3. Confirm the core installation

```bash
umsmfburasbofe --version
umsmfburasbofe self-test
umsmfburasbofe token-mode status
```

The self-test must return `"ok": true` and `"status": "COMPLETE"`.

## 4. Choose how agents will use it

For Codex, install/authenticate Codex and initialize with `--agent codex`:

```bash
codex
```

For another CLI that this tool should launch itself, initialize with
`--agent generic`, then configure `[agent].argv_template` in
`.umsmfburasbofe/config.toml`.

For an AI IDE that is already running in the repo, do not make this harder than
it is. Give it `GIVE-THIS-TO-YOUR-IDE-AGENT.md` or the repo-local skill created
by `umsmfburasbofe init`.

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
umsmfburasbofe init --agent codex
umsmfburasbofe doctor --json
```

Do not continue until `doctor.ok` is `true`. If no verification gates were detected, add explicit `[[verification.gates]]` entries to `.umsmfburasbofe/config.toml` using the project's real test, lint, type-check, or build commands.

## 6. Write the product request

Edit:

```text
.umsmfburasbofe/PRODUCT-BRIEF.md
```

Describe what the product should do, what it must not break, what is out of
scope, and how you want the result demonstrated. You do not need to tell the
agent which functions to edit.

## 7. Run UMSMFBURASBOFE

New product or feature:

```bash
umsmfburasbofe run --repo . --mode build --brief .umsmfburasbofe/PRODUCT-BRIEF.md --apply
```

Repair existing code:

```bash
umsmfburasbofe run --repo . --mode repair --brief .umsmfburasbofe/PRODUCT-BRIEF.md --apply
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
