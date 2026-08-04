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

## Clawpatch

Clawpatch is a command-owned review and repair lane.

For an existing npm- or pnpm-managed installation, Manageroo proves which package manager owns the active executable and uses that same manager. The supported pinned update is one of:

```bash
npm install -g clawpatch@0.7.2
pnpm add -g clawpatch@0.7.2
clawpatch doctor
```

Manageroo refuses the update if neither ownership lane can be proved. It does not move an installation between npm and pnpm merely because both tools exist.

Manageroo does not claim Clawpatch is healthy merely because the executable exists. The post-update doctor remains part of the update result.

Clawpatch findings remain command-owned. Manageroo must not hand them to a worker for unconstrained freehand repair.

For final project closeout, use Manageroo's cross-platform native sweep instead of manually copying one finding at a time:

```bash
# Dedicated external terminal command with live [current/total] output, one fix per finding,
# exact-path commits, and a verified push after each repair
clawpatch-supervise --repo . --branch current --push each

# Read-only plan
manageroo clawpatch release-sweep --repo .

# Execute locally on an automatically created branch when starting from main/master
manageroo clawpatch release-sweep --repo . --apply

# Push only when explicitly requested
manageroo clawpatch release-sweep --repo . --apply --push final

# Trusted code on an already-isolated host: avoid a nested Codex sandbox
manageroo clawpatch release-sweep --repo . --apply --trusted-host-codex-sandbox-bypass
```

`clawpatch-supervise` is a separate installed console command for an operator who wants to launch and watch the workflow directly rather than enter through the `manageroo` command tree. It works in any Git repository and does not require `.manageroo/config.toml`. It prints named process-preflight, fresh initialization, status, lock-cleanup, map, review, review-verification, queue, show, fix, stopped, and fixed phases. Every command includes its exact argv and the single allowed attempt. The 30-second heartbeat reports time in the currently displayed phase and the exact configured child watchdog. It uses the same command-owned repair controller described below.

The sweep first proves repository, process, Git, status, and lock state. It maps
the repository, asks Clawpatch to review every pending feature, and verifies a
review dry-run has zero remaining work. It then repeats Clawpatch's documented
one-finding lifecycle: `next --json`, `show --json`, `fix`, validation, and
revalidation. There is no report-derived queue, cached finding list, status
triage, manual repair, or concurrent Clawpatch process. Manageroo adds project
validation when Manageroo gates are configured, exact patch-attempt path
staging, authorized commit/push boundaries, final zero-open and zero-lock proof,
and remote-SHA verification without
replacing Clawpatch's command-owned repair.

In a plain Git repository, ClawPatch's applied `fix` result and exact-finding
revalidation own repair validation; Manageroo does not guess a test runner or
invent native gates. In a Manageroo-configured repository, those gates remain
mandatory before review, after each fix, and at final closure. External durable
checkpoint and proof files live in the Manageroo-owned external-runner state
directory, so the command adds nothing to the target worktree or Git metadata.

The trusted-host bypass is explicit and temporary. It sets Clawpatch's documented
Codex sandbox override only in child-process environment and never persists it.
It removes the nested Codex approval/sandbox boundary, so use it only for trusted
source on a host that already supplies isolation. Manageroo's path restrictions,
project gates, revalidation, and exact-path commit rules still apply.

Every Clawpatch child command uses the explicit shared process-group and provider timeout. A timeout
kills that process group. Each command and each finding-scoped `fix` runs once.
A failed fix leaves its source edits visible and records the exact paths in a
stopped checkpoint. Manageroo does not stash, triage, reopen, retry, skip,
remap, advance, run final closure, commit, or push that repair. Revalidation
that is `uncertain` because read-only execution is blocked gets one controlled
workspace-write revalidation guarded by an exact source fingerprint; that is a
documented validation transition, not a new source fix.

