A very serious local CLI that keeps AI coding agents on task: one brief in, repo-aware build or repair work, checks, review, and proof out.

## Plain-English summary

- Run `manageroo projects --add` when you want it to scan common folders, show a checkbox-style list of Git repos, initialize only the ones you select, and accept pasted paths it missed.
- Run `manageroo projects --pick` when you only want a read-only project list and the next command for one repo.
- Run `manageroo solo /path/to/project` when you want the guided product-team-in-a-box path.
- Run `manageroo solo /path/to/new-project --create --want "Describe it"` when the project does not exist yet.
- Use `--starter static-site`, `python-cli`, or `docs-project` when a new project needs a tiny scaffold and smoke check.
- Say what should exist in normal language.
- If the request is rough, angry, long, or reusable, use the bundled `pimp-my-prompt` skill to turn it into scope, proof, stop rules, and fallback behavior without changing the intent.
- Solo captures an intent lock: what you want, what must not happen, what proof matters, rejected ideas, corrections, and scope boundaries.
- Before or after chat compaction, audit the summary so it cannot quietly drop locked intent.
- Use `manageroo next` when you only want the current stage and one next command.
- The CLI turns the request into a product brief, project memory, repository-aware plan, and smaller agent jobs.
- Manageroo stores durable controller truth under `.manageroo/runs/<run-id>/`; workers are disposable and do not rely on chat memory.
- `manageroo run --continue <run-id>` reloads saved jobs and artifacts from disk and gives unfinished jobs fresh packets.
- AI IDE agents can use the installed `manageroo` command plus the repo-local skill; direct fresh-process orchestration is optional.
- Independent map and review chunks can run in parallel. Implementation stays dependency ordered in one isolated repo.
- It records pictures, PDFs, media, and big prose files in a document manifest and can run a configured document/prose evidence command.
- It runs the repo's real checks and gets a separate review pass.
- If review finds a verified problem, repair is bounded and all checks run again.
- It writes the patch, reports, logs, evidence, and next action to disk.
- Use `manageroo memory show` or `manageroo memory add` for the short repo-local continuity file.
- Runs emit evidence-backed learning cards; applying a supported card still requires explicit approval.
- The installer can guide the optional local stack: GBrain, GitNexus, AUTOREVIEW, Clawpatch, and Obsidian.
- Token reduction is one feature with two styles: clean `caveman` or profanity-enabled `uncle-matts-caveman-curse`.
- The installer offers a recommended local skill pack and defaults to installing it; it can be skipped with `--skill-pack skip` and installed later with `manageroo skills reconcile --apply`.
- That pack includes MANAGEROO routing, Pimp My Prompt, Brain Ops, Query, Ingest, Media Ingest, Voice Note Ingest, Article Enrichment, Book Mirror, Strategic Reading, PDF, Brain PDF, Citation Fixer, Reports, Exact Text Replacement, To PRD, To Issues, Grill Me, Grill With Docs, Diagnose, TDD, Testing, AUTOREVIEW, Security Review, Cross Modal Review, Playwright, Open Design, Web Design Guidelines, Fix My Bad Website, Plain Web Copy, Subagent Orchestrator, Minion Orchestrator, Write A Skill, Skillify, Edit Skill, Skillpack Check, and both Caveman modes.
- Copied skill folders can be curated locally with `manageroo skills reconcile --source ~/Downloads/SKILLS --include-external --apply`.
- Project init writes managed guidance blocks into `AGENTS.md` and `CONTEXT.md` while preserving existing content.
- Before release, `manageroo release-ready` checks the latest completed run, review, final report, final patch, applied source, gates, clean Git state, target, rollback plan, and approval, then writes a production handoff and updates project memory when ready.

## Why it exists

AI coding agents are powerful, but one giant chat is a bad project-management system. They lose context, touch unrelated files, skip checks, and say “done” too early.

MANAGEROO puts a local controller around the agent so the work stays attached to the repo, the brief, the checks, the review, and the final evidence.

Manageroo is not “AI remembers better.” Manageroo makes remembering unnecessary. The controller saves truth to disk and gives each fresh worker one complete bounded assignment.

## How it works

```text
Plain-English request
        ↓
Product brief + intent lock
        ↓
Repo inventory + memory/graph context
        ↓
Bounded task plan
        ↓
Disposable worker jobs with durable records
        ↓
Real checks + independent review
        ↓
Bounded repair if needed
        ↓
Patch + report + evidence
```

## Originality and attribution

- MANAGEROO is an original orchestration implementation.
- Credit to Clawpatch for the “small patch + proof” direction.
- Credit to Matthew Berman / Forward Future's public loop-engineering work, including Loop Library, for conceptual framing of bounded action, independent verification, budgets, stop rules, and evidence. Manageroo does not connect to or depend on Loop Library.
- Credit to Peter Yang / @petergyang for public skill hygiene, self-improving skill loops, and the edit-skill idea.
- Credit to GBrain and GitNexus for memory and code graph integration patterns.
- Credit to OpenClaw Agent Skills and AUTOREVIEW for agent skill/review patterns.
- Credit to the OpenAI Codex skill system for the simple `SKILL.md` routing and packaging convention.
- Credit to Obsidian for human-readable Markdown-vault context.
- See `docs/CREDITS.md` for links and exact boundaries.

## Special Thanks: The MANAGEROO Super Team

- **Peter Yang / @petergyang as The Skill Smith**
  - Stats: STR 8 | DEX 12 | CON 14 | INT 18 | WIS 17 | CHA 16
  - Power: turns messy repeated agent behavior into tight reusable skills, then keeps those skills short with edit passes.
  - Credit: skill hygiene, self-improving skill loops, and the edit-skill idea.
- **Matthew Berman / Forward Future as Captain Looplight**
  - Stats: STR 10 | DEX 13 | CON 15 | INT 17 | WIS 18 | CHA 17
  - Power: makes agent loops easy to understand: bounded task, verifier, stop rule, and evidence.
  - Credit: plain-language framing of bounded action, independent verification, budgets, stop rules, and evidence. This is conceptual influence; Manageroo has no Loop Library runtime dependency.
- **Garry Tan / GBrain as The Memory Architect**
  - Stats: STR 11 | DEX 11 | CON 18 | INT 18 | WIS 18 | CHA 14
  - Power: gives agents durable memory without dumping the whole universe into the prompt.
  - Credit: GBrain local memory and retrieval.
- **Abhigyan Patwari / GitNexus as The Graph Cartographer**
  - Stats: STR 9 | DEX 16 | CON 14 | INT 18 | WIS 16 | CHA 13
  - Power: turns codebases into navigable graphs so agents can reason about impact.
  - Credit: GitNexus code graph and impact-analysis direction.
- **OpenClaw Agent Skills, AUTOREVIEW, and Clawpatch as The Patch Council**
  - Stats: STR 15 | DEX 15 | CON 16 | INT 17 | WIS 17 | CHA 12
  - Power: maps work into bounded slices, reviews with evidence, and keeps patching explicit.
  - Credit: agent skill packaging, structured review, and Clawpatch-style fix loops.
- **OpenAI Codex skill system as The Skill Forge**
  - Stats: STR 10 | DEX 14 | CON 15 | INT 18 | WIS 16 | CHA 15
  - Power: gives local agents a simple skill format: trigger text first, then instructions and resources only when needed.
  - Credit: Codex skill routing, skill-creator guidance, and agent-readable skill packaging.
- **Obsidian as The Vault Keeper**
  - Stats: STR 8 | DEX 13 | CON 17 | INT 16 | WIS 17 | CHA 15
  - Power: keeps human notes in plain Markdown that the user can read and own.
  - Credit: Markdown-vault notes as a human-readable context lane.

Together they are the local-agent super team: skills shape the ask, loops define the mission, memory remembers the map, graphs show the blast radius, review catches the bad stuff, and notes keep a human-readable trail.

## Current state

- Implemented local CLI
- Build and repair modes
- Solo Operator Mode with optional new-project creation
- Guided project discovery and multi-project setup
- Intent lock and compaction audit
- Repo inventory and context compiler
- Durable worker job store and continuation
- GBrain, GitNexus, Obsidian, document/prose, AUTOREVIEW, and Clawpatch integration points
- Deterministic check runner
- Independent review and repair loop
- Patch/report/evidence output
- Proactive learning cards with approval-gated apply
- Recommended local skill pack with routing, intake, research, document, testing, review, design, orchestration, skill-creation, skill-editing, and token modes
- Release-ready operator handoff gate
- Linux/macOS/PowerShell installer launchers
- Original generated chiptune installer music
