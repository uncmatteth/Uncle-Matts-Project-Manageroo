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
controller/truth.json
controller/phase-journal.jsonl
jobs/
worker-attempts/
packets/<job-id>/<attempt-id>/
agent-output/<job-id>/<attempt-id>.json
artifacts/
logs/
review-workspace/
delivery/failure.json
delivery/FINAL-REPORT.md
```

A failed run does not apply its patch to the source repository.

To continue from the saved worker job queue:

```bash
manageroo run --continue <run-id>
```

That reloads controller state and worker job records from disk. It does not
pretend the old terminal process stayed alive. The controller replays from the
saved run folder, skips completed worker jobs, and gives unfinished jobs a clean
new attempt packet.

## The source changed during a run

MANAGEROO blocks application. Preserve both sets of work. Start a new run from the current source state. Do not force-apply the old patch without a developer review.

## An agent edited outside scope

MANAGEROO blocks before the controller checkpoint. The isolated mirror contains the evidence; the source remains unchanged. Tighten the plan or task boundary, then start a new run.

## A gate repeatedly fails

After the bounded repair count, the run becomes `BLOCKED`. This is evidence that the task, acceptance oracle, environment, or architecture needs a product/technical decision. Increasing the loop count is not the default remedy.

## Reviewer disagreement

Only evidence-backed current-file findings are accepted. Blocking findings need
a non-empty quote that matches the current file. Invalid paths, stale lines,
mismatched quotes, or findings outside the locked task scope cause review
validation failure. Deterministic tests take precedence over reviewer rhetoric.

## Backup

The source repository is not modified until successful delivery, but ordinary Git remote backups remain recommended. MANAGEROO is not a backup system.
