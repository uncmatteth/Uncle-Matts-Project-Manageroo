# GitHub Description Copy

## Repository Description

```text
A local project controller for AI coding agents: one brief in, repo-aware build or repair work, bounded jobs, checks, independent review, durable state, and evidence out.
```

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
> **Manageroo for beginners:** Think of Manageroo as the project foreman above your coding agent. You describe the result you want; Manageroo records the mission, maps the repository, gives the coding agent bounded jobs in an isolated workspace, runs the project's checks, performs separate review, and produces evidence and a patch. It does not treat the worker saying “done” as proof. Use `manageroo run --apply` when you want a successfully verified patch applied to your project. Use `manageroo status RUN_ID --repo .` to check a run and `manageroo report RUN_ID --repo .` to read what happened.

## What Manageroo is

Manageroo is the controller above the coding agents.

The human defines the mission. Manageroo preserves the mission, maps the repository, discovers important unknowns, creates bounded worker jobs, routes those jobs to compatible agents, checks what actually changed, runs project verification, performs independent review, repairs failed work within budgets, and keeps durable evidence on disk.

The worker does the work. The controller owns the mission, state, boundaries, review, proof, and definition of done.

Built-in worker paths cover Codex, Claude Code, Gemini, and compatible generic CLIs. The worker layer is replaceable by design.

## Discovery, decisions, and hardware

Manageroo runs an **unknown-unknowns preflight** before large implementation work. The point is not to dump internal process jargon on the user; it is to inspect the repository for important risks and requirements the original brief may have missed, answer what the repository can answer, and stop only for genuinely high-impact unresolved choices.

When a run needs an operator decision:

```bash
manageroo decisions show RUN_ID --repo .
manageroo decisions answer RUN_ID --repo .
manageroo run --continue RUN_ID --repo . --apply
```

Manageroo core is **hardware-agnostic**. A target project or selected local AI tool may have its own hardware needs, but Manageroo itself does not auto-tune worker concurrency from one developer machine. Inspect the host as informational context with:

```bash
manageroo capacity
manageroo capacity --json
```

## Skills: exact public boundary

The repository currently contains **50 bundled skill packages**.

- **18 portable core skills** are the recommended/default Manageroo-owned pack.
- **32 additional bundled skills** are optional and are not silently installed as Manageroo-owned defaults.
- Existing host-installed skills can also be discovered and used when relevant without Manageroo claiming ownership of the user's entire skill environment.

### 18 portable core skills

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

### 32 bundled optional skills

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

## Optional surrounding tool stack

Manageroo can work with optional tools that add specialized capabilities without becoming the source of truth for completion:

- **GitNexus** — repository and code-graph intelligence;
- **GBrain** — external durable knowledge and retrieval;
- **AUTOREVIEW** — structured external review;
- **Clawpatch** — evidence-driven findings and repair loops;
- **Obsidian** — human-readable Markdown knowledge.

Manageroo can still operate when optional surrounding tools are intentionally skipped or unavailable.

For projects that use Clawpatch at final release, `manageroo clawpatch release-sweep --repo .` previews a cross-platform closeout loop. Adding `--apply` runs map/review, processes one fresh finding at a time, requires validation before an exact-path commit, checkpoints progress, reruns every open finding, and proves zero open against the final Git HEAD. Pushes remain separately opt-in.

## Credits and influences

Manageroo deliberately combines ideas from people and projects across the agent ecosystem instead of pretending those ideas appeared from nowhere.

- **Peter Yang / @petergyang** — skill hygiene, self-improving skill loops, and the `edit-skill` direction.
- **Matthew Berman / Forward Future** — bounded agent work, independent verification, budgets, stopping rules, and evidence.
- **Garry Tan / @garrytan / GBrain** — durable local memory and retrieval direction.
- **Abhigyan Patwari / GitNexus** — code-graph and impact-analysis direction.
- **OpenClaw Agent Skills, AUTOREVIEW, and Clawpatch** — agent-skill packaging, structured review, and explicit fix loops.
- **OpenAI Codex skill ecosystem** — specifically Codex-oriented skill routing, skill-creator guidance, and agent-readable skill packaging; not the invention of skills as a general concept.
- **Obsidian** — human-readable Markdown knowledge.

Manageroo's contribution is the controller above those pieces: the layer that owns the mission, durable run state, decisions, boundaries, verification, evidence, and definition of done.

## Core boundary

```text
Manageroo controller
    -> owns mission, state, jobs, proof, review, repair, and completion
    -> installs only the 18-skill portable core by default
    -> can use different compatible coding-agent providers

Bundled optional library
    -> contains 32 additional skill packages
    -> available without becoming default Manageroo-owned installs

Host environment
    -> may contain additional skills and optional tools
    -> remains independently owned and maintained
    -> can contribute capabilities without becoming Manageroo's authority
```

For the full public-facing explanation, installation commands, skill inventory, integrations, and credits, see `README.md`.
