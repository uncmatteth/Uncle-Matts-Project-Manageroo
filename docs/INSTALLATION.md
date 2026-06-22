# Installation

## Requirements

- Python 3.11 or newer
- Git
- Internet access only if installing or updating a selected external agent/tool

Install Python 3.11+ and Git first. The installer is supposed to be the easy
part, not a treasure hunt.

## Install

```bash
./install.sh
```

Same installer, same behavior. Use `./install.sh` from a normal Unix-style
terminal, or `.\install.ps1` from PowerShell. Those are launchers, not separate
products.

## Installer controls

```bash
./install.sh --no-music
./install.sh --no-animation
./install.sh --install-codex
./install.sh --install-stack
./install.sh --skip-stack
./install.sh --gbrain-lane local
./install.sh --gbrain-lane official
./install.sh --clawpatch-codex-login run
./install.sh --loop-library-agent codex
./install.sh --loop-library-agent YOUR_AGENT
./install.sh --skill-pack install
./install.sh --skill-pack skip
./install.sh --project-discovery add
./install.sh --project-discovery pick
./install.sh --project-discovery skip
./install.sh --token-mode caveman
./install.sh --token-mode curse
./install.sh --skip-tests
```

Normal users should not need these.

PowerShell exposes the same important controls with parameter names like
`-GBrainLane`, `-ProjectDiscovery`, `-StackDoctor`, and
`-ClawpatchCodexLogin`.

## Recommended stack

The installer can install or guide the surrounding stack that makes the whole
thing useful:

- GBrain: choose `--gbrain-lane local` for this installer's local CLI path, or
  `--gbrain-lane official` for Garry Tan/GBrain's upstream
  `INSTALL_FOR_AGENTS.md` protocol. Existing installs are inspected, not
  reinitialized.
- GitNexus: installed with `npm install -g gitnexus`; run `gitnexus setup` afterward for MCP wiring.
- AUTOREVIEW: detected in `~/.agents/skills/autoreview` or `~/.codex/skills/autoreview`; installed from `openclaw/agent-skills` only when missing.
- Clawpatch: installed with `pnpm add -g clawpatch`; the installer can install
  `pnpm` with npm when needed, runs `clawpatch doctor`, checks Codex login for
  Clawpatch's codex provider, and can run `codex login` when
  `--clawpatch-codex-login run` is selected.
- Loop Library: installed with `npx --yes skills add Forward-Future/loop-library --skill loop-library ...` for the selected agent.
- Obsidian: installed through a detected package manager when possible, otherwise the installer prints the official install path.

Interactive installs ask whether to run this lane. Non-interactive installs skip
it unless `--install-stack` is passed.

The installer writes a stack summary into `install-lock.json`. It lists what was
installed, what was skipped, what still needs action, and the next command for
each unfinished piece.

For an existing GBrain install, the lock records the detected engine, embedding
model, schema pack, source count, unembedded chunks, and coverage summary. It
also includes safe mapping commands:

```bash
gbrain sources list
gbrain sources add YOUR_SOURCE_ID --path /absolute/path/to/folder
gbrain sync --source YOUR_SOURCE_ID --json --yes
gbrain status --json --section sync
```

The installer does not choose broad personal folders for you.

The local GBrain lane is:

```bash
bun install -g github:garrytan/gbrain
gbrain init --pglite
gbrain doctor --json
```

The official upstream lane is not guessed by this installer because it includes
API-key questions, search-mode choice, source mapping, skills, recurring jobs,
and verification. The installer prints the exact protocol URL instead:

```text
https://raw.githubusercontent.com/garrytan/gbrain/master/INSTALL_FOR_AGENTS.md
```

Clawpatch is also deterministic. After install, run its project commands in the
repo you want reviewed:

```bash
clawpatch init
clawpatch map
clawpatch review --limit 3 --jobs 3
clawpatch next
clawpatch fix --finding FINDING_ID
```

