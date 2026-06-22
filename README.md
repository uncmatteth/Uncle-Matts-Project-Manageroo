# Uncle Matt's Super Mega Forward Build Ultimate Remix All-Star Booty of Fire Edition

Use `umsmfburasbofe` at the terminal. The name is incredibly super serious.

This is a local tool for putting an actual process around AI coding agents.
The main path is **Solo Operator Mode**: one technically minded person uses AI
coding tools like a product team in a box.

Give it a Git repo, or let it create a new empty one. Then give it a
plain-English brief and real checks. It helps the agent read the project, make
a plan, work in smaller pieces, run the checks, review the result, repair the
bad parts, and leave a report you can inspect.

The whole point is to stop the usual AI coding mess: one giant chat, too much
context, half-remembered requirements, surprise file changes, and a confident
"done" with no proof.

## GitHub description

Copy this into the GitHub repository description:

```text
A very serious local CLI that keeps AI coding agents on task: one brief in, repo-aware build or repair work, checks, review, and proof out.
```

## Explain It Like I Am Five

- You have an app, website, script, or repo.
- If you have nothing yet, `umsmfburasbofe solo --create` can make the first
  empty Git project for you.
- You want an AI coding agent to work on it without wandering off.
- You do not want to hire a whole team just to get from idea to releaseable product.
- `umsmfburasbofe solo` is the front door: explain the job, get a brief,
  readiness check, and one next action.
- You write what you want in normal language.
- If the request is messy, angry, long, or half-formed, the bundled
  `pimp-my-prompt` skill helps turn it into exact scope, proof, and stop rules
  without losing what you meant.
- `umsmfburasbofe` reads the repo and breaks the job into smaller chunks.
- If GBrain or GitNexus commands are configured, it asks them for useful memory
  or code-graph context during discovery and records what worked or failed.
- Independent map and review chunks can run in parallel; actual code changes stay dependency ordered.
- Pictures, PDFs, and big prose files are not invisible. The tool records media metadata and bounded prose summaries so the agent knows they exist and can ask for the right slice.
- Most UMSMFBURASBOFE work is a `goal`: keep going until a verifiable outcome is true, then stop.
- A `loop` repeats while you are present. A `routine` runs later or on a schedule. UMSMFBURASBOFE can adapt those ideas into one bounded local repo run; it does not pretend to be a cloud scheduler.
- Your AI tool does the code work.
- `umsmfburasbofe` runs the checks you told it to run: tests, lint, typecheck, build, or whatever your repo actually uses.
- A separate review pass looks for problems before the run gets called done.
- If the work is not good enough, it goes back through repair.
- You get the patch, the checks, the review notes, and the report.
- The installer also includes `edit-skill`, a helper for keeping local skills
  short, non-duplicative, and free of stale AI junk.
- It also includes `write-a-skill` and `skillify`, so repeated painful work can
  become a small reusable skill instead of another giant thread.
- Optional token-reduction modes are included: clean `caveman` or profane `curse`.
- The installer should be simple for normal users, but still fun: color, ASCII art, and generated chiptune music.

## What Problem It Solves

AI coding agents are useful. They also drift.

- They forget parts of the request.
- They touch files they did not need to touch.
- They miss the test that would have caught the bug.
- They treat "looks plausible" like "works."
- They leave you digging through a chat transcript to figure out what happened.

This tool is meant to make that harder. It keeps the work tied to the repo, the
brief, the checks, the review, and the final evidence.

The idea came from the thing Clawpatch gets right: AI agents work better when
they look at one real slice of the product at a time, with the right files and
some proof. UMSMFBURASBOFE uses that same kind of structure for build and repair
work, not only bug review.

Credit where it is due: Matthew Berman / Forward Future's Loop Library and the
larger loop-engineering discussion helped name the pattern clearly. Good agent
work needs a bounded action, an independent verifier, a budget, a stop
condition, and evidence. UMSMFBURASBOFE applies that goal-style loop idea to
local build and repair runs.

## Special Thanks: The UMSMFBURASBOFE Super Team

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

```text
ONE PLAIN-ENGLISH BRIEF
      ↓
REPO MAP
      ↓
SMALL JOBS FOR THE AI AGENT
      ↓
CHECKS + REVIEW
      ↓
REPAIR IF NEEDED
      ↓
PATCH + REPORT + EVIDENCE
```