On relaunch, a stopped attempt is resumable only when the checkpoint branch,
finding, and owned paths match current state, and Clawpatch reports exactly one
applied patch attempt for that finding, current HEAD,
and path set. Manageroo then runs gates and resumes revalidation of that existing
attempt. It does not invoke `fix`, remap, or review before returning to `next`.
Any missing, stale, or ambiguous proof stops with the checkpoint and edits
unchanged.

An interrupted provider can leave a ClawPatch patch attempt in `planned` state
before any source edit exists. For that source-clean case, the supervisor
requires the checkpoint branch and HEAD, same open finding, empty attempt path
set, and planned attempt base SHA to agree. It preserves `.clawpatch` state,
clears only its external checkpoint, and requires ClawPatch `next` to return the
same finding before continuing through `show` and `fix`.

If the worktree is source-clean and the checkpoint predates current HEAD, the
external supervisor inspects descendant commits. It clears the checkpoint only
when one commit's exact non-ClawPatch path set equals the checkpoint-owned path
set. Generic commit subjects do not block this proof, while commits containing
any additional source path do. With no ClawPatch project state, the external
supervisor runs `clawpatch init` automatically before status, map, and review.

An `open` revalidation is also a documented state transition rather than a
failed command. Manageroo commits only the current applied patch-attempt paths
as a continuation checkpoint, verifies an authorized push, and calls
Clawpatch's `next` again. Because the finding remains open, Clawpatch selects the
same finding for another `show` and `fix` cycle. This has no arbitrary attempt
cap and never substitutes a Manageroo-written repair.

Tracked Clawpatch state is never mixed into a repair commit. To publish it after
all final gates pass, use `--publish-clawpatch-state` with an explicit push mode;
Manageroo creates one separate `.clawpatch/**`-only final state commit.

Clawpatch 0.7.2's `show` output includes a human triage template. Manageroo
records that inspection but does not execute or fill in the template. Its
explicit release policy sends every current open finding to Clawpatch's own
finding-scoped `fix`. Failed attempts are never called fixed or skipped:
the supervisor stops and requires an explicit operator decision. Only `--fresh`
can automatically discard source and initialize a new Clawpatch run. In the
portable external supervisor, that flag explicitly discards every current
source change whether or not a checkpoint exists, so operators must commit or
copy work they want to keep first. The Manageroo project command keeps the
stricter exact-checkpoint ownership rule.

The implementation is native Python and uses argv-only subprocesses. It does
not depend on Bash, PowerShell scripts, `jq`, or copy/paste loops, and supports
Windows, macOS, and Linux. On Windows, Manageroo resolves command shims and uses
native PowerShell process inspection conservatively to prevent concurrent
Clawpatch execution.

Manageroo gives each Clawpatch child process group and provider the same explicit timeout and sets
the same default for its Codex worker. A user-supplied
`CLAWPATCH_CODEX_TIMEOUT_MS` value takes precedence inside Clawpatch, but does
not extend Manageroo's outer watchdog. Durable progress lives beside the
Manageroo-owned `clawpatch-supervise` installation for the external command and
under `.manageroo/cache` for the Manageroo project command. Ordinary relaunch
resumes only the exact stopped applied attempt proven by that record and current
Clawpatch state, or clears an already-committed checkpoint using exact descendant
Git path proof; it refuses to guess when any ownership proof differs. For the external
`clawpatch-supervise` command, explicit `--fresh` discards all current tracked
and untracked source changes and old `.clawpatch` run state, then initializes a
clean run. The Manageroo project command remains narrower: its `--fresh` may
discard source only when current dirty paths exactly equal the checkpoint-owned
paths.
On upgrade, the external runner recognizes and verifies its legacy version-2
checkpoint under `.manageroo/cache`, moves that ownership record into the
Manageroo-owned external state directory, and then applies the external fresh
reset contract.
Manageroo is not an OS daemon and
cannot relaunch its own terminated controller process.

The proof can be made mandatory for the final operator gate with `manageroo release-ready --require-clawpatch` or the `[project]` setting `require_clawpatch_release_sweep = true`.

Project: https://github.com/openclaw/clawpatch

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