MANAGEROO can run configured AUTOREVIEW/Clawpatch commands as
command-owned lanes, but it does not ask the AI to freehand repairs from their
findings. See [`REVIEW_REPAIR_LANES.md`](REVIEW_REPAIR_LANES.md).

## Recommended skill pack

The installer offers the routed Manageroo skill pack under `~/.agents/skills`.
The pack is optional but strongly suggested because it lets AI IDE agents pick
the right helper without making the user remember which skill to call. Agents
should load only the skills that match the current job, not the whole pack.

In a normal terminal, the installer asks and defaults to yes. Non-interactive
installs use the recommended yes path. Skip it with `./install.sh --skill-pack
skip` or `./install.sh --skip-skill-pack`. Reconcile it later with
`manageroo skills reconcile --apply`.

- `uncle-matts-project-manageroo`:
  tells agents how to follow the controller.
- `pimp-my-prompt`: turns rough requests into exact scope, acceptance criteria,
  fallback rules, and runnable product briefs.
- `brain-ops`: searches and writes GBrain-backed durable context while keeping
  current repo truth higher than memory.
- `query`: answers from stored brain knowledge with source-grounded context.
- `ingest`, `idea-ingest`, `media-ingest`, and `voice-note-ingest`: turn links,
  articles, screenshots, PDFs, transcripts, voice notes, and media sources into
  usable local context.
- `article-enrichment`, `book-mirror`, and `strategic-reading`: handle long
  articles, books, manuscripts, research, and prose in bounded sections.
- `pdf`, `brain-pdf`, `citation-fixer`, and `reports`: support PDF checks,
  brain-page PDF rendering, citation cleanup, and durable reports.
- `exact-text-replacement`: preserves literal user wording when exact text
  matters.
- `academic-verify`, `data-research`, and `perplexity-research`: support cited
  research, structured tracking, and current-state checks.
- `repo-architecture`, `find-skills`, and `skillpack-check`: support brain
  filing, discovering specialist skills, and checking GBrain skillpack health.
- `write-a-skill`: creates a concise reusable skill when a workflow keeps
  coming back.
- `edit-skill`: tightens existing skills by removing duplicate instructions,
  stale rules, vague wording, and AI slop.
- `skillify`: checks whether a repeated workflow deserves a skill, then makes
  sure it has triggers and proof.
- `handoff`, `to-prd`, `to-issues`, `grill-me`, `grill-with-docs`, and
  `functional-area-resolver`: support clean handoffs, product definition,
  issue breakdown, requirement pressure, and smaller ownership boundaries.
- `diagnose`: builds a fast feedback loop before fixing bugs, flakes, crashes,
  or confusing failures.
- `tdd`: uses one behavior test at a time when code changes need proof.
- `testing`, `improve-codebase-architecture`, `security-review`, and
  `cross-modal-review`: support broader test health, architecture review,
  security review, and second-model pressure.
- `subagent-orchestrator` and `minion-orchestrator`: support safe worker fan-out
  only when the work is large or durable enough to justify it.
- `autoreview`: runs the closeout review lane before commit, release, or
  handoff.
- `plain-web-copy`: keeps public copy factual, readable, and free of fake-live
  hype.
- `fix-my-bad-website`: helps agents make web pages feel like the actual
  product instead of generic AI output.
- `web-design-guidelines`, `open-design`, `playwright`, and
  `playwright-interactive`: support UI quality, visual review, browser proof,
  screenshots, and interactive web debugging.
- `caveman`: token reduction in the clean style.
- `uncle-matts-caveman-curse`: the same token reduction with appropriately
  placed profanity when selected.

They are available even when token mode is off. Reinstall them later with:

```bash
manageroo skills reconcile --apply
```

If you copied skills from another machine, reconcile them without manual file
moving:

```bash
manageroo skills reconcile --source ~/Downloads/SKILLS --include-external --apply
```