UMSMFBURASBOFE is not trying to replace your AI tool, your IDE, GBrain,
GitNexus, Obsidian, AUTOREVIEW, Clawpatch, CI, or your own judgment. It is the
local command that makes those pieces follow a job instead of becoming one more
pile of loose chat.

## Solo Operator Mode

The intended user is a technically minded non-coder who can explain what should
exist, make product decisions, and judge proof, but does not want the headache
of managing a software team.

Start here:

```bash
cd /absolute/path/to/your/git-project
umsmfburasbofe solo
```

Starting from an empty or missing folder:

```bash
umsmfburasbofe solo /absolute/path/to/new-product \
  --create \
  --want "Build a simple first release checklist"
```

Or pass the first ask directly:

```bash
umsmfburasbofe solo \
  --want "Make checkout less confusing" \
  --outcome "One clear payment path" \
  --must-not "Do not change admin exports" \
  --proof "Run checkout tests" \
  --force
```

`solo` prepares the project, writes the product brief, checks readiness, and
prints exactly one next command. If readiness is already green during the first
intake command, add `--run --apply` to let it start the build or repair run.

If the repo has no detected tests or build checks, add one real command without
editing config by hand:

```bash
umsmfburasbofe checks add smoke -- npm test
umsmfburasbofe checks list
umsmfburasbofe ready
```

The full target path is:

```text
idea -> brief -> setup -> build/repair -> checks -> review -> repair -> report -> release readiness
```

See [`docs/SOLO_OPERATOR_MODE.md`](docs/SOLO_OPERATOR_MODE.md).

## Choose the correct package

- **GitHub source repository:** the checked-out source tree is what gets committed to GitHub. If you seed it from a ZIP, extract the ZIP first and commit the files, not the ZIP file itself.
- **End-user release archive:** the generated release ZIP and checksum file go on a GitHub Release. Normal users download that ZIP, extract it, and run the installer.

See [`PUBLISH_TO_GITHUB.md`](PUBLISH_TO_GITHUB.md).

## Install from an extracted release archive

```bash
unzip UMSMFBURASBOFE-End-User-Release-v2026.6.20.1.zip
cd Uncle-Matts-Super-Mega-Forward-Build-Ultimate-Remix-All-Star-Booty-of-Fire-Edition
./install.sh
```

Same installer, same behavior. Use `./install.sh` from a normal Unix-style
terminal, or `.\install.ps1` from PowerShell. Those are launchers, not separate
products.

The installer validates the source, runs the tests, installs the command for the
current user, installs bundled helper skills, runs `self-test`, and writes
`install-lock.json`. It does not require Codex. Use `./install.sh
--install-codex` only when you specifically want this machine to install or
update Codex too.

The bundled helper skills are installed under `~/.agents/skills`:

- `pimp-my-prompt`: turns a rough request into exact scope, acceptance criteria,
  fallback rules, and a product brief shape.
- `edit-skill`: tightens skill files by removing duplicate rules, stale
  instructions, vague wording, and AI slop.
- `write-a-skill`: creates a concise reusable skill when a workflow keeps
  coming back.
- `skillify`: checks whether a feature or repeated habit deserves to become a
  proper skill, then makes sure there is proof.

The installer also offers the recommended local stack:

- GBrain for memory.
- GitNexus for code graph context.
- AUTOREVIEW for independent review passes.
- Clawpatch for feature-slice review and explicit fix loops.
- Obsidian for human-readable notes.
- Matthew Berman / Forward Future's Loop Library skill for published agent loops.

Interactive installs ask before touching those third-party tools. To force the
guided stack lane:

```bash
./install.sh --install-stack --loop-library-agent codex
```

If Bun, Node/npm/npx/pnpm, Flatpak, Snap, Homebrew, or Winget is missing, the
installer records the missing piece and prints the exact next commands instead
of pretending it finished that part.

If GBrain already exists, the stack lane inspects it instead of blindly running
`gbrain init --pglite` over an existing Postgres/Ollama setup. It records the
engine, embedding model, schema pack, source count, and embedding coverage, then
prints source-mapping commands only when sources are missing.

After install, inspect what happened:

