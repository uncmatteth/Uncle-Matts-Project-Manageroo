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

Completed jobs are loaded from recorded artifacts. They are not rerun merely because a chat was compacted or a new worker process starts. A completed job record must include a matching output-artifact SHA-256 hash or it is treated as stale.

`manageroo run --continue <run-id>` replays the Python controller from the saved run folder. The old worker process is not trusted or required. Replay keeps logical job IDs stable so later attempts continue the original job instead of creating shifted duplicate work.

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

Clawpatch release commits use the current successful patch-attempt record as the
only source-path allowlist. Manageroo stages only those source paths after full
project validation and exact `fixed` revalidation. It never builds a finding
queue from reports, commits partial repairs, or mixes `.clawpatch/**` state into
a repair commit. The Manageroo project command requires configured Manageroo
gates and runs them against the unchanged repository baseline. The separately
installed external supervisor is portable to any Git repository: it runs those
gates when present, otherwise leaves validation to Clawpatch's applied `fix`
result and exact-finding revalidation instead of inventing test commands. Its
checkpoint and proof artifacts live in the Manageroo-owned external-runner state
directory rather than in the target worktree or Git metadata. A red configured
baseline is reported with the exact failing gate, command, exit code, and captured
output; Clawpatch is not sent into a finding repair that cannot possibly satisfy
the mandatory whole-project gate. The cross-platform controller reviews all pending Clawpatch
features, obtains one current open finding from `next --json`, records `show`
for auditability, and automatically chooses Clawpatch's finding-scoped `fix`.
The human triage template printed by `show` is not treated as executable and
Manageroo never issues a triage command. Each current finding receives one
Clawpatch-owned `fix`. Any failed or unsupported transition stops with the exact
changed source paths visible and checkpointed; Manageroo does not stash, reopen,
retry, skip, remap, hand-repair, advance, commit, or push that finding.
Read-only revalidation that cannot execute targeted tests gets one
workspace-write validation retry guarded by an exact source-state fingerprint;
it cannot silently modify the repair. A durable per-finding progress record binds
the repository, branch, HEAD, finding, phase, and exact owned source paths.
Ordinary relaunch refuses continuation; explicit `--fresh` is the only automatic
recovery and requires an exact ownership match before discarding those paths.
One explicit timeout controls both the child-process watchdog
and the ClawPatch provider and kills the complete Clawpatch/Codex process group.
Operator interruption also terminates and reaps that complete child group before
the supervisor exits.
Every failed command stops immediately and is not retried.
An explicit fresh run may discard dirty source only when durable progress binds
the interrupted `fix` to the current repository, branch, and compatible HEAD,
and the dirty-path set exactly matches the checkpoint's recorded owned paths. Unrelated dirty paths
block without mutation.

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
