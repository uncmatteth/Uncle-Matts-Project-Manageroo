# Determinism

MANAGEROO uses “deterministic” to mean reproducible control and evidence, not identical model prose.

Deterministic properties:

- explicit phase transitions;
- immutable locked artifact hashes;
- exact source snapshot hashes;
- exact build-backend versions installed from a SHA-256 lock before offline wheel building;
- stable repository inventory ordering;
- fixed context budgets;
- exact included line ranges;
- task dependency ordering;
- allowlisted gate commands;
- configurable whole-run call and runtime budgets, with optional explicit phase caps;
- exact changed-file comparison;
- binary reviewer status derived from validated findings, never model-reported confidence;
- source freshness check before patch application;
- complete run ledger.

Probabilistic properties:

- product interpretation by the model;
- reuse recommendations;
- architecture synthesis;
- implementation content;
- defect discovery.

Probabilistic outputs are accepted only after deterministic controls test their observable consequences.
