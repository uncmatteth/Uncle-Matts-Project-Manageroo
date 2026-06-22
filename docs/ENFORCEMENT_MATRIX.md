# Enforcement matrix

Not every control is equally strong. This document distinguishes prevention from detection.

| Requirement | Mechanism | Strength |
|---|---|---|
| Agent follows role instructions | Prompt packet + schema | Guidance plus output validation |
| Agent cannot alter source repository | Isolated mirror | Preventive |
| Agent cannot silently edit outside task | Post-role Git diff + scope policy | Detective, blocks acceptance |
| AI cannot request broad edit scope | Exact allowed-path validation before plan lock | Preventive |
| Agent cannot commit normally | Failing pre-commit hook | Preventive for normal commit |
| Agent cannot bypass commit rule | `HEAD` comparison | Detective, blocks acceptance |
| Agent cannot invent executable gates | Gate IDs reference controller config | Preventive |
| Dangerous shell interpolation | argv-only subprocess execution; no `shell=True` | Preventive in controller |
| Codex reviewer cannot write normally | `read-only` Codex sandbox | Provider enforcement |
| Reviewer mutation by any route | Disposable clone + before/after inventory | Detective, original protected |
| Locked requirements cannot change | Artifact hash ledger | Detective, blocks next phase |
| Compaction cannot drop must-not rules | Intent lock plus compaction audit | Detective, blocks continuation |
| Worker memory cannot become run truth | Durable job store, packet manifests, artifact hashes | Preventive in controller |
| Failed worker attempt is not treated as completion | Worker-attempt records plus retry/failed-job status | Preventive in controller |
| Completed worker job is not casually repeated | Completed job artifact hash check | Detective, blocks stale reuse |
| Continue cannot shift later failed job IDs | Replay matches worker calls to saved job spec hashes | Preventive in controller |
| Unresolved product decision cannot be skipped on continue | `planning/blocking-decisions.json` blocks replay | Preventive in controller |
| Stale context cannot be reused | Source hashes in packet manifest | Detective, blocks execution |
| Required context cannot disappear | Budget compiler raises instead of truncating | Preventive |
| Model cannot mark run complete | Controller state machine | Preventive |
| Unverified patch cannot reach source | Apply only after COMPLETE path and source hash check | Preventive |
| Crash during final apply loses proof | Final result/report/patch are written before source apply; continue retries apply only | Detective and recoverable |
| Acceptance cannot be auto-passed | `verification/acceptance-evidence.json` binds outcomes to gates, demo evidence, and review | Preventive in controller |
| Release-ready cannot ship without a Manageroo run | Latest completed run proof, approved review, final report, final patch, and applied-source status | Preventive release gate |
| Generic third-party agent is fully sandboxed | Not guaranteed | Unsupported claim; use Codex adapter for hard mode |

## Critical limitation

A local process running with the operator's full operating-system permissions can attempt hostile behavior. MANAGEROO reduces blast radius through an isolated repository, provider sandbox settings, argv-only controller commands, and validation. It is not a hostile multi-tenant security boundary or virtual machine.

For untrusted models or plugins, run the entire harness inside an OS container or disposable machine.
