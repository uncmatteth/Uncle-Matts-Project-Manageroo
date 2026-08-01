# Uncle Matt's Project Manageroo

> [!TIP]
> ## Quick Start
>
> **1. Install Manageroo**
>
> Linux / macOS:
>
> ```bash
> git clone https://github.com/uncmatteth/Uncle-Matts-Project-Manageroo.git && cd Uncle-Matts-Project-Manageroo && ./install.sh
> ```
>
> Windows PowerShell:
>
> ```powershell
> git clone https://github.com/uncmatteth/Uncle-Matts-Project-Manageroo.git; Set-Location Uncle-Matts-Project-Manageroo; .\install.ps1
> ```
>
> If Git is not installed yet, use GitHub's **Code → Download ZIP**, extract it, open a terminal in the folder, and run the platform command above. The installer checks Python 3.11+ and Git and offers guided setup with the normal platform path: a verified Python package and Apple's Command Line Tools on macOS, common system package managers on Linux, or winget on Windows.
>
> **2. Follow the guided setup**
>
> Manageroo checks for Codex, Claude Code, and Gemini CLI. If it finds one, it uses it automatically. If it finds several, you can keep automatic selection or choose your preferred tool. If it finds none, it offers to install Codex and its Node.js/npm requirement. It does not guess or replace the account or model configured inside your coding tool. The installer then walks through the portable skill pack, optional supporting tools, token style, project discovery, and a read-only stack check.
>
> Project discovery itself is read-only. Manageroo shows what it found and asks which projects to enroll. Only selected projects receive the context bundle; everything else is left alone.
>
> **3. Point Manageroo at a project**
>
> Open a new terminal and run:
>
> ```bash
> manageroo solo /absolute/path/to/your-project
> ```
>
> Answer the questions in plain English: what you want built or fixed, who it is for, what must not change, and what proof should count. If you are ever unsure what comes next, run `manageroo next`.
>
> You do **not** have to create or fill agent context files yourself. `solo` safely creates or updates `AGENTS.md`, `CONTEXT.md`, `.manageroo/PROJECT-MEMORY.md`, `.manageroo/PRODUCT-BRIEF.md`, the current intent lock, Manageroo configuration, and the repo-local Manageroo skill. Existing human-written `AGENTS.md` and `CONTEXT.md` content is preserved.
>
> **Manageroo for beginners:** Think of Manageroo as the project foreman above your coding agent. You describe the result you want; Manageroo records the mission, maps the repository, gives the coding agent bounded jobs in an isolated workspace, runs the project's checks, performs separate review, and produces evidence and a patch. It does not treat the worker saying “done” as proof. Use `manageroo run --apply` when you want a successfully verified patch applied to your project. Use `manageroo status RUN_ID --repo .` to check a run and `manageroo report RUN_ID --repo .` to read what happened.

---

# What Manageroo is

Manageroo is a local project controller for AI coding agents working on real Git repositories.

The problem is simple: one giant AI chat should not be expected to remember an entire project, discover every hidden risk, write all the code, review itself, verify itself, repair itself, and then decide that its own work is finished.

Manageroo puts a controller above the workers.

```text
YOU DESCRIBE WHAT YOU WANT
        ↓
MANAGEROO CAPTURES THE MISSION
        ↓
PROJECT DISCOVERY + REPOSITORY MAPPING
        ↓
BOUNDED JOBS FOR CODING AGENTS
        ↓
REAL CHECKS + INDEPENDENT REVIEW
        ↓
BOUNDED REPAIR WHEN SOMETHING FAILS
        ↓
EVIDENCE + DELIVERY
```

The coding agents do the work. Manageroo owns the mission, state, boundaries, review, proof, and definition of done.

# Who it is for

Manageroo is for people whose projects have outgrown the normal "paste everything into one chat and hope" workflow.

It is especially useful for:

- large, old, or messy repositories;
- long-running AI-assisted projects;
- work spread across multiple agent sessions;
- requirements that cannot safely disappear during context compaction;
- changes where blast radius matters;
- projects where the agent that wrote the code should not be the only thing reviewing it;
- repair work that needs budgets and stop conditions instead of endless autonomous thrashing;
- solo builders tired of manually saying "keep going, check the rest, test it, are you sure?";
- teams that want evidence instead of "the model says it is done."

Manageroo keeps important project truth outside the worker so a model change, terminal restart, failed run, or new chat does not erase the mission.

# What Manageroo actually does

Manageroo can:

