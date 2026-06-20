# Uncle Matt's Super Mega Forward Build Ultimate Remix All-Star Booty of Fire Edition

**UMSMFBURASBOFE** is the acronym, the command, and the public name.

UMSMFBURASBOFE is a local command-line tool for people who use AI coding agents
on real software projects.

It is for build and repair work. You write what you want the product to do in
plain English. UMSMFBURASBOFE helps the agent read the repo, make a plan, work
in small pieces, run checks, review the result, repair problems, and leave a
clear report of what happened.

The point is simple: do not throw a whole repo into one giant chat and hope the
agent remembers everything. Give the agent the right files, the right job, and a
way to prove the work.

## GitHub description

Copy this into the GitHub repository description:

```text
A local command-line tool that helps AI coding agents build or repair a Git repo from one plain-English brief, with checks, review, and evidence.
```

## Explain It Like I Am Five

- You have an app, website, script, or repo.
- You want an AI coding agent to improve it without wandering all over the project.
- You write one plain-English brief saying what should be built or fixed.
- UMSMFBURASBOFE reads the repo and turns the request into smaller jobs.
- The AI agent works on those jobs.
- UMSMFBURASBOFE runs the checks you configured, such as tests, lint, typecheck, or build.
- A fresh review pass looks for problems before the work is called done.
- If something important is wrong, UMSMFBURASBOFE sends it back for repair.
- It saves the plan, patch, checks, review notes, and final report so the work is inspectable.
- The command is always `umsmfburasbofe`.
- The installer is meant to be simple, but still fun: color, ASCII art, and generated chiptune music.

## What Problem It Solves

- A normal AI chat can lose track of files, requirements, and proof.
- A giant repo dump gives the agent too much unrelated information.
- A tiny prompt gives the agent too little information to make good decisions.
- UMSMFBURASBOFE tries to give the agent the right slice of the repo for the job.
- It keeps planning, coding, review, repair, and final delivery as separate steps.
- It records what files were used, what checks ran, what changed, and what still needs human judgment.
- It is meant for local use first, on a Git-backed repo you control.

The idea came from the thing Clawpatch gets right: AI agents work better when
they review or fix one real feature at a time, with evidence, tests, and a clear
scope. UMSMFBURASBOFE uses that same kind of structure for build and repair
runs, not only bug review.

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

UMSMFBURASBOFE is not an IDE and not a replacement for GBrain, GitNexus,
Obsidian, AUTOREVIEW, Clawpatch, CI, or whatever AI agent you already use. It is
the local command those tools can work through so the job has a brief, a repo
map, a plan, checks, review, repair, and evidence before anyone says it is done.

## Choose the correct package

- **GitHub source repository:** commit the source tree itself to GitHub. Do not upload the source ZIP as the repository contents without extracting it first.
- **End-user release archive:** attach the generated release ZIP and checksum file to a GitHub Release. End users download and extract that archive.

See [`PUBLISH_TO_GITHUB.md`](PUBLISH_TO_GITHUB.md).

## Install from an extracted release archive

```bash
unzip UMSMFBURASBOFE-End-User-Release-v2026.6.20.1.zip
cd Uncle-Matts-Super-Mega-Forward-Build-Ultimate-Remix-All-Star-Booty-of-Fire-Edition
./install.sh
```

PowerShell users can run `.\install.ps1`; it starts the same installer.

The installer validates the source, runs the test suite, installs UMSMFBURASBOFE under the current user's local application directory, creates the `umsmfburasbofe` launcher, runs the deterministic self-test, and writes an `install-lock.json` record. It does not require Codex. Use `./install.sh --install-codex` only when Codex is the adapter you want this machine to use.

Disable terminal presentation only when needed:

```bash
./install.sh --no-music --no-animation
```

## One-line installation after the GitHub repository exists

Replace the repository visibility as desired before sharing these commands.

```bash
git clone --depth 1 https://github.com/uncmatteth/Uncle-Matts-Super-Mega-Forward-Build-Ultimate-Remix-All-Star-Booty-of-Fire-Edition.git && cd Uncle-Matts-Super-Mega-Forward-Build-Ultimate-Remix-All-Star-Booty-of-Fire-Edition && ./install.sh
```

## First local use

```bash
umsmfburasbofe --version
umsmfburasbofe self-test
cd /absolute/path/to/your/git-project
umsmfburasbofe init --agent codex
umsmfburasbofe doctor
```

Use `--agent codex` for the Codex adapter. Use `--agent generic` when another CLI will run the agent roles; then set `[agent].argv_template` in `.umsmfburasbofe/config.toml`.

If you are using an AI IDE or another agent shell, it does not need a special UMSMFBURASBOFE build. Give it `GIVE-THIS-TO-YOUR-IDE-AGENT.md` or the repo-local skill created by `umsmfburasbofe init`, and it can drive the same controller commands.

Complete `.umsmfburasbofe/PRODUCT-BRIEF.md`, then run one of:

```bash
umsmfburasbofe run --repo . --mode build --brief .umsmfburasbofe/PRODUCT-BRIEF.md --apply
```

```bash
umsmfburasbofe run --repo . --mode repair --brief .umsmfburasbofe/PRODUCT-BRIEF.md --apply
```

## Context-window control

Each agent role receives a fresh context packet with the files and instructions
needed for that job. It does not rely on the previous chat staying perfect.
UMSMFBURASBOFE stores state on disk, records source hashes and line ranges,
tracks omitted files, refuses silent truncation, and rejects stale packets.

See [`docs/CONTEXT_COMPILER.md`](docs/CONTEXT_COMPILER.md).

## Intended Local Stack

UMSMFBURASBOFE was built around the local agent stack you described:

- GBrain for durable memory.
- GitNexus for code graph and impact context.
- Obsidian for notes a human can read.
- AUTOREVIEW and Clawpatch for review and repair lanes.
- Any AI IDE or CLI agent that can read files and run commands in the repo.

Those tools do not need separate UMSMFBURASBOFE versions. They use the same
installed command and the same repo-local skill.

## Current maturity

This is an **alpha source implementation**. The deterministic mock workflow and package tests are included. A real build requires a configured agent adapter, a Git-backed target repository, and valid verification commands for that repository. Review the limitations before using it on sensitive or production-critical software.

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
