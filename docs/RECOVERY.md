# Recovery

## A run fails

Inspect:

```bash
manageroo status <run-id>
manageroo report <run-id>
```

The run directory preserves:

```text
state.json
source-snapshot.json
packets/
agent-output/
artifacts/
logs/
review-workspace/
delivery/failure.json
delivery/FINAL-REPORT.md
```

A failed run does not apply its patch to the source repository.

## The source changed during a run

MANAGEROO blocks application. Preserve both sets of work. Start a new run from the current source state. Do not force-apply the old patch without a developer review.

## An agent edited outside scope

MANAGEROO blocks before the controller checkpoint. The isolated mirror contains the evidence; the source remains unchanged. Tighten the plan or task boundary, then start a new run.

## A gate repeatedly fails

After the bounded repair count, the run becomes `BLOCKED`. This is evidence that the task, acceptance oracle, environment, or architecture needs a product/technical decision. Increasing the loop count is not the default remedy.

## Reviewer disagreement

Only evidence-backed current-file findings are accepted. Invalid paths, stale lines, or mismatched quotes cause review validation failure. Deterministic tests take precedence over reviewer rhetoric.

## Backup

The source repository is not modified until successful delivery, but ordinary Git remote backups remain recommended. MANAGEROO is not a backup system.