- read and inventory a Git repository;
- capture the requested outcome, must-not rules, and proof expectations;
- preserve an intent lock so important requirements survive long runs and context compaction;
- perform discovery before implementation and surface important unknowns;
- map the repository before assigning implementation work;
- split large work into bounded worker jobs;
- route those jobs to compatible coding-agent CLIs;
- keep job, attempt, retry, and run state on disk;
- isolate worker attempts from the operator's source repository;
- verify changed-file scope and repository state;
- run deterministic project checks;
- bind requested outcomes to required proof;
- perform review separately from implementation;
- run bounded repair loops when work fails verification or review;
- stop and surface high-impact decisions instead of guessing them;
- resume interrupted work from durable state;
- produce reports, evidence, and a patch for delivery.

Manageroo is not an IDE, model host, deployment platform, cloud scheduler, memory database, or code-graph database. It can work with tools that provide those capabilities without handing them control over Manageroo's definition of done.

# The controller is the boss

Built-in worker paths cover:

- Codex;
- Claude Code;
- Gemini;
- compatible generic CLIs.

The default worker mode is provider-neutral `auto`.

```bash
manageroo agent list
```

Workers are intentionally replaceable. The project truth is not.

A worker can write code, investigate a problem, review a change, or repair a failure. It does not get to certify its own work just because it returned a confident answer.

# How Manageroo keeps a project from forgetting itself

Manageroo keeps controller-owned run state under:

```text
.manageroo/runs/<run-id>/
```

That run state records what happened, what is still pending, what failed, what was retried, and what evidence exists.

Project continuity also uses repository-local files such as:

```text
.manageroo/PROJECT-MEMORY.md
.manageroo/intent/INTENT-LOCK.json
.manageroo/intent/INTENT-LOCK.md
```

The point is not to create another giant memory dump. The point is to preserve the pieces of project truth that must survive outside a temporary conversation.

# Discovery before implementation

Before large implementation work, Manageroo looks beyond the literal request and checks areas that commonly get missed, including:

- failure, interruption, rollback, and recovery;
- proof strength;
- scope and non-goals;
- authentication and authorization;
- payments and reconciliation;
- migrations and data preservation;
- deployment and rollback;
- target-project hardware assumptions;
- external services, rate limits, cost, and degraded modes;
- accessibility and user-facing states.

When repository evidence can answer a question, Manageroo uses the evidence. When a genuinely high-impact decision still requires the operator, Manageroo surfaces it explicitly instead of guessing.

# Source isolation and bounded changes

Manageroo performs worker activity in run-owned isolated repositories instead of giving every coding worker unrestricted access to the operator's source tree.

The purpose is simple: workers can work aggressively inside a bounded workspace without casually poisoning the original repository.

Successful work is delivered back through a patch after Manageroo checks that the source repository has not unexpectedly changed underneath the run.

# Proof before "done"

Manageroo reconciles completion against:

- what the user actually requested;
- required proof gates;
- changed-file scope;
- deterministic verification;
- independent review;
- required demonstration evidence.

A passing unit test does not automatically prove a browser flow. A worker saying something was deployed does not prove deployment. A model claiming something is secure does not make it secure.

Claims that require observable evidence remain unproven until matching evidence exists.

# How to actually use Manageroo

## 1. Point Manageroo at a project

Discover Git repositories on your machine and add them to Manageroo's project list:

```bash
manageroo projects --add
```

For one specific existing repository:

```bash
manageroo solo /absolute/path/to/product
```

`solo` prepares the repository for Manageroo. It safely creates or updates `AGENTS.md`, `CONTEXT.md`, `.manageroo/PROJECT-MEMORY.md`, `.manageroo/PRODUCT-BRIEF.md`, the current intent lock, project configuration, the repo-local Manageroo skill, and readiness state, then tells you the next useful action. You answer normal questions; you do not hand-build or remember these files. Existing human-written instruction and context content is preserved.

For a brand-new project that does not exist yet, or an empty directory:

```bash
manageroo solo /absolute/path/to/new-product \
  --create \
  --want "Describe what should be built first"
```

This creates the starting project structure and captures the initial mission instead of forcing you to hand-build Manageroo's project files first.

## 2. Ask Manageroo what to do next

```bash
manageroo next
```

Use this when you do not remember the workflow or do not know what the current project needs next. Manageroo prints one useful next operator action instead of dumping an enormous checklist on you.

## 3. Run a build or implementation job

```bash
manageroo run --apply
```

This starts a normal Manageroo work run for the current project.

