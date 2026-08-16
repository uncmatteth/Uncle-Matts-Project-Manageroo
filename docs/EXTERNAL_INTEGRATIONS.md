# External integrations

Manageroo is the controller. GitNexus, GBrain, TruffleHog, AUTOREVIEW,
Clawpatch, Obsidian, and document-analysis tools are external capability lanes.
They are **optional enhancements for ordinary portable-core runs** unless the
current project or operation explicitly requires one of them.

Current repository files, Manageroo's locked request and run artifacts,
deterministic gates, source-delivery transaction, and signed completion receipt
remain authoritative. External output is evidence only. It cannot authorize an
edit, approve a review, pass a gate, apply a patch, or mark a run `COMPLETE`.

## Capability contract

Manageroo records each enhanced lane as one of:

- available and used;
- available but not needed;
- unavailable and optional;
- explicitly required and satisfied;
- explicitly required and blocking.

A missing optional lane does not silently weaken the core controller. Manageroo
still uses isolated workers, its own independent review path, deterministic
verification, and signed completion proof. A missing required lane fails with a
message naming that capability only.

## Configure enhanced lanes

Installations make tools available. Project configuration opts a repository into
the corresponding controlled lanes:

```bash
manageroo integrations configure . --full \
  --obsidian-vault /path/to/existing/vault \
  --obsidian-export-folder Existing-Inbox
```

The full configurator may wire:

- GBrain search and final capture;
- GitNexus indexing and query;
- bounded document analysis;
- AUTOREVIEW;
- Clawpatch CI review/repair;
- Markdown-vault search and export.

The full stack is an enhancement, not a hidden prerequisite for every real-agent
run. A narrower setup can select only GBrain or GitNexus. `manageroo ready`
reports optional unavailable lanes separately from required blockers.

## Evidence provider boundary

Configured provider output is normalized into provenance-aware evidence with its
source, location when known, authority, confidence, freshness, retrieval time,
and content hash. Provider failures remain visible in the run record.

The combined evidence artifact is stored at:

```text
.manageroo/runs/<run-id>/artifacts/discovery/evidence.json
```

Required current-repository files are budgeted before retrieved context. A
bounded ranked subset may enter worker packets through `ContextCompiler`.
Retrieved evidence never overrides direct current source truth.

See `docs/EVIDENCE_RETRIEVAL.md`.

## GitNexus

GitNexus is optional repository/code-graph intelligence. When selected, it has
two scopes:

### Machine setup

The guided enhanced-stack installer may install a pinned persistent CLI and run
its setup command. The real result is recorded in `install-lock.json`; failure is
reported rather than represented as success.

### Project indexing

Repository indexing is project-specific. Manageroo's configured lane uses the
installed syntax and a portable CPU embedding path where supported. GitNexus may
inform exploration, dependency analysis, impact analysis, debugging, and
refactoring, while direct Git files remain authoritative.

A missing GitNexus installation does not block portable-core work. It blocks
only an operation or project configuration that explicitly requires GitNexus.

Project: https://github.com/nxpatterns/gitnexus

## GBrain

GBrain is optional durable external knowledge. `.manageroo/PROJECT-MEMORY.md`
remains repo-local continuity; neither source overrides current repository truth.

When GBrain is selected or explicitly required, Manageroo enforces **exact source
mapping** for the target repository. It:

1. identifies the exact mapped source;
2. queries with that source ID;
3. rejects malformed or cross-source results;
4. records the evidence with provenance;
5. captures the final pending report back to the same source when capture is
   enabled.

A source mapping for another repository is never substituted. Missing or failed
GBrain is optional unless the request/project explicitly requires external
memory, such as an instruction to use GBrain or Obsidian-backed prior context.

Supported maintenance includes `gbrain upgrade` and `gbrain doctor --json`.
Manageroo never reinitializes an existing brain merely to update it.

Project: https://github.com/garrytan/gbrain

## AUTOREVIEW and TruffleHog

AUTOREVIEW is an optional command-owned closeout lane. Its current preflight may
require TruffleHog. The enhanced-stack installer can reuse an existing binary or
install a release-pinned official archive with a pinned platform checksum.
Manageroo records ownership only for copies it created.

AUTOREVIEW findings do not become an unconstrained AI repair prompt. The command
runs from a clean controller checkpoint; Manageroo captures its result,
scope-checks changes, rejects Git-history changes, and verifies rollback on a
failed or out-of-scope lane.

AUTOREVIEW project:
https://github.com/openclaw/agent-skills/tree/main/skills/autoreview

TruffleHog project: https://github.com/trufflesecurity/trufflehog

## Clawpatch and the standalone supervisor

Clawpatch is an optional command-owned review/repair lane. Manageroo runs its
configured command directly without a shell, captures evidence, and preserves
controller ownership of checkpoints and completion.

The separately versioned `clawpatch-supervise` package owns multi-finding queue
transitions, process watchdogs, fixed-point review, and its typed exit codes.
Manageroo's thin adapter must not duplicate that state machine or translate a
terminal result into an invented retry.

Example direct invocation:

```bash
clawpatch-supervise --repo . --branch current --push none \
  --timeout-minutes 60 --resume-stopped
```

Manageroo can preview or invoke the adapter explicitly. The normal portable-core
run does not require the standalone supervisor.

Supervisor project: https://github.com/uncmatteth/clawpatch-supervise

Clawpatch project: https://github.com/openclaw/clawpatch

## Obsidian

Obsidian is an optional human-readable Markdown knowledge and export lane.
Manageroo does not require a plugin or the GUI application. A configured vault
and export directory must satisfy Manageroo's no-follow filesystem safety checks.
The controller supports secure descriptor-relative export on supported Linux and
macOS filesystems.

When no safe package-manager update can be identified, Manageroo leaves the
application untouched and reports the boundary.

Official download: https://obsidian.md/download

## Document analysis

Document and media analysis is selected when the request or repository actually
requires it. The bounded analyzer is command-owned and receives a manifest rather
than unrestricted repository authority. If the current request explicitly needs
PDF, image, audio, video, transcript, manuscript, chapter, or exact-text analysis,
a missing configured analyzer is a precise blocker for that request. It is not a
blanket prerequisite for ordinary source work.

## Safe maintenance

Preview supported maintenance without changing anything:

```bash
manageroo stack-update
```

Target selected tools:

```bash
manageroo stack-update gitnexus
manageroo stack-update gbrain gitnexus
```

Apply only the explicit supported plan:

```bash
manageroo stack-update gitnexus --apply
```

Setup and update probes parse structured/stdout data while retaining redacted
stderr diagnostics. They do not silently install unrelated products merely
because an optional lane is absent.

## Failure and trust boundary

For every external integration:

1. current repository truth beats stale external context;
2. setup, authentication, and update failures are reported;
3. credentials remain user-owned;
4. optional absence is recorded, not disguised;
5. explicitly required absence fails precisely;
6. successful provider setup is not product completion proof;
7. Manageroo alone owns intent, run state, acceptance evidence, delivery, and
   the signed `COMPLETE` decision.
