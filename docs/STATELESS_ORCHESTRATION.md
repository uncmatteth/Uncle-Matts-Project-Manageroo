# Stateless Worker Orchestration

Manageroo is not "AI remembers better."

Manageroo makes remembering unnecessary.

The controller saves the truth. Each AI worker gets one complete assignment.
If a worker drifts, dies, lies, or runs out of room, Manageroo throws that
worker away and starts a clean one from saved facts.

## The Rule

No long chat is the boss.

No compacted summary is the boss.

No worker process is the boss.

The Python controller is the boss. It writes durable run state, locked
artifacts, job records, attempt records, packet manifests, gate evidence, and
final reports under `.manageroo/runs/<run-id>/`.

## Run Layout

```text
.manageroo/runs/<run-id>/
|-- state.json
|-- controller/
|   |-- truth.json
|   `-- phase-journal.jsonl
|-- jobs/<job-id>.json
|-- worker-attempts/<job-id>/<attempt-id>.json
|-- packets/<job-id>/<attempt-id>/prompt.md
|-- agent-output/<job-id>/<attempt-id>.json
`-- artifacts/
```

The old idea was one agent chat remembering the whole job. Manageroo does the
opposite. It turns the job into controller-owned facts and bounded worker jobs.

## Worker Jobs

Each job records the role, output schema, exact instructions, requested context,
allowed edit paths, dependencies, status, output artifact path and hashes, and
failure details.

Each attempt records the packet path, packet hash, output path, output hash,
adapter command, completion status, and error when the worker failed.

## What Happens When Workers Fail

Invalid JSON, schema failure, timeout, or process failure becomes a failed
attempt. Manageroo retries with a fresh packet and a fresh worker. By default it
does not impose a separate per-job attempt cap; retryable work continues until
success or the configured whole-run budget is exhausted. A project may set an
explicit per-job limit when it genuinely needs one.

Required context that does not fit is different. That blocks the job. Manageroo
does not silently chop required context or ask the AI to guess.

Completed jobs are reused from recorded artifacts only when the artifact exists
and its SHA-256 hash still matches the job record. A completed job without an
artifact hash is treated as stale and is not trusted.

## Continue A Run

Use:

```bash
manageroo run --continue <run-id>
```

That means "continue the saved worker job queue from disk." It is not a promise
that closing a terminal magically keeps a process alive. It is a promise that
the important facts are on disk, so Manageroo does not need a worker's memory to
know what happened.

On continue, the Python controller replays from the saved run folder. Completed
jobs and locked controller artifacts are reused. Failed, running, or missing
worker attempts get a new clean attempt with a fresh packet.

Job IDs are deterministic during replay. If an earlier phase is already
complete and a later worker failed, Manageroo reuses that later worker's
original job record instead of shifting the numbering and pretending it is a
new job.

If `planning/blocking-decisions.json` exists, continue stays blocked until the
operator resolves the product decisions. Manageroo does not replay past
unresolved decisions.

Delivery is crash-durable. Manageroo writes `delivery/final-result.json`,
`delivery/FINAL-REPORT.md`, and `delivery/final.patch` before applying to the
source repo. If the process dies after writing the final result but before
source apply, `manageroo run --continue <run-id> --apply` retries only the
apply step. If the patch is already present in the source repo, Manageroo marks
the apply complete instead of rerunning workers.

Inspect a run with:

```bash
manageroo status <run-id>
```

Status explains what happened, what it means, and what to do next in plain
English. Use `--json` when you explicitly need the phase, current job, completed
job count, failed attempts, blocking reason, and other machine-readable details.

## Operator Pause Is Final

The host continuity hook treats direct language such as `stop`, `pause until I
tell you`, and `stop and wait` as an operator pause, not another task. It keeps
the saved objective but allows the current turn to end without a completion
receipt and blocks tool use while paused. Questions do not resume that work.

`Resume the saved work` reactivates the saved objective. A clear new command
such as `Please fix only the pause behavior` starts only that new work and
replaces the paused backlog. Manageroo must never use unfinished-work
continuation to override an operator pause.
