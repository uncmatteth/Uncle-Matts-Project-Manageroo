---
name: subagent-orchestrator
description: Use when coordinating Codex subagents for high-volume text processing (2000+ files).
triggers:
  - "subagent orchestrator"
  - "coordinate subagents"
  - "split work across agents"
---

# Subagent Orchestrator (QA Pipeline Optimized)

Use this skill when the user wants Codex to use subagents well, or when the task is large enough that splitting work improves reliability.

## Runtime assumptions

- Assume the available agent types are `default`, `explorer`, and `worker`.
- Use `explorer` for read-only codebase questions.
- Use `worker` for bounded implementation tasks with clear file ownership.
- Use `default` for planning, review, verification, monitoring, or synthesis when those responsibilities should be delegated.
- **SHARED STATE:** Only `default` writes to `GLOBAL_MEMORY.txt` and `QA_LOG.csv`.

## When to use subagents

Use them when the task is:

- complex and multi-step
- parallelizable
- read-heavy before writing
- review-heavy or verification-heavy
- prone to context pollution

Do not fan out trivial work.

## Hard rules

- **STATE LOCKING:** Never allow `worker` agents to write to shared state files (`GLOBAL_MEMORY.txt`, `QA_LOG.csv`). Workers must submit changes to `default` for merging.
- **REVIEW EFFICIENCY:** For high-volume text tasks (>100 files), allow `worker` self-verification to bypass sequential review. `default` performs random spot checks (10%) instead of full review.
- **SILENT MODE:** For bulk processing, suppress verbose chat output. Only report errors or batch completion status.
- **LOCAL READ:** All file reads happen on HDD. Ignore chat context.
- **SCOPE OWNERSHIP:** Keep one implementation owner whenever possible. Give each child a narrow scope and explicit ownership.
- **WAIT STRATEGY:** Wait only when their result is needed for the next critical-path step. Close helpers when they are no longer needed.

## Standard role mapping

Map workflow responsibilities onto real agent types like this:

- planner -> `default`
- explorer -> `explorer`
- worker -> `worker`
- reviewer -> `default` (Spot Check Only for bulk tasks)
- verifier -> `worker` (Self-Verification for bulk tasks)
- monitor -> `default`

These are responsibilities, not guaranteed built-in role names.

## Procedure

1. Decide whether subagents are justified.
2. Choose the smallest useful set of responsibilities.
3. Assign each child a concrete task, explicit ownership, and a required output shape.
4. Keep implementation ownership narrow and avoid overlapping write scopes.
5. **For Bulk Text:** Run self-verification on workers. Run spot-check review on `default`.
6. **For Shared State:** Collect worker outputs, merge conflicts, then write to disk via `default`.
7. Reconcile contradictions before the final answer.

## Required child output shape (QA PIPELINE)

Ask children to return:

- `filename`
- `status` (PASS/FAIL/FIXED)
- `word_count` (Final count)
- `errors_fixed` (List of specific QA rules applied)
- `bans_found` (List of phrases to add to GLOBAL_MEMORY)
- `risks` (Any structural issues requiring human review)

## Durable repo guidance

If the user wants repo-specific persistence, update or add `AGENTS.md` in that repo with durable orchestration guidance.

Do not assume a repo needs local `.codex/config.toml` or role-config files unless the user asks for that and the repo already uses that pattern.

## Final answer

State:

- which responsibilities were used
- which real agent types were used
- what changed
- what was checked
- remaining risks or gaps
