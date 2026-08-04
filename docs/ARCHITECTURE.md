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

The source repository is inventoried through Git-visible tracked and unignored files. Manageroo copies those files into a run-owned repository and commits an internal baseline. Coding agents never need direct write access to the operator's source repository.

After successful delivery:

1. Manageroo generates a binary-capable Git patch from isolated baseline to final checkpoint.
2. Manageroo writes `delivery/final-result.json`, `delivery/FINAL-REPORT.md`, and `delivery/final.patch` with `applied_to_source: false`.
3. Manageroo verifies that every source file still matches the original source manifest.
4. `git apply --check` verifies the patch.
5. The controller applies the patch when `--apply` or project policy allows it.
6. The controller rewrites the final result and report with `applied_to_source: true`.

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

Clawpatch release commits use exact source paths owned by the current finding.
Manageroo stages only those source paths. A validation-failed-after-apply result
or `open` revalidation creates or amends one recognizable local-only temporary
iteration commit, then the same finding's `fix` runs again from the clean
combined tree. Only exact `fixed` completes the finding and converts changed
source into one normal commit directly above the finding's original HEAD. When
an overlapping earlier finding already supplied the repair, exact `fixed` with
unchanged HEAD and no source changes completes without manufacturing an empty
commit or push. It never
builds a finding queue from reports or mixes `.clawpatch/**` state into a source
commit. The Manageroo project command requires configured Manageroo
gates and runs them against the unchanged repository baseline. The separately
installed external supervisor is portable to any Git repository: it runs those
gates when present, otherwise leaves validation to Clawpatch's applied `fix`
result and exact-finding revalidation instead of inventing test commands. Its
checkpoint and proof artifacts live in the Manageroo-owned external-runner state
directory rather than in the target worktree or Git metadata. A red configured
baseline is reported with the exact failing gate, command, exit code, and captured
output; Clawpatch is not sent into a finding repair that cannot possibly satisfy
the mandatory whole-project gate. A gate that exits successfully but changes any
tracked or unignored project source also stops before map or review, with the exact
paths left visible; validation side effects are never treated as finding input. The
cross-platform controller reviews all pending Clawpatch
features in bounded worker waves. Before each wave, ClawPatch's review dry-run
reports the pending count and current job count. Manageroo runs one
`review --limit <jobs>` child and requires the next dry-run to decrease pending
features by exactly the child's reviewed count. There is no arbitrary wave cap;
zero pending completes review, no progress stops, and the 900-second process-tree
watchdog remains enforced per child instead of spanning the whole repository.
On Windows, argv-only child execution resolves native command shims and invokes
`.cmd` or `.bat` launchers through `COMSPEC /d /s /c` while retaining
`shell=False`. The native installer records the exact supported Node directory it
verified, pins that directory in the generated launcher, and enables UTF-8 Python
I/O. Controller child readers decode UTF-8 with replacement so one malformed byte
cannot erase gate diagnostics, and output sanitization accepts absent streams.
Persistent byte-range lock files update owner metadata in place
instead of truncating a file another Windows process has locked. Git reference
transactions use an exact binary UTF-8/LF protocol, and console status markers
fall back to ASCII when the active stream encoding cannot represent Unicode.
The release verifier gives the complete native unit suite its own 900-second
limit so the verifier does not terminate a healthy Windows run at five minutes.
macOS filesystem identity checks canonicalize the `/var` to `/private/var`
alias before containment and package-manager ownership comparisons. The native
macOS installer also discovers Homebrew at its standard Apple Silicon and Intel
locations when a non-login shell does not include Homebrew on `PATH`.
Before the queue, the external supervisor may satisfy one narrowly discovered
repository validation contract: tests that explicitly require
`TEST_DATABASE_URL` plus an `*_ALLOW_DATABASE_RESET` guard, together with one
root Compose file declaring one official versioned PostgreSQL image. Manageroo
does not start that Compose stack or use its volumes. It creates a separately
named Docker container with tmpfs database storage, a random password, and one
random loopback-only port, then passes the URL and reset guard only to child
ClawPatch processes. Repository identity labels prove ownership before stale
container recovery or deletion. An unknown image, ambiguous Compose state,
missing reset guard, foreign same-named container, or unavailable Docker fails
closed or leaves automatic provisioning disabled; no existing database is
reset. Cleanup runs after completion, stop, failure, or interruption and a
cleanup failure is reported.
The controller then obtains one current open finding from `next --json`, records `show`
for auditability, and automatically chooses Clawpatch's finding-scoped `fix`.
The human triage template printed by `show` is not treated as executable and
Manageroo never issues a triage command. There is no arbitrary fix-attempt cap,
but another attempt is permitted only when ClawPatch produced a genuinely new
source-tree state. No source changes, a repeated state, a cycle to the original
tree, temporary-history mismatch, or an external failure stops with combined
source changes visible at the original HEAD. Manageroo does not stash, triage,
skip, remap, hand-repair, push temporary work, or advance to another finding.
Read-only revalidation that cannot execute targeted tests gets one
workspace-write validation retry guarded by an exact source-state fingerprint;
the external supervisor then permits one child-scoped trusted-host pass if the
writable sandbox still blocks required local sockets or locks. No revalidation
pass can silently modify the repair. A durable per-finding progress record binds
the repository, branch, HEAD, finding, phase, and exact owned source paths.
Final closure also uses ClawPatch's own status-filtered queue transition for
pre-existing uncertainty: `next --status uncertain`, `show`, then guarded
exact-finding revalidation. `fixed` closes without a source commit, `open`
re-enters the normal same-finding repair loop, and a second `uncertain` stops as
an external validation blocker.
Queue exhaustion is only generation closure. When that generation found or
recovered findings, Manageroo preserves committed ClawPatch configuration,
rebuilds generated run/discovery state, maps the resulting HEAD, and completes
another full review. It repeats until a fresh full review generation finds zero
findings. There is no arbitrary generation cap; a repeated non-clean source
tree is deterministic nonconvergence and stops. Only the clean terminal
generation can authorize `COMPLETE`, final state cleanup or publication, and
the fixed-point proof that records every reviewed generation.
Ordinary relaunch resumes a stopped applied attempt only when the durable
checkpoint's branch, finding, and exact dirty path set agree, and exactly one
applied Clawpatch patch-attempt record matches current HEAD. It resumes at gates
and revalidation without invoking `fix` again; an `open` outcome creates the
same local-only temporary iteration and continues the same finding without a
push. Any mismatch or ambiguity refuses continuation and preserves the
checkpoint and edits. The Manageroo project command's
explicit `--fresh` requires an exact ownership match before discarding paths.
An older stopped checkpoint may own zero paths because exact revalidation
already returned `fixed` for an overlapping repair. Ordinary relaunch retires
that checkpoint without rerunning `fix`, committing, or pushing only when the
source tree is clean, checkpoint HEAD is current, the same finding remains
`fixed`, and an applied zero-file patch attempt is bound to that HEAD.
The stopped checkpoint also records an exact source-content fingerprint. When an
operator rebuilds `.clawpatch`, ordinary relaunch recognizes the newer empty run
generation only if repository, branch, HEAD, owned paths, and fingerprint still
agree. It then restores only those owned paths and clears the obsolete checkpoint;
changed or additional source paths fail closed. Legacy version-2 checkpoints use
their narrower pre-checkpoint file-timestamp proof for this one compatibility path.
When a stopped checkpoint owns no source paths and the old finding disappeared in
a later ClawPatch generation, relaunch may retire only that external checkpoint
after proving a clean worktree, a newer generation on the same branch, and the
checkpoint-HEAD to generation-HEAD to current-HEAD ancestry chain. The later
generation may already contain committed findings and runs because no source
cleanup is performed in this zero-path transition.
If interruption leaves a source-clean `planned` attempt, ordinary relaunch
requires the same open finding, branch, current HEAD, empty changed-file record,
and no active process. It preserves ClawPatch state and reenters only through
`next`; that command must return the same finding before `show` and `fix` run.
When the worktree is source-clean because the stopped attempt was already
committed, the external supervisor clears the stale checkpoint only after Git
proves that one descendant commit's complete non-ClawPatch path set exactly
equals the checkpoint-owned paths. A new external repository is initialized
automatically, making bare `clawpatch-supervise` the normal universal interface.
Every bare external invocation starts fresh. It first proves and recovers any
temporary iteration commit, then discards only the exact checkpoint-owned dirty
paths before rebuilding ClawPatch run/discovery state. Unrelated dirty source
blocks unchanged. If the worktree is clean and Git proves that the current
branch advanced from the checkpoint's original HEAD without containing the
checkpoint's temporary commit, that dangling checkpoint is obsolete: fresh
startup retires only the external checkpoint and preserves the current commit
and files exactly.
After a fresh complete review finds zero findings, final open and uncertain
reports are empty, and every gate passes, generated ClawPatch runtime state is
removed and the committed `.clawpatch` tree is restored exactly unless the
operator explicitly authorized a separate state-only commit. An exact source
fingerprint guards this cleanup. A prior nonempty generation cannot take this
terminal path; it must start the next fresh review generation instead.
One explicit timeout controls both the child-process watchdog
and the ClawPatch provider and kills the complete Clawpatch/Codex process group.
Operator interruption also terminates and reaps that complete child group before
the supervisor exits.
Every failed non-fix command stops immediately. Only ClawPatch's source-
progressing same-finding continuation may invoke `fix` again.
An explicit fresh run through the Manageroo project command may discard dirty
source only when durable progress binds the interrupted `fix` to the current
repository, branch, and compatible HEAD, and the dirty-path set exactly matches
the checkpoint's recorded owned paths. The separately installed external
supervisor uses the same exact-ownership boundary and never treats `--fresh` as
permission to discard unrelated source.

