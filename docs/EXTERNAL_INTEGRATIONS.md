# External integrations

Manageroo is the controller. GitNexus, GBrain, TruffleHog, AUTOREVIEW, Clawpatch, and Obsidian provide surrounding capabilities. Current repository truth, Manageroo's locked run artifacts, deterministic gates, and evidence remain authoritative.

## Recommended full stack

The intended full installation can include:

- GitNexus for repository/code-graph intelligence;
- GBrain for external durable knowledge when explicitly relevant;
- TruffleHog for AUTOREVIEW's local pre-review secret scan;
- AUTOREVIEW for external review;
- Clawpatch for external review and repair;
- Obsidian for human-readable knowledge.

These integrations are first-class parts of the full Manageroo experience without becoming completion authorities.

## Evidence provider boundary

GitNexus and GBrain now feed Manageroo's generic evidence layer rather than being treated as interchangeable "memory" systems.

Configured discovery commands remain command-owned. Successful output is normalized into provenance-aware evidence records with source, location when known, authority, confidence, freshness, retrieval time, and content hash. Failed provider calls remain visible as provider errors.

Manageroo combines that with selected native project/run evidence in:

```text
.manageroo/runs/<run-id>/artifacts/discovery/evidence.json
```

A bounded highest-ranked subset can enter planning worker packets through `ContextCompiler`. Required repository files are budgeted first. Retrieved evidence is context only and cannot authorize edits, approve review, pass gates, or mark a run `COMPLETE`.

See `docs/EVIDENCE_RETRIEVAL.md`.

## Safe maintenance

Preview the current supported update plan without changing anything:

```bash
manageroo stack-update
```

Target one or more tools when useful:

```bash
manageroo stack-update gitnexus
manageroo stack-update gbrain gitnexus
```

Apply only explicitly selected supported updates:

```bash
manageroo stack-update gitnexus --apply
manageroo stack-update --apply
```

The command is intentionally explicit and fail-visible. It does not silently install missing third-party products merely because an update command was requested.
Stack maintenance probes parse configuration, JSON, and package-manager paths from stdout only;
separately captured stderr is retained as redacted diagnostic output.

`skills` is part of the default stack plan alongside GBrain, GitNexus,
TruffleHog, AUTOREVIEW, Clawpatch, and Obsidian. Unlike the third-party tools,
its update source is the core skill pack bundled with the installed Manageroo
release. `manageroo stack-update skills --apply` uses the skill ownership ledger
and full-tree digests: it installs missing core skills, replaces unchanged
Manageroo-owned copies transactionally, prunes ledger entries whose trees no
longer exist, and preserves tOS-, host-, or user-owned same-name trees. An
environment-selected `MANAGEROO_SKILLS_DIR` keeps its ledger inside that root;
test and temporary roots therefore cannot pollute the user's global Manageroo
ownership file.

## GitNexus

GitNexus is Manageroo's first-class recommended repository-intelligence integration.

The integration has two distinct scopes:

### Machine-level setup

When the surrounding stack is selected during Manageroo installation, Manageroo installs a persistent GitNexus CLI and completes:

```bash
gitnexus setup
```

The platform installer updates `install-lock.json` with the real setup result. If selected GitNexus setup fails, the installation fails visibly instead of pretending GitNexus is configured.

### Project-level indexing

Repository indexing is project-specific and runs from the target repository:

```bash
gitnexus analyze
```

GitNexus can then provide repository exploration, dependency awareness, impact analysis, debugging, and refactoring context through its current installed integration surfaces.

When a configured GitNexus discovery command returns evidence, Manageroo ranks that output as current repository intelligence, while still preferring direct current Git file reads whenever exact source truth is required.

Manageroo remains the controller. Current Git files and command output beat stale graph data, and Manageroo can still operate when GitNexus was intentionally skipped or is temporarily unavailable.

For an existing persistent installation, `manageroo stack-update gitnexus --apply` refreshes the CLI with the detected supported global package-manager lane. Stack update does not install GitNexus merely because it is absent; use the Manageroo installer when you want to add the recommended stack.

Project: https://github.com/nxpatterns/gitnexus

## GBrain

GBrain is external memory and retrieval. Manageroo's own `.manageroo/PROJECT-MEMORY.md` remains the normal repo-local continuity lane.

GBrain becomes required only when the operator explicitly wants GBrain, a brain page, Obsidian-backed external context, or another external knowledge source.

When a configured GBrain search command returns evidence, Manageroo preserves it as external knowledge with provenance rather than allowing it to override current repository state or locked run truth.

Supported maintenance path:

```bash
gbrain upgrade
gbrain doctor --json
```

Fresh local installs can use:

```bash
bun install -g github:garrytan/gbrain
gbrain init --pglite
gbrain skillpack scaffold --all
gbrain doctor
```

For the full agent-supervised setup, use GBrain's upstream agent installation protocol instead of Manageroo guessing API keys, embedding choices, integrations, recurring jobs, or source mapping.

