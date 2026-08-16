# Architecture

## Thin controller, strong artifacts

Manageroo is a **portable core** coding foreman. It is not an IDE, model host,
code-graph database, or conversational-memory substitute. It coordinates
isolated workers and optional external tools through durable, inspectable
artifacts.

```text
Operator request
  └─ Continuity and repository binding
      └─ CLI / Orchestrator
          ├─ Durable state machine and job store
          ├─ Run-owned source mirror
          ├─ Context and capability compiler
          ├─ Isolated worker adapter
          ├─ Scope, command, and transaction policy
          ├─ Deterministic disposable gates
          ├─ Independent review
          ├─ Optional enhanced integration lanes
          ├─ Delivery transaction and recovery
          └─ Signed completion receipt
```

Manageroo owns run truth, intent, repository identity, verification, delivery,
and completion. An agent response or external provider output is never itself
completion authority.

## Automatic managed execution

Codex continuity hooks provide the operator-facing automatic routing boundary.
For actionable repository work they:

1. classify execution intent;
2. resolve and bind the exact repository before tool lockdown;
3. persist the exact operator request and ordered additions;
4. deny freehand repository mutation;
5. allow only the corresponding Manageroo run/status/report path;
6. require controller-owned completion proof before Stop succeeds.

A mutating request routes to the applying path only when mutation is authorized.
A read-only repository audit routes to a non-applying run. Status questions,
acknowledgments, pause, resume, cancel, and replacement are lifecycle operations,
not accidental implementation jobs.

The current repository binding wins over convenience guesses. An explicit path
or project name outranks the current directory and project registry. Ambiguous or
unresolved identity fails visibly instead of selecting an unrelated sole project.
Once a request is bound, changing repositories requires explicit replacement.

## Request continuity

A managed request has:

- a session identity;
- a generation number;
- the original request;
- ordered additional requirements;
- an execution intent;
- an exact bound repository;
- request and metadata digests;
- an optional exact authorized completion receipt.

Acknowledgments such as “thanks” or “okay” do not change the canonical task or
invalidate proof. Genuine additional requirements create a new generation and
invalidate old completion authorization. Pause preserves the request but blocks
new work. Resume continues the same durable generation. Cancel removes work
authority and completion binding. Replacement creates a fresh generation and may
bind a different repository.

Continuity state is signed with a private local authority key. Missing state can
represent an unmanaged session. Existing malformed, truncated, unreadable,
unsupported, or invalidly signed state fails closed at PreToolUse and Stop. It
never silently tells the agent to continue normally.

Controlled workers run in `structured-worker` mode so operator continuity hooks
do not interfere with schema-bound worker output.

## Read-only repository analysis

Read-only audits are first-class managed runs. They use isolated read-only
workers, current repository evidence, bounded context, and independent
controller validation. They produce durable structured and human-readable
reports while proving that the product repository did not change.

A read-only completion receipt records read-only intent and cannot satisfy a
mutating request. A request such as “review this repository and do not change
anything” never receives `--apply` authority.

## Source isolation

The source repository is inventoried through Git-visible tracked and unignored
files. Manageroo copies it into a run-owned repository and verifies file digest,
size, mode, and identity before establishing the internal baseline.

Workers do not need direct write access to the operator's source repository.
Visible source paths and pending paths must be supported regular files or real
directories. Unsafe symlinks, FIFOs, sockets, devices, path escapes, and unstable
filesystem identities fail closed.

Workspace-write workers may modify only their disposable repository. They may
not change Git history, refs, repository-local Git metadata, or controller-owned
run truth. Failed attempts restore the exact pre-attempt Git and controller
state. Read-only worker mutation is detected and discarded.

## Durable worker jobs

Manageroo does not rely on a worker remembering previous chat. Each role receives
one complete bounded packet. Durable truth lives on disk:

```text
.manageroo/runs/<run-id>/
├─ controller/truth.json
├─ controller/phase-journal.jsonl
├─ jobs/<job-id>.json
├─ worker-attempts/<job-id>/<attempt-id>.json
├─ packets/<job-id>/<attempt-id>/prompt.md
├─ agent-output/<job-id>/<attempt-id>.json
├─ artifacts/
└─ delivery/
```

A completed job is reusable only when its immutable specification, output
artifact, artifact digest, parsed result digest, and latest completed attempt
still agree. Missing, replaced, symlinked, or stale output returns the job to a
retryable state instead of trusting it.

`manageroo run --continue <run-id>` replays the Python controller from durable
facts. It does not depend on the old model process.

## Roles and planning

Typical fresh roles include:

- product analyst;
- reuse researcher;
- repository mapper;
- map reducer;
- plan compiler;
- plan reviewer;
- implementer;
- independent reviewer;
- repairer.

Only verified structured artifacts move between roles. Exact-task mode can omit
unnecessary analysis/model phases when targets, exclusions, outcomes, proof, and
scope are already explicit; implementation, verification, review, and delivery
controls remain active.

