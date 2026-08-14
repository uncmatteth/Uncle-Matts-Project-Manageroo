# Architecture

## Thin controller, strong artifacts

Manageroo deliberately avoids becoming another IDE, code graph database, memory system, or model host. The controller coordinates workers and surrounding tools through durable, inspectable artifacts.

```text
CLI
 └─ Orchestrator
     ├─ State machine
     ├─ Artifact ledger and locked contracts
     ├─ Source mirror
     ├─ Evidence retrieval and provenance ranking
     ├─ Context compiler
     ├─ Automatic capability router and bounded task capsules
     ├─ Durable worker job store
     ├─ Agent adapter / worker pool
     ├─ Scope and command policies
     ├─ Deterministic gate runner
     ├─ Isolated reviewer
     ├─ External review / repair lanes
     ├─ Proactive learning card writer
     └─ Delivery reporter
```

## Operator and worker boundaries

Manageroo uses two distinct control layers. Codex continuity hooks preserve the
operator-facing agent's unfinished objective across follow-up messages,
resumption, and compaction. `UserPromptSubmit` classifies actionable repository
work and writes the exact accumulated operator request to a private
controller-owned brief. The user does not name Manageroo or remember a skill.
Side questions remain conversation; explicit cancel/replace language and clear
natural corrections supersede unfinished work.

## Automatic managed execution

For actionable repository work, `PreToolUse` permits the Manageroo run/status/
report path and denies freehand repository execution. A requested `manageroo
run` is rewritten to use the controller-owned exact-request brief and the bound
repository. The `Stop` hook permits completion only after an exact-brief run has
a controller-owned `COMPLETE` result, passed intent conformance, and an applied
source receipt. A failed or interrupted run remains resumable from durable jobs;
it does not turn into permission for the outer agent to improvise.

Read-only questions do not create a controlled run. An explicit pause remains
authoritative, and a later reaffirmation resumes the saved request without
making the operator repeat it. Explicit exclusions and `only` boundaries remain
binding inside the managed brief and worker packets.

Missing continuity state starts a new session. Unreadable, malformed, non-object,
or unsupported-version state fails closed without replacing the original file.

Operator sessions and controlled Codex workers use an explicit execution-mode
seam. The Codex adapter marks every concrete worker launch, including fallback
launches, as `structured-worker` through `MANAGEROO_EXECUTION_MODE`. Continuity
hooks return no output and create no continuity state in that mode, so the
worker's declared JSON schema remains its only output contract. Unknown or
malformed schema type declarations fail closed. Unset and unrecognized execution
modes retain operator continuity. This environment marker selects Manageroo
behavior; it is not an operating-system security boundary.

Routine prompt events save the objective privately and return no output. Successful
tool checks also return no output. Session start injects one compact controller
contract; session recovery, subagent startup, and post-compaction recovery inject
the exact active requests with compressed control wording. This keeps routine
operation invisible and at zero prompt-token overhead while retaining the
context needed after an actual recovery event.

Paused state is advisory recovery context. It never denies tools and never
requires a resume password. A direct resume can reactivate the saved objective,
but any current operator request is authoritative whether or not the parser
classifies that wording as resume.

At ordinary Codex `SessionStart`, the hook supplies one compact global controller
contract even when no prior objective exists. It tells the operator-facing agent
to select relevant installed skills automatically and routes actionable
repository work into Manageroo. It also forbids treating the user's home
directory as an implicit project. This makes Manageroo event-driven and globally
active after the one-time Codex hook trust step without adding a daemon,
scheduler, model runtime, or background mutation loop.

Hook denials use a consistent target, reason, and next-action layout instead of
one dense implementation sentence. Only explicit operator-written exclusions
or `only` boundaries can produce those denials.

The stronger repository boundary controls processes launched through
`manageroo run`. The host's normal workspace and approval policy remains the
operator-facing security boundary; continuity hooks are not a hostile-process
sandbox. The action gateway is a scope boundary for supported Codex tool calls,
not an operating-system claim about same-user processes that bypass hooks.

Inside a controlled run, each worker receives an immutable packet containing
the current brief, exact task-owned paths, named reuse sources, exclusions, and
proof bindings. The isolated mirror, command policy, changed-file checks,
source-manifest comparison, gates, independent review, and final apply checks
enforce that packet. This is where Manageroo prevents agent drift.