`skills reconcile` installs one active Manageroo-managed copy of each bundled
skill under `~/.agents/skills`, copies support files for skills that need them,
backs up different existing target files first, and reports duplicate skill
names found in other scanned roots. It does not delete outside agent skill
directories.

## Validate

```bash
manageroo --version
manageroo banner --no-animation
manageroo self-test
manageroo skills list
manageroo token-mode status
manageroo stack-status
manageroo repair-install --no-apply
manageroo projects --add
```

## Token reduction

Token reduction is one feature with two styles. The package includes both skill
files so you can switch later, but only the selected mode is active:

- `caveman`: terse, clean output.
- `uncle-matts-caveman-curse`: terse output plus profanity, because life is
  more fun with appropriately placed, well-used profanity.

Switch later:

```bash
manageroo token-mode set off
manageroo token-mode set caveman
manageroo token-mode set curse
```

If a different local `SKILL.md` already exists for one of those names, the tool
backs it up before installing the bundled copy.

## Start Or Add Product Projects

The easiest install-time path is guided project setup:

```bash
manageroo projects --add
```

It scans common folders, shows a checkbox-style list, lets you choose exactly
which repos to add, then asks whether you want to paste any extra project paths
it missed. Selected existing Git repos get MANAGEROO project files.
Missing or empty manual paths can become new Git projects. Non-empty non-Git
folders are refused until you run `git init` there yourself.

It does not initialize or edit every project on the machine.

If you only want the read-only picker:

```bash
manageroo projects --pick
```

That scans common folders, lists Git repos, and prints the exact next command.

For an existing Git repository:

```bash
manageroo solo /absolute/path/to/product
```

For a brand-new missing or empty folder:

```bash
manageroo solo /absolute/path/to/new-product \
  --create \
  --want "Describe what should be built first"
```

Bare `solo` is the normal first-run path. It asks:

- what AI you are using;
- what repo should be initialized;
- what should be built or fixed;
- who it is for;
- what result must be true;
- what must not break;
- what proof should verify the work;
- whether to check GBrain, GitNexus, Obsidian, or Loop Library.

With `--create`, it initializes Git, writes a minimal `README.md` and
`.gitignore`, and makes the first scaffold commit before continuing. It refuses
non-empty non-Git folders and nested repos.

It writes `.manageroo/PRODUCT-BRIEF.md`, writes
`.manageroo/PROJECT-MEMORY.md`, captures
`.manageroo/intent/INTENT-LOCK.json`, writes or updates managed `AGENTS.md`
and `CONTEXT.md` guidance blocks, checks readiness, and prints exactly one next
command. Existing human content in those files is preserved. If every required
check is already ready during that first
command, you can combine intake and execution:

```bash
manageroo solo --want "Describe the result" --run --apply --force
```

When you are unsure where the project is in the path, ask for one next action:

```bash
manageroo next
```

It prints the stage, the reason, and one command to run next.

Lower-level setup is still available when you want only repo initialization:

```bash
manageroo setup
```

Use `--agent codex` only when this tool should launch Codex itself. Use
`manageroo agent list` to see built-in agent presets:

Use project memory to keep future runs from forgetting what matters:

```bash
manageroo memory show
manageroo memory add --must-not "Do not remove the import flow"
```

Use the intent lock when a long chat, handoff, or continuation summary might
have lost the real request:

```bash
manageroo intent show
manageroo compact audit --summary SUMMARY.md
```

```bash
manageroo agent list
manageroo agent preset gemini
manageroo agent preset generic
```

The non-Codex presets are command templates. If your CLI needs different flags,
edit `[agent].argv_template` in `.manageroo/config.toml`.

If an AI IDE can read the repo and run commands, it does not need a special
vendor build. Give it the installed command plus the repo-local skill.

No IDE-specific directory is created.

For a brand-new product, `solo --create` can start from a small starter instead
of a blank repo:

```bash
manageroo solo /absolute/path/to/new-site \
  --create \
  --starter static-site \
  --want "Build a simple product homepage"
```

