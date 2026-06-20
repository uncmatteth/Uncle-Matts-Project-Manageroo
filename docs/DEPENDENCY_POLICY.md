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

These are first-class systems in the UMSMFBURASBOFE workflow. They are not installed silently because they touch local memory, code graph context, human notes, review output, and patch workflows that should be explicit on each machine.

## Agent surfaces

UMSMFBURASBOFE should not need a special build for each AI vendor. Any AI IDE or agent that can read the repo and run shell commands can use the installed `umsmfburasbofe` CLI and the repo-local skill.

When UMSMFBURASBOFE itself launches fresh role processes, it uses a configured runtime adapter:

- `codex` for the built-in Codex adapter.
- `generic` for any CLI that can be wired to the adapter contract and produce the required JSON artifacts.

No single AI product is the requirement.

## Not required

- Any particular IDE
- Codex specifically, unless the project config selects the Codex adapter
- Node, npm, Cargo, Go, Maven, Gradle, or other build tools unless the target repo's verification gates call them

The installer records selected external tools in `install-lock.json`. It installs Codex only when run with `--install-codex`.
