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
attempt. Manageroo retries with a fresh packet and a fresh worker until the
configured attempt limit is reached.

Required context that does not fit is different. That blocks the job. Manageroo
does not silently chop required context or ask the AI to guess.

Completed jobs are reused from recorded artifacts. They are not rerun unless the
recorded artifact is missing or changed.

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

Inspect a run with:

```bash
manageroo status <run-id>
```

Status shows the phase, current job, completed job count, failed attempts,
blocking reason, and the next action.
