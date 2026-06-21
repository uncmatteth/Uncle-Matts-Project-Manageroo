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
`umsmfburasbofe` CLI and the repo-local skill.

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

The package includes both bundled token modes:

- `caveman`
- `uncle-matts-caveman-curse`

They are local skill files, not network dependencies. The installer can select a
mode with `--token-mode caveman` or `--token-mode curse`. Users can switch later
with `umsmfburasbofe token-mode set ...`.

Existing different local skill files are backed up before the bundled files are
installed.

## Loop Library

UMSMFBURASBOFE can read Matthew Berman / Forward Future's live Loop Library
catalog and generate a local product brief from a selected loop. That is a
network read of public catalog data, not a package dependency. Installing the
Loop Library skill itself remains optional and must be requested separately.

## AUTOREVIEW and Clawpatch

The stack installer installs AUTOREVIEW from the canonical OpenClaw
`agent-skills` repository when it is missing. Clawpatch uses the upstream
package install path, `pnpm add -g clawpatch`, and records failures or missing
package managers instead of claiming completion.
