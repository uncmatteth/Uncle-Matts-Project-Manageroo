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
| Agent cannot persist Git config, hooks, or other Git-directory metadata | In-memory Git-directory checkpoint, comparison, and verified restoration | Detective, blocks acceptance and restores metadata |
| Agent cannot invent executable gates | Gate IDs reference controller config | Preventive |
| Dangerous shell interpolation | argv-only subprocess execution; no `shell=True` | Preventive in controller |
| Timed-out release-sweep child leaves Clawpatch or its provider editing the project | Dedicated process group terminated as a unit before reconciliation and retry | Preventive and recoverable |
| Retryable release-sweep failure silently advances to another finding | Verified stash, Clawpatch `show`, mechanical reopen, exact same-finding `next`, and retry | Preventive in controller |
| Relaunched release sweep loses its interrupted current finding | Durable repository, branch, HEAD, finding, phase, and retry progress reconciled against existing `.clawpatch` state | Recoverable in controller; relaunch remains external |
| Project memory creation escapes the repository | Resolve the destination parent and reject symlinked memory paths before writing | Preventive |
| Codex reviewer cannot write normally | `read-only` Codex sandbox | Provider enforcement |
| Reviewer mutation by any route | Disposable clone + before/after inventory | Detective, original protected |
| Locked requirements cannot change | Artifact hash ledger | Detective, blocks next phase |
| Compaction cannot drop must-not rules | Intent lock plus compaction audit | Detective, blocks continuation |
| Worker memory cannot become run truth | Durable job store, packet manifests, artifact hashes | Preventive in controller |
| Failed worker attempt is not treated as completion | Worker-attempt records plus retry/failed-job status | Preventive in controller |
| Concurrent callers cannot allocate the same worker attempt | Per-job interprocess lock plus exclusive attempt-file reservation | Preventive |
| Cached references cannot bypass project config mutation locking | Lock inside each public read-modify-write mutation entry point | Preventive |
| Concurrent adapters cannot exceed the durable worker-call budget | Interprocess ledger lock around reload, limit check, increment, and atomic write | Preventive |
| Concurrent skill installers cannot overlap or overwrite a linked lock target | Permanent cross-platform advisory lock on a validated private regular file; existing contents are not rewritten | Preventive |
| Idea-inbox lock acquisition cannot overwrite a linked target | Reject symlinks, Windows reparse points, multiple links, and opened-path identity mismatches before truncation | Preventive |
| Concurrent worker attempts cannot share one repository transaction | Interprocess lock keyed to the canonical Git common directory, held from pristine check through validation or rollback | Preventive |
| Git metadata snapshots consume unbounded memory | Explicit entry, file, and aggregate-byte limits before worker launch | Preventive, fails closed |
| A crashed artifact-lock reclaimer wedges the store | Portable atomic claim directory plus incomplete-publication grace and stale-owner recovery | Preventive and recoverable |
| Completed worker job is not casually repeated | Completed job artifact hash check | Detective, blocks stale reuse |
| Continue cannot shift later failed job IDs | Replay matches worker calls to saved job spec hashes | Preventive in controller |
| Unresolved product decision cannot be skipped on continue | `planning/blocking-decisions.json` blocks replay | Preventive in controller |
| Stale context cannot be reused | Source hashes in packet manifest | Detective, blocks execution |
| Untrusted context cannot escape prompt framing | Dynamic payload fences, single-line metadata labels, and validated content hashes | Preventive |
| Required context cannot disappear | Budget compiler raises instead of truncating | Preventive |
| Model cannot mark run complete | Controller state machine | Preventive |
| Unverified patch cannot reach source | Apply only after COMPLETE path and source hash check | Preventive |
| Release verification gate mutates source used by later gates | Exact-HEAD disposable clone plus post-gate HEAD, tracked, untracked, and ignored mutation checks | Preventive |
| Uninstall plan targets a lookalike Python prefix | Matching resolved install lock plus SHA-256-bound random ownership marker; old locks require matching app digest, launcher, venv, and prefix | Preventive |
| Crash during final apply loses proof | Final result/report/patch are written before source apply; continue retries apply only | Detective and recoverable |
| Acceptance cannot be auto-passed | `verification/acceptance-evidence.json` binds outcomes to gates, demo evidence, and review | Preventive in controller |
| Release-ready cannot ship without a valid Manageroo run | Fail-closed final-result schema validation, latest completed run proof, post-gate HEAD and source-tree proof, approved review, final report, final patch, and boolean applied-source status | Preventive release gate |
| Generic third-party agent is fully sandboxed | Not guaranteed | Unsupported claim; use Codex adapter for hard mode |

## Critical limitation

A local process running with the operator's full operating-system permissions can attempt hostile behavior. MANAGEROO reduces blast radius through an isolated repository, provider sandbox settings, argv-only controller commands, and validation. It is not a hostile multi-tenant security boundary or virtual machine.

For untrusted models or plugins, run the entire harness inside an OS container or disposable machine.
