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
> Windows (WSL2 terminal):
>
> ```powershell
> git clone https://github.com/uncmatteth/Uncle-Matts-Project-Manageroo.git && cd Uncle-Matts-Project-Manageroo && ./install.sh
> ```
>
> Already cloned it? Stay in that existing folder and rerun `./install.sh`. Native Windows is not supported by the secure artifact backend; use WSL2.
>
> If Git is not installed yet, use GitHub's **Code → Download ZIP**, extract it, open a Linux/macOS or WSL2 terminal in the folder, and run the platform command above. The installer checks Python 3.11+ and Git.
>
> **2. Follow the guided setup**
>
> Manageroo reports Codex, Claude Code, and Gemini CLI when found. Controlled runs currently enable only Codex because its native sandbox supplies the required host filesystem boundary. Claude Code and Gemini detection is informational. If no controlled worker is found, setup offers Codex and its Node.js/npm requirement.
>
> At the end, Manageroo scans the usual project folders read-only. It does not make you select one project during installation.
>
> **3. Tell Manageroo what you want**
>
> ```text
> Hi! I'm Manageroo! Let's do!
> >
> ```
>
> Type what you want built or fixed. Manageroo matches the request to the projects it found and asks which project only when the request is ambiguous. Run `manageroo` later to reopen the same front door.
>
> **Manageroo for beginners:** Think of Manageroo as the project foreman above your coding agent. You describe the result you want; Manageroo records the mission, maps the repository, gives the coding agent bounded jobs in an isolated workspace, runs the project's checks, performs separate review, and produces evidence and a patch. It does not treat the worker saying “done” as proof. Use `manageroo run --apply` when you want a successfully verified patch applied to your project. Use `manageroo status RUN_ID --repo .` to check a run and `manageroo report RUN_ID --repo .` to read what happened.

## What Manageroo is

Manageroo is the controller above the coding agents.

The human defines the mission. Manageroo preserves the mission, maps the repository, discovers important unknowns, creates bounded worker jobs, routes those jobs to compatible agents, checks what actually changed, runs project verification, performs independent review, repairs failed work within budgets, and keeps durable evidence on disk.

The worker does the work. The controller owns the mission, state, boundaries, review, proof, and definition of done.

Controlled runs currently use Codex. Other CLI templates remain extension points, but Manageroo refuses them until they can prove an equivalent host filesystem boundary.

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

The repository currently contains **55 bundled skill packages**.

- **22 portable core skills** are the recommended/default Manageroo-owned pack.
- **33 additional bundled skills** are optional and are not silently installed as Manageroo-owned defaults.
- Existing host-installed skills can also be discovered and used when relevant without Manageroo claiming ownership of the user's entire skill environment.

### 22 portable core skills

- `uncle-matts-project-manageroo`
- `use-installed-skills-first`
- `skill-vetter`
- `pimp-my-prompt`
- `setup-matt-pocock-skills`
- `to-spec`
- `to-tickets`
- `grill-me`
- `grilling`
- `grill-with-docs`
- `domain-modeling`
- `codebase-design`
- `diagnosing-bugs`
- `tdd`
- `testing`
- `security-review`
- `handoff`
- `writing-for-agents`
- `edit-skill`
- `skillify`
- `caveman`
- `uncle-matts-caveman-curse`

### 33 bundled optional skills

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
- `go-get-uncle-matts-hammerrr`
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
    -> installs only the 22-skill portable core by default
    -> currently runs Codex workers with a verified host filesystem sandbox

Bundled optional library
    -> contains 33 additional skill packages
    -> available without becoming default Manageroo-owned installs

Host environment
    -> may contain additional skills and optional tools
    -> remains independently owned and maintained
    -> can contribute capabilities without becoming Manageroo's authority
```

For the full public-facing explanation, installation commands, skill inventory, integrations, and credits, see `README.md`.
