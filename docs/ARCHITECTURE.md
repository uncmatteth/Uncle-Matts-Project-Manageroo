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

## Source isolation

The source repository is inventoried through Git-visible tracked and unignored files. Manageroo copies those files into a run-owned repository and verifies each copy's digest, size, and mode against that inventory before committing an internal baseline. Coding agents never need direct write access to the operator's source repository.
Inventory inspection opens every path through pinned directory descriptors with
no-follow semantics, snapshots and hashes each regular file through that one open
descriptor, retries files that change identity or metadata, and fails closed when
descriptor-relative access is unavailable. Only stable records reach the cache.
Repository-relative paths containing backslashes fail closed instead of being
normalized into a different file identity during workspace mirroring.

After successful delivery:

1. Manageroo generates a binary-capable Git patch from isolated baseline to final checkpoint.
2. Manageroo writes `delivery/final-result.json`, `delivery/FINAL-REPORT.md`, and `delivery/final.patch` with `applied_to_source: false`.
3. Manageroo verifies that every source file still matches the original source manifest.
4. `git apply --check` verifies the patch.
5. Manageroo revalidates the source immediately before applying the patch.
6. The controller applies the patch when `--apply` or project policy allows it.
7. Manageroo verifies the applied tree against the reviewed workspace; if a concurrent edit is
   detected, it reverse-checks and reverses only its patch while preserving that edit.
8. The controller rewrites the final result and report with `applied_to_source: true`.

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

ClawPatch queue supervision is an optional external integration. The standalone `clawpatch-supervise` package owns finding transitions, partial-progress commits, checkpoints, recovery, validation environments, fixed-point review, and service exit policy.

Manageroo keeps only an argv adapter in `clawpatch_release.py`. A dry run renders the exact standalone command. An applying run resolves the installed executable, requires its `--version` output to match the declared supervisor version exactly, invokes it with `shell=False`, streams its terminal output, and returns its exit code unchanged. The release-ready gate asks that executable for its external state path before reading the proof, so Manageroo does not duplicate platform path or checkpoint logic.

The package metadata no longer publishes a `clawpatch-supervise` console script, and Manageroo does not import the standalone Python package. Native supervisor installers and the ownership-checked stack updater pin the public standalone repository independently. Before mutating an owned supervisor environment, the updater installs a tiny stdlib-only console-entry gate. Direct, service, and Manageroo-mediated queue launches then hold the same cross-platform installation lock for their complete lifetime, while updates hold it across package mutation and verification. A one-time platform process snapshot covers only migration from the older ungated launcher; it is not the ongoing synchronization primitive.

## Parallel mapping and review, sequential implementation

Tasks are dependency ordered and executed sequentially in the same isolated integration repository. This is slower than unconstrained parallel editing but avoids incompatible branches and hidden interface assumptions.

Repository mapping and isolated review may run as bounded parallel worker calls. Their packet names, output files, artifact writes, budgets, and completion state remain controller-owned. Manageroo does not run parallel implementation branches against the same files.

## Recommended surrounding stack

The surrounding stack provides first-class capabilities without taking control away from Manageroo:

- **GitNexus**: recommended repository/code-graph intelligence for exploration, dependency awareness, impact analysis, debugging, and refactoring. The installer can install and configure GitNexus. Repository indexing is project-specific. Manageroo remains usable when GitNexus is intentionally skipped or unavailable.
- **GBrain**: external durable knowledge retrieval and capture when a task explicitly needs external memory or a knowledge base.
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
predated the lane are fingerprinted in checkpoint state, preserved across controller commits, and
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

Controller policies and saved prose preferences are not ordinary task
capabilities. In particular, `use-installed-skills-first` is native Manageroo
behavior, while normal/Caveman/Caveman Curse remains installer-selected state.
Skill-pack and token-mode installation is serialized with a permanent advisory
file lock, so another process cannot enter while owner diagnostics are still
being published. Existing lock inodes must be private regular files and are
never truncated or rewritten.

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
