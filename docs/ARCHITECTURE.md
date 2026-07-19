# Architecture

## Thin controller, strong artifacts

Manageroo deliberately avoids becoming another IDE, code graph database, memory system, or model host. The controller coordinates workers and surrounding tools through durable, inspectable artifacts.

```text
CLI
 └─ Orchestrator
     ├─ State machine
     ├─ Artifact ledger and locked contracts
     ├─ Source mirror
     ├─ Context compiler
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

## Controller-owned commits

Agents are forbidden from committing. The isolated repository contains a failing pre-commit hook. The controller also compares `HEAD` before and after every agent role. Once scope, acceptance evidence, review, and gates pass, the controller creates an internal checkpoint while bypassing the hook itself.

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

These systems are capabilities, not completion authorities.

```text
GitNexus / GBrain / AUTOREVIEW / Clawpatch / Obsidian
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

## Proactive learning, no silent self-mutation

Every run can emit improvement cards under `artifacts/learning/improvement-cards.json` and copy pending cards into `.manageroo/cache/learning/pending/`.

Those cards are structured suggestions. They rank value and risk, route the lesson to a destination such as project memory, skill improvement, config, docs, installer, GBrain capture, or backlog, and cite run evidence.

The controller may save pending cards automatically. It must not silently change behavior, skills, config, docs, installer behavior, or memory. Applying a supported card requires:

```bash
manageroo learning apply CARD_ID --approve
```
