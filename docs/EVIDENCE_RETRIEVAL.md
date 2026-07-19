# Evidence Retrieval Architecture

Manageroo does not have AI memory. Manageroo retrieves evidence.

The controller remains the authority for task scope, run state, verification gates, review, proof, patch application, and completion. Retrieval systems can inform a run; they cannot certify one.

## Provider boundary

Manageroo can normalize evidence from multiple sources without turning any provider into a hard dependency or a completion authority:

- current repository intelligence, including GitNexus;
- locked Manageroo run artifacts;
- explicit project decisions and project memory;
- GBrain knowledge sources;
- future external providers that satisfy the same provenance contract.

The built-in evidence layer is implemented in `src/manageroo/evidence.py`. Discovery integration lives in `src/manageroo/evidence_policy.py`.

## Evidence contract

Every evidence item carries:

- `content`;
- `source`;
- `location` when known;
- `authority`;
- `confidence`;
- `freshness`;
- `created_at` when supplied by the source;
- `retrieved_at`;
- `content_sha256`;
- provider metadata.

External providers may return structured JSON or plain text. Structured output can preserve richer provenance. Plain text remains usable, but Manageroo does not invent missing source details.

## Ranking

Ranking is deterministic and intentionally favors current authoritative evidence over old context:

1. current repository evidence;
2. Manageroo run evidence;
3. explicit project decisions;
4. curated project memory;
5. external knowledge;
6. historical evidence;
7. unknown provenance.

Confidence and freshness refine the ordering inside those authority classes. A high-confidence old note does not automatically outrank current repository truth.

## Contradictions

Manageroo preserves conflicting evidence instead of silently overwriting it.

Providers can attach `metadata.claim_key` when multiple records describe the same fact. If records with the same claim key have different content hashes, Manageroo records a contradiction and identifies the highest-ranked item as preferred context. Lower-ranked evidence remains visible.

The preferred item is not automatically declared true. It is simply the strongest retrieved evidence under the ranking policy. Current repository inspection and deterministic proof still win when correctness matters.

## Context compilation

`ContextCompiler` accepts ranked `EvidenceItem` objects in addition to repository `ContextRequest` files.

Required repository context is budgeted first. Retrieved evidence then uses the remaining packet budget. Each included evidence block retains provenance and its original content hash in the packet manifest. Evidence that does not fit is recorded as omitted rather than silently treated as included.

Worker prompts explicitly state that retrieved evidence is context, not controller truth.

## Discovery integration

Manageroo's existing discovery lanes already run configured GitNexus and GBrain commands. The evidence policy normalizes successful provider output plus native project/run evidence into:

```text
.manageroo/runs/<run-id>/artifacts/discovery/evidence.json
```

That artifact contains ranked evidence, contradictions, provider errors when applicable, and the authority rule used by the controller.

GitNexus remains the first-class repository/code-graph intelligence integration. GBrain remains the external durable knowledge lane. Manageroo artifacts remain durable run evidence. None of them can mark a run `COMPLETE`.

## Non-goals

Manageroo does not bundle a giant vector database, crawl private systems automatically, or claim that semantic retrieval is truth.

It also does not replace direct repository reads with embeddings. Exact current code, locked controller artifacts, scope checks, gates, review evidence, and release proof remain the authoritative path to completion.