At run intake, a run-owned intent snapshot binds the brief used for that run.
It does not become repository-wide authority and does not block a later current
request. Every worker packet receives the current request verbatim plus its
structured targets, named sources, exclusions, and proof when supplied. The
controller repairs generated packets that omitted this block before launch.
If a saved run is continued after its brief changed, Manageroo automatically
supersedes it with a fresh run derived from the newer request instead of making
the operator repeat or authorize the change. Post-worker scope, named-source,
review, acceptance, and completion checks audit the agent's work against that
request. Intent auditing never decides whether the operator is allowed to issue
the request.

When source, targets, exclusions, and proof are already explicit, the exact-task
path deterministically creates the product outcome and task packet without
product-analysis, reuse-research, repository-mapping, or plan-review model calls.
Explicit `Required outcomes` in the product brief remain authoritative. Exact
mode normalizes punctuation, case, and whitespace only for comparison, requires
the `--proof` set to match those outcomes, and preserves the brief wording in
the locked product model and proof bindings. Missing or unrelated proof text
blocks before implementation.
The implementation, verification, independent review, and delivery controls
remain active.

Operator reuse directives are also locked. A sentence directing Manageroo to
use, reuse, copy, or port existing, finished, or named work must be copied
exactly into one reuse decision's evidence and classified as `reuse-internal`,
`reuse-external`, or `platform-native`. The task plan then binds the same need,
decision, candidate, implementation method, and empty deviation. A custom
replacement, changed candidate, omitted binding, or declared deviation blocks
before implementation. Review receives those bindings and treats substitution
as a blocking scope and truth defect even when substitute-specific tests pass.
The generated instruction to use the current Git repository as source truth is
repository scope, not a component-reuse directive, so it does not create a
model-owned permission gate or require the reuse worker to quote boilerplate.

The standard installer removes obsolete Manageroo permission-firewall hook
entries, installs the bounded continuity hook set, and preserves unrelated hooks.
It stages the complete Manageroo runtime beside the live installation before a
directory swap, so concurrently executing hooks cannot repopulate a directory
that the installer is recursively deleting.
The staged app must match the source-app digest captured before installation.
The install lock records whether Git provenance was knowable, the exact source
commit and dirty state when known, the complete source-tree SHA-256, and the
installed-app SHA-256. Source drift before the atomic app swap stops the update.
The install repair command verifies required hook groups and every portable core
skill instead of treating missing components as advisory success. Controller
updates replay the complete verified source installer with recorded prefix,
launcher directory, agent, and token-mode choices while preserving the optional
surrounding stack. Guided uninstall separates runtime, hooks, owned skills, and
state; it removes only a confirmed selection, keeps user-edited skill trees, and
lists shared tools without claiming removal ownership.

## Source isolation

The source repository is inventoried through Git-visible tracked and unignored files. Manageroo copies those files into a run-owned repository and verifies each copy's digest, size, and mode against that inventory before committing an internal baseline. Coding agents never need direct write access to the operator's source repository.
Inventory inspection opens every path through pinned directory descriptors with
no-follow semantics, snapshots and hashes each regular file through that one open
descriptor, retries files that change identity or metadata, and fails closed when
descriptor-relative access is unavailable. Only stable records reach the cache.
Repository-relative paths containing backslashes fail closed instead of being
normalized into a different file identity during workspace mirroring.
Visible source paths and pending workspace paths must be regular files or
directories; FIFOs, sockets, devices, and symlinks fail closed. Resume cleanup
uses the double-force form of `git clean` only inside Manageroo's own disposable
workspace so ignored nested Git repositories cannot survive as worker residue,
then verifies that no ignored state remains.

After successful delivery:

1. Manageroo generates a binary-capable Git patch from isolated baseline to final checkpoint.
2. Manageroo writes only pending result/report artifacts while required GBrain capture and Obsidian export run.
3. Manageroo verifies that every source file still matches the original source manifest.
4. `git apply --check` verifies the patch.
5. Manageroo revalidates the source immediately before applying the patch.
6. The controller applies the patch only when `--apply` was explicit or an existing project policy allows it; new configs default to no apply.
7. Manageroo verifies the applied tree against the reviewed workspace; if a concurrent edit is
   detected, it reverse-checks and reverses only its patch while preserving that edit.
8. Only after delivery and the durable state transition succeed does the controller publish `COMPLETE` in the final result and report. A late failure overwrites stale success evidence and reverses the exact applied patch.

Every deterministic gate runs in its own disposable checkout at the reviewed
checkpoint. Any tracked, untracked, ignored, mode, symlink, or HEAD mutation is
rejected and discarded; gate output can never become the delivery patch.

Command output remains exact inside the controller. Secret redaction happens only
when logs, reports, or machine-readable command records are persisted or displayed,
so a Git patch is never rewritten into literal `<REDACTED>` content.

