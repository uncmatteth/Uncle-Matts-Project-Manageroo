# Local setup

This is the straight path from a release archive or cloned repository to a working Manageroo install.

## 1. Install

The recommended first install is human-first so the operator can see what is happening and choose optional components intentionally.

Unix-like systems:

```bash
cd /path/to/Uncle-Matts-Project-Manageroo
./install.sh
```

Windows PowerShell:

```powershell
cd C:\path\to\Uncle-Matts-Project-Manageroo
.\install.ps1
```

If the shell cannot immediately find `manageroo` on Unix-like systems:

```bash
export PATH="$HOME/.local/bin:$PATH"
```

Persist that line in the shell profile used on the machine when needed.

## 2. Hardware truth

Manageroo core is hardware-agnostic. It does not require a particular GPU, VRAM amount, CPU tier, or RAM class.

Inspect the current host:

```bash
manageroo capacity
```

That profile is informational only. It does not auto-tune worker concurrency or decide whether Manageroo is supported. A target repo or explicitly selected local AI tool may still have its own hardware requirements.

## 3. Portable core skills

The default Manageroo-owned skill pack is intentionally small and portable:

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

Reconcile that core later if needed:

```bash
manageroo skills reconcile --apply
```

Inspect additional local host skills without changing them:

```bash
manageroo host-skills
manageroo host-skills --json
```

Extra host skills remain host-owned. Manageroo may use a relevant installed skill through `use-installed-skills-first`, but it does not automatically copy, delete, upgrade, or claim the whole host environment.

## 4. Recommended surrounding stack

The full recommended setup can include:

- GitNexus for repository/code-graph intelligence;
- GBrain for external durable knowledge when explicitly relevant;
- AUTOREVIEW for external review;
- Clawpatch for external review and repair;
- Obsidian for human-readable knowledge.

These tools add capabilities around Manageroo without replacing its controller authority.

When GitNexus is selected during installation, Manageroo installs it and completes `gitnexus setup`. Repository indexing remains project-specific.

Inspect the stack:

```bash
manageroo stack-status
manageroo stack-doctor
```

Preview supported updates:

```bash
manageroo stack-update
```

Target one installed tool when useful:

```bash
manageroo stack-update gitnexus
manageroo stack-update gitnexus --apply
```

Apply supported updates only when explicitly requested.

## 5. Confirm the installation

```bash
manageroo --version
manageroo self-test
manageroo skills list
manageroo host-skills
manageroo token-mode status
manageroo stack-status
manageroo stack-doctor
manageroo repair-install --no-apply
```

The self-test must return `"ok": true` and `"status": "COMPLETE"`.

## 6. Choose an agent path

The default provider-neutral mode can use compatible installed workers.

Built-in paths include Codex, Claude Code, Gemini, and a generic CLI template.

```bash
manageroo agent list
```

A real run requires at least one usable agent path. The agent may be cloud-backed, remote, or local; Manageroo does not infer its hardware cost from the host machine.

## 7. Start a project

Discover local Git projects:

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

`solo` prepares the repo, product brief, project memory, intent lock, readiness state, and one next action.

When unsure what to do next:

```bash
manageroo next
```

## 8. Run Manageroo

Build:

```bash
manageroo run --apply
```

Repair:

```bash
manageroo run --mode repair --apply
```

Inspect a run:

```bash
manageroo status RUN_ID --repo .
manageroo report RUN_ID --repo .
```

Run artifacts and evidence are stored under `.manageroo/runs/RUN_ID/`.

## 9. Release gate

Before a real production release of a managed project:

```bash
manageroo release-ready \
  --target "Production deploy path" \
  --rollback "Rollback steps" \
  --approved-by "Your name"
```

That is an operator gate, not a deployment command.

## 10. Manageroo's own release proof

For the Manageroo repository itself:

```bash
python3 scripts/release.py
```

That command is fail-closed. It must complete Manageroo product proof, regression verification, packaging, checksums, and clean-install ZIP smoke before the release is considered shippable.

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
