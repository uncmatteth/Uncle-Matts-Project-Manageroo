# Manageroo Product Proof

`manageroo prove` is the adversarial certification lane for the Manageroo control plane.

It exists to answer a harder question than "do the unit tests pass?":

> Can Manageroo preserve the real assignment, control disposable AI workers, reject bad evidence, survive interrupted work, enforce scope, and refuse fake completion?

## Run it

```bash
manageroo prove
```

Machine-readable output:

```bash
manageroo prove --json
```

A deliberately reduced diagnostic run is available:

```bash
manageroo prove --no-regression
```

That mode is useful while debugging the proof harness, but it is intentionally fail-closed. It returns `PARTIAL`, never `COMPLETE`, because source-level adversarial regression evidence was skipped.

## Completion rule

Manageroo may print:

```text
RESULT: COMPLETE
```

only when every required machine-checked proof lane passes.

A model saying "done", a worker returning `COMPLETE`, a plausible patch, or a passing subset of tests is not sufficient.

## Proof lanes

The certification command exercises and reports these areas explicitly:

1. Whole-project lifecycle through a real deterministic fixture run.
2. Intent preservation and compaction-defense behavior.
3. Scope enforcement and command allowlist enforcement.
4. Durable worker state, artifact hashing, replay prevention, and changed-job-spec rejection.
5. Context overflow, omission recording, and stale-packet rejection.
6. Worker retry isolation and artifact-integrity enforcement.
7. Interrupted-run continuation from the saved worker queue.
8. Rejection of dishonest or insufficient acceptance evidence.
9. Intent-lock adversarial regression coverage.
10. Policy-enforcement adversarial regression coverage.
11. Review, release, and truthful-completion gates.
12. The complete repository regression suite.

The source-level lanes reuse Manageroo's regression fixtures so the certification command proves the same failure modes that protect normal development. The complete suite is run last as a broad final guard.

## Why this is separate from `self-test`

`manageroo self-test` proves that a deterministic fixture can complete the normal orchestration path.

`manageroo prove` is broader. It deliberately tries to prove that the controller also says **no** correctly:

- no to lost intent;
- no to out-of-scope changes;
- no to spoofed command paths;
- no to stale worker truth;
- no to replaying completed work;
- no to missing evidence;
- no to silent context loss;
- no to fake release readiness.

That distinction matters because Manageroo is not merely a code generator. It is the control, memory, verification, and evidence layer above coding agents.

## Source checkout requirement

Full `COMPLETE` certification requires a source checkout or release layout containing the repository regression suite. A minimal wheel installation without the source tests cannot provide that evidence and therefore cannot honestly produce complete product certification.

This is intentional. Missing proof is a blocker, not a reason to lower the standard.

## No GitHub Actions dependency

Manageroo's official release process remains local. `manageroo prove` does not require GitHub Actions and does not add a workflow dependency. It can be run directly from the source checkout before the normal local release-verification and packaging commands.

Recommended final sequence:

```bash
manageroo prove
python3 scripts/verify_release.py
python3 scripts/package_release.py
```

A release should not be described as product-certified unless the first command reports `RESULT: COMPLETE` and the normal release verification also passes.
