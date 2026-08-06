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
| Agent cannot persist Git config, hooks, or other Git-directory metadata | In-memory checkpoint materialized in a sibling directory with fsynced file data and supported directory entries, then installed by recoverable rename while retaining the live directory until verification | Detective, blocks acceptance and restores metadata |
| Agent cannot invent executable gates | Gate IDs reference controller config | Preventive |
| Dangerous shell interpolation | argv-only subprocess execution; no `shell=True` | Preventive in controller |
| Decision artifacts redirect reads or writes through a replaced planning directory, or change after answer validation | Hold a run-owned answer lock outside the replaceable planning path, pin no-follow run/artifact/planning descriptors, perform reads and atomic writes relative to them, privately claim the validated blocking artifact during the write, quarantine a mismatched concurrent replacement before restoring the claimed original and fsyncing the directory, and atomically republish the validated artifact tree as the commit boundary | Preventive, recoverable, and fail-closed |
| Discovery preflight follows a replaced file or ancestor path outside the repository, or blocks on a special file | Traverse through pinned directory descriptors, open children relative to those descriptors with no-follow and nonblocking flags, require regular-file descriptors, and fail closed where those primitives are unavailable | Preventive |
| Inventory or Obsidian access follows a path replaced after containment validation | Open complete repository and Obsidian paths from pinned root descriptors in one Linux `openat2` call with beneath and no-symlink resolution; read through one stable descriptor; require vault/export directories to be owned by the current user and not writable by another account; create export files exclusively without overwriting existing inodes; require export directories to preexist; and fail closed where those primitives are unavailable | Preventive against lower-privilege filesystem actors |
| Chiptune cleanup deletes a caller-selected directory | Private non-init playback state plus an internally owned temporary-directory handle | Preventive |
| External repair restoration or rollback deletes a path created or replaced after its preflight snapshot | Materialize the target checkpoint outside the live workspace, retain displaced workspace data in run-owned quarantine, and move pre-existing ignored entries only while their recorded identities still match | Preventive and recoverable |
| External repair command changes Git config, hooks, refs, objects, index, or other repository metadata outside allowed paths | Capture bounded repository-local Git metadata immediately before command execution, restore and reject any mutation before Git-based path checks, and reconstruct rollback or resume workspaces from the captured snapshot instead of the live `.git` directory | Detective, blocks acceptance and restores metadata |
| Manageroo drifts back into owning the ClawPatch queue runtime | Keep only the argv adapter and proof-path query in Manageroo; package and test queue transitions in the standalone public repository | Preventive, deep-module boundary |
| Manageroo masks a retryable or terminal standalone stop | Return the standalone process exit code unchanged, including `75` for typed retryable stops and `2` for terminal or safety stops | Preventive, service-policy preservation |
| Manageroo reads a stale in-repository ClawPatch proof | Ask the standalone executable for its external state root, then bind its complete zero-open proof to current Git HEAD | Preventive, single checkpoint authority |
| Stack update overwrites an unowned supervisor installation | Update only an executable resolved inside a recognized native-installer virtual environment at the pinned public commit | Preventive, ownership-gated updater |
| Stack update mutates the supervisor virtual environment while its queue is active | Cross-platform advisory lock keyed to the resolved supervisor executable and held across the complete queue or update lifetime; process inspection is supplemental only | Preventive for Manageroo-managed execution and updates |
| Push begins from an unsynchronized branch | Compare local HEAD with live `origin/<branch>` before creating a repair branch or starting queue work | Preventive |
| Project memory creation escapes the repository | Resolve the destination parent and reject symlinked memory paths before writing | Preventive |
| Codex reviewer cannot write normally | `read-only` Codex sandbox | Provider enforcement |
| Reviewer mutation by any route | Disposable clone + before/after inventory | Detective, original protected |
| Locked requirements cannot change, including through an in-root symlink alias | Symlink-free artifact paths plus artifact hash ledger | Preventive and detective, blocks next phase |
| Failed or interrupted artifact replacement desynchronizes content and ledger metadata | Write-ahead staging with prior-artifact and prior-ledger recovery under the transaction lock | Preventive and recoverable |
| Compaction cannot drop must-not rules or consume a malformed, non-UTF-8, structurally invalid, or mixed-generation intent lock pair | Canonical JSON intent lock plus compaction audit, with decoding, schema validation, and a Markdown generation marker; validated reads regenerate mismatched Markdown from the stable JSON snapshot under the mutation lock, and agent instructions prohibit direct reads of the generated Markdown | Preventive and recoverable |
| Concurrent intent replacement cannot pair one payload with another generation's hash | Hash and parse one immutable JSON byte snapshot; writers hold the mutation lock through capture result construction | Preventive |
| Worker memory cannot become run truth | Durable job store, packet manifests, artifact hashes | Preventive in controller |
| Failed worker attempt is not treated as completion | Worker-attempt records plus retry/failed-job status | Preventive in controller |
| Concurrent callers cannot allocate the same worker attempt | Per-job interprocess lock plus exclusive attempt-file reservation | Preventive |
| Cached references or a writable cache directory cannot bypass project config mutation locking | Lock inside each public read-modify-write mutation entry point; validate cache ownership and permissions through a stable directory descriptor and use directory-relative lock operations | Preventive |
| Concurrent adapters cannot exceed the durable worker-call budget | Interprocess ledger lock around reload, limit check, increment, and atomic write | Preventive |
| Concurrent decision submissions or an already-open source descriptor can diverge product and resolution artifacts | Run-scoped interprocess transaction lock, a product-model digest in the resolution record, and descriptor-relative no-overwrite publication of a validated source snapshot | Preventive and detective |
| Concurrent skill installers cannot overlap or overwrite a linked lock target | Permanent cross-platform advisory lock on a validated private regular file; existing contents are not rewritten | Preventive |
| A skill support file changes after import approval while `SKILL.md` stays unchanged | Bind every scan candidate to a race-checked full-tree digest covering relative paths, file modes, and content; require the same digest before staging | Preventive |
| Concurrent release packagers cannot publish a mixed archive pair or mismatched drop | Cross-platform advisory lock held across archive-pair publication and drop-folder refresh | Preventive |
| Concurrent GitNexus finalizers collide on one temporary file or discard a completed setup update | Cross-platform advisory lock held across finalizer read, setup, and atomic unique-temporary-file replacement | Preventive |
| Release file-list or staging paths escape their repository-owned roots | Reject non-normalized, absolute, dot, parent, symlink-resolved, and out-of-root paths before selection, copy, or archive creation | Preventive |
| Idea-inbox lock acquisition cannot overwrite a linked target | Reject symlinks, Windows reparse points, multiple links, and opened-path identity mismatches before truncation | Preventive |
| Concurrent worker attempts cannot share one repository transaction | Interprocess lock keyed to the canonical Git common directory, held from pristine check through validation or rollback; the per-user lock root requires the expected owner and non-writable group/world permissions, and POSIX leaf locks open relative to its validated directory descriptor | Preventive |
| Worker cannot redirect controller-truth restoration through a symlinked protected directory | Canonical run-root identity checkpoint plus lstat-based directory-topology restoration before protected file reads or writes | Detective, blocks acceptance and restores protected topology |
| Git metadata snapshots consume unbounded memory | Explicit entry, file, and aggregate-byte limits before worker launch | Preventive, fails closed |
| Artifact lock publication or reclamation admits overlapping writers | Permanent cross-platform advisory file lock around the portable owner-directory lock and stale-owner recovery | Preventive and recoverable |
| Completed worker job is not casually repeated | Completed job artifact hash check | Detective, blocks stale reuse |
| Continue cannot shift later failed job IDs | Replay matches worker calls to saved job spec hashes | Preventive in controller |
| Unresolved product decision cannot be skipped on continue | `planning/blocking-decisions.json` blocks replay | Preventive in controller |
| Volatile host capacity changes make a durable worker job appear to have a different specification on continuation | Lock system capacity and unknown-unknowns preflight as run artifacts on first use; `run --continue` reuses those exact artifacts | Preventive, deterministic continuation |
| Stale or internally inconsistent context cannot be reused | Excerpts and source hashes derive from one immutable byte snapshot; freshness validation checks that hash against the live source | Preventive during compilation and detective before execution |
| Untrusted context cannot escape prompt framing | Dynamic payload fences, single-line metadata labels, and validated content hashes | Preventive |
| Required context cannot disappear | Budget compiler raises instead of truncating | Preventive |
| Model cannot mark run complete | Controller state machine | Preventive |
| Unverified patch cannot reach source | Apply only after COMPLETE path and source hash check | Preventive |
| A completed-run proof is attached to a clean commit or replacement patch created after review | Capture source HEAD before the run, reconstruct the reviewed patch from the run-owned workspace, fail completion on any pre-proof mismatch, and require release readiness to match the recorded HEAD and digests | Preventive and detective |
| Release verification gate mutates source used by later gates | Exact-HEAD disposable clone plus post-gate HEAD, tracked, untracked, and ignored mutation checks | Preventive |
| Concurrent clean commit replaces the release candidate while final evidence is written | Git reference transaction held through handoff persistence plus a final HEAD, source-digest, and cleanliness snapshot | Preventive and detective |
| Worktree mutation after the final cleanliness snapshot changes the bytes an operator ships | READY handoff names a SHA-256-bound tar archive generated from the locked exact commit instead of authorizing the mutable worktree | Preventive |
| Windows Git reference transaction receives CRLF-corrupted commands | Write the `update-ref --stdin` transaction as exact binary UTF-8 with LF separators | Preventive |
| Windows contender cannot inspect owner metadata while another process holds a byte-range lock | Rewrite the persistent lock payload in place without truncating the locked file | Preventive |
| Windows cannot execute an npm or other `.cmd` shim directly with `shell=False` | Resolve the shim and invoke it through an explicit `COMSPEC /d /s /c` argv; reject arguments containing cmd.exe metacharacters before launch | Preventive |
| Windows installer selects an incompatible or mismatched Node/npm pair | Probe all known Node candidates, choose one supported Node version, and prefer npm adjacent to that executable | Preventive |
| A later Windows shell resolves an older Node than the installer verified | Persist the selected Node directory in the generated launcher, fail if its executable disappears, and put it before ambient Node installations | Preventive |
| Windows gate output crashes decoding or secondary redaction | Force UTF-8 launcher I/O, decode child output as UTF-8 with replacement, and sanitize absent or byte streams | Preventive and diagnostic-preserving |
| macOS path aliases create false containment or package-manager ownership failures | Compare canonical filesystem parents while preserving the selected executable name | Preventive |
| Non-login macOS shell hides an existing Homebrew installation | Probe `/opt/homebrew/bin/brew` and `/usr/local/bin/brew` before declaring Homebrew unavailable | Preventive |
| Uninstall plan targets a lookalike or dangerously broad prefix | Reject prefixes that contain home or the current working directory; require a matching resolved install lock plus SHA-256-bound random ownership marker; old locks require matching app digest, launcher, venv, and prefix | Preventive |
| Crash during final apply loses proof | Final result/report/patch are written before source apply; continue retries apply only | Detective and recoverable |
| Acceptance cannot be auto-passed | `verification/acceptance-evidence.json` binds outcomes to gates, demo evidence, and review | Preventive in controller |
| Release-ready cannot ship without a valid Manageroo run | Fail-closed final-result schema validation, latest completed run proof, post-gate HEAD and source-tree proof, approved review, final report, final patch, and boolean applied-source status | Preventive release gate |
| Generic worker receives requested read-only/workspace-write enforcement | Explicit non-empty provider argv required per mode; launch and doctor fail closed when missing | Provider enforcement for configured modes; use Codex adapter for a tested native sandbox |

## Critical limitation

A local process running with the operator's full operating-system permissions can attempt hostile behavior. MANAGEROO reduces blast radius through an isolated repository, provider sandbox settings, argv-only controller commands, and validation. It is not a hostile multi-tenant security boundary or virtual machine.

For untrusted models or plugins, run the entire harness inside an OS container or disposable machine.
