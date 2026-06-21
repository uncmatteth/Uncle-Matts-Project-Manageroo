# Stack integrations

This was built for your local stack, not for one blessed AI vendor. These tools
are not random extras; they are the point of the setup.

## AI IDEs and CLI agents

Any AI IDE or agent that can read the repo and run shell commands can use the
same installed `umsmfburasbofe` command and repo-local skill. There should not
be a special build for every AI logo.

## Codex

Codex is one adapter. When selected, this tool can start fresh `codex exec`
processes and pass the repo path, sandbox mode, schema, and output path.
`umsmfburasbofe doctor` checks the installed CLI before a run.

Official reference: https://developers.openai.com/codex/noninteractive

## OpenClaw

OpenClaw can call `umsmfburasbofe`, host the same skill, or act as the surface
where the work happens.

Official reference: https://docs.openclaw.ai/

## GBrain

Memory lane. GBrain can provide useful past context, but current repo files
still win.

The guided installer can run `bun install -g github:garrytan/gbrain` and
`gbrain init --pglite` when GBrain is missing and Bun is available.

If GBrain already exists, the installer does not run a new init. It probes:

- `gbrain config show`
- `gbrain status --json --section sync`
- `gbrain doctor --json --fast`

That means a Postgres/Ollama setup is reported, not overwritten.

Source mapping is guided, not guessed:

```bash
gbrain sources list
gbrain sources add YOUR_SOURCE_ID --path /absolute/path/to/folder
gbrain sync --source YOUR_SOURCE_ID --json --yes
gbrain status --json --section sync
```

Project reference: https://github.com/garrytan/gbrain

## GitNexus

Code graph lane. GitNexus can help explain what code touches what.

The guided installer can run `npm install -g gitnexus` when npm is available.
Run `gitnexus setup` afterward when you want its MCP wiring.

Project reference: https://github.com/abhigyanpatwari/GitNexus

Review GitNexus licensing before commercial embedding.

## Obsidian

Human notes lane. The tool can use an Obsidian vault as Markdown. No Obsidian
plugin is required.

Official reference: https://obsidian.md/help/data-storage

## AUTOREVIEW and Clawpatch

Review and patch lanes. AUTOREVIEW and Clawpatch can be configured as external
commands. Their findings still have to point at real files and real evidence.

The guided installer installs AUTOREVIEW from `openclaw/agent-skills` into
`~/.agents/skills/autoreview` when missing. It first checks both
`~/.agents/skills/autoreview` and `~/.codex/skills/autoreview`, because either
location can be valid on a local agent setup.

It installs Clawpatch with `pnpm add -g clawpatch` when pnpm is available, or
installs pnpm through npm when possible.

AUTOREVIEW reference: https://github.com/openclaw/agent-skills
Clawpatch reference: https://github.com/openclaw/clawpatch

## Forward Future Loop Library

Credit to Matthew Berman / Forward Future's Loop Library for the plain-language
agent-loop framing. The useful distinction is simple:

- `goal`: keep working until a verifiable outcome is true, then stop.
- `loop`: repeat a bounded task while the operator is present.
- `routine`: run later or on a schedule outside this local controller.

UMSMFBURASBOFE is native goal-style local build/repair control. It can read the
live catalog and turn a selected Loop Library entry into a repo-local product
brief. The controller profile labels the entry as `goal`, `loop`, or `routine`
and adds the missing safety rails: budget/caps, independent verification,
anti-spin stops, completion contract, and evidence. It caches the catalog for
offline fallback and can print a controller profile for a loop:

```bash
umsmfburasbofe loop-library search docs
umsmfburasbofe loop-library profile overnight-docs-sweep
umsmfburasbofe loop-library brief overnight-docs-sweep --output .umsmfburasbofe/PRODUCT-BRIEF.md --force
```

It does not require Loop Library for normal use. The guided installer can also
install the Loop Library skill for selected agents, for example
`--install-stack --loop-library-agent codex`. Other skills-compatible agents can
be passed the same way.

Reference: https://signals.forwardfuture.ai/loop-library/

## Prompt and skill hygiene

Two bundled local skills are installed during core setup:

- `pimp-my-prompt`: converts a rough, frustrated, overloaded, or reusable
  request into clear scope, acceptance criteria, fallback behavior, and a
  runnable brief.
- `edit-skill`: cleans up local skills by removing duplicate rules, stale
  instructions, vague requirements, and AI slop while preserving the behavior
  that actually matters.

This is the small version of the long-thread workflow: let the agent keep
working across compaction, but keep the reusable skills tight enough that future
threads start clean.
