# Uncle Matt's Project Manageroo

## Install in one command

**Linux / macOS**

```bash
git clone https://github.com/uncmatteth/Uncle-Matts-Project-Manageroo.git && cd Uncle-Matts-Project-Manageroo && ./install.sh
```

**Windows PowerShell**

```powershell
git clone https://github.com/uncmatteth/Uncle-Matts-Project-Manageroo.git; Set-Location Uncle-Matts-Project-Manageroo; .\install.ps1
```

Requirements: Python 3.11+ and Git. For real AI work, install or connect at least one compatible coding-agent CLI.

---

## What this is

Manageroo is a local project controller for AI coding agents working on real Git repositories.

The problem it is built for is simple: one giant AI chat should not be expected to remember an entire project, discover every hidden risk, write all the code, review itself, verify itself, and then decide that its own work is finished.

Manageroo puts a controller above the workers.

```text
ONE PLAIN-ENGLISH BRIEF
        ↓
PROJECT DISCOVERY + REPO MAPPING
        ↓
BOUNDED WORKER JOBS
        ↓
REAL CHECKS + INDEPENDENT REVIEW
        ↓
BOUNDED REPAIR WHEN NEEDED
        ↓
EVIDENCE + DELIVERY
```

The coding agents do the work. The controller owns the mission, state, boundaries, review, proof, and definition of done.

## Why it exists

Manageroo is for people whose projects have outgrown the normal "paste everything into one chat and hope" workflow.

It is designed to help with:

- large or old repositories;
- long-running AI-assisted projects;
- work spread across multiple agent sessions;
- requirements that cannot safely disappear during context compaction;
- changes where blast radius matters;
- projects that need review independent from the agent that wrote the code;
- repair work that should be bounded instead of turning into endless autonomous thrashing;
- teams or solo builders who want evidence instead of "trust me, it is done."

Manageroo keeps important project truth outside the worker so a model change, terminal restart, failed run, or new chat does not erase the mission.

## What Manageroo actually does

Manageroo can:

- read and inventory a Git repository;
- capture the requested outcome, must-not rules, and proof expectations;
- preserve an intent lock so important requirements survive long runs and compaction;
- perform discovery before implementation and surface high-impact unknowns;
- map the repository before assigning work;
- split work into bounded jobs;
- route work to compatible coding-agent CLIs;
- keep job, attempt, retry, and run state on disk;
- isolate worker attempts from the operator's source repository;
- verify changed-file scope and repository state;
- run deterministic project checks;
- require proof bindings for claimed outcomes;
- perform independent review;
- run bounded repair loops when work fails review or verification;
- resume interrupted runs from durable state;
- produce reports, evidence, and a patch for delivery.

Manageroo is not an IDE, model host, deployment platform, cloud scheduler, memory database, or code-graph database. It can work with tools that provide those capabilities without giving them control over Manageroo completion.

## The controller is the boss

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

Manageroo keeps controller-owned state for the mission, jobs, attempts, decisions, review, evidence, and completion. A worker can help build the project, but it does not get to certify its own work just because it returned a confident answer.

## Durable project truth

Every run stores controller-owned state under:

```text
.manageroo/runs/<run-id>/
```

Project continuity also uses human-readable repository files such as:

```text
.manageroo/PROJECT-MEMORY.md
.manageroo/intent/INTENT-LOCK.json
.manageroo/intent/INTENT-LOCK.md
```

A run can be resumed from its saved state:

```bash
manageroo run --continue RUN_ID --repo /path/to/repo --apply
```

That is a real continuation from durable artifacts. Manageroo does not pretend a dead background process kept working after it stopped.

## Discovery before implementation

Before large implementation work, Manageroo's discovery preflight looks beyond the literal request and checks areas that commonly get missed, including:

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

When repository evidence can answer a question, Manageroo uses the evidence. When a genuinely high-impact decision still requires the operator, it becomes explicit instead of being guessed.

```bash
manageroo decisions show RUN_ID --repo /path/to/repo
manageroo decisions answer RUN_ID --repo /path/to/repo
manageroo run --continue RUN_ID --repo /path/to/repo --apply
```

## Source isolation and bounded changes

Manageroo performs worker activity in run-owned isolated repositories rather than giving every coding worker unrestricted access to the operator's source tree.

Successful work is delivered back through a patch after Manageroo verifies the source repository has not drifted underneath the run.

The goal is simple: workers can work aggressively inside the bounded workspace without casually poisoning the original repository.

## Proof before "done"

Manageroo reconciles completion against:

- requested outcomes;
- required proof gates;
- changed-file scope;
- deterministic verification;
- independent review;
- required demonstration evidence.

