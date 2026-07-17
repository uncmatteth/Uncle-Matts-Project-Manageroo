# Local setup

This is the simplest way to install and use Uncle Matt's Project Manageroo.

## Unix-style terminals

```bash
./install.sh
```

## PowerShell

```powershell
.\install.ps1
```

Both launch the same Python installer. The interactive installer keeps the
animated colors, moving turtle, generated chiptune music, optional local stack,
recommended skill pack, project discovery, and stack doctor.

To install the guided local stack without prompts:

```bash
./install.sh --install-stack
```

The guided stack can install or guide GBrain, GitNexus, AUTOREVIEW, Clawpatch,
and Obsidian. Codex is optional and installs only with `--install-codex`.

To skip the optional stack:

```bash
./install.sh --skip-stack
```

To skip music or animation:

```bash
./install.sh --no-music --no-animation
```

The recommended local skill pack installs by default. Skip it with:

```bash
./install.sh --skill-pack skip
```

Install or repair it later with:

```bash
manageroo skills reconcile --apply
```

If you copied a skills folder from another computer, reconcile it instead of
overwriting your local skills:

```bash
manageroo skills reconcile \
  --source ~/Downloads/SKILLS \
  --include-external \
  --apply
```

## Verify the install

```bash
manageroo --version
manageroo self-test
manageroo skills list
manageroo stack-status
manageroo stack-doctor
```

## Start with projects

Use guided project setup when you do not want to remember paths:

```bash
manageroo projects --add
```

It scans common project folders, shows a checkbox-style list, initializes only
the repos you select, and accepts pasted paths it missed.

For a read-only picker:

```bash
manageroo projects --pick
```

## Prepare one project

Existing repository:

```bash
manageroo solo /absolute/path/to/project
```

New missing or empty folder:

```bash
manageroo solo /absolute/path/to/new-project \
  --create \
  --want "Describe what should be built first"
```

New project with a starter:

```bash
manageroo solo /absolute/path/to/new-site \
  --create \
  --starter static-site \
  --want "Build a simple product homepage"
```

Bare `solo` asks for the project, request, visible outcome, must-not rules,
proof, stop rule, mode, and optional GBrain/GitNexus/Obsidian guidance. It
writes the brief, project memory, intent lock, managed guidance blocks, and one
next command.

Useful lower-level commands:

```bash
manageroo ready
manageroo next
manageroo checks suggest --apply-first
manageroo run --apply
```

For broken existing code:

```bash
manageroo run --mode repair --apply
```

## Long-running work

Every run stores durable state under:

```text
.manageroo/runs/<run-id>/
```

Inspect it:

```bash
manageroo status RUN_ID
```

Continue it:

```bash
manageroo run --continue RUN_ID
```

Audit a compacted summary against the intent lock:

```bash
manageroo compact audit --summary SUMMARY.md
```

## Release handoff

Before a real release:

```bash
manageroo release-ready \
  --target "Production deploy path" \
  --rollback "Rollback steps" \
  --approved-by "Your name"
```

This does not deploy. It writes a production handoff and blocks when evidence is
missing.

## Uninstall planning

Manageroo never silently removes third-party tools. Inspect the plan first:

```bash
manageroo uninstall-plan
```

The command prints the core Manageroo paths and notes which external tools need
separate intentional removal.
