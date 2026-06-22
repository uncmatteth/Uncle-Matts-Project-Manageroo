# Start here

## The product

**Uncle Matt's Super Mega Forward Build Ultimate Remix All-Star Booty of Fire Edition** is a local CLI for making AI coding agents follow the job.

Run it with `umsmfburasbofe`.

The acronym is `UMSMFBURASBOFE` because this is incredibly super serious.

```text
You write what should be built or fixed.
If the request is messy, $pimp-my-prompt can turn it into scope and proof.
Solo Operator Mode turns the ask into a brief and one next action.
Solo also writes an intent lock so long chats and handoffs can be audited.
The tool reads the repo and breaks the job up.
If configured, GBrain/GitNexus add memory and code-graph context.
Independent map/review chunks can run in parallel.
Media and big prose files are recorded in a document manifest and can use a
configured document/prose command lane.
Your AI agent does the code work.
The tool runs checks and keeps the receipts.
Bad work goes back through review and repair.
Compacted summaries must keep the intent lock intact.
If skills get bloated, $edit-skill trims duplicate and stale instructions.
If a painful workflow repeats, $write-a-skill and $skillify package it.
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
umsmfburasbofe skills list
umsmfburasbofe token-mode status
umsmfburasbofe stack-status
umsmfburasbofe projects --pick
```

Optional token modes:

```bash
umsmfburasbofe token-mode set caveman
umsmfburasbofe token-mode set curse
umsmfburasbofe token-mode set off
```

Token reduction is one feature with two styles. `caveman` is terse and clean.
`curse` is the same compression with appropriately placed profanity because
life is more fun that way.

Recommended skill pack:

```bash
umsmfburasbofe skills install
```

That installs the UMSMFBURASBOFE router skill plus helper lanes for rough
intake, memory lookup, source ingest, media/PDF work, long prose, exact wording,
debugging, test-first work, closeout review, public copy, website cleanup,
reusable skills, and token reduction under `~/.agents/skills`. The
installer offers this pack during normal install, defaults to yes, and lets you
skip it with `--skill-pack skip` or `--skip-skill-pack`. It is optional but
strongly suggested because agents can use the router skill to choose helpers
automatically.

Project init also handles the agent/context files. It writes managed blocks to
`AGENTS.md` and `CONTEXT.md` if they are missing, preserves existing content,
and points agents at `.umsmfburasbofe/PROJECT-MEMORY.md` and the current brief.

If you copied a skills folder from another computer, do not copy it whole over
your current skills. Scan first, then import only after reviewing the report:

```bash
umsmfburasbofe skills scan /home/Tommy/Downloads/SKILLS
umsmfburasbofe skills import /home/Tommy/Downloads/SKILLS --apply
```

## Start any product repository

When you do not want to remember paths, start with the read-only project picker:

```bash
umsmfburasbofe projects --pick
```

It scans common project folders, shows numbered Git repos, and prints the exact
next command for the one you choose.

Existing Git repository:

```bash
umsmfburasbofe solo /absolute/path/to/product
```

Brand-new missing or empty folder:

```bash
umsmfburasbofe solo /absolute/path/to/new-product \
  --create \
  --want "Describe what should be built first"
```

Bare `solo` is the main wizard. It asks what AI you are using, which repo to
use, what should be built or fixed, what must not break, what proof should pass,
and whether to check GBrain, GitNexus, Obsidian, or Loop Library. It writes the
brief, writes `.umsmfburasbofe/PROJECT-MEMORY.md`, and prints exactly one next
command.

It also writes:

```text
.umsmfburasbofe/intent/INTENT-LOCK.json
.umsmfburasbofe/intent/INTENT-LOCK.md
```

If an agent compacts the chat, summarizes the thread, or hands off to another
agent, audit that summary before relying on it:

```bash
umsmfburasbofe compact audit --summary SUMMARY.md
```

At any later point, use this when you just need to know the next move:

```bash
umsmfburasbofe next
```

It prints one command only: `solo` for setup/brief work, `checks suggest --apply-first`
when proof gates are missing, or `run` when the repo is ready.

`--create` initializes Git and creates the first small scaffold commit for a
missing or empty folder. It refuses non-empty non-Git folders and nested repos.

For a less blank start, add `--starter`:

```bash
umsmfburasbofe solo /absolute/path/to/new-site \
  --create \
  --starter static-site \
  --want "Build a simple product homepage"
```

Starter choices are `blank`, `static-site`, `python-cli`, and `docs-project`.
The non-blank starters include a small `python3 -m unittest discover` smoke
check so the first repo has a proof command.

Use lower-level `setup` only when you want to initialize the repo without
writing the product brief yet:

```bash
umsmfburasbofe setup
```

Use `--agent codex` when this tool should launch Codex. Use `umsmfburasbofe
agent list` to see built-in presets for other CLI agents. Use
`umsmfburasbofe agent preset generic` when you want to edit the command template
yourself.

Project memory is the short continuity file future agents should read first:

```bash
umsmfburasbofe memory show
umsmfburasbofe memory add --shipped "First useful release" --proof "Smoke test passed"
```

If an AI IDE is already driving the work, it does not need a special adapter. It
can use the installed `umsmfburasbofe` command and the repo-local skill.

Make the brief:

```bash
umsmfburasbofe brief \
  --want "Say exactly what you want built or fixed" \
  --outcome "The visible result that must be true" \
  --must-not "Anything the agent must not touch" \
  --proof "The check or demo that proves it worked" \
  --force
```

Check readiness:

```bash
umsmfburasbofe ready
umsmfburasbofe next
```

`ready` blocks when the brief explicitly asks for a missing lane. Document,
media, transcript, long-prose, or exact-wording requests need
`document_analysis_command`. GBrain/memory/prior-decision requests need mapped
GBrain sources. Passive document/media files in the repo show as `WARN`, not a
block.

If it says no checks are configured, ask for repo-aware suggestions:

```bash
umsmfburasbofe checks suggest --apply-first
umsmfburasbofe checks list
```

If GBrain should know this repo, map only this folder:

```bash
umsmfburasbofe gbrain-setup
umsmfburasbofe gbrain-setup --source-id my-product --path "$PWD" --apply --sync
```

Run:

```bash
umsmfburasbofe run --apply
```

For broken existing code:

```bash
umsmfburasbofe run --mode repair --apply
```

Before a real release:

```bash
umsmfburasbofe release-ready \
  --target "Production deploy path" \
  --rollback "Rollback steps" \
  --approved-by "Your name"
```

That does not deploy. It checks the release gate and writes the operator
handoff here:

```text
.umsmfburasbofe/cache/production-handoff.md
```

If the release gate is ready, it also updates `.umsmfburasbofe/PROJECT-MEMORY.md`
with what shipped and what proof passed. Commit that memory update if you want
future agents to see it from Git.

After any run, inspect proactive learning cards:

```bash
umsmfburasbofe learning list
umsmfburasbofe learning show CARD_ID
umsmfburasbofe learning apply CARD_ID --approve
```

Those cards are suggestions with run evidence. The tool may save the cards, but
it does not silently rewrite skills, config, docs, installer behavior, prompts,
checks, code, or project memory.

## What `umsmfburasbofe setup` changes

```text
.umsmfburasbofe/config.toml
.umsmfburasbofe/PRODUCT-BRIEF.md
.umsmfburasbofe/PROJECT-MEMORY.md
.umsmfburasbofe/ideas/
.agents/skills/uncle-matts-super-mega-forward-build-ultimate-remix-all-star-booty-of-fire-edition/SKILL.md
AGENTS.md managed block
```

It creates no IDE-specific directory.
