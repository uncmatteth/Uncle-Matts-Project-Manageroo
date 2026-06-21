# Start here

## The product

**Uncle Matt's Super Mega Forward Build Ultimate Remix All-Star Booty of Fire Edition** is a local CLI for making AI coding agents follow the job.

Run it with `umsmfburasbofe`.

The acronym is `UMSMFBURASBOFE` because this is incredibly super serious.

```text
You write what should be built or fixed.
The tool reads the repo and breaks the job up.
Independent map/review chunks can run in parallel.
Media and big prose files are recorded as metadata or summaries.
Your AI agent does the code work.
The tool runs checks and keeps the receipts.
Bad work goes back through review and repair.
```

## Install

```bash
./install.sh
```

Same installer, same behavior. Use `./install.sh` from a normal Unix-style
terminal, or `.\install.ps1` from PowerShell. Those are launchers, not separate
products.

Then:

```bash
umsmfburasbofe self-test
umsmfburasbofe token-mode status
umsmfburasbofe stack-status
```

Optional token modes:

```bash
umsmfburasbofe token-mode set caveman
umsmfburasbofe token-mode set curse
umsmfburasbofe token-mode set off
```

`caveman` is terse and clean. `curse` is terse and profane. Both are included.

## Initialize any product repository

```bash
cd /absolute/path/to/product
umsmfburasbofe init --agent codex
umsmfburasbofe doctor
```

Use `--agent codex` when this tool should launch Codex. Use `--agent generic`
for another CLI and configure `[agent].argv_template`.

If an AI IDE is already driving the work, it does not need a special adapter. It
can use the installed `umsmfburasbofe` command and the repo-local skill.

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
```

It creates no IDE-specific directory.
