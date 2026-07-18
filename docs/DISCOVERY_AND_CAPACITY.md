# Discovery and system capacity

Manageroo is intended to do more than execute a literal prompt. Before implementation, the product-analysis stage now receives two controller-owned preflight inputs:

1. a deterministic unknown-unknowns checklist based on the brief and repository signals;
2. a best-effort profile of the machine running Manageroo.

The goal is to surface important questions the operator may not know to ask without turning every run into a giant interview.

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
- CPU, RAM, GPU, VRAM, disk, model, and concurrency assumptions;
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

Every question includes:

- why the decision matters;
- the available options;
- Manageroo's recommended option when a safe recommendation exists.

The selected answers are recorded as run evidence. Continue the same durable run afterward:

```bash
manageroo run --continue <run-id> --repo /path/to/repo --apply
```

Manageroo validates that each answer is one of the product analyst's locked options before applying it to the saved product model.

## System capacity

Inspect the current machine with:

```bash
manageroo capacity
```

Machine-readable output:

```bash
manageroo capacity --json
```

The profile includes, when detectable:

- operating system and architecture;
- logical CPU count;
- total system RAM;
- NVIDIA GPU model and VRAM through `nvidia-smi`;
- free disk space;
- a conservative recommended maximum for simultaneous agent calls.

GPU detection is intentionally best-effort. A non-NVIDIA accelerator may not be reported automatically.

## What the capacity profile means

The detected machine is a **development-host profile**, not a declaration of the product's minimum requirements.

Manageroo uses it as context when hardware and local-runtime assumptions matter. For example, a local AI project should not accidentally assume that every future user has the same 128 GB RAM and 16 GB VRAM workstation as its developer.

The conservative parallel-worker recommendation is based on CPU count and an approximate RAM allowance. Repository-specific builds may require lower concurrency. Manageroo does not silently rewrite project configuration or increase concurrency merely because a powerful GPU is present.

For a public product, minimum requirements, recommended requirements, and the developer's own machine should be documented separately.
