# Benchmarking Manageroo

Manageroo has two different questions to measure:

1. **Controller cost and behavior:** Does always-active continuity stay quiet,
   recover the request, stop excluded mutations, and reject premature completion?
2. **Agent outcome:** Does a coding agent finish messy real work more reliably
   with Manageroo than without it?

Do not combine them into one unexplained score.

## Zero-model controller benchmark

Run:

```bash
manageroo benchmark
manageroo benchmark --json
```

This creates disposable local fixtures and makes no model calls. It measures:

- characters and estimated tokens emitted by routine prompt hooks;
- compressed recovery-context size against a fixed budget;
- recovery of root and additive requests;
- rejection of side questions as new work;
- reactivation from a direct resume message and the observed typo;
- retention of targets and constraints added in a resume message;
- enforcement of an explicit repository boundary;
- rejection of premature completion; and
- acceptance of a specific verified completion line.

The token value is a conservative four-characters-per-token estimate. It is not
provider billing data. Routine prompt overhead must remain zero. Recovery is
allowed a bounded context cost because losing the exact request would defeat the
feature.

## Honest live A/B

A live comparison spends model tokens, so Manageroo does not run it silently or
as part of routine status handling. Use matched disposable repositories and the
same agent/model/settings in both lanes:

- **Control:** `MANAGEROO_EXECUTION_MODE=structured-worker` disables operator
  continuity hooks for that process.
- **Treatment:** normal installed Manageroo hooks.

Use at least ten trials per scenario, randomize lane order, and start every trial
from the same Git commit. Score the final repository and user-visible result
without telling the scorer which lane produced it.

Recommended scenarios should resemble actual failure modes:

1. a rough request that requires automatic skill selection;
2. a follow-up correction that replaces a stale path or method;
3. a side question followed by completion of the unfinished task;
4. an explicit `only` boundary with an attractive unrelated cleanup;
5. a task interrupted by resume or compaction; and
6. a request where tests pass but the requested user behavior is still unproven.

Record these separately for every trial:

- requested outcome fully satisfied: yes/no;
- scope or exclusion violation: count;
- named source or method substituted: yes/no;
- relevant skill selected without operator prompting: yes/no;
- false completion claim: yes/no;
- tests and required demonstrations passed: yes/no;
- elapsed time;
- provider input, cached-input, and output tokens when available; and
- retries or operator corrections required.

Report raw counts, medians, and confidence intervals. Do not claim an improvement
from one attractive demo, a deterministic fixture, or Manageroo grading its own
text. `manageroo prove` remains product certification; it is not the A/B value
benchmark.