Plan proof bindings connect every acceptance outcome to configured deterministic
gates. Observable, security, deployment, authentication, visual, and user-journey
outcomes require appropriate demonstration evidence rather than an unrelated
green command.

## Deterministic gates

Every gate runs in a disposable checkout containing the reviewed current working
tree. Manageroo validates the executable against command policy and rejects any
tracked, untracked, ignored, mode, symlink, HEAD, or Git-history mutation of that
checkout. Gate output can never become the delivery patch.

A required gate failure blocks completion. At least one real gate is required for
a normal completion claim.

## Independent review and repair

Independent review receives the reviewed checkpoint, changed files, plan,
acceptance bindings, and relevant evidence. It cannot edit the implementation
workspace.

Core Manageroo review and repair do not require AUTOREVIEW or Clawpatch. Those
are optional enhanced command-owned lanes. When configured, each runs from a
clean controller checkpoint. Manageroo captures and scope-checks changes,
rejects Git-history or controller-metadata mutation, and verifies rollback on
failure. External findings are not copied into an unrestricted AI repair prompt.

## Evidence retrieval

Manageroo normalizes current repository intelligence, run artifacts, project
memory, and optional external knowledge into provenance-preserving evidence.
Each item retains source, location when known, authority, confidence, freshness,
retrieval time, and content hash.

```text
Current Git files ───────┐
Run artifacts ───────────┤
Project memory ──────────┼─> ranking ─> bounded ContextCompiler packets
GitNexus (optional) ─────┤
GBrain (optional) ───────┘
```

Direct current repository evidence outranks stale or semantic external context.
Evidence can inform planning; it cannot authorize edits, pass gates, approve
review, apply a patch, or mark a run complete.

## Portable core and enhanced capabilities

The portable core requires Python, Git, a supported isolated coding-agent
adapter, a Git-backed project, deterministic gates, and Manageroo's own
transactional/evidence/completion machinery.

Enhanced capabilities are optional unless explicitly required:

- GitNexus repository intelligence;
- GBrain exact-repository durable context and capture;
- AUTOREVIEW;
- Clawpatch;
- Obsidian Markdown search/export;
- bounded document/media analysis when the request actually requires it.

Readiness, setup, installer output, and runtime consume the same capability
contract. Optional absence is reported but does not produce a false blocker.
Explicitly required absence names the missing capability and remediation.

When GBrain is used, queries and capture require an exact source mapping for the
bound repository and reject cross-source output. When Obsidian is used, vault
and export operations use no-follow descriptor-relative filesystem checks on
supported platforms.

## Delivery and recovery

Mutating runs deliver through a transaction:

1. generate a binary-capable patch from the isolated baseline to the reviewed
   final checkpoint;
2. bind the patch digest and expected source state;
3. verify the source still matches the original manifest;
4. run `git apply --check`;
5. record the delivery transaction before source mutation;
6. apply only when the request authorizes mutation;
7. verify the resulting source tree against the reviewed workspace;
8. reverse only Manageroo's patch if a concurrent source edit makes final
   verification fail;
9. write final result/report and durable completion proof.

Incomplete delivery recovery runs before optional integration checks or ordinary
preflight. It uses only local Git, filesystem state, and Manageroo transaction
records. External provider outages cannot prevent restoration of repository
consistency. Recovery is idempotent across repeated restarts.

## Signed completion receipt

The Stop boundary does not search historical run folders for files that merely
look complete. A successful run creates one signed controller-owned receipt bound
to:

- session and request generation;
- exact request and metadata digests;
- execution intent;
- exact run ID and repository identity;
- starting Git HEAD;
- final patch digest where applicable;
- final result and conformance proof digests;
- applied/current source-tree identity;
- creation time and authority signature.

Continuity state points to the one exact receipt authorized for the active
request. Stop verifies the signature, every bound artifact, and the current
repository state. Forged JSON, another request's receipt, an earlier generation,
another repository, a reverted patch, or source edits after completion all fail.

## Completion authority

Only the controller state machine can transition to `COMPLETE`. Worker prose,
operator chat claims, external tool success, and committed validation summaries
are not substitutes for current proof.

A completion claim therefore means:

- the exact current request and repository were used;
- authorized work was performed in isolation;
- scope and Git/controller integrity held;
- deterministic gates passed;
- independent review and acceptance evidence passed;
- delivery was completed or read-only immutability was proven;
- a signed receipt still matches the current repository.

## Concurrency

Implementation tasks remain dependency ordered and exclusive when they share a
writable integration workspace. Read-only mapping and review can use isolated
per-worker checkouts and bounded parallel calls. Parallel result collection is
deterministic, while any attempted mutation of a read-only checkout is rejected.

## Installation and updates

The installer stages the complete runtime before replacing the live app tree,
checks source/app digests, preserves unrelated hooks, records provenance, and
reports whether the portable core is usable. It distinguishes:

- core installed and ready;
- installed but coding-agent setup required;
- optional enhanced lanes available;
- optional enhanced lanes unavailable;
- precise required next action.

Updates and uninstall act only on Manageroo-owned unchanged resources. Existing
user-owned tools and edited skill trees are preserved.