Manageroo never reinitializes an existing brain merely to update it.

Project: https://github.com/garrytan/gbrain

## AUTOREVIEW

AUTOREVIEW is a command-owned closeout review lane. The canonical source is `openclaw/agent-skills`.

Current AUTOREVIEW requires TruffleHog and fails closed when the binary is missing. The recommended Manageroo installer therefore reuses an existing TruffleHog or installs a release-pinned official binary with a pinned per-platform SHA-256 checksum. Supported release assets cover Linux, macOS, and Windows on amd64 and arm64. A Manageroo-owned copy is recorded in `install-lock.json`; an existing user-owned copy is reused without Manageroo claiming update or uninstall ownership.

Manageroo's stack updater refreshes an existing AUTOREVIEW installation from the canonical `skills/autoreview` tree and rejects symlinked downloaded content. A discovered alias is accepted only when it resolves to an `autoreview` directory directly beneath an approved resolved skill root and its `SKILL.md` names `autoreview`; unsafe destinations fail without replacement. Replacement uses same-filesystem rollback storage outside the discovered skills root; it restores the prior copy on a failed swap and removes the rollback storage after a successful update, so normal updates do not create duplicate `autoreview` skill folders. If only that final cleanup fails, the updater reports the already-installed update as successful, returns the retained rollback path, and surfaces a cleanup warning instead of falsely reporting that the swap failed.

AUTOREVIEW findings do not become unconstrained freehand AI repair prompts. When configured as a Manageroo command-owned lane, its command owns its result and Manageroo scope-checks any resulting edits.

Project: https://github.com/openclaw/agent-skills/tree/main/skills/autoreview

TruffleHog project: https://github.com/trufflesecurity/trufflehog

## ClawPatch and the standalone supervisor

ClawPatch remains a command-owned review and repair lane. Manageroo updates the pinned ClawPatch CLI through its proven npm or pnpm owner and reruns `clawpatch doctor`; it does not freehand a repair from a finding.

Clawpatch findings remain command-owned. Manageroo must not hand them to a
worker for unconstrained freehand repair.

The multi-finding queue engine is the separately versioned [`clawpatch-supervise`](https://github.com/uncmatteth/clawpatch-supervise) package. It owns queue transitions, checkpoints, fixed-point review, partial-progress handling, process watchdogs, and typed exit codes. Manageroo owns none of that runtime now.

Run it directly:

```bash
clawpatch-supervise --repo . --branch current --push none --timeout-minutes 60 --resume-stopped
```

Manageroo retains a thin optional adapter for discovery and operator consistency:

```bash
# Read-only plan
manageroo clawpatch release-sweep --repo .

# Invoke the standalone executable and preserve its exit code
manageroo clawpatch release-sweep --repo . --apply --branch current --push none --timeout-minutes 60 --resume-stopped
```

The adapter passes argv directly with no command shell. It does not import the standalone package, duplicate its state machine, translate a terminal exit into a retry, or create a second checkpoint. Exit `75` remains retryable and exit `2` remains terminal.

`manageroo release-ready --require-clawpatch` asks the standalone executable for its state directory and validates `clawpatch-release-proof.json` against the current Git HEAD. This avoids duplicating platform-specific state paths.

`manageroo stack-update clawpatch-supervise` previews the pinned standalone commit. Apply is allowed only for an executable resolved inside one of the native-installer virtual environments; unowned installations are left untouched. Before the first package mutation, Manageroo installs a stdlib-only console-entry gate that makes direct and service supervisor runs share the updater's cross-platform installation lock. Migration from an older ungated launcher also requires a successful platform-native process snapshot. Later updates rely on the shared lock rather than a process-list snapshot. The native Windows and macOS supervisor installers still install the standalone repository pin rather than Manageroo itself.

The standalone project is the authoritative source for detailed transition, recovery, checkpoint, disposable validation, and systemd service behavior.

Project: https://github.com/uncmatteth/clawpatch-supervise

ClawPatch: https://github.com/openclaw/clawpatch

## Obsidian

Obsidian is a human-readable Markdown knowledge lane. Manageroo does not require an Obsidian plugin and does not treat the GUI application as a completion authority.

`manageroo stack-update obsidian --apply` uses a detected operating-system package manager when a safe update command is available:

- Windows: Winget;
- macOS: Homebrew cask;
- Linux: Flatpak, or Snap when that is the detected installation lane.

When no safe package-manager update can be identified, Manageroo leaves Obsidian alone and reports the boundary instead of inventing an updater.

Official download: https://obsidian.md/download

## Failure and trust boundary

For every surrounding integration:

1. current repo truth beats stale external context;
2. update and setup failures are reported, not hidden;
3. credentials and authentication remain user-owned;
4. Manageroo does not auto-install unrelated dependencies merely to chase a missing integration;
5. a successful external-tool setup or update is not proof that a target product is ready for production;
6. Manageroo alone owns its run state, acceptance evidence, and `COMPLETE` decision.