Starter choices are `blank`, `static-site`, `python-cli`, and `docs-project`.
The non-blank starters include no-dependency unittest smoke checks.

Create a normal-language brief:

```bash
manageroo brief \
  --want "Say exactly what should be built or fixed" \
  --outcome "The result that must be true" \
  --must-not "Anything the agent must not touch" \
  --proof "The check or demo that proves it worked" \
  --force
```

Check whether it is ready to run:

```bash
manageroo ready
```

Readiness is allowed to stop a run when the brief asks for a lane that is not
configured. Plain English version:

- If the brief asks for GBrain, memory, Obsidian, or prior decisions, map
  GBrain sources before the run starts.
- If the brief asks for PDFs, transcripts, screenshots, images, long prose, or
  exact wording, configure `document_analysis_command` first.
- If the repo only contains document/media files and the brief does not ask to
  use them, readiness prints `WARN` but does not block.
- If AUTOREVIEW or Clawpatch commands are configured, those commands own their
  findings and repairs. The AI must not freehand fixes from them.

More detail lives in `docs/DOCUMENT_LANE.md`,
`docs/REVIEW_REPAIR_LANES.md`, and `docs/EXTERNAL_INTEGRATIONS.md`.

If the repo has no detected verification command, let the tool add the first
detected repo-aware check without hand-editing TOML:

```bash
manageroo checks suggest --apply-first
manageroo checks list
```

If GBrain should know this repo, inspect first and map only the selected folder:

```bash
manageroo gbrain-setup
manageroo gbrain-setup --source-id my-product --path "$PWD" --apply --sync
```

Run the default build flow:

```bash
manageroo run --apply
```

For already-broken code:

```bash
manageroo run --mode repair --apply
```

Before a real release, run the final operator gate:

```bash
manageroo release-ready \
  --target "Production deploy path" \
  --rollback "Rollback steps" \
  --approved-by "Your name"
```

It does not deploy. It blocks until readiness is green, the latest completed
Manageroo run is proven, review is approved, the final report and patch exist,
the patch is applied to source, checks pass, Git is clean, and the release
target, rollback plan, and human approval are recorded. It also writes
`.manageroo/cache/production-handoff.md` so the operator gets one plain-English
release summary: current commit, latest changed files, Manageroo run ID, final
report, final patch, review status, proof commands, blockers, ship target,
rollback plan, and next action. On a ready release, it appends the shipped
target, Manageroo run ID, and passing proof to `.manageroo/PROJECT-MEMORY.md`;
commit that memory update if you want it tracked.

## Use a Loop Library loop

Matthew Berman / Forward Future's Loop Library can be used as the source of a
job pattern:

```bash
manageroo loop-library search docs
manageroo loop-library show overnight-docs-sweep
manageroo loop-library profile overnight-docs-sweep
manageroo loop-library brief overnight-docs-sweep --output .manageroo/PRODUCT-BRIEF.md --force
```

MANAGEROO reads the catalog and turns the selected loop into a repo-local
brief. It also caches the catalog for offline fallback and can print a structured
controller profile for a loop. That profile calls out whether the pattern is a
`goal`, `loop`, or `routine`, then adds budget/caps, verifier, anti-spin, and
completion-contract fields. Loop Library itself is not installed unless the
operator separately asks for that exact tool.

## Uninstall

Print the plan first:

```bash
manageroo uninstall-plan
```

The plan does not delete anything. It names the core files and reminds you that
third-party tools are separate.

```bash
rm -rf "$HOME/.local/share/manageroo"
rm -f "$HOME/.local/bin/manageroo" "$HOME/.local/bin/manageroo.cmd"
```

If the launcher or recommended skill pack gets damaged, run:

```bash
manageroo repair-install --no-apply
manageroo repair-install
```


## Source checkout versus release archive

A GitHub checkout and an extracted release archive use the same installer. The GitHub repository is the source of truth; a release archive is a versioned convenience copy for end users.