A concurrent source change blocks application instead of guessing.

## Fresh process roles

Each agent role starts as a new process:

- product analyst;
- reuse researcher;
- repository mapper;
- map reducer;
- plan compiler;
- plan reviewer;
- implementer;
- reviewer;
- repairer.

Only verified artifacts move between roles. Conversational reasoning does not.

## Stateless worker jobs

Manageroo is not “AI remembers better.” Manageroo makes remembering unnecessary.

The controller writes run truth to disk. Each AI worker receives one complete assignment packet. If a worker drifts, dies, lies, or runs out of room, the controller records the failed attempt and starts a fresh worker from saved facts.

Every worker call is represented as a durable job:

```text
.manageroo/runs/<run-id>/
|-- controller/truth.json
|-- controller/phase-journal.jsonl
|-- jobs/<job-id>.json
|-- worker-attempts/<job-id>/<attempt-id>.json
|-- packets/<job-id>/<attempt-id>/prompt.md
`-- agent-output/<job-id>/<attempt-id>.json
```

Completed jobs are loaded from recorded artifacts. They are not rerun merely because a chat was compacted or a new worker process starts. A completed job record must include a matching output-artifact SHA-256 hash, and the parsed artifact must match the recorded result hash, or it is treated as stale.
The lexical artifact entry must also remain a single-link regular file. Manageroo
hashes and parses bytes from the same validated descriptor so a symlink alias
cannot be recorded or reused as run-owned output.

`manageroo run --continue <run-id>` replays the Python controller from the saved run folder. The old worker process is not trusted or required. Replay keeps logical job IDs stable so later attempts continue the original job instead of creating shifted duplicate work.
Product-analysis continuation also reuses the locked system-capacity and
unknown-unknowns-preflight artifacts from that run; volatile host values such as
free disk space cannot change the durable worker specification between attempts.

## Evidence retrieval, not AI memory

Manageroo has a generic evidence boundary. It can normalize current repository intelligence, locked run artifacts, curated project knowledge, and external knowledge into a common provenance-preserving model.

```text
GitNexus ───────────────┐
GBrain ─────────────────┤
Manageroo run artifacts ├─> evidence normalization ─> ranking ─> ContextCompiler
Project memory ─────────┘
```

Each evidence item retains source, location, authority, confidence, freshness, retrieval time, and a content hash. Providers may also attach a stable claim key so contradictions are surfaced instead of silently merged.

The ranking policy prefers current repository evidence over run evidence, explicit project knowledge, external knowledge, and historical context. Confidence and freshness refine that ordering but do not let an old semantic match outrank current source truth merely because it sounds relevant.

Successful configured GitNexus and GBrain discovery output is normalized into `artifacts/discovery/evidence.json` together with native Manageroo project/run evidence. Retrieved evidence can inform planning, but it cannot authorize edits, pass gates, approve review, apply patches, or mark a run `COMPLETE`.

`ContextCompiler` can include ranked `EvidenceItem` objects after required repository context has been budgeted. Packet manifests retain evidence provenance and hashes, and prompts explicitly tell workers that retrieval is context rather than controller truth.

See `docs/EVIDENCE_RETRIEVAL.md` for the provider and ranking contract.

## Controller-owned commits

Agents are forbidden from committing. The isolated repository contains a failing pre-commit hook. The controller also compares `HEAD` before and after every agent role. Once scope, acceptance evidence, review, and gates pass, the controller creates an internal checkpoint while bypassing the hook itself.

For pytest-configured Python projects, validation uses a disposable environment with the project's declared runtime and test dependencies. Manageroo adds its default pytest range only when those dependencies do not declare pytest themselves.

ClawPatch queue supervision is an optional external integration. The standalone `clawpatch-supervise` package owns finding transitions, partial-progress commits, checkpoints, recovery, validation environments, fixed-point review, and service exit policy.

Manageroo keeps only an argv adapter in `clawpatch_release.py`. A dry run renders the exact standalone command. An applying run resolves the installed executable, requires its `--version` output to match the declared supervisor version exactly, invokes it with `shell=False`, streams its terminal output, and returns its exit code unchanged. The release-ready gate asks that executable for its external state path before reading the proof, so Manageroo does not duplicate platform path or checkpoint logic.

The package metadata no longer publishes a `clawpatch-supervise` console script, and Manageroo does not import the standalone Python package. Native supervisor installers and the ownership-checked stack updater pin the public standalone repository independently. Before mutating an owned supervisor environment, the updater installs a tiny stdlib-only console-entry gate. Direct, service, and Manageroo-mediated queue launches then hold the same cross-platform installation lock for their complete lifetime, while updates hold it across package mutation and verification. A one-time platform process snapshot covers only migration from the older ungated launcher; it is not the ongoing synchronization primitive.

Supervisor `--version` probes use that same runtime lock; only the tiny
Manageroo gate-version query is lock-free because it does not import or execute
the installed supervisor package.

## Parallel mapping and review, sequential implementation

Tasks are dependency ordered and executed sequentially in the same isolated integration repository. This is slower than unconstrained parallel editing but avoids incompatible branches and hidden interface assumptions.

Repository mapping and isolated review may run as bounded parallel worker calls. Their packet names, output files, artifact writes, budgets, and completion state remain controller-owned. Manageroo does not run parallel implementation branches against the same files.

## Required surrounding stack

The surrounding stack provides first-class capabilities without taking control away from Manageroo:

- **GitNexus**: required repository/code-graph intelligence for exploration, dependency awareness, impact analysis, debugging, and refactoring. Missing or failed discovery blocks a normal run.
- **GBrain**: required exact-repository durable knowledge retrieval and pre-apply capture. The user never has to name it.
- **AUTOREVIEW**: command-owned external review lane. Stack updates retain the
  discovered candidate, approved root, resolved target, and filesystem identities;
  any destination change before replacement fails closed without updating it. The
  entry moved into rollback storage must still have the planned device and inode
  before the staged installation can replace it or rollback storage can be removed.
- **Clawpatch**: command-owned review and repair lane. Its own command owns its findings and repairs.
- **Obsidian**: human-readable Markdown knowledge lane. Automatic updates use one
  ownership contract for Winget, Homebrew, Flatpak, and Snap and fail closed when
  the detected manager cannot prove ownership of the active installation.
- **Document/prose command lane**: optional evidence over a run-owned manifest for long prose, PDFs, transcripts, articles, and exact-text workflows.

Successful external repair reports are reusable only for the same run, command configuration,
approved paths, and inputs. Continuation verifies the recorded checkpoint chain and Git diffs,
then restores the exact clean final checkpoint only from a clean workspace. Ignored paths that
predated the lane, including empty directory hierarchy and directory modes, are fingerprinted in
checkpoint state, preserved across controller commits, and
must remain unchanged and disjoint from checkpoint-tracked paths during restoration; incomplete
legacy reports and dirty or unapproved ignored resume state fail closed without restoration.
Immediately before each external command, Manageroo captures a bounded snapshot of repository-local
Git metadata. Any command mutation of that metadata is restored and rejects the lane before Git-based
path inspection. Checkpoint restoration and rollback reconstruct `.git` from the captured snapshot;
they never copy the post-command live Git directory into the replacement workspace.
Checkpoint restoration and failed-lane rollback materialize the desired Git tree outside the live
workspace, move unchanged pre-existing ignored entries into that staged tree, and rotate the live
workspace into run-owned recovery storage before installing the replacement. They never reset or
clean the live workspace in place, so lane residue or data created during preflight races remains in
the displaced workspace quarantine instead of being deleted. Quarantines are retained for recovery.
If an ignored-entry move or workspace rotation fails before installation, Manageroo reverses every
recorded move and restores the displaced workspace; an incomplete rollback keeps its quarantine.
Before the final report exists, successful lane manifests form the same command-ordered chain, so
an interrupted run restores its latest validated checkpoint without repeating completed lanes.

These systems are capabilities, not completion authorities.

`manageroo integrations configure --full` is the one-time project-level bridge
between an installed surrounding stack and controlled-run use. It validates an
existing Obsidian vault/export folder and writes argv-only templates for every
available lane. Merely finding a binary in the host stack is not reported as an
active Manageroo integration.

```text
GitNexus / GBrain / TruffleHog / AUTOREVIEW / Clawpatch / Obsidian
                        ↓
              evidence and capabilities
                        ↓
               Manageroo controller
                        ↓
        scope + gates + review + proof + completion
