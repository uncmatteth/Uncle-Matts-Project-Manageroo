# Dependency policy

## Required

- Python 3.11+
- Git
- A Git-backed target repository for real product runs
- One AI IDE, CLI agent, or configured runtime for live coding-agent operation
- At least one deterministic verification gate for completion claims
- GBrain with an exact source mapping for the target repository
- GitNexus
- An existing Obsidian Markdown vault/export folder
- TruffleHog for AUTOREVIEW
- AUTOREVIEW
- Clawpatch

## Required local stack

- GBrain
- GitNexus
- Obsidian
- TruffleHog
- AUTOREVIEW
- Clawpatch

These systems stay external to the thin controller, but normal product runs
require their configured lanes. A missing, unhealthy, unscoped, or failed lane
blocks the run. The deterministic `mock` adapter is the test harness and does
not turn third-party commands into unit-test dependencies.

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
- Bun or Node except when the selected external stack installation needs them

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

Existing different host-owned skill files are reused in place and are not
overwritten or copied into a backup trail. Manageroo records ownership only for
trees it creates; later updates replace only an unchanged owned tree. A user edit
is preserved and revokes Manageroo's removal/update claim for that tree.

## Required skill pack

Core install adds the Manageroo skill pack under `~/.agents/skills`. During
Manageroo runs, the controller
automatically chooses the right helper without the user remembering skill names;
compatible AI IDE agents can also use the installed metadata directly. A deliberately
minimal package/test installation may omit it, but a normal operator installation
must reconcile it before claiming the Manageroo workflow is ready.

- `uncle-matts-project-manageroo`
  for controller routing.
- `pimp-my-prompt` for rough request intake and reusable prompt cleanup.
- `brain-ops` and `query` for GBrain-backed memory lookup.
- `ingest`, `idea-ingest`, `media-ingest`, and `voice-note-ingest` for source
  capture.
- `article-enrichment`, `book-mirror`, and `strategic-reading` for long prose.
- `pdf`, `brain-pdf`, `citation-fixer`, `reports`, and
  `exact-text-replacement` for PDF work, citations, reports, and exact wording.
- `writing-for-agents` for writing predictable skills and agent instruction files.
- `edit-skill` for keeping local skills short, clear, and non-duplicative.
- `skillify` for deciding whether a workflow deserves a skill and checking its proof.
- `diagnosing-bugs` for broken, flaky, confusing, or slow behavior.
- `tdd` for one behavior test at a time.
- `autoreview` for closeout code review before commit, release, or handoff.
- `plain-web-copy` for factual public copy.
- `fix-my-bad-website` for website and app-screen cleanup when the page looks generic.
- `caveman` for clean token reduction.
- `uncle-matts-caveman-curse` for token reduction with profanity when selected.

These are bundled files, not network dependencies. Existing different local
versions are reused without replacement. Manageroo-owned versions update only
while their recorded full-tree digest still matches. They are available even
when token mode is off.

The reviewed Matt Pocock subset, pinned source commit, dependency graph, side effects, and upgrade policy are documented in `docs/MATT_POCOCK_SKILLS.md`.

Copied skill folders can be curated locally with
`manageroo skills reconcile --source ~/Downloads/SKILLS --include-external
--apply`. This imports skill entrypoints plus their support files, backs up
same-name conflicts, reports duplicate names across scanned roots, and does not
fetch anything from the network. Later scans exclude Manageroo-generated backup
and staging directories so archived copies cannot become candidates or false duplicates.

## AUTOREVIEW and Clawpatch

The stack installer installs AUTOREVIEW from the canonical OpenClaw
`agent-skills` repository when it is missing. It checks both
`~/.agents/skills/autoreview` and `~/.codex/skills/autoreview` first. Because
AUTOREVIEW's preflight requires TruffleHog, Manageroo reuses an existing binary
or downloads the release-pinned official archive for the detected Linux,
macOS, or Windows architecture, verifies its pinned SHA-256 checksum, and
installs only the executable beside the Manageroo launcher. Existing copies
remain user-owned. Clawpatch
uses the upstream package install path, `pnpm add -g clawpatch`, runs
`clawpatch doctor`, checks Codex login status for Clawpatch's codex provider,
and records failures or missing package managers instead of claiming completion.

AUTOREVIEW and Clawpatch are required command-owned repair
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