Manageroo reads the project truth, performs discovery and planning, creates bounded worker jobs, sends those jobs to compatible coding agents, checks the resulting changes, runs verification, performs review, and attempts bounded repair when necessary.

`--apply` means Manageroo is allowed to apply a successfully verified delivery patch back to the source repository when its safety checks pass.

Without permission to apply, Manageroo can still perform the run and produce delivery evidence without silently changing the source repository.

## 4. Run an explicit repair job

```bash
manageroo run --mode repair --apply
```

Use repair mode when the mission is specifically to diagnose and fix an existing broken project or failed implementation rather than build a normal new change.

Repair mode still uses bounded work, verification, review, evidence, and controlled retries. It is not a command for endlessly changing files until something happens to pass.

## 5. Check what a run is doing or what happened

Every Manageroo run has a run ID.

See the current state of a run:

```bash
manageroo status RUN_ID --repo .
```

Use `status` for the concise operational view: where the run is, whether it is blocked, whether it failed, and what state it currently holds.

See the fuller human-readable result and evidence:

```bash
manageroo report RUN_ID --repo .
```

Use `report` when you want the explanation of what Manageroo did, what changed, what passed, what failed, what evidence was collected, and what still needs attention.

`--repo .` means "use the repository in my current directory." Replace `.` with an absolute repository path when running the command from somewhere else.

## 6. Continue an interrupted or blocked run

```bash
manageroo run --continue RUN_ID --repo . --apply
```

Use this after a terminal closes, a worker fails, a run pauses for a decision, or another recoverable interruption occurs.

Manageroo reloads the durable state for that exact run and continues from the recorded project truth. It does not pretend the old process kept running in the background.

## 7. Answer a blocking decision

When Manageroo reaches a genuinely high-impact choice that repository evidence cannot safely answer, it can stop instead of making up the answer.

See the decision:

```bash
manageroo decisions show RUN_ID --repo .
```

Record the operator's answer:

```bash
manageroo decisions answer RUN_ID --repo .
```

Then continue the same run:

```bash
manageroo run --continue RUN_ID --repo . --apply
```

The point is to interrupt you only for decisions that actually matter, while letting evidence answer everything else it safely can.

## 8. Inspect project memory and protected intent

Show the current project memory:

```bash
manageroo memory show
```

This is the durable human-readable project continuity Manageroo keeps outside any one agent conversation.

Show the current intent lock:

```bash
manageroo intent show
```

The intent lock protects the important outcomes, constraints, must-not rules, and proof expectations that should not quietly disappear during a long run.

Audit whether a compacted or summarized project description still preserves the important intent:

```bash
manageroo compact audit --summary SUMMARY.md
```

This is useful when a long project history has been summarized and you want to check that the summary did not accidentally throw away something important.

## 9. Run the final Clawpatch release sweep

Preview the complete closeout lifecycle without changing the repository:

```bash
manageroo clawpatch release-sweep --repo .
```

Execute it on a dedicated branch:

```bash
manageroo clawpatch release-sweep --repo . --apply
```

When Clawpatch runs inside a trusted project and the host already supplies the
required isolation, its Codex worker can be allowed to edit without nested
sandbox failures:

```bash
manageroo clawpatch release-sweep --repo . --apply --trusted-host-codex-sandbox-bypass
```

That flag is deliberately explicit. It disables Codex approval prompts and
sandboxing only for the Clawpatch child processes in this sweep; it is not saved
as a global setting. Do not use it for untrusted code. Manageroo still runs the
project's configured verification gates, requires Clawpatch revalidation, stages
only the exact changed paths, and commits one cleared finding at a time.

Clawpatch exit code 6 means its fix was applied but its immediate validator did
not clear. Manageroo treats that as a revalidation transition, not success: it
runs the project gates, revalidates that same finding, and commits only when the
gates pass and Clawpatch reports the finding fixed.

When a configured gate refreshes the tracked `BUILD-VALIDATION.json` proof,
Manageroo includes that known controller artifact in the same exact repair
commit. Any other unexpected gate-created source change still stops the sweep.

If revalidation says a gate-passing repair is still `open`, Manageroo records an
explicit partial commit and asks Clawpatch to repair that same finding again.
This is bounded to three gated attempts per finding; `uncertain` still stops
without a commit, and only `fixed` counts as cleared.

Release sweeps also give Clawpatch's Codex worker up to 30 minutes by default,
instead of Clawpatch's shorter interactive default. An existing
`CLAWPATCH_CODEX_TIMEOUT_MS` environment setting still wins.