```

Core acceptance still belongs to Manageroo's state, scope, gates, and evidence.

Manageroo writes `verification/acceptance-evidence.json` instead of auto-marking human acceptance outcomes as passed. User-journey, browser, demo, deploy, visual, and security claims need matching demonstration evidence or they remain `unknown` and block `COMPLETE`.

## Host-owned capabilities

A user's host environment may contain additional skills and tools. Manageroo may use relevant capabilities when available, but it does not copy, delete, upgrade, or claim ownership of the entire host environment.

The public Manageroo package must remain portable and free of private machine assumptions, personal paths, and user-specific configuration.

Before every worker job, the capability router indexes local skill metadata,
repository-local skills, and enabled local Codex plugin skill roots outside
model context. It selects from controller-owned normal-language intent (never
rendered packets or repository evidence), applies role/sandbox/interaction
compatibility policy, injects only complete selected entrypoints within a hard
budget, and records raw entrypoint plus full-tree digests as controller evidence.
Discovery and ingestion pin each capability root and directory with no-follow
descriptors, then derive entrypoint instructions and every tree hash from the
same regular-file descriptor snapshots. Identity or metadata changes reject the
capability instead of allowing content and audit metadata from different states.
Generated task text can only rerank candidates already made eligible by the
operator's original brief; it cannot activate or explicitly request another skill.
The selected trees are rehashed immediately before every concrete provider
launch, including fallback attempts. Codex catalog identities are refreshed at
that same boundary before its ephemeral isolation profile is built.
Codex workers receive a short-lived layered profile that removes the discovered
global and repository catalog by canonical name and source path from model-visible
context for that process. This is a deep module
behind one automatic interface; workers and users do not implement routing at
each call site.
Capability source paths are canonicalized after the requested root itself passes
the no-symlink check, so macOS aliases such as `/var` and `/private/var` cannot
split disabled-path matching, selection records, and isolation records.
Job artifacts and stack-tool destinations canonicalize ancestor directories while
preserving the final path entry for independent link and executable-name checks.

Controller policies and saved prose preferences are not ordinary task
capabilities. In particular, `use-installed-skills-first` is native Manageroo
behavior, while normal/Caveman/Caveman Curse remains installer-selected state.
Skill-pack and token-mode installation is serialized with a permanent advisory
file lock, so another process cannot enter while owner diagnostics are still
being published. Existing lock inodes must be private regular files and are
never truncated or rewritten.

Project-config mutation locks first attempt exclusive file creation. A contender
that observes an existing lock reopens it without creation, avoiding the macOS
concurrent-creation race while retaining the existing inode and link checks.

The durable worker budget is updated by Manageroo immediately before each real
provider launch. Its newest controller-owned bytes remain authoritative for all
parallel transaction guards, so one worker does not blame another controller
reservation on its worker. Any later worker-authored change to that record is
still restored and rejected.

Each independent review uses a fresh run-owned checkout name. An incomplete
checkout left by an interrupted review is preserved for evidence and skipped;
it cannot block the next review attempt.

Workers sharing one disposable repository serialize their transaction windows
to keep rollback and tamper detection coherent. The wait window is derived from
the whole-run runtime budget, so normal long-running parallel calls do not fail
on an unrelated fixed 30-second lock timeout.

`release-ready` executes configured verification gates in a disposable local
clone checked out at the exact candidate commit. After every gate, Manageroo
rejects any HEAD, tracked, untracked, or ignored mutation before another gate
can run or the release can be authorized. An official Git reference transaction
holds that candidate HEAD while final evidence is persisted, followed by another
HEAD, source-digest, and cleanliness snapshot. A READY handoff binds deployment
to a tar archive generated from that locked commit and records the archive's
SHA-256, so a later source-worktree mutation cannot change the authorized ship
bytes. The repository's configured gate uses
`verify_release.py --check-only` and an isolated bytecode cache; the normal
operator invocation still refreshes `BUILD-VALIDATION.json`.

`doctor`, `ready`, and `stack-doctor` are deliberately narrower diagnostics.
Their JSON reports expose `release_authority: false`, a named diagnostic scope,
and `manageroo release-ready` as the final release command. Only
`release-ready` has `release_authority: true`; its positive result is still an
operator handoff, not a deployment.

A completed Manageroo run records the source repository HEAD captured before the
run together with the reviewed patch and final source-tree digests. If HEAD or
the patch changes before that proof is attached, the run is downgraded instead
of publishing `COMPLETE`. `release-ready` requires the current HEAD to equal that
run-bound commit in addition to matching both digests.

## Proactive learning, no silent self-mutation

Every run can emit improvement cards under `artifacts/learning/improvement-cards.json` and copy pending cards into `.manageroo/cache/learning/pending/`.

Those cards are structured suggestions. They rank value and risk, route the lesson to a destination such as project memory, skill improvement, config, docs, installer, GBrain capture, or backlog, and cite run evidence.

The controller may save pending cards automatically. It must not silently change behavior, skills, config, docs, installer behavior, or memory. Applying a supported card requires:

```bash
manageroo learning apply CARD_ID --approve
```
