# Discovery and host hardware context

Manageroo is intended to do more than execute a literal prompt. Before implementation, the product-analysis stage receives two controller-owned preflight inputs:

1. a deterministic unknown-unknowns checklist based on the brief and repository signals;
2. a best-effort profile of the machine currently running Manageroo.

The host profile is **context only**. It is not a Manageroo system requirement and it does not automatically change Manageroo worker concurrency.

## Unknown-unknowns preflight

Manageroo always asks the product analyst to review:

- failure, retry, interruption, rollback, and recovery behavior;
- observability and support evidence;
- whether the proposed proof actually proves the requested outcome;
- tempting adjacent work that should remain outside the run.

When repository or brief signals make them relevant, it also reviews:

- identity, authentication, authorization, and account recovery;
- billing, payments, refunds, reconciliation, and financial side effects;
- data preservation, migrations, backups, rollback, and deletion;
- deployment environments, secrets, runtime differences, and rollback paths;
- hardware or local-AI assumptions of the **target project**;
- external-service failures, rate limits, cost boundaries, and degraded behavior;
- accessibility, responsive behavior, browser states, loading, errors, and keyboard use.

This checklist is not automatically treated as product truth. The product analyst must answer questions from repository evidence whenever possible, infer reversible conventional details, and create a blocking decision only when guessing could materially change the product or create serious risk.

## Blocking questions

If a genuinely high-impact choice cannot be inferred safely, Manageroo saves the decision and a readable question sheet under the run:

```text
.manageroo/runs/<run-id>/artifacts/planning/BLOCKING-QUESTIONS.md
```

Show the unresolved questions:

```bash
manageroo decisions show <run-id> --repo /path/to/repo
```

Answer them interactively:

```bash
manageroo decisions answer <run-id> --repo /path/to/repo
```

Every question includes why the decision matters, the available options, and Manageroo's recommended option when a safe recommendation exists.

The selected answers are recorded as run evidence. Continue the same durable run afterward:

```bash
manageroo run --continue <run-id> --repo /path/to/repo --apply
```

## Host hardware profile

Inspect the current machine with:

```bash
manageroo capacity
manageroo capacity --json
```

The command reports, when detectable:

- operating system and architecture;
- logical CPU count;
- total system RAM;
- NVIDIA GPU model and VRAM through `nvidia-smi`;
- free disk space.

### What this does **not** mean

Manageroo does **not** require a particular GPU, VRAM amount, CPU class, or RAM tier. A machine does not become an unsupported Manageroo host merely because it is weaker than the developer's workstation.

Manageroo also does **not** automatically throttle or increase worker concurrency from CPU/RAM/GPU detection. The configured agent may be cloud-backed, remote, local, or a custom CLI, so Manageroo cannot truthfully infer the resource cost of one worker call from host hardware.

The core requirements remain the software requirements documented by the installer, primarily Python 3.11+ and Git, plus at least one usable agent path for real AI work.

### Why record hardware at all?

The profile helps the product analyst avoid accidentally designing the **target project** around one developer machine. For example, a local-model application, CUDA pipeline, game build, or video workflow may have real hardware requirements. Those requirements belong to that target project or selected local tool—not to Manageroo itself.

In plain English:

```text
Manageroo can run on different classes of computers.
The project Manageroo is managing may have its own hardware needs.
Those are separate things.
```
