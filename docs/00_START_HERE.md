# Start here

## The product

**Uncle Matt's Super Mega Forward Build Ultimate Remix All-Star Booty of Fire Edition** is a local command-line tool for using AI coding agents on a Git repo.

Short command: `umsmfburasbofe`.

Full funny acronym: `UMSMFBURASBOFE`.

```text
You write what should be built or fixed.
UMSMFBURASBOFE reads the repo and makes smaller jobs.
An AI IDE, CLI agent, or configured runtime does the code work.
UMSMFBURASBOFE runs checks and keeps evidence.
A fresh review pass looks for problems before the run is called done.
```

## Install

```bash
./install.sh
```

PowerShell users can run `.\install.ps1`; it starts the same installer.

Then:

```bash
umsmfburasbofe self-test
```

## Initialize any product repository

```bash
cd /absolute/path/to/product
umsmfburasbofe init --agent codex
umsmfburasbofe doctor
```

Use `--agent codex` for Codex. Use `--agent generic` for another CLI and configure `[agent].argv_template`.

If an AI IDE is driving the work itself, it does not need a special adapter. It can use the installed `umsmfburasbofe` command and the repo-local skill.

Do not run a product build until `umsmfburasbofe doctor` reports `READY`.

Edit:

```text
.umsmfburasbofe/PRODUCT-BRIEF.md
```

Then:

```bash
umsmfburasbofe run --repo . --mode build --brief .umsmfburasbofe/PRODUCT-BRIEF.md --apply
```

For broken existing code, change `build` to `repair`.

## What `umsmfburasbofe init` changes

```text
.umsmfburasbofe/config.toml
.umsmfburasbofe/PRODUCT-BRIEF.md
.umsmfburasbofe/ideas/
.agents/skills/uncle-matts-super-mega-forward-build-ultimate-remix-all-star-booty-of-fire-edition/SKILL.md
AGENTS.md managed block
CLAUDE.md when absent
```

It creates no IDE-specific directory.