```bash
umsmfburasbofe stack-status
umsmfburasbofe uninstall-plan
umsmfburasbofe repair-install --no-apply
```

Disable terminal presentation only when needed:

```bash
./install.sh --no-music --no-animation
```

Choose token-reduction mode during install:

```bash
./install.sh --token-mode caveman
./install.sh --token-mode curse
./install.sh --token-mode off
```

`caveman` is clean compressed output. `curse` is Uncle Matt's Caveman Curse:
compressed output with profanity for people who want the funny version. Code,
commands, JSON keys, exact errors, and quoted source stay clean unless you ask
for profanity there.

## One-line installation after the GitHub repository exists

Replace the repository visibility as desired before sharing these commands.

```bash
git clone --depth 1 https://github.com/uncmatteth/Uncle-Matts-Super-Mega-Forward-Build-Ultimate-Remix-All-Star-Booty-of-Fire-Edition.git && cd Uncle-Matts-Super-Mega-Forward-Build-Ultimate-Remix-All-Star-Booty-of-Fire-Edition && ./install.sh
```

## First local use

```bash
umsmfburasbofe --version
umsmfburasbofe self-test
umsmfburasbofe skills list
umsmfburasbofe token-mode status
cd /absolute/path/to/your/git-project
umsmfburasbofe solo
```

Lower-level commands are still available when you want them:

```bash
umsmfburasbofe setup
```

Run bare `setup` for the lower-level wizard. It asks:

- what AI you are using;
- what repo you want to work on;
- whether you want GBrain, GitNexus, Obsidian, or Loop Library help.

Use `--agent codex` when this tool should launch Codex itself. Use another
preset when the agent CLI is already installed and you do not want the prompt:

```bash
umsmfburasbofe agent list
umsmfburasbofe setup --agent gemini
umsmfburasbofe agent preset generic
```

The `generic`, `gemini`, and `claude-code` presets are command templates. They
are useful starters, not separate vendor products. If your CLI needs different
flags, edit `[agent].argv_template` in `.umsmfburasbofe/config.toml`.

If you are using an AI IDE or another agent shell, it does not need a special
build of this thing. If it can read files and run commands in the repo, it can
use `umsmfburasbofe`.

Switch token-reduction mode later:

```bash
umsmfburasbofe token-mode set off
umsmfburasbofe token-mode set caveman
umsmfburasbofe token-mode set curse
```

The switch command installs the bundled `caveman` and
`uncle-matts-caveman-curse` skills under `~/.agents/skills` when needed. If a
different local skill file already exists there, it is backed up before the
bundled copy is installed.

Reinstall the always-on helper skills later if needed:

```bash
umsmfburasbofe skills install
```

Then a compatible agent can call `$pimp-my-prompt`, `$write-a-skill`,
`$edit-skill`, or `$skillify` directly. The intended workflow is long-running
agent threads with compaction, plus small skills that get created and tightened
instead of growing forever.

Make the first brief without hand-editing the template:

```bash
umsmfburasbofe brief \
  --want "Make checkout less confusing without breaking admin exports." \
  --outcome "One clear payment path" \
  --must-not "Do not change admin order export" \
  --proof "Run checkout tests" \
  --force
```

Then check the whole setup:

```bash
umsmfburasbofe ready
```

If readiness says no checks are configured, add the simplest real proof command
for that repo:

```bash
umsmfburasbofe checks add smoke -- npm test
```

If you want GBrain memory mapped for this repo, inspect first and add only the
folder you choose. Run bare `gbrain-setup` for the prompt, or pass everything
explicitly:

```bash
umsmfburasbofe gbrain-setup
umsmfburasbofe gbrain-setup --source-id my-product --path "$PWD" --apply --sync
```

If you want `run` to use your memory or code graph, wire the commands in
`.umsmfburasbofe/config.toml`. Empty arrays mean off. Failed optional tools are
recorded, but they do not block the normal controller path:

```toml
[integrations]
gbrain_search_command = ["gbrain", "search", "{query}", "--json"]
gbrain_capture_command = ["gbrain", "capture", "--file", "{report_file}"]
gitnexus_analyze_command = ["gitnexus", "analyze", "{repo}", "--json"]
gitnexus_query_command = ["gitnexus", "query", "{query}", "--json"]
```