The applied sweep runs Clawpatch doctor, initialization when needed, map, and review. For a project without existing Clawpatch state, Manageroo keeps that new state under Git's private directory so setup does not dirty the source tree. It then asks Clawpatch for one fresh open finding at a time, shows and applies that finding, runs the project's Manageroo verification gates, requires Clawpatch to revalidate the finding as fixed, stages only the exact changed paths, and creates one commit. It checkpoints between findings so a validated partial sweep can resume. At the end it revalidates every open finding, requires a zero-open report, reruns the gates, requires clean Git state, and writes proof tied to the exact final commit.

Dry-run is the default. `--apply` is required for local changes. Nothing is pushed unless you explicitly add `--push each` or `--push final`. On `main` or `master`, the default `--branch auto` creates a timestamped `clawpatch/release-sweep-*` branch; use `--branch current` only when you deliberately want the current branch.

To make the normal release gate require that proof, use:

```bash
manageroo release-ready --require-clawpatch
```

Or set `require_clawpatch_release_sweep = true` under `[project]` in `.manageroo/config.toml`.

# Hardware compatibility

Manageroo core is hardware-agnostic.

It does not require a specific GPU, VRAM amount, CPU tier, or RAM class. A target project or explicitly selected local AI tool may have its own hardware requirements, but those belong to that project or tool.

Inspect the current host:

```bash
manageroo capacity
manageroo capacity --json
```

The hardware profile is informational context. Manageroo does not silently rewrite worker concurrency based on one developer machine.

# Skills: exactly what is included

Users do not need to remember or type skill names. Before every worker job,
Manageroo indexes installed skill metadata locally, matches the normal-language
assignment, and injects only the strongest relevant full instructions into a
bounded task packet. The route is automatic and never asks the operator to
choose implementation machinery. The operator's original brief controls which
skills are eligible; an implementation task may only rerank that approved set,
so model-generated plan text cannot activate a new capability.

The installer's **normal**, **Caveman**, and **Caveman Curse** choice is a
separate saved communication preference. It is selected once during setup and
applied automatically; those modes do not compete in task routing.

This repository currently contains **50 bundled skill packages**.

That does **not** mean Manageroo installs all 50 by default.

The boundary is:

- **18 portable core skills** are the recommended/default Manageroo-owned pack;
- **32 additional bundled skills** ship in the repository as optional capabilities;
- **host-installed skills** can also be discovered and used when relevant, but Manageroo does not claim ownership of the user's entire skill environment.

Before installing a core skill, setup checks the standard agent skill roots. It
reuses an existing same-name skill instead of creating another copy, and it does
not overwrite a differing host-owned skill. Manageroo updates only skill trees
recorded in its ownership ledger and still unchanged since Manageroo installed
them; a user edit revokes that ownership automatically.

## 18 portable core skills installed by default

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

These are the small portable core Manageroo installs as its own default skill pack.

## 32 additional bundled optional skills

These ship with the repository but are **not installed as Manageroo-owned defaults**:

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

Optional means exactly that: available in the bundled library, not silently installed as part of the portable core.

## Host skills are a separate boundary

A user's machine may already contain additional skills. Manageroo can inventory them without taking ownership of them:

```bash
manageroo host-skills
manageroo host-skills --json
```

Automatic capability routing is native controller behavior. `use-installed-skills-first` remains a portable compatibility policy for work that happens outside a Manageroo-controlled run. Manageroo does not copy, delete, upgrade, or pretend it owns the whole host skill environment.

Advanced diagnostics can explain the same decision without changing it:

```bash
manageroo skills explain "describe the job normally"
```

`skill-vetter` exists so third-party skills can be reviewed before adoption instead of being treated as trusted just because somebody put a `SKILL.md` in a folder.

# Optional surrounding tool stack

Manageroo is the controller. It can also work with optional tools that add specialized capabilities:

```text
Manageroo
├── GitNexus   → repository and code-graph intelligence
├── GBrain     → external durable knowledge and retrieval
├── TruffleHog → local secret scanning required by AUTOREVIEW
├── AUTOREVIEW → structured external review
├── Clawpatch  → evidence-driven findings and repair loops
└── Obsidian   → human-readable Markdown knowledge
```

These integrations add capabilities. They do not become the authority over Manageroo completion.

Inspect what is installed and configured:

```bash
manageroo stack-status
```

Check the surrounding stack for configuration or health problems:

```bash
manageroo stack-doctor
```

Preview supported updates without changing anything:

```bash
manageroo stack-update
```

Apply supported updates explicitly:

