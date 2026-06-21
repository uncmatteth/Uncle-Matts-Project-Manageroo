# Uncle Matt's Super Mega Forward Build Ultimate Remix All-Star Booty of Fire Edition

Use `umsmfburasbofe` at the terminal. The name is incredibly super serious.

This is a local tool for putting an actual process around AI coding agents.

Give it a Git repo, a plain-English brief, and real checks. It helps the agent
read the project, make a plan, work in smaller pieces, run the checks, review
the result, repair the bad parts, and leave a report you can inspect.

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
- You want an AI coding agent to work on it without wandering off.
- You write what you want in normal language.
- `umsmfburasbofe` reads the repo and breaks the job into smaller chunks.
- Your AI tool does the code work.
- `umsmfburasbofe` runs the checks you told it to run: tests, lint, typecheck, build, or whatever your repo actually uses.
- A separate review pass looks for problems before the run gets called done.
- If the work is not good enough, it goes back through repair.
- You get the patch, the checks, the review notes, and the report.
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

Credit where it is due: Matthew Berman / Forward Future's Loop Library helped
name the bigger pattern clearly. Good agent work is a loop: a bounded action, a
real check, a stop condition, and evidence. UMSMFBURASBOFE applies that loop
idea to local build and repair runs.

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
current user, runs `self-test`, and writes `install-lock.json`. It does not
require Codex. Use `./install.sh --install-codex` only when you specifically
want this machine to install or update Codex too.

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
umsmfburasbofe token-mode status
cd /absolute/path/to/your/git-project
umsmfburasbofe init --agent codex
umsmfburasbofe doctor
```

Use `--agent codex` when this tool should launch Codex itself. Use
`--agent generic` for another CLI, then set `[agent].argv_template` in
`.umsmfburasbofe/config.toml`.

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

Use Matthew Berman / Forward Future's Loop Library directly when a published
loop is the right shape for the job:

```bash
umsmfburasbofe loop-library search docs
umsmfburasbofe loop-library show overnight-docs-sweep
umsmfburasbofe loop-library brief overnight-docs-sweep --output .umsmfburasbofe/PRODUCT-BRIEF.md --force
```

That reads the live catalog, credits the source loop, and turns it into a
repo-local UMSMFBURASBOFE brief. It does not install Loop Library or make it a
required dependency.

Complete `.umsmfburasbofe/PRODUCT-BRIEF.md`, then run one of:

```bash
umsmfburasbofe run --repo . --mode build --brief .umsmfburasbofe/PRODUCT-BRIEF.md --apply
```

```bash
umsmfburasbofe run --repo . --mode repair --brief .umsmfburasbofe/PRODUCT-BRIEF.md --apply
```

## Context-window control

Each role gets a fresh packet with the files and instructions for that job. The
tool does not trust the chat to remember everything. It stores state on disk,
records hashes and line ranges, tracks omitted files, refuses silent truncation,
and rejects stale packets.

See [`docs/CONTEXT_COMPILER.md`](docs/CONTEXT_COMPILER.md).

## Intended Local Stack

This was built around the local agent stack you actually wanted:

- GBrain for durable memory.
- GitNexus for code graph and impact context.
- Obsidian for notes a human can read.
- AUTOREVIEW and Clawpatch for review and repair lanes.
- Matthew Berman / Forward Future's Loop Library as a reference for clear
  agent loops, checks, and stopping conditions.
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
- [`docs/INSTALLATION.md`](docs/INSTALLATION.md)
- [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md)
- [`docs/CONTEXT_COMPILER.md`](docs/CONTEXT_COMPILER.md)
- [`docs/ENFORCEMENT_MATRIX.md`](docs/ENFORCEMENT_MATRIX.md)
- [`docs/OPERATOR_GUIDE.md`](docs/OPERATOR_GUIDE.md)
- [`docs/LIMITATIONS.md`](docs/LIMITATIONS.md)
