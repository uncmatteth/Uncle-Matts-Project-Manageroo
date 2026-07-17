# Manageroo Product Proof

`manageroo prove` is the adversarial certification lane for the Manageroo control plane.

It exists to answer a harder question than "do the unit tests pass?":

> Can Manageroo preserve the real assignment, control disposable AI workers, reject bad evidence, survive interrupted work, enforce scope, and refuse fake completion?

## Run it

Run the complete proof directly:

```bash
manageroo prove
```

Manageroo automatically selects any supported live coding-agent command it can find locally. The worker may be Codex, Claude Code, or Gemini. The vendor is not the certification boundary; the configured adapter protocol and resulting evidence are.

To force a particular installed worker:

```bash
manageroo prove --live-agent codex
manageroo prove --live-agent claude-code
manageroo prove --live-agent gemini
```

Machine-readable output:

```bash
manageroo prove --json
```

A deliberately reduced diagnostic run is also available:

```bash
manageroo prove --no-regression
```

Skipping source regressions is fail-closed. It returns `PARTIAL`, never `COMPLETE`.

If no supported real worker command is available, the live integration lane also remains blocked and the result cannot be `COMPLETE`.

## Completion rule

Manageroo may print:

```text
RESULT: COMPLETE
```

only when every required machine-checked proof lane passes, including one real disposable coding-agent run under Manageroo control.

A model saying "done", a worker returning `COMPLETE`, a plausible patch, a passing subset of tests, or the mock adapter succeeding is not sufficient for full product certification.

## Proof lanes

The certification command exercises and reports these areas explicitly:

1. Whole-project lifecycle through a deterministic fixture run.
2. Intent preservation and compaction-defense behavior.
3. Scope enforcement and command allowlist enforcement.
4. Durable worker state, artifact hashing, replay prevention, and changed-job-spec rejection.
5. Context overflow, omission recording, and stale-packet rejection.
6. Worker retry isolation and artifact-integrity enforcement.
7. Interrupted-run continuation from the saved worker queue.
8. Rejection of dishonest or insufficient acceptance evidence.
9. Optional external-tool failure without corruption of controller truth.
10. Intent-lock adversarial regression coverage.
11. Policy-enforcement adversarial regression coverage.
12. Bounded retry, review, release, and truthful-completion gates.
13. The complete repository regression suite.
14. One real coding-agent fixture run that must actually finish under Manageroo control.

The source-level lanes reuse Manageroo's regression fixtures so the certification command proves the same failure modes that protect normal development. The complete suite is run last as a broad final guard.

The live-agent fixture is disposable. The selected worker must create an exact file in a temporary Git repository, pass a real unittest verification gate, survive Manageroo's normal planning and review path, and reach controller-owned `COMPLETE` status. The fixture is deleted afterward.

## Interchangeable workers

Manageroo owns the worker protocol. The coding-agent provider is replaceable labor.

The universal CLI adapter supports explicit prompt transport by file path, command argument, or stdin. Regardless of the transport or provider, the worker response is normalized through the same schema-validation path and remains subject to the same Manageroo scope, verification, review, retry, and completion rules.

See `docs/AGENT_PROTOCOL.md` for the complete adapter contract.

## Why this is separate from `self-test`

`manageroo self-test` proves that a deterministic fixture can complete the normal orchestration path with the mock adapter.

`manageroo prove` is broader. It deliberately tries to prove that the controller also says **no** correctly:

- no to lost intent;
- no to out-of-scope changes;
- no to spoofed command paths;
- no to stale worker truth;
- no to replaying completed work;
- no to missing evidence;
- no to silent context loss;
- no to fake release readiness;
- no to claiming full product certification without a real coding-agent run.

That distinction matters because Manageroo is not merely a code generator. It is the control, memory, verification, and evidence layer above coding agents.

## Source checkout requirement

Full `COMPLETE` certification requires a source checkout or release layout containing the repository regression suite. A minimal wheel installation without the source tests cannot provide that evidence and therefore cannot honestly produce complete product certification.

This is intentional. Missing proof is a blocker, not a reason to lower the standard.

## Live-agent requirement

At least one supported real coding-agent command must already be installed and authenticated. Manageroo does not fake this lane or silently substitute the mock adapter.

By default Manageroo chooses any available supported worker. `--live-agent` exists only as an override when the operator wants to certify a specific preset.

A release can be certified against more than one worker by running the command separately with explicit overrides.

## No GitHub Actions dependency

Manageroo's official release process remains local. `manageroo prove` does not require GitHub Actions and does not add a workflow dependency. It can be run directly from the source checkout before the normal local release-verification and packaging commands.

Recommended final sequence:

```bash
manageroo prove
python3 scripts/verify_release.py
python3 scripts/package_release.py
```

A release should not be described as product-certified unless the first command reports `RESULT: COMPLETE` and the normal release verification also passes.