```bash
manageroo stack-update --apply
```

For npm/pnpm command-line tools, Manageroo updates through the package manager proven to own the active executable and tries the other supported manager only when ownership is verified there. It refuses ambiguous installations instead of guessing.

AUTOREVIEW requires TruffleHog. When the recommended stack is selected, Manageroo reuses an existing `trufflehog` command or installs the release-pinned official binary for Linux, macOS, or Windows after SHA-256 verification. Manageroo records ownership only for the copy it installed, so stack updates and uninstall planning do not overwrite or remove a user-managed copy.

GitNexus is treated as a first-class recommended repository-intelligence integration when selected during installation. Manageroo can still operate when optional surrounding tools are intentionally skipped or unavailable.

# Credits and influences

Manageroo did not appear from nowhere. It deliberately combines ideas from people and projects across the agent ecosystem while keeping its own controller as the authority over the run.

## Peter Yang / [@petergyang](https://x.com/petergyang) — The Skill Smith

Credit for the skill-hygiene direction: tighter reusable skills, self-improving skill loops, and the `edit-skill` idea.

## Matthew Berman / [@MatthewBerman](https://x.com/MatthewBerman) and Forward Future / [@ForwardFuture](https://x.com/ForwardFuture) — Captain Looplight

Credit for the plain-language framing of bounded agent work: a task, verifier, budget, stopping rule, and evidence. Manageroo implements its own orchestration and has no Loop Library runtime dependency.

Loop Library: https://signals.forwardfuture.com/loop-library/

## Garry Tan / [@garrytan](https://x.com/garrytan) — GBrain / The Memory Architect

Credit for GBrain's local durable-memory and retrieval direction: useful knowledge should survive outside the immediate prompt instead of forcing every agent session to rediscover the world.

GBrain: https://github.com/garrytan/gbrain

## Abhigyan Patwari — GitNexus / The Graph Cartographer

Credit for code-graph and impact-analysis direction: repositories have relationships and blast radius, not just flat piles of files.

No X handle is listed here because one has not been confidently verified.

GitNexus: https://github.com/abhigyanpatwari/GitNexus

## OpenClaw / [@OpenClaw](https://x.com/OpenClaw) — Agent Skills, AUTOREVIEW, and Clawpatch / The Patch Council

Credit for agent-skill packaging, structured review, and explicit evidence-to-fix loops.

Agent Skills: https://github.com/openclaw/agent-skills

Clawpatch: https://github.com/openclaw/clawpatch

## OpenAI / [@OpenAI](https://x.com/OpenAI) — Codex skill ecosystem / The Skill Forge

Credit specifically for Codex-oriented skill routing, skill-creator guidance, and agent-readable skill packaging. This is **not** a claim that OpenAI invented the general concept of skills.

Codex: https://developers.openai.com/codex/

## Obsidian / [@obsdmd](https://x.com/obsdmd) — The Vault Keeper

Credit for the human-readable Markdown knowledge direction: important project context should remain understandable and editable by the person who owns the project.

Obsidian: https://obsidian.md/

Together, these influences cover different parts of the problem: skills shape specialized work, loops bound the mission, memory preserves useful knowledge, graphs reveal code relationships, review catches failures, repair closes the loop, and Markdown keeps a human-readable trail.

Manageroo's contribution is the controller above those pieces: the layer that owns the mission, durable run state, decisions, boundaries, verification, evidence, and definition of done.

# Documentation

- [`docs/00_START_HERE.md`](docs/00_START_HERE.md)
- [`docs/INSTALLATION.md`](docs/INSTALLATION.md)
- [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md)
- [`docs/AGENT_PROTOCOL.md`](docs/AGENT_PROTOCOL.md)
- [`docs/CONTEXT_COMPILER.md`](docs/CONTEXT_COMPILER.md)
- [`docs/DISCOVERY_AND_CAPACITY.md`](docs/DISCOVERY_AND_CAPACITY.md)
- [`docs/EVIDENCE_RETRIEVAL.md`](docs/EVIDENCE_RETRIEVAL.md)
- [`docs/HOST_SKILL_ECOSYSTEM.md`](docs/HOST_SKILL_ECOSYSTEM.md)
- [`docs/REVIEW_REPAIR_LANES.md`](docs/REVIEW_REPAIR_LANES.md)
- [`docs/LIMITATIONS.md`](docs/LIMITATIONS.md)
- [`docs/CREDITS.md`](docs/CREDITS.md)

# License

See [`LICENSE`](LICENSE).