A passing unit test does not automatically prove a browser flow. A model saying something is deployed does not prove deployment. A worker claiming something is secure does not make it secure.

Claims that require observable evidence remain unproven until the matching evidence exists.

## Hardware compatibility

Manageroo core is hardware-agnostic.

It does not require a specific GPU, VRAM amount, CPU tier, or RAM class. A target project or an explicitly selected local AI tool may have its own requirements, but those belong to that project or tool.

Inspect the current host:

```bash
manageroo capacity
manageroo capacity --json
```

The hardware profile is informational context. Manageroo does not silently rewrite worker concurrency based on one developer machine.

# Skills: what is actually included

This repository currently contains **50 bundled skill packages**.

That does **not** mean Manageroo installs all 50 by default.

The public boundary is:

- **18 portable core skills** are the recommended/default Manageroo-owned pack;
- **32 additional bundled skills** are available in the repository as optional capabilities;
- **host-installed skills** can also be discovered and used when relevant, but Manageroo does not claim ownership of the user's entire skill environment.

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

These are shipped in the repository but are **not installed as Manageroo-owned defaults**:

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

Optional means exactly that: available, not silently installed as part of the portable core.

## Host skills are a separate boundary

A user's machine may already contain other skills. Manageroo can inventory them without taking ownership of them:

```bash
manageroo host-skills
manageroo host-skills --json
```

`use-installed-skills-first` lets compatible workers use relevant host capabilities when appropriate. Manageroo does not copy, delete, upgrade, or pretend it owns the whole host skill environment.

`skill-vetter` exists so third-party skills can be reviewed before adoption instead of being treated as trusted just because somebody put a `SKILL.md` in a folder.

# Optional surrounding tool stack

Manageroo is the controller. It can also work with a surrounding stack of optional tools:

```text
Manageroo
├── GitNexus   → repository and code-graph intelligence
├── GBrain     → external durable knowledge and retrieval
├── AUTOREVIEW → structured external review lane
├── Clawpatch  → evidence-driven findings and repair loops
└── Obsidian   → human-readable Markdown knowledge
```

These integrations add capabilities. They do not become the authority over Manageroo completion.

Inspect the current stack:

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

GitNexus is treated as a first-class recommended repository-intelligence integration when selected during installation. Manageroo can still operate when optional surrounding tools are intentionally skipped or unavailable.

# First project

Discover existing projects:

```bash
manageroo projects --add
```

Start in an existing repository:

```bash
manageroo solo /absolute/path/to/product
```

Create a new missing or empty repository:

```bash
manageroo solo /absolute/path/to/new-product \
  --create \
  --want "Describe what should be built first"
```

When you are not sure what comes next:

```bash
manageroo next
```

## Run work

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

# Credits and influences

Manageroo did not appear from nowhere. It deliberately combines ideas from people and projects across the agent ecosystem while keeping its own controller as the authority over the run.

## Peter Yang / @petergyang — The Skill Smith

Credit for the skill-hygiene direction: tighter reusable skills, self-improving skill loops, and the `edit-skill` idea.

https://x.com/petergyang

## Matthew Berman / Forward Future — Captain Looplight

Credit for the plain-language framing of bounded agent work: a task, verifier, budget, stopping rule, and evidence. Manageroo implements its own orchestration and has no Loop Library runtime dependency.

https://signals.forwardfuture.com/loop-library/

## Garry Tan / @garrytan — GBrain / The Memory Architect

Credit for GBrain's local durable-memory and retrieval direction: useful knowledge should survive outside the immediate prompt instead of forcing every agent session to rediscover the world.

https://github.com/garrytan/gbrain

## Abhigyan Patwari — GitNexus / The Graph Cartographer

Credit for code-graph and impact-analysis direction: repositories have relationships and blast radius, not just flat piles of files.

https://github.com/abhigyanpatwari/GitNexus

## OpenClaw Agent Skills, AUTOREVIEW, and Clawpatch — The Patch Council

Credit for agent-skill packaging, structured review, and explicit evidence-to-fix loops.

https://github.com/openclaw/agent-skills

https://github.com/openclaw/clawpatch

## OpenAI Codex skill ecosystem — The Skill Forge

Credit specifically for Codex-oriented skill routing, skill-creator guidance, and agent-readable skill packaging. This is **not** a claim that OpenAI invented the general concept of skills.

https://developers.openai.com/codex/

## Obsidian — The Vault Keeper

Credit for the human-readable Markdown knowledge direction: important project context should remain understandable and editable by the person who owns the project.

https://obsidian.md/

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