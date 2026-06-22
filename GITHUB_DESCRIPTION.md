# GitHub Description Copy

## Repository Description

```text
A very serious local CLI that keeps AI coding agents on task: one brief in, repo-aware build or repair work, checks, review, and proof out.
```

## Plain-English About Text

- The command is `manageroo`.
- The full name is incredibly super serious.
- Use it when you want an AI coding agent to work on a real Git repo without drifting all over the place.
- If you are starting from nothing, `solo --create` can make a missing or empty Git repo first.
- `solo --create --starter static-site` can start a tiny homepage with a smoke test instead of a blank folder.
- You write the brief. The tool maps the repo, splits the job up, runs checks, sends bad work back for repair, and saves the report.
- It includes `pimp-my-prompt`, so rough, long, frustrated, or half-formed requests can become clear scope, proof, and stop rules.
- It includes memory and document helpers, so GBrain lookup, source ingest, screenshots, PDFs, transcripts, long prose, exact wording, citations, reports, and PDF export have obvious lanes.
- It includes `diagnose`, `tdd`, and `autoreview`, so bugs get a feedback loop, behavior gets proof, and finished work gets a review lane.
- It includes `plain-web-copy` and `fix-my-bad-website`, so public pages do not have to look or read like generic AI slop.
- It includes `edit-skill`, so your local skills can get tighter instead of turning into long duplicate slop files.
- It includes `write-a-skill` and `skillify`, so repeated painful work can become a small reusable skill with triggers and proof.
- It includes one token-reduction feature with two styles: clean `caveman` or profane `curse`, because life is more fun with appropriately placed, well-used profanity.
- The recommended skill pack is optional but strongly suggested. The installer offers it, defaults to yes, `--skill-pack skip` skips it, and `manageroo skills install` adds it later.
- The installer can scan common project folders, show a checkbox-style list of found repos, initialize only the ones selected, and ask for extra paths it missed.
- The repo-local MANAGEROO skill tells AI IDE agents when to use each helper, so the user does not have to remember which skill to call.
- Project init handles `AGENTS.md`, `CONTEXT.md`, `.manageroo/PROJECT-MEMORY.md`, and the repo-local skill block so the user does not have to figure out agent-context files by hand.
- `skills scan` and `skills import --apply` turn a copied skills folder into a curated local toolbox without blindly copying duplicate folders.
- The normal path is simple: run `manageroo solo`, answer normal product questions, then follow the one next command.
- `.manageroo/PROJECT-MEMORY.md` keeps the project identity, shipped facts, must-not-break rules, proof, and operator notes in the repo instead of hidden in chat.
- Every run can leave learning cards with evidence: remember this, fix that lane, consider a media/prose workflow, or turn a repeated problem into a future task.
- Learning cards are approval-gated. `learning apply CARD_ID --approve` is required, and only low-risk project-memory notes apply automatically right now.
- Manual-only cards do not give the AI permission to rewrite skills, config, docs, installer behavior, checks, prompts, or code.
- `setup`, `brief`, `ready`, `run --apply`, and `release-ready` are still available when you want lower-level control.
- `next` is the low-noise helper for "what do I do now?": it prints the current stage, the reason, and one command.
- Bare `setup` is the lower-level wizard: AI choice, repo path, and optional stack checks.
- If configured, GBrain/GitNexus feed memory and code-graph context into the run; if they fail, the report says so and the core path keeps going.
- If configured, `document_analysis_command` reads a run-owned document manifest and adds long-prose/PDF/transcript evidence without giving the AI permission to freehand a whole manuscript.
- GBrain setup has two lanes: the local Bun/PGLite path, or the official upstream agent-supervised `INSTALL_FOR_AGENTS.md` protocol.
- Clawpatch setup checks `clawpatch doctor` and Codex login status for its codex provider.
- AUTOREVIEW and Clawpatch are command-owned lanes; their findings do not become AI freehand repair prompts.
- `gbrain-setup` can prompt for one selected folder. No broad personal-folder crawl.
- `agent list` and `agent preset` make Codex, Gemini, Claude Code, mock, or generic CLI setup visible instead of hidden in docs.
- `repair-install` inspects and fixes the local launcher and recommended skill-pack install.
- It was built around GBrain, GitNexus, Obsidian, AUTOREVIEW, Clawpatch, and any AI IDE or CLI agent that can run commands in the repo.
- The installer can guide or install the recommended local stack: GBrain, GitNexus, AUTOREVIEW, Clawpatch, Obsidian, and Matthew Berman / Forward Future's Loop Library skill.
- Solo Operator Mode reports every selected extra: configured, missing, skipped, or the exact command to fix next.
- `checks suggest --apply-first` looks at the repo and saves the first detected proof command without hand-editing TOML.
- `release-ready` is the final no-bullshit operator gate: completed Manageroo run proven, review approved, final report and patch present, patch applied to source, checks green, Git clean, deployment target named, rollback notes written, human approval recorded, and a plain-English production handoff written.
- Credit to Matthew Berman / Forward Future's Loop Library for making the agent-loop idea easy to point at: bounded action, fixed check, stop condition, evidence.
- Credit to Peter Yang's public skill-writing advice for the skill-hygiene idea: clear triggers, examples/evals when useful, memory only when it is actually read, and an edit-skill pass to remove duplicate or stale instructions.
- It does not need a special version for Codex, Claude Code, Gemini, Grok, or the next AI thing. If the agent can work in the repo, it can use the same installed command.
- It is alpha software. First real run goes on a clone, branch, or disposable copy.
- It is not a replacement for tests, backups, security review, or human judgment.

## Special Thanks: The MANAGEROO Super Team

These are the real-world powers this project remixes:

- **Peter Yang / @petergyang as The Skill Smith**
  - Stats: STR 8 | DEX 12 | CON 14 | INT 18 | WIS 17 | CHA 16
  - Power: turns messy repeated agent behavior into tight reusable skills, then keeps those skills short with edit passes.
  - Credit: skill hygiene, self-improving skill loops, and the edit-skill idea.
- **Matthew Berman / Forward Future as Captain Looplight**
  - Stats: STR 10 | DEX 13 | CON 15 | INT 17 | WIS 18 | CHA 17
  - Power: makes agent loops easy to understand: bounded task, verifier, stop rule, and evidence.
  - Credit: Loop Library and plain-language loop framing.
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

Together they are the local-agent super team: skills shape the ask, loops define
the mission, memory remembers the map, graphs show the blast radius, review
catches the bad stuff, and notes keep a human-readable trail.