## Parallel mapping and review, sequential implementation

Tasks are dependency ordered and executed sequentially in the same isolated integration repository. This is slower than unconstrained parallel editing but avoids incompatible branches and hidden interface assumptions.

Repository mapping and isolated review may run as bounded parallel worker calls. Their packet names, output files, artifact writes, budgets, and completion state remain controller-owned. Manageroo does not run parallel implementation branches against the same files.

## Recommended surrounding stack

The surrounding stack provides first-class capabilities without taking control away from Manageroo:

- **GitNexus**: recommended repository/code-graph intelligence for exploration, dependency awareness, impact analysis, debugging, and refactoring. The installer can install and configure GitNexus. Repository indexing is project-specific. Manageroo remains usable when GitNexus is intentionally skipped or unavailable.
- **GBrain**: external durable knowledge retrieval and capture when a task explicitly needs external memory or a knowledge base.
- **AUTOREVIEW**: command-owned external review lane.
- **Clawpatch**: command-owned review and repair lane. Its own command owns its findings and repairs.
- **Obsidian**: human-readable Markdown knowledge lane.
- **Document/prose command lane**: optional evidence over a run-owned manifest for long prose, PDFs, transcripts, articles, and exact-text workflows.

Successful external repair reports are reusable only for the same run, command configuration,
approved paths, and inputs. Continuation verifies the recorded checkpoint chain and Git diffs,
then restores the exact clean final checkpoint; incomplete legacy reports fail closed.

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
HEAD, source-digest, and cleanliness snapshot. The repository's configured gate uses
`verify_release.py --check-only` and an isolated bytecode cache; the normal
operator invocation still refreshes `BUILD-VALIDATION.json`.

## Proactive learning, no silent self-mutation

Every run can emit improvement cards under `artifacts/learning/improvement-cards.json` and copy pending cards into `.manageroo/cache/learning/pending/`.

Those cards are structured suggestions. They rank value and risk, route the lesson to a destination such as project memory, skill improvement, config, docs, installer, GBrain capture, or backlog, and cite run evidence.

The controller may save pending cards automatically. It must not silently change behavior, skills, config, docs, installer behavior, or memory. Applying a supported card requires:

```bash
manageroo learning apply CARD_ID --approve
```
