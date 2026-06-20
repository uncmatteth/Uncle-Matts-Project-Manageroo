# Uncle Matt's Super Mega Forward Build
## Ultimate Remix All-Star Booty of Fire Edition

**UMSMFBURASBOFE** is the acronym, the command, and the public name.

By **bttlabs.fun**, this is a local control plane for coding agents. It gives
Codex a safer, more organized way to work on a real product repo.

## GitHub description

Copy this into the GitHub repository description:

```text
A local controller for Codex: turn one product brief into scoped agent work, tests, review, repair, and a final patch with evidence.
```

## Explain It Like I Am Five

- You have an app, website, script, or repo you want improved.
- You write one plain-English product brief.
- UMSMFBURASBOFE reads the repo and makes a plan before code changes.
- Codex does the coding work in small, bounded jobs.
- UMSMFBURASBOFE keeps Codex away from unrelated files.
- UMSMFBURASBOFE runs your real checks, such as tests, lint, typecheck, or build.
- UMSMFBURASBOFE asks a fresh review role to look for problems.
- If review finds a blocking problem, UMSMFBURASBOFE sends Codex back to repair it.
- UMSMFBURASBOFE writes a final patch, report, and evidence folder.
- Your original repo is changed only after the controller reaches `COMPLETE`.
- The fun installer has color, ASCII art, and generated chiptune music.
- The command is uniform everywhere: `umsmfburasbofe`.

## What Problem It Solves

- A normal AI chat can lose track of files, requirements, and proof.
- UMSMFBURASBOFE gives each agent role a fresh packet of only the context it needs.
- It records hashes, line ranges, omitted files, commands, and evidence.
- It separates planning, coding, review, repair, and delivery.
- It is meant for local use first, on a Git-backed repo you control.

```text
ONE REQUEST IN
      ↓
PRODUCT + REPOSITORY MAPPING
      ↓
REUSE RESEARCH + LOCKED PLAN
      ↓
BOUNDED CODING AGENTS
      ↓
TESTS + INDEPENDENT REVIEW + REPAIR
      ↓
WORKING PRODUCT + EVIDENCE OUT
```

UMSMFBURASBOFE is not an IDE and not a replacement for Codex. It launches coding agents, supplies bounded context, owns workflow state, rejects scope drift, runs deterministic verification, and decides whether a run may be marked complete.

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

The installer validates the source, runs the test suite, installs or updates Codex unless disabled, installs UMSMFBURASBOFE under the current user's local application directory, creates the `umsmfburasbofe` launcher, runs the deterministic self-test, and writes an `install-lock.json` record.

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

Complete `.umsmfburasbofe/PRODUCT-BRIEF.md`, then run one of:

```bash
umsmfburasbofe run --repo . --mode build --brief .umsmfburasbofe/PRODUCT-BRIEF.md --apply
```

```bash
umsmfburasbofe run --repo . --mode repair --brief .umsmfburasbofe/PRODUCT-BRIEF.md --apply
```

## Context-window control

Each agent role receives a fresh, bounded context packet rather than an entire repository or prior conversation. UMSMFBURASBOFE stores authoritative state on disk, records source hashes and line ranges, refuses silent truncation, partitions large repositories, reduces partial maps into a canonical system model, and rejects stale packets.

See [`docs/CONTEXT_COMPILER.md`](docs/CONTEXT_COMPILER.md).

## Minimal-sprawl policy

The core install contains UMSMFBURASBOFE and Codex. OpenClaw, GBrain, GitNexus, Clawpatch, AUTOREVIEW, Obsidian, and IDE integrations remain optional adapters rather than mandatory machine-wide dependencies.

## Current maturity

This is an **alpha source implementation**. The deterministic mock workflow and package tests are included. A real build requires an authenticated compatible Codex CLI, a Git-backed target repository, and valid verification commands for that repository. Review the limitations before using it on sensitive or production-critical software.

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