If the local command gets broken after install, inspect or repair it:

```bash
umsmfburasbofe repair-install --no-apply
umsmfburasbofe repair-install
```

Use Matthew Berman / Forward Future's Loop Library directly when a published
loop is the right shape for the job:

```bash
umsmfburasbofe loop-library search docs
umsmfburasbofe loop-library show overnight-docs-sweep
umsmfburasbofe loop-library profile overnight-docs-sweep
umsmfburasbofe loop-library brief overnight-docs-sweep --output .umsmfburasbofe/PRODUCT-BRIEF.md --force
```

That reads the live catalog, credits the source loop, and turns it into a
repo-local UMSMFBURASBOFE brief with a controller profile. The profile labels
the pattern as `goal`, `loop`, or `routine`, adds budget and anti-spin stops,
and states the verifier rule: the worker does not grade itself. The catalog is
cached for offline fallback. It does not install Loop Library or make it a
required dependency.

Run the build:

```bash
umsmfburasbofe run --apply
```

For already-broken code:

```bash
umsmfburasbofe run --mode repair --apply
```

`run` defaults to the current repo, `.umsmfburasbofe/PRODUCT-BRIEF.md`, and
`build` mode. You can still pass `--repo`, `--brief`, and `--mode` explicitly
when scripting.

## Context-window control

Each role gets a fresh packet with the files and instructions for that job. The
tool does not trust the chat to remember everything. It stores state on disk,
records hashes and line ranges, tracks omitted files, refuses silent truncation,
uses generated summaries for media and oversized prose when explicitly requested,
and rejects stale packets.

Unchanged file/media/prose summaries are cached under:

```text
.umsmfburasbofe/cache/file-summaries.json
.umsmfburasbofe/cache/system-map.json
```

The cache is keyed by file path, size, and SHA-256. If a file changes, its
summary is regenerated. If it does not change, the next run reuses the summary
instead of doing that work again. The system-map cache is stricter: it reuses
the repo map only when the inventory fingerprint and product brief hash match
exactly.

Configured GBrain and GitNexus commands are treated as optional context, not as
the source of truth. Passing output is included in the planning prompts. Missing
or failing tools are written to
`.umsmfburasbofe/runs/<run-id>/artifacts/discovery/external-intelligence.json`
so you can see exactly what happened.

See [`docs/CONTEXT_COMPILER.md`](docs/CONTEXT_COMPILER.md).

## Intended Local Stack

This was built around the local agent stack you actually wanted:

- GBrain for durable memory.
- GitNexus for code graph and impact context.
- Obsidian for notes a human can read.
- AUTOREVIEW and Clawpatch for review and repair lanes.
- Matthew Berman / Forward Future's Loop Library as a reference for clear
  agent loops, checks, and stopping conditions.
- `pimp-my-prompt` for rough request intake.
- `write-a-skill` and `skillify` for turning repeated work into reusable skills.
- `edit-skill` for keeping skills short, specific, and useful.
- Any AI IDE or CLI agent that can read files and run commands in the repo.

Those tools do not need separate versions of this package. They use the same
installed command and the same repo-local skill.

## Current maturity

This is **alpha software**. The mock run and package tests are included.
Real use still depends on your target repo, your selected AI tool, and your real
checks. Do the first live run on a clone, branch, or disposable copy.

## Documentation

- [`LOCAL_SETUP.md`](LOCAL_SETUP.md)
- [`PUBLISH_TO_GITHUB.md`](PUBLISH_TO_GITHUB.md)
- [`docs/00_START_HERE.md`](docs/00_START_HERE.md)
- [`docs/SOLO_OPERATOR_MODE.md`](docs/SOLO_OPERATOR_MODE.md)
- [`docs/INSTALLATION.md`](docs/INSTALLATION.md)
- [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md)
- [`docs/CONTEXT_COMPILER.md`](docs/CONTEXT_COMPILER.md)
- [`docs/ENFORCEMENT_MATRIX.md`](docs/ENFORCEMENT_MATRIX.md)
- [`docs/OPERATOR_GUIDE.md`](docs/OPERATOR_GUIDE.md)
- [`docs/LIMITATIONS.md`](docs/LIMITATIONS.md)
- [`docs/CREDITS.md`](docs/CREDITS.md)
