# Dependency policy

## Required

- Python 3.11+
- Git
- A Git-backed target repository for real product runs
- One AI IDE, CLI agent, or configured runtime for live coding-agent operation
- At least one deterministic verification gate for completion claims

## Intended local stack

- GBrain
- GitNexus
- Obsidian
- AUTOREVIEW
- Clawpatch
- Loop Library catalog

These are the intended surrounding tools. Interactive installs ask before
installing or guiding them. Non-interactive installs skip them unless
`--install-stack` is passed.

## Agent surfaces

This should not need a special build for each AI vendor. Any AI IDE or agent
that can read the repo and run shell commands can use the installed
`manageroo` CLI and the repo-local skill.

When this tool launches fresh agent processes itself, it uses a configured
adapter:

- `codex` for the built-in Codex adapter.
- `generic` for any CLI that can be wired to the adapter contract and produce the required JSON artifacts.

No single AI product is the point.

## Not required

- Any particular IDE
- Codex specifically, unless the project config selects the Codex adapter
- Node, npm, Cargo, Go, Maven, Gradle, or other build tools unless the target repo's verification gates call them
- Bun or Node unless the user chooses the recommended stack lane

The installer records selected external tools in `install-lock.json`. It installs Codex only when run with `--install-codex`.

## Token-reduction skills

Token reduction is one feature with two styles. The package includes both
bundled skill files so the user can switch later, but only the selected mode is
active:

- `caveman`: clean style.
- `uncle-matts-caveman-curse`: curse style, because life is more fun with
  appropriately placed, well-used profanity.

They are local skill files, not network dependencies. The installer can select a
mode with `--token-mode caveman` or `--token-mode curse`. Users can switch later
with `manageroo token-mode set ...`.

Existing different local skill files are backed up before the bundled files are
installed.

## Recommended skill pack

Core install offers the recommended skill pack under `~/.agents/skills`. The
pack is optional but strongly suggested because it lets compatible AI IDE agents
choose the right helper without the user remembering skill names. The installer
defaults to installing it. Use `--skill-pack skip` or `--skip-skill-pack` to
leave it out and install it later with `manageroo skills reconcile --apply`.

- `uncle-matts-project-manageroo`
  for controller routing.
- `pimp-my-prompt` for rough request intake and reusable prompt cleanup.
- `brain-ops` and `query` for GBrain-backed memory lookup.
- `ingest`, `idea-ingest`, `media-ingest`, and `voice-note-ingest` for source
  capture.
- `article-enrichment`, `book-mirror`, and `strategic-reading` for long prose.
- `pdf`, `brain-pdf`, `citation-fixer`, `reports`, and
  `exact-text-replacement` for PDF work, citations, reports, and exact wording.
- `write-a-skill` for making a repeated workflow into a concise reusable skill.
- `edit-skill` for keeping local skills short, clear, and non-duplicative.
- `skillify` for deciding whether a workflow deserves a skill and checking its proof.
- `diagnose` for broken, flaky, confusing, or slow behavior.
- `tdd` for one behavior test at a time.
- `autoreview` for closeout code review before commit, release, or handoff.
- `plain-web-copy` for factual public copy.
- `fix-my-bad-website` for website and app-screen cleanup when the page looks generic.
- `caveman` for clean token reduction.
- `uncle-matts-caveman-curse` for token reduction with profanity when selected.

These are bundled files, not network dependencies. Existing different local
versions are backed up before replacement. They are available even when token
mode is off.

Copied skill folders can be curated locally with
`manageroo skills reconcile --source ~/Downloads/SKILLS --include-external
--apply`. This imports skill entrypoints plus their support files, backs up
same-name conflicts, reports duplicate names across scanned roots, and does not
fetch anything from the network.

## Loop Library

MANAGEROO can read Matthew Berman / Forward Future's live Loop Library
catalog, cache it locally for offline fallback, print a controller profile, and
generate a local product brief from a selected loop. That is a network read of
public catalog data, not a package dependency. Installing the Loop Library skill
itself remains optional and must be requested separately.

## AUTOREVIEW and Clawpatch

The stack installer installs AUTOREVIEW from the canonical OpenClaw
`agent-skills` repository when it is missing. It checks both
`~/.agents/skills/autoreview` and `~/.codex/skills/autoreview` first. Clawpatch
uses the upstream package install path, `pnpm add -g clawpatch`, runs
`clawpatch doctor`, checks Codex login status for Clawpatch's codex provider,
and records failures or missing package managers instead of claiming completion.

When configured for a run, AUTOREVIEW and Clawpatch are command-owned repair
lanes, not optional AI advice. MANAGEROO runs the configured command,
captures the result, scope-checks any edits, and blocks on command failure. The
AI repairer must not freehand fixes from AUTOREVIEW or Clawpatch findings.

## GBrain lanes

The installer exposes both GBrain paths instead of hiding the choice:

- `--gbrain-lane local`: the MANAGEROO local lane using Bun, PGLite init,
  status probes, and source-mapping commands.
- `--gbrain-lane official`: the upstream GBrain agent-supervised protocol at
  `INSTALL_FOR_AGENTS.md`.

The official lane is not compressed into a silent one-button guess because it
asks about API keys, search mode, source mapping, skills, recurring jobs, and
verification.
