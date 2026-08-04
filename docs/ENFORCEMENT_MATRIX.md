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
| Chiptune cleanup deletes a caller-selected directory | Private non-init playback state plus an internally owned temporary-directory handle | Preventive |
| Timed-out release-sweep child leaves Clawpatch or its provider editing the project | Dedicated process group terminated as a unit with bounded cleanup; timed-out non-fix commands are not restarted | Preventive and recoverable |
| Interrupted release-sweep supervisor leaves Clawpatch or its provider editing the project | Keyboard interruption terminates and reaps the dedicated child process group before supervisor exit while retaining durable progress | Preventive and recoverable |
| Non-`/proc` Unix process preflight mistakes its supervisor or another repository for a conflict | Parse PIDs separately, exclude the current process, validate Clawpatch argv, and compare `lsof` working directories to the target repository | Preventive and fail-closed when ownership cannot be proven |
| Release-sweep repeatedly repairs a finding that cannot pass because a configured repository baseline is already red | Run Manageroo gates when configured before map/review/fix and report exact failing gate output; the portable external lane does not invent gates for plain Git repositories | Preventive when project gates exist; ClawPatch owns validation otherwise |
| External supervisor pollutes a plain target repo or its Git metadata with Manageroo runtime files | Store external checkpoint and proof artifacts beside the Manageroo-owned external-runner installation; keep `.manageroo/cache` for the Manageroo project lane | Preventive |
| Failed release-sweep fix is silently retried, hidden, or advanced | One fix invocation, stopped checkpoint with exact owned paths, source left in place, and no stash/triage/remap/next transition | Preventive in controller |
| Workspace-write revalidation silently changes a repair | Exact source-state fingerprint before and after the single escalated validation pass | Detective; blocks commit and stops |
| Concurrent mutation is silently included in an external repair checkpoint | Exact staged Git tree captured before checkpoint creation and compared with the immutable checkpoint commit tree | Detective; blocks continuation and restores the baseline |
| Relaunched release sweep guesses how to continue an interrupted finding | Durable repository, branch, HEAD, finding, phase, and exact owned paths cause ordinary relaunch to refuse | Preventive; explicit fresh recovery remains operator-owned |
| Manageroo-project fresh release deletes unrelated operator work | Require a compatible stopped/fix checkpoint and exact equality between current dirty paths and checkpoint-owned paths | Preventive; unrelated dirty paths block unchanged |
| External fresh unexpectedly preserves or mixes prior work into a new ClawPatch run | Treat explicit external `--fresh` as authorization to restore all current source paths to HEAD, delete untracked source files, clear old `.clawpatch` state, and verify cleanliness | Preventive reset; destructive behavior is explicit and documented |
| External-runner state relocation orphans an interrupted fix checkpoint | Validate and migrate the legacy version-2 `.manageroo/cache` ownership record before external `--fresh` evaluation | Preventive and recoverable |
| Push begins from an unsynchronized branch | Compare local HEAD with live `origin/<branch>` before creating a repair branch or starting queue work | Preventive |
| Project memory creation escapes the repository | Resolve the destination parent and reject symlinked memory paths before writing | Preventive |
| Codex reviewer cannot write normally | `read-only` Codex sandbox | Provider enforcement |
| Reviewer mutation by any route | Disposable clone + before/after inventory | Detective, original protected |
| Locked requirements cannot change | Artifact hash ledger | Detective, blocks next phase |
| Failed or interrupted artifact replacement desynchronizes content and ledger metadata | Write-ahead staging with prior-artifact and prior-ledger recovery under the transaction lock | Preventive and recoverable |
| Compaction cannot drop must-not rules or audit a structurally invalid intent lock | Intent lock plus compaction audit, with schema validation | Detective, blocks continuation |
| Concurrent intent replacement cannot pair one payload with another generation's hash | Hash and parse one immutable JSON byte snapshot; writers hold the mutation lock through capture result construction | Preventive |
| Worker memory cannot become run truth | Durable job store, packet manifests, artifact hashes | Preventive in controller |
| Failed worker attempt is not treated as completion | Worker-attempt records plus retry/failed-job status | Preventive in controller |
| Concurrent callers cannot allocate the same worker attempt | Per-job interprocess lock plus exclusive attempt-file reservation | Preventive |
| Cached references cannot bypass project config mutation locking | Lock inside each public read-modify-write mutation entry point | Preventive |
| Concurrent adapters cannot exceed the durable worker-call budget | Interprocess ledger lock around reload, limit check, increment, and atomic write | Preventive |
| Concurrent decision submissions can diverge product and resolution artifacts | Run-scoped interprocess transaction lock plus a product-model digest in the resolution record | Preventive and detective |
| Concurrent skill installers cannot overlap or overwrite a linked lock target | Permanent cross-platform advisory lock on a validated private regular file; existing contents are not rewritten | Preventive |
| Concurrent release packagers cannot publish a mixed archive pair or mismatched drop | Cross-platform advisory lock held across archive-pair publication and drop-folder refresh | Preventive |
| Release file-list or staging paths escape their repository-owned roots | Reject non-normalized, absolute, dot, parent, symlink-resolved, and out-of-root paths before selection, copy, or archive creation | Preventive |
| Idea-inbox lock acquisition cannot overwrite a linked target | Reject symlinks, Windows reparse points, multiple links, and opened-path identity mismatches before truncation | Preventive |
| Concurrent worker attempts cannot share one repository transaction | Interprocess lock keyed to the canonical Git common directory, held from pristine check through validation or rollback | Preventive |
| Worker cannot redirect controller-truth restoration through a symlinked protected directory | Canonical run-root identity checkpoint plus lstat-based directory-topology restoration before protected file reads or writes | Detective, blocks acceptance and restores protected topology |
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
| Concurrent clean commit replaces the release candidate while final evidence is written | Git reference transaction held through handoff persistence plus a final HEAD, source-digest, and cleanliness snapshot | Preventive and detective |
| Worktree mutation after the final cleanliness snapshot changes the bytes an operator ships | READY handoff names a SHA-256-bound tar archive generated from the locked exact commit instead of authorizing the mutable worktree | Preventive |
| Uninstall plan targets a lookalike or dangerously broad prefix | Reject prefixes that contain home or the current working directory; require a matching resolved install lock plus SHA-256-bound random ownership marker; old locks require matching app digest, launcher, venv, and prefix | Preventive |
| Crash during final apply loses proof | Final result/report/patch are written before source apply; continue retries apply only | Detective and recoverable |
| Acceptance cannot be auto-passed | `verification/acceptance-evidence.json` binds outcomes to gates, demo evidence, and review | Preventive in controller |
| Release-ready cannot ship without a valid Manageroo run | Fail-closed final-result schema validation, latest completed run proof, post-gate HEAD and source-tree proof, approved review, final report, final patch, and boolean applied-source status | Preventive release gate |
| Generic worker receives requested read-only/workspace-write enforcement | Explicit non-empty provider argv required per mode; launch and doctor fail closed when missing | Provider enforcement for configured modes; use Codex adapter for a tested native sandbox |

## Critical limitation

A local process running with the operator's full operating-system permissions can attempt hostile behavior. MANAGEROO reduces blast radius through an isolated repository, provider sandbox settings, argv-only controller commands, and validation. It is not a hostile multi-tenant security boundary or virtual machine.

For untrusted models or plugins, run the entire harness inside an OS container or disposable machine.
