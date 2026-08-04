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
| A healthy large ClawPatch review exceeds one absolute child watchdog before all features finish | Use ClawPatch dry-run to read pending features and job count, run one `review --limit <jobs>` worker wave per child, and require an exact pending-count decrease after every wave | Preventive, progress-bounded continuation |
| Interrupted release-sweep supervisor leaves Clawpatch or its provider editing the project | Keyboard interruption terminates and reaps the dedicated child process group before supervisor exit while retaining durable progress | Preventive and recoverable |
| Release-sweep repeatedly repairs a finding that cannot pass because a configured repository baseline is already red | Run Manageroo gates when configured before map/review/fix and report exact failing gate output; the portable external lane does not invent gates for plain Git repositories | Preventive when project gates exist; ClawPatch owns validation otherwise |
| Native Windows ClawPatch repeatedly fails a valid repository wrapper command written as `./wrapper` | After fresh initialization, replace only the leading token with an existing repository-root `.bat` or `.cmd` wrapper and leave every argument and unrelated command unchanged | Preventive, platform-bounded normalization |
| External supervisor pollutes a plain target repo or its Git metadata with Manageroo runtime files | Store external checkpoint and proof artifacts beside the Manageroo-owned external-runner installation; keep `.manageroo/cache` for the Manageroo project lane | Preventive |
| Validation-failed ClawPatch partial work is discarded or blindly retried forever | Save exact changed paths in one local-only temporary iteration commit, rerun only the same finding, and continue only for a genuinely new source-tree state | Preventive, progress-bounded continuation |
| ClawPatch finishes a repair but its broad validation fails for unrelated repository problems, then the next pass makes no further source change | Revalidate the exact saved repair with ClawPatch; finalize and advance only when ClawPatch reports `fixed` and the configured Manageroo project gates pass, otherwise stop with the repair visible | Preventive, exact-finding convergence recovery |
| Revalidation keeps a ClawPatch finding open but the supervisor stops or pushes partial work | Amend only the exact new patch paths into the local iteration commit and rerun the same finding; push only after exact `fixed` revalidation produces one final combined commit | Preventive, command-owned continuation |
| An overlapping finding is already repaired by a prior validated commit and exact revalidation returns fixed with no new source changes | Require unchanged HEAD and a source-clean tree, record no source commit required, clear the checkpoint, and continue without an empty commit or redundant push | Preventive, documented fixed transition |
| An older supervisor already stopped that fixed overlapping finding with a zero-path checkpoint | Require current checkpoint HEAD, source-clean worktree, same finding still fixed, and an applied zero-file attempt bound to that HEAD before clearing only the checkpoint and continuing through `next` | Preventive, exact-proof compatibility recovery |
| A same-finding iteration makes no progress or cycles | After the exact saved-repair convergence check, detect no changes, a repeated tree, the original tree, or temporary-history mismatch; unwind the temporary commit to visible source changes at the original HEAD and stop without advancing | Preventive, deterministic stop |
| A stopped ClawPatch process leaves an already-applied attempt dirty | Resume only when checkpoint branch, base HEAD, exact dirty paths, finding state, and one applied patch record agree; run gates and revalidation without rerunning `fix` | Preventive, exact-ownership recovery |
| An older supervisor stops after unwinding a verified temporary same-finding commit | Require the checkpoint base HEAD, exact dirty paths, recognized temporary-commit identity, direct parent, and matching committed path set; revalidate with ClawPatch and run project gates before committing or resuming that same finding | Preventive, exact-checkpoint compatibility recovery |
| An interrupted ClawPatch provider leaves a `planned` attempt and no source changes | Require a source-clean tree, matching branch and HEAD, the same open finding, and at least one empty planned attempt at that HEAD; preserve ClawPatch state and require `next` to return that same finding | Preventive, command-owned restart recovery |
| A completed ClawPatch repair remains blocked by its old stopped checkpoint | With a source-clean worktree, require an ancestor checkpoint HEAD and one descendant commit whose complete non-ClawPatch path set exactly equals the checkpoint-owned paths before clearing it | Preventive, repository-independent reconciliation |
| Rebuilding `.clawpatch` leaves an external checkpoint pointing at a finding from the deleted generation | Record an exact stopped-source fingerprint; accept only a newer empty ClawPatch generation at the same branch and HEAD, restore only the exact matching owned paths, and preserve all state on a fingerprint or path mismatch | Preventive, universal reset-generation recovery |
| A source-clean zero-path checkpoint survives while a rebuilt ClawPatch generation and later commits advance HEAD | Require the old finding to be absent, the same branch, a newer generation, and checkpoint-to-generation-to-current Git ancestry; clear only the obsolete external checkpoint and leave all repository files unchanged | Preventive, zero-ownership generation reconciliation |
| A new repository requires manual ClawPatch setup before the external supervisor works | Bare `clawpatch-supervise` initializes missing ClawPatch project state, then follows status, map, review, and current-finding transitions | Preventive, universal entrypoint |
| Escalated revalidation silently changes a repair | Exact source-state fingerprint before and after the bounded validation sequence | Detective; blocks commit and stops |
| Required validation cannot run because both read-only and workspace-write Codex sandboxes block host temp, socket, or lock facilities | External supervisor performs one final child-scoped trusted-host revalidation while retaining the same source fingerprint guard | Preventive, bounded environment escalation |
| Open queue is empty but a repaired finding remains uncertain only because read-only validation could not create test files | Select with ClawPatch's `next --status uncertain`, show, and run guarded exact-finding revalidation; accept fixed without a commit or return open to the normal repair loop | Preventive, documented recovery transition |
| Successful closure leaves generated or modified ClawPatch runtime state in the target checkout | Unless separately authorized for publication, remove the runtime tree and restore committed `.clawpatch` bytes from HEAD while proving the project-source fingerprint is unchanged | Preventive, exact-scope cleanup |
| One exhausted ClawPatch queue is mistaken for proof that the repaired HEAD has no newly discoverable findings | After every nonempty generation, preserve committed configuration, rebuild generated run/discovery state, map and completely review the new HEAD; emit `COMPLETE` only after a fresh zero-finding generation | Preventive, fixed-point closure |
| Fresh ClawPatch reviews keep rediscovering findings without changing the repaired source tree | Record each generation's source tree and stop as nonconvergent when a non-clean tree repeats; do not impose an arbitrary generation cap or claim completion | Preventive, deterministic no-progress stop |
| Relaunched release sweep guesses how to continue an interrupted finding | Resume only an exact stopped applied attempt proven by durable repository, branch, HEAD, finding, phase, owned paths, and Clawpatch patch record; otherwise refuse | Preventive; explicit fresh recovery remains operator-owned |
| Manageroo-project fresh release deletes unrelated operator work | Require a compatible stopped/fix checkpoint and exact equality between current dirty paths and checkpoint-owned paths | Preventive; unrelated dirty paths block unchanged |
| External fresh deletes unrelated project work | Make fresh the normal external start but recover and discard only source paths exactly proven by the interrupted checkpoint; any extra or mismatched path blocks unchanged | Preventive, exact-ownership reset |
| External-runner state relocation orphans an interrupted fix checkpoint | Validate and migrate the legacy version-2 `.manageroo/cache` ownership record before external `--fresh` evaluation | Preventive and recoverable |
| Push begins from an unsynchronized branch | Compare local HEAD with live `origin/<branch>` before creating a repair branch or starting queue work | Preventive |
| Project memory creation escapes the repository | Resolve the destination parent and reject symlinked memory paths before writing | Preventive |
| Codex reviewer cannot write normally | `read-only` Codex sandbox | Provider enforcement |
| Reviewer mutation by any route | Disposable clone + before/after inventory | Detective, original protected |
| Locked requirements cannot change | Artifact hash ledger | Detective, blocks next phase |
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
| Uninstall plan targets a lookalike or dangerously broad prefix | Reject prefixes that contain home or the current working directory; require a matching resolved install lock plus SHA-256-bound random ownership marker; old locks require matching app digest, launcher, venv, and prefix | Preventive |
| Crash during final apply loses proof | Final result/report/patch are written before source apply; continue retries apply only | Detective and recoverable |
| Acceptance cannot be auto-passed | `verification/acceptance-evidence.json` binds outcomes to gates, demo evidence, and review | Preventive in controller |
| Release-ready cannot ship without a valid Manageroo run | Fail-closed final-result schema validation, latest completed run proof, post-gate HEAD and source-tree proof, approved review, final report, final patch, and boolean applied-source status | Preventive release gate |
| Generic worker receives requested read-only/workspace-write enforcement | Explicit non-empty provider argv required per mode; launch and doctor fail closed when missing | Provider enforcement for configured modes; use Codex adapter for a tested native sandbox |

## Critical limitation

A local process running with the operator's full operating-system permissions can attempt hostile behavior. MANAGEROO reduces blast radius through an isolated repository, provider sandbox settings, argv-only controller commands, and validation. It is not a hostile multi-tenant security boundary or virtual machine.

For untrusted models or plugins, run the entire harness inside an OS container or disposable machine.
