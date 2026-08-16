# Dependency policy

Manageroo is a **portable core controller** with optional enhanced integrations. The
controller owns intent, repository binding, worker isolation, durable run truth,
verification, delivery, recovery, and completion authority. An external tool may add
evidence or a specialized lane, but it never becomes the authority for completion.

## Portable core requirements

A normal controlled coding run requires:

- Python 3.11 or newer;
- Git;
- a Git-backed target repository;
- one supported coding-agent adapter with a verified host filesystem boundary;
- at least one deterministic verification gate appropriate to the target project;
- Manageroo's own transactional workspace, evidence, review, delivery, and completion
  machinery.

The deterministic `mock` adapter is a test double. It proves controller behavior but is
not a live coding-agent runtime.

## Enhanced integration stack

The following lanes are **optional for ordinary portable-core runs**:

- GBrain for exact-repository durable knowledge;
- GitNexus for repository and code-graph intelligence;
- AUTOREVIEW for an additional command-owned review/repair lane;
- Clawpatch for an additional command-owned review/repair lane;
- Obsidian for Markdown context search and report export;
- TruffleHog when the selected AUTOREVIEW installation requires it.

When an enhanced lane is configured and healthy, Manageroo records and uses it. When it
is absent, the run records the lane as unavailable and continues with Manageroo's core
controller unless the current operation explicitly requires that capability.

A project or operation may explicitly require individual lanes through the authoritative
runtime capability contract. In that case, only the named missing or failed capability
blocks the run. Manageroo must not convert every real-agent run into a hidden full-stack
requirement.

## Exact source mapping

GBrain output is trusted only as external context. When GBrain is selected or explicitly
required, Manageroo requires an exact source mapping for the target repository, scopes
queries to that source, filters returned records to it, and binds capture to the same
source. A mapping for another repository is never substituted.

## Agent surfaces

Manageroo does not require a special build for each AI vendor. Any AI IDE or agent that
can run the installed CLI can use the controller-facing workflow. When Manageroo launches
workers itself, it uses a configured adapter:

- `codex` for the built-in Codex adapter;
- `generic` for a CLI wired to the structured output contract and independently isolated
  from the host filesystem;
- `mock` only for deterministic tests.

A provider approval flag is not equivalent to a host filesystem boundary. Manageroo
refuses a live worker that lacks verified isolation.

## Target-project tools

Node, npm, pnpm, Bun, Cargo, Go, Maven, Gradle, databases, browsers, or other build tools
are required only when:

- the target repository's deterministic gates call them; or
- the operator selects an enhanced integration whose installer/runtime needs them.

Codex is required only when the project selects the Codex adapter. The installer records
selected external tools and their provenance in `install-lock.json`.

## Skill pack

A normal operator installation reconciles Manageroo's bundled core skill pack under
`~/.agents/skills`. The controller automatically routes relevant helper instructions; the
operator does not need to remember skill names.

Bundled skills are files, not network runtime dependencies. Existing host-owned versions
are reused rather than overwritten. Manageroo updates or removes only trees it created
and whose recorded digest still matches. User edits revoke Manageroo's ownership claim.

The pack includes controller routing, prompt cleanup, ingestion, document and exact-text
workflows, diagnostics, test-driven development, reporting, web-copy, interface cleanup,
and token-reduction styles. The reviewed Matt Pocock subset and its pinned provenance are
documented in `docs/MATT_POCOCK_SKILLS.md`.

Copied skill folders can be curated locally with:

```bash
manageroo skills reconcile --source ~/Downloads/SKILLS --include-external --apply
```

The command remains local, reports duplicate names, preserves conflicts, and does not
fetch arbitrary skills from the network.

## AUTOREVIEW, Clawpatch, and TruffleHog

AUTOREVIEW and Clawpatch are enhanced **command-owned** lanes, not freehand AI prompts.
When configured, Manageroo runs each command from a clean controller checkpoint, captures
its result, scope-checks its edits, rejects Git-history changes, and rolls back a failed or
out-of-scope lane before continuing. Their findings are not copied into an unrestricted AI
repair prompt.

The guided stack installer may install AUTOREVIEW from its pinned source, install or reuse
a pinned TruffleHog executable required by that lane, and install Clawpatch through its
pinned package path. Those actions are separate from the portable core installation and
must not be reported as core prerequisites.

## GBrain installation lanes

The installer exposes both GBrain paths instead of hiding the choice:

- `--gbrain-lane local`: Manageroo's local setup path with status and source-mapping
  checks;
- `--gbrain-lane official`: the upstream agent-supervised protocol.

Either path is optional unless the operator or project explicitly requires GBrain. Once
selected, setup and readiness must agree on its executable health and exact source
mapping before reporting that capability ready.

## Token-reduction modes

Token reduction is one optional presentation feature with two bundled styles:

- `caveman`;
- `uncle-matts-caveman-curse`.

Only the selected mode is active. Users can change it with
`manageroo token-mode set ...`; neither style changes Manageroo's safety or completion
contract.
