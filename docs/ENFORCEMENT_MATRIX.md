# Enforcement matrix

Not every control is equally strong. This document distinguishes prevention from detection.

| Requirement | Mechanism | Strength |
|---|---|---|
| Agent follows role instructions | Prompt packet + schema | Guidance plus output validation |
| Agent cannot alter source repository | Isolated mirror | Preventive |
| Agent cannot silently edit outside task | Post-role Git diff + scope policy | Detective, blocks acceptance |
| Agent cannot commit normally | Failing pre-commit hook | Preventive for normal commit |
| Agent cannot bypass commit rule | `HEAD` comparison | Detective, blocks acceptance |
| Agent cannot invent executable gates | Gate IDs reference controller config | Preventive |
| Dangerous shell interpolation | argv-only subprocess execution; no `shell=True` | Preventive in controller |
| Codex reviewer cannot write normally | `read-only` Codex sandbox | Provider enforcement |
| Reviewer mutation by any route | Disposable clone + before/after inventory | Detective, original protected |
| Locked requirements cannot change | Artifact hash ledger | Detective, blocks next phase |
| Compaction cannot drop must-not rules | Intent lock plus compaction audit | Detective, blocks continuation |
| Stale context cannot be reused | Source hashes in packet manifest | Detective, blocks execution |
| Required context cannot disappear | Budget compiler raises instead of truncating | Preventive |
| Model cannot mark run complete | Controller state machine | Preventive |
| Unverified patch cannot reach source | Apply only after COMPLETE path and source hash check | Preventive |
| Generic third-party agent is fully sandboxed | Not guaranteed | Unsupported claim; use Codex adapter for hard mode |

## Critical limitation

A local process running with the operator's full operating-system permissions can attempt hostile behavior. UMSMFBURASBOFE reduces blast radius through an isolated repository, provider sandbox settings, argv-only controller commands, and validation. It is not a hostile multi-tenant security boundary or virtual machine.

For untrusted models or plugins, run the entire harness inside an OS container or disposable machine.
