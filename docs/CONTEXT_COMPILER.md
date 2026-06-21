# Context compiler

## Problem

A model context window is finite. Replaying an entire chat, repository, product notebook, and previous agent transcript causes omission, stale assumptions, lost-in-the-middle behavior, and expensive repetition.

UMSMFBURASBOFE treats context as a compiled artifact.

## Packet structure

Every role receives a packet directory:

```text
packets/NNN-role/
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
- every omitted optional source and reason.
- context mode: full source or generated summary.

## Hard rules

1. Required context is never silently truncated.
2. A required file slice exceeding the single-file limit blocks the plan.
3. A required packet exceeding the total budget blocks or forces decomposition.
4. Optional context may be omitted only with an explicit manifest reason.
5. A packet becomes stale when any included source hash changes.
6. Fresh agent processes receive artifacts, not previous chat transcripts.
7. Planning artifacts have explicit size limits and must be reduced before the next phase.
8. Review is partitioned across changed-code chunks when the changed set exceeds the review packet budget.
9. Media files are represented as generated metadata summaries, not silently skipped.
10. Oversized prose can be included through explicit summary mode; full required prose still must be sliced or decomposed.

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

## Media and prose

Git-visible images, PDFs, audio/video assets, and design files are included in
inventory as media. The context packet includes metadata such as path, suffix,
bytes, SHA-256, image dimensions when available, and approximate PDF page count
when available. This is not OCR, screenshot analysis, or vision interpretation.

Long Markdown/text/prose files are inventoried with line counts and generated
summaries. A role may receive summary mode for discovery and planning. A task
that needs exact prose still has to request line ranges that fit the context
budget.

## Summary cache

Discovery caches file, media, and prose summaries here:

```text
.umsmfburasbofe/cache/file-summaries.json
.umsmfburasbofe/cache/system-map.json
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
