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
./install.sh --token-mode caveman
./install.sh --token-mode curse
./install.sh --skip-tests
```

Normal users should not need these.

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

UMSMFBURASBOFE can run configured AUTOREVIEW/Clawpatch commands as
command-owned lanes, but it does not ask the AI to freehand repairs from their
findings. See [`REVIEW_REPAIR_LANES.md`](REVIEW_REPAIR_LANES.md).

## Recommended skill pack

The installer offers these local skills under `~/.agents/skills`. The pack is
optional but strongly suggested because it lets AI IDE agents route the work
without making the user remember which skill to call. In a normal terminal, the
installer asks and defaults to yes. Non-interactive installs use the recommended
yes path. Skip it with `./install.sh --skill-pack skip` or
`./install.sh --skip-skill-pack`.

- `uncle-matts-super-mega-forward-build-ultimate-remix-all-star-booty-of-fire-edition`:
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
- `write-a-skill`: creates a concise reusable skill when a workflow keeps
  coming back.
- `edit-skill`: tightens existing skills by removing duplicate instructions,
  stale rules, vague wording, and AI slop.
- `skillify`: checks whether a repeated workflow deserves a skill, then makes
  sure it has triggers and proof.
- `diagnose`: builds a fast feedback loop before fixing bugs, flakes, crashes,
  or confusing failures.
- `tdd`: uses one behavior test at a time when code changes need proof.
- `autoreview`: runs the closeout review lane before commit, release, or
  handoff.
- `plain-web-copy`: keeps public copy factual, readable, and free of fake-live
  hype.
- `fix-my-bad-website`: helps agents make web pages feel like the actual
  product instead of generic AI output.
- `caveman`: token reduction in the clean style.
- `uncle-matts-caveman-curse`: the same token reduction with appropriately
  placed profanity when selected.

They are available even when token mode is off. Reinstall them later with:

```bash
umsmfburasbofe skills install
```

If you copied skills from another machine, scan before importing:

```bash
umsmfburasbofe skills scan /home/Tommy/Downloads/SKILLS
umsmfburasbofe skills import /home/Tommy/Downloads/SKILLS --apply
```

`scan` is read-only. `import --apply` copies only `SKILL.md` files into
`~/.agents/skills` and backs up different existing skills first. Use
`--limit 0` or `--json` when you want the full scan list.

## Validate

```bash
umsmfburasbofe --version
umsmfburasbofe banner --no-animation
umsmfburasbofe self-test
umsmfburasbofe skills list
umsmfburasbofe token-mode status
umsmfburasbofe stack-status
umsmfburasbofe repair-install --no-apply
```

## Token reduction

Token reduction is one feature with two styles. The package includes both skill
files so you can switch later, but only the selected mode is active:

- `caveman`: terse, clean output.
- `uncle-matts-caveman-curse`: terse output plus profanity, because life is
  more fun with appropriately placed, well-used profanity.

Switch later:

```bash
umsmfburasbofe token-mode set off
umsmfburasbofe token-mode set caveman
umsmfburasbofe token-mode set curse
```

If a different local `SKILL.md` already exists for one of those names, the tool
backs it up before installing the bundled copy.

## Start a product project

For an existing Git repository:

```bash
cd /absolute/path/to/product
umsmfburasbofe solo
```

For a brand-new missing or empty folder:

```bash
umsmfburasbofe solo /absolute/path/to/new-product \
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

It writes `.umsmfburasbofe/PRODUCT-BRIEF.md`, writes
`.umsmfburasbofe/PROJECT-MEMORY.md`, writes or updates managed `AGENTS.md` and
`CONTEXT.md` guidance blocks, checks readiness, and prints exactly one next
command. Existing human content in those files is preserved. If every required
check is already ready during that first
command, you can combine intake and execution:

```bash
umsmfburasbofe solo --want "Describe the result" --run --apply --force
```

When you are unsure where the project is in the path, ask for one next action:

```bash
umsmfburasbofe next
```

It prints the stage, the reason, and one command to run next.

Lower-level setup is still available when you want only repo initialization:

```bash
umsmfburasbofe setup
```

