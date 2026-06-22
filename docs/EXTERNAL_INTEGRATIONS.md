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
`umsmfburasbofe ready` reports whether the selected CLI, brief, repo-local
project memory, and checks are ready before a run.

Official reference: https://developers.openai.com/codex/noninteractive

## OpenClaw

OpenClaw can call `umsmfburasbofe`, host the same skill, or act as the surface
where the work happens.

Official reference: https://docs.openclaw.ai/

License note: the OpenClaw core repository and official docs identify OpenClaw
as MIT licensed. That means the public code can be used under the MIT license
terms; it does not prove anything about private hiring, acquisition, sponsorship,
or compensation arrangements around the project or its creator. Treat those as
separate facts unless a primary source states the deal terms.

## GBrain

Memory lane. GBrain can provide useful past context, but current repo files
still win.

The guided installer offers two lanes:

- `--gbrain-lane local`: run this installer's local CLI path with
  `bun install -g github:garrytan/gbrain`, `gbrain init --pglite`, status
  probes, and source-mapping guidance.
- `--gbrain-lane official`: print Garry Tan/GBrain's upstream
  `INSTALL_FOR_AGENTS.md` protocol for an agent-supervised install. This lane
  is for the full setup: API-key questions, search-mode choice, source mapping,
  bundled skills, recurring jobs, and verification.

Default interactive installs ask. Non-interactive stack installs use the local
lane unless a lane is passed explicitly.

If GBrain already exists, the installer does not run a new init. It probes:

- `gbrain config show`
- `gbrain status --json --section sync`
- `gbrain doctor --json --fast`

That means a Postgres/Ollama setup is reported, not overwritten.

Source mapping is guided, not guessed:

```bash
umsmfburasbofe gbrain-setup
umsmfburasbofe gbrain-setup --source-id my-product --path "$PWD" --apply --sync
gbrain sources list
gbrain sources add YOUR_SOURCE_ID --path /absolute/path/to/folder
gbrain sync --source YOUR_SOURCE_ID --json --yes
gbrain status --json --section sync
```

When `gbrain_search_command` is configured in `.umsmfburasbofe/config.toml`,
`umsmfburasbofe run` asks GBrain for brief-related context during discovery and
feeds the successful output into planning. When `gbrain_capture_command` is
configured, the final report/result can be captured after a successful run.
Both are optional. If the command is missing, fails, or times out, the run
records that fact and continues through the normal controller path.

Project reference: https://github.com/garrytan/gbrain

## GitNexus

Code graph lane. GitNexus can help explain what code touches what.

The guided installer can run `npm install -g gitnexus` when npm is available.
Run `gitnexus setup` afterward when you want its MCP wiring.

Project reference: https://github.com/abhigyanpatwari/GitNexus

Review GitNexus licensing before commercial embedding.

When `gitnexus_analyze_command` or `gitnexus_query_command` is configured,
`run` records the output under
`.umsmfburasbofe/runs/<run-id>/artifacts/discovery/external-intelligence.json`
and includes passing context in the product, reuse, and planning prompts. Git
files and current command output still win if GitNexus is stale or unavailable.

## Obsidian

Human notes lane. The tool can use an Obsidian vault as Markdown. No Obsidian
plugin is required.

Official reference: https://obsidian.md/help/data-storage

## AUTOREVIEW and Clawpatch

Command-owned review and repair lanes. AUTOREVIEW and Clawpatch can be
configured as external commands, but their findings are not handed to the AI
agent as freehand fix instructions.

When `autoreview_command` or `clawpatch_command` is configured, UMSMFBURASBOFE
runs that argv exactly inside the isolated workspace, captures the output in
`review/external-review-repair.json`, scope-checks any edits, and blocks on a
nonzero exit, timeout, `HEAD` change, or out-of-scope edit. If either command
changes files successfully, deterministic gates run again before the internal
review continues.

If AUTOREVIEW or Clawpatch has a repair/apply mode, configure that exact command.
If the tool cannot repair its own finding, the run stops with the tool output.
The controller must not freehand fixes from AUTOREVIEW or Clawpatch findings.

See [`REVIEW_REPAIR_LANES.md`](REVIEW_REPAIR_LANES.md).

The guided installer installs AUTOREVIEW from `openclaw/agent-skills` into
`~/.agents/skills/autoreview` when missing. It first checks both
`~/.agents/skills/autoreview` and `~/.codex/skills/autoreview`, because either
location can be valid on a local agent setup.

It installs Clawpatch with `pnpm add -g clawpatch` when pnpm is available, or
installs pnpm through npm when possible. It then runs `clawpatch doctor` and
checks `codex login status` for Clawpatch's default codex provider. Use
`--clawpatch-codex-login run` if you want the installer to launch `codex login`
during the stack setup.

AUTOREVIEW reference: https://github.com/openclaw/agent-skills
Clawpatch reference: https://github.com/openclaw/clawpatch
GBrain official agent protocol: https://raw.githubusercontent.com/garrytan/gbrain/master/INSTALL_FOR_AGENTS.md

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

Bundled local skills are installed during core setup:

- `pimp-my-prompt`: converts a rough, frustrated, overloaded, or reusable
  request into clear scope, acceptance criteria, fallback behavior, and a
  runnable brief.
- `diagnose`: builds a fast failure loop before fixing broken, flaky, confusing,
  or slow behavior.
- `tdd`: keeps behavior changes test-first when proof should be executable.
- `autoreview`: gives the agent a closeout review lane before commit, release,
  or handoff.
- `plain-web-copy`: keeps public words factual and readable.
- `fix-my-bad-website`: keeps website work tied to the real product instead of
  generic AI layout patterns.
- `write-a-skill`: creates a concise local skill when a workflow keeps coming
  back and should not be rediscovered in every thread.
- `edit-skill`: cleans up local skills by removing duplicate rules, stale
  instructions, vague requirements, and AI slop while preserving the behavior
  that actually matters.
- `skillify`: checks whether a repeated feature, workflow, or local habit
  deserves to become a skill, then makes sure it has triggers and proof.

This is the small version of the long-thread workflow: let the agent keep
working across compaction, but turn repeated pain into reusable skills and keep
those skills tight enough that future threads start clean.

Codex's built-in `skill-creator` skill is also useful when it is present on a
developer machine. UMSMFBURASBOFE does not copy that system skill into the
public package; it ships its own smaller agent-neutral helpers instead.
