# Recovery

## A run fails

Inspect:

```bash
manageroo status <run-id>
manageroo report <run-id>
```

Resume the same run when the controller, terminal, or agent call died and the
saved run directory is still the right source of truth:

```bash
manageroo resume <run-id> --repo /path/to/product
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

A failed run does not apply its patch to the source repository unless it had
already reached final delivery. Resume verifies the existing workspace and
reuses locked artifacts, completed task checkpoints, gate evidence, and review
evidence instead of asking finished roles to run again.

## The source changed during a run

MANAGEROO blocks application when the source changed in a way that is not the
same final patch already being applied. Preserve both sets of work. Start a new
run from the current source state unless a developer intentionally reviews and
adopts the old patch.

## An agent edited outside scope

MANAGEROO blocks before the controller checkpoint. The isolated mirror contains
the evidence; the source remains unchanged. If the issue was a transient agent
or terminal failure, use `manageroo resume <run-id>`. If the plan or task
boundary was wrong, tighten it and start a new run.

## A gate repeatedly fails

After the bounded repair count, the run becomes `BLOCKED`. This is evidence that the task, acceptance oracle, environment, or architecture needs a product/technical decision. Increasing the loop count is not the default remedy.

## Reviewer disagreement

Only evidence-backed current-file findings are accepted. Invalid paths, stale lines, or mismatched quotes cause review validation failure. Deterministic tests take precedence over reviewer rhetoric.

## Backup

The source repository is not modified until successful delivery, but ordinary Git remote backups remain recommended. MANAGEROO is not a backup system.
