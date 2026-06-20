# Start here

## The product

**Uncle Matt's Super Mega Forward Build: Ultimate Remix All-Star Booty of Fire Edition** is the program manager around coding agents.

Short command: `umsmfburasbofe`.

Full funny acronym: `UMSMFBURASBOFE`.

```text
You define product behavior.
UMSMFBURASBOFE compiles and enforces delivery.
Codex or another adapter performs bounded coding roles.
Git and deterministic checks provide ground truth.
A fresh independent role reviews the result.
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