Use `--agent codex` only when this tool should launch Codex itself. Use
`umsmfburasbofe agent list` to see built-in agent presets:

Use project memory to keep future runs from forgetting what matters:

```bash
umsmfburasbofe memory show
umsmfburasbofe memory add --must-not "Do not remove the import flow"
```

```bash
umsmfburasbofe agent list
umsmfburasbofe agent preset gemini
umsmfburasbofe agent preset generic
```

The non-Codex presets are command templates. If your CLI needs different flags,
edit `[agent].argv_template` in `.umsmfburasbofe/config.toml`.

If an AI IDE can read the repo and run commands, it does not need a special
vendor build. Give it the installed command plus the repo-local skill.

No IDE-specific directory is created.

For a brand-new product, `solo --create` can start from a small starter instead
of a blank repo:

```bash
umsmfburasbofe solo /absolute/path/to/new-site \
  --create \
  --starter static-site \
  --want "Build a simple product homepage"
```

Starter choices are `blank`, `static-site`, `python-cli`, and `docs-project`.
The non-blank starters include no-dependency unittest smoke checks.

Create a normal-language brief:

```bash
umsmfburasbofe brief \
  --want "Say exactly what should be built or fixed" \
  --outcome "The result that must be true" \
  --must-not "Anything the agent must not touch" \
  --proof "The check or demo that proves it worked" \
  --force
```

Check whether it is ready to run:

```bash
umsmfburasbofe ready
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
umsmfburasbofe checks suggest --apply-first
umsmfburasbofe checks list
```

If GBrain should know this repo, inspect first and map only the selected folder:

```bash
umsmfburasbofe gbrain-setup
umsmfburasbofe gbrain-setup --source-id my-product --path "$PWD" --apply --sync
```

Run the default build flow:

```bash
umsmfburasbofe run --apply
```

For already-broken code:

```bash
umsmfburasbofe run --mode repair --apply
```

Before a real release, run the final operator gate:

```bash
umsmfburasbofe release-ready \
  --target "Production deploy path" \
  --rollback "Rollback steps" \
  --approved-by "Your name"
```

It does not deploy. It blocks until readiness is green, checks pass, Git is
clean, and the release target, rollback plan, and human approval are recorded.
It also writes `.umsmfburasbofe/cache/production-handoff.md` so the operator
gets one plain-English release summary: current commit, latest changed files,
proof commands, blockers, ship target, rollback plan, and next action. On a
ready release, it appends the shipped target and passing proof to
`.umsmfburasbofe/PROJECT-MEMORY.md`; commit that memory update if you want it
tracked.

## Use a Loop Library loop

Matthew Berman / Forward Future's Loop Library can be used as the source of a
job pattern:

```bash
umsmfburasbofe loop-library search docs
umsmfburasbofe loop-library show overnight-docs-sweep
umsmfburasbofe loop-library profile overnight-docs-sweep
umsmfburasbofe loop-library brief overnight-docs-sweep --output .umsmfburasbofe/PRODUCT-BRIEF.md --force
```

UMSMFBURASBOFE reads the catalog and turns the selected loop into a repo-local
brief. It also caches the catalog for offline fallback and can print a structured
controller profile for a loop. That profile calls out whether the pattern is a
`goal`, `loop`, or `routine`, then adds budget/caps, verifier, anti-spin, and
completion-contract fields. Loop Library itself is not installed unless the
operator separately asks for that exact tool.

## Uninstall

Print the plan first:

```bash
umsmfburasbofe uninstall-plan
```

The plan does not delete anything. It names the core files and reminds you that
third-party tools are separate.

```bash
rm -rf "$HOME/.local/share/umsmfburasbofe"
rm -f "$HOME/.local/bin/umsmfburasbofe" "$HOME/.local/bin/umsmfburasbofe.cmd"
```

If the launcher or recommended skill pack gets damaged, run:

```bash
umsmfburasbofe repair-install --no-apply
umsmfburasbofe repair-install
```


## Source checkout versus release archive

A GitHub checkout and an extracted release archive use the same installer. The GitHub repository is the source of truth; a release archive is a versioned convenience copy for end users.
