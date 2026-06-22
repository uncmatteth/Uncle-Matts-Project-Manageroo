# Architecture

## Thin controller, strong artifacts

MANAGEROO deliberately avoids becoming another IDE, code graph database, memory system, or model host. The controller coordinates existing agents through a small number of durable primitives.

```text
CLI
 └─ Orchestrator
     ├─ State machine
     ├─ Artifact ledger and locked contracts
     ├─ Source mirror
     ├─ Context compiler
     ├─ Durable worker job store
     ├─ Agent adapter
     ├─ Scope/command policies
     ├─ Deterministic gate runner
     ├─ Isolated reviewer
     ├─ Proactive learning card writer
     └─ Delivery reporter
```

## Source isolation

The source repository is inventoried through Git-visible tracked and unignored files. MANAGEROO copies those files into a run-owned repository and commits an internal baseline. Coding agents never need direct write access to the operator's source repository.

After successful delivery:

1. MANAGEROO generates a binary-capable Git patch from isolated baseline to final checkpoint.
2. MANAGEROO verifies that every source file still matches the original source manifest.
3. `git apply --check` verifies the patch.
4. The controller applies the patch when `--apply` or project policy allows it.

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

MANAGEROO is not "AI remembers better." MANAGEROO makes remembering
unnecessary.

The controller writes the run truth to disk. Each AI worker gets one complete
assignment packet. If a worker drifts, dies, lies, or runs out of room, the
controller records the failed attempt and starts a fresh worker from saved
facts.

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

Completed jobs are loaded from their recorded artifacts. They are not rerun
just because a chat was compacted or a new agent process starts.

`manageroo run --continue <run-id>` replays the Python controller from the
saved run folder. The old worker process is not trusted or required; completed
jobs, locked artifacts, and the isolated workspace are loaded from disk.

## Controller-owned commits

Agents are forbidden from committing. The isolated repository contains a failing pre-commit hook. The controller also compares `HEAD` before and after every agent role. Once scope and gates pass, the controller creates an internal checkpoint while bypassing the hook itself.

## Parallel map/review, sequential implementation

Tasks are dependency ordered and executed sequentially in the same isolated integration repository. This is slower than unconstrained parallel editing but avoids incompatible branches and hidden interface assumptions. Repository mapping may run as bounded map/reduce; implementation prioritizes correctness over theatrical agent count.

Independent repository-mapper chunks and isolated reviewer chunks can run in
parallel through separate fresh agent calls. Their packet names, output files,
and artifact ledger writes stay controller-owned. The controller does not run
parallel implementation branches against the same files.

## External systems

The surrounding stack provides lanes, not authorities:

- GBrain: durable memory retrieval/capture.
- GitNexus: supplementary code graph analysis.
- Obsidian: human-readable Markdown knowledge.
- Document/prose command lane: optional evidence over a run-owned manifest for
  long prose, PDFs, transcripts, articles, and exact-text workflows.
- Clawpatch/AUTOREVIEW: command-owned review/repair lanes that run their own
  configured commands; their findings are never converted into AI freehand fixes.
- OpenClaw/Claude/Gemini/Cursor: alternate execution surfaces.

Core acceptance still belongs to MANAGEROO's state, scope, gates, and evidence.

## Proactive learning, no silent self-mutation

Every run can emit improvement cards under
`artifacts/learning/improvement-cards.json` and copy pending cards into
`.manageroo/cache/learning/pending/`.

Those cards are structured suggestions. They rank value and risk, route the
lesson to a destination like project memory, skill improvement, config, docs,
installer, GBrain capture, or backlog, and cite run evidence.

The controller may save pending cards automatically. It must not silently change
behavior, skills, config, docs, installer behavior, or memory. Applying a
supported card requires `manageroo learning apply CARD_ID --approve`.
