# Context compiler

## Problem

A model context window is finite. Replaying an entire chat, repository, product notebook, and previous agent transcript causes omission, stale assumptions, lost-in-the-middle behavior, and expensive repetition.

MANAGEROO treats context as a compiled artifact.

Chat compaction is not the source of truth. The repo-local intent lock is the
truth surface for the operator's current ask, must-not rules, rejected ideas,
latest corrections, proof, open questions, and scope boundaries. A compacted
summary or handoff has to preserve that truth before the next long-running agent
step can rely on it.

## Packet structure

Every role receives a packet directory:

```text
packets/<job-id>/<attempt-id>/
├── prompt.md
└── manifest.json
```

The manifest records:

- usable token budget;
- reserved output budget;
- estimated packet tokens;
- instruction hash;
- prompt hash;
- each source path;
- exact included line range;
- source SHA-256;
- excerpt SHA-256;
- inclusion reason;
- required/optional status;
- every omitted optional source and reason;
- context mode: full source or generated summary;
- each included evidence item's source, location, authority, confidence, freshness, retrieval timestamp, and content hash;
- evidence omitted because the bounded packet budget was already consumed.

## Hard rules

1. Required context is never silently truncated.
2. A required file slice exceeding the single-file limit blocks the plan.
3. A required packet exceeding the total budget blocks or forces decomposition.
4. Optional context may be omitted only with an explicit manifest reason.
5. A packet becomes stale when any included repository source hash changes.
6. Fresh agent processes receive artifacts, not previous chat transcripts.
7. Planning artifacts have explicit size limits and must be reduced before the next phase.
8. Review is partitioned across changed-code chunks when the changed set exceeds the review packet budget.
9. Media files are represented as generated metadata summaries, not silently skipped.
10. Oversized prose can be included through explicit summary mode; full required prose still must be sliced or decomposed.
11. Intent locks are audited with a strict phrase-preservation audit before a compact summary is trusted.
12. Worker jobs are stateless. A retry receives a fresh packet generated from controller-owned facts, not from the previous worker's memory.
13. Completed jobs are loaded from recorded artifacts and hashes, not rerun from a compacted chat summary. Missing artifact hashes make the job stale.
14. Continue reuses the original saved job when the logical worker call already exists, so skipped completed phases do not shift later failed jobs.
15. Required repository context is budgeted before retrieved evidence.
16. Retrieved evidence is context, not controller truth, and cannot override current repository state, locked decisions, gates, review, or completion proof.
17. Evidence provenance survives packet compilation. If an excerpt is clipped to fit the per-item budget, the original content hash remains recorded.

## Intent lock and compaction audit

`manageroo solo` writes:

```text
.manageroo/intent/INTENT-LOCK.json
.manageroo/intent/INTENT-LOCK.md
```

Run this when a long thread is summarized, compacted, or handed off:

```bash
manageroo compact audit --summary SUMMARY.md
```

The audit checks for exact locked phrases. That is intentionally strict. If the
operator said "Do not deploy production", a compacted summary that only says
"be careful with release stuff" is not good enough.

## Repository map/reduce

For a large repository:

```text
Git-visible inventory
→ deterministic token estimates
→ bounded file chunks
→ fresh repository-mapper role per chunk
→ canonical map reducer
→ locked system map
```

No mapper is expected to remember or inspect the entire repository.

## Evidence retrieval

Discovery may produce `artifacts/discovery/evidence.json`. Manageroo normalizes successful configured GitNexus and GBrain output together with selected native project/run evidence, ranks it by authority, confidence, and freshness, and preserves contradictions when providers supply a shared claim key.

For planning roles, the controller selects a small bounded subset of the highest-ranked evidence and records that selection in the worker job specification. `ContextCompiler` then renders those records as explicit evidence blocks after required repository files.

The evidence layer does not replace direct file context. GitNexus can provide structural repository intelligence and GBrain can provide external durable knowledge, but exact current code and locked Manageroo artifacts remain stronger evidence.

See `docs/EVIDENCE_RETRIEVAL.md`.

## Media and prose

Git-visible images, PDFs, audio/video assets, and design files are included in
inventory as media. The context packet includes metadata such as path, suffix,
bytes, SHA-256, image dimensions when available, and approximate PDF page count
when available. This is not OCR, screenshot analysis, or vision interpretation.

Long Markdown/text/prose files are inventoried with line counts and generated
summaries. A role may receive summary mode for discovery and planning. A task
that needs exact prose still has to request line ranges that fit the context
budget.

The document/prose lane adds a command-owned evidence hook on top of that
inventory. Each run writes `document-manifest.json`; a configured
`document_analysis_command` can read it and produce additional intelligence in
`document-intelligence.json`. Missing or failing document commands are recorded
as optional context. They do not become permission for a model to freehand a
whole book, transcript, PDF, or exact-text replacement.

## Summary cache

Discovery caches file, media, and prose summaries here:

```text
.manageroo/cache/file-summaries.json
.manageroo/cache/system-map.json
```

The cache key is the repository-relative path plus file size and SHA-256. An
unchanged file reuses its summary on later runs. A changed file is summarized
again.

The system-map cache is exact-match only. It is reused only when the inventory
fingerprint and product brief hash match the cached run. That avoids carrying a
map from one product request into a different one. The cache does not replace
source hashes or stale-packet checks.

## Task context

The plan compiler assigns `context_paths` and `allowed_paths` to each task. The context compiler builds a packet from those files. If a task cannot fit, the task is invalid and must be split before implementation.

## External memory

GBrain and Obsidian may contribute selected relevant notes. They do not dump all memory into the packet. Retrieved excerpts are treated as evidence with explicit provenance and can never override current repository facts or locked product decisions.
