# Architecture

## Thin controller, strong artifacts

UMSMFBURASBOFE deliberately avoids becoming another IDE, code graph database, memory system, or model host. The controller coordinates existing agents through a small number of durable primitives.

```text
CLI
 └─ Orchestrator
     ├─ State machine
     ├─ Artifact ledger and locked contracts
     ├─ Source mirror
     ├─ Context compiler
     ├─ Agent adapter
     ├─ Scope/command policies
     ├─ Deterministic gate runner
     ├─ Isolated reviewer
     └─ Delivery reporter
```

## Source isolation

The source repository is inventoried through Git-visible tracked and unignored files. UMSMFBURASBOFE copies those files into a run-owned repository and commits an internal baseline. Coding agents never need direct write access to the operator's source repository.

After successful delivery:

1. UMSMFBURASBOFE generates a binary-capable Git patch from isolated baseline to final checkpoint.
2. UMSMFBURASBOFE verifies that every source file still matches the original source manifest.
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

## Controller-owned commits

Agents are forbidden from committing. The isolated repository contains a failing pre-commit hook. The controller also compares `HEAD` before and after every agent role. Once scope and gates pass, the controller creates an internal checkpoint while bypassing the hook itself.

## Sequential implementation by default

Tasks are dependency ordered and executed sequentially in the same isolated integration repository. This is slower than unconstrained parallel editing but avoids incompatible branches and hidden interface assumptions. Repository mapping may run as bounded map/reduce; implementation prioritizes correctness over theatrical agent count.

## External systems

The surrounding stack provides lanes, not authorities:

- GBrain: durable memory retrieval/capture.
- GitNexus: supplementary code graph analysis.
- Obsidian: human-readable Markdown knowledge.
- Clawpatch/AUTOREVIEW: supplementary review engines.
- OpenClaw/Claude/Gemini/Cursor: alternate execution surfaces.

Core acceptance still belongs to UMSMFBURASBOFE's state, scope, gates, and evidence.
