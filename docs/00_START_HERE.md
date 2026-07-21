# Start here

## What Manageroo is

**Uncle Matt's Project Manageroo** is a local project controller for AI coding agents working on real Git repositories.

```text
You explain what should be built or fixed.
Manageroo captures the mission and protected intent.
Manageroo reads and maps the repository.
Manageroo creates bounded worker jobs.
Compatible AI coding agents do the implementation work.
Manageroo checks the result, reviews it independently, repairs failures within budgets, and keeps the evidence.
```

The controller, not the worker, decides whether the job is complete.

## Install

### Linux / macOS

```bash
git clone https://github.com/uncmatteth/Uncle-Matts-Project-Manageroo.git && cd Uncle-Matts-Project-Manageroo && ./install.sh
```

### Windows PowerShell

```powershell
git clone https://github.com/uncmatteth/Uncle-Matts-Project-Manageroo.git; Set-Location Uncle-Matts-Project-Manageroo; .\install.ps1
```

Requirements: Python 3.11+ and Git. Real AI work also requires at least one compatible coding-agent CLI.

Useful checks after installation:

```bash
manageroo --version
manageroo self-test
manageroo skills list
manageroo host-skills
manageroo token-mode status
manageroo stack-status
manageroo stack-doctor
```

## Hardware

Manageroo core is hardware-agnostic. It does not require a particular GPU, VRAM tier, CPU class, or RAM amount.

```bash
manageroo capacity
manageroo capacity --json
```

Those commands report the current host as informational context. A target project or explicitly selected local AI tool can still have its own hardware requirements.

# Skills

The repository contains **50 bundled skill packages**.

- **18 portable core skills** are installed as the recommended/default Manageroo-owned pack.
- **32 additional bundled skills** are optional capabilities and are not silently installed as Manageroo-owned defaults.
- Skills already installed on the user's machine remain host-owned and can be discovered separately.

## 18 portable core skills

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

## 32 bundled optional skills

- `academic-verify`
- `article-enrichment`
- `autoreview`
- `book-mirror`
- `brain-ops`
- `brain-pdf`
- `citation-fixer`
- `cross-modal-review`
- `data-research`
- `exact-text-replacement`
- `find-skills`
- `fix-my-bad-website`
- `functional-area-resolver`
- `idea-ingest`
- `improve-codebase-architecture`
- `ingest`
- `media-ingest`
- `minion-orchestrator`
- `open-design`
- `pdf`
- `perplexity-research`
- `plain-web-copy`
- `playwright`
- `playwright-interactive`
- `query`
- `repo-architecture`
- `reports`
- `skillpack-check`
- `strategic-reading`
- `subagent-orchestrator`
- `voice-note-ingest`
- `web-design-guidelines`

Inspect skills already present on the host without changing them:

```bash
manageroo host-skills
manageroo host-skills --json
```

# Optional surrounding stack

Manageroo can also work with:

- **GitNexus** for repository and code-graph intelligence;
- **GBrain** for external durable knowledge and retrieval;
- **AUTOREVIEW** for structured external review;
- **Clawpatch** for evidence-driven findings and repair loops;
- **Obsidian** for human-readable Markdown knowledge.

These tools add capabilities. They do not replace Manageroo's controller authority.

Inspect the stack:

```bash
manageroo stack-status
manageroo stack-doctor
```

Preview supported updates:

```bash
manageroo stack-update
```

Apply supported updates explicitly:

```bash
manageroo stack-update --apply
```

# Start a project

## Existing projects on your machine

```bash
manageroo projects --add
```

This discovers Git repositories and lets Manageroo register projects you already have.

## One existing repository

```bash
manageroo solo /absolute/path/to/product
```

`solo` prepares the project configuration, product brief, project memory, intent lock, readiness state, and one next action.

## New or empty repository

```bash
manageroo solo /absolute/path/to/new-product \
  --create \
  --want "Describe what should be built first"
```

This creates the starting project structure and records the initial mission.

# Use Manageroo

## Ask what comes next

```bash
manageroo next
```

This prints one useful next operator action based on the current project state.

## Start normal build or implementation work

```bash
manageroo run --apply
```

Manageroo loads the project truth, performs discovery and planning, creates bounded worker jobs, routes work to compatible coding agents, verifies the resulting changes, performs review, and attempts bounded repair when necessary.

`--apply` gives Manageroo permission to apply a successfully verified delivery patch back to the source repository when its safety checks pass.

## Start explicit repair work

```bash
manageroo run --mode repair --apply
```

Use repair mode when the mission is specifically to diagnose and fix an existing broken project or failed implementation.

Repair mode still uses bounded work, verification, review, evidence, retry budgets, and stop conditions.

## Check a run

Every run has a run ID.

For the concise operational state:

```bash
manageroo status RUN_ID --repo .
```

For the fuller explanation, results, and evidence:

```bash
manageroo report RUN_ID --repo .
```

`--repo .` means the repository in the current directory. Replace `.` with an absolute path when running the command somewhere else.

## Continue an interrupted or blocked run

```bash
manageroo run --continue RUN_ID --repo . --apply
```

Manageroo reloads the durable state for that exact run and continues from the recorded project truth.

## Handle a blocking decision

See the decision:

```bash
manageroo decisions show RUN_ID --repo .
```

Record the operator's answer:

```bash
manageroo decisions answer RUN_ID --repo .
```

Continue the same run:

```bash
manageroo run --continue RUN_ID --repo . --apply
```

Manageroo should only stop for decisions that are important enough that repository evidence cannot safely answer them.

# Project memory and intent

Show durable project memory:

```bash
manageroo memory show
```

Show the protected intent lock:

```bash
manageroo intent show
```

Audit whether a compacted or summarized project description still preserves the important requirements:

```bash
manageroo compact audit --summary SUMMARY.md
```

The point is to keep important project truth outside any one chat transcript so the mission survives long runs, new sessions, and context compaction.

# The boundary

```text
Manageroo controller
    mission + state + jobs + decisions + proof + review + repair + completion

Portable core
    18 default Manageroo-owned skills

Bundled optional library
    32 additional skills available without becoming default installs

Optional surrounding stack
    GitNexus + GBrain + AUTOREVIEW + Clawpatch + Obsidian when selected

Host environment
    independently owned additional skills and tools

Target repository
    its own code, runtime, deployment, data, and project-specific requirements
```

Keep those layers separate. Manageroo can use capabilities from the surrounding environment without pretending it owns everything on the machine.

For the full public overview, credits, architecture, and complete skill inventory, see the repository `README.md`.