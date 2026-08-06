# Uncle Matt's Project Manageroo

> [!TIP]
> ## Quick Start
>
> **1. Install Manageroo**
>
> Linux / macOS:
>
> ```bash
> git clone https://github.com/uncmatteth/Uncle-Matts-Project-Manageroo.git && cd Uncle-Matts-Project-Manageroo && ./install.sh
> ```
>
> Windows PowerShell:
>
> ```powershell
> git clone https://github.com/uncmatteth/Uncle-Matts-Project-Manageroo.git; Set-Location Uncle-Matts-Project-Manageroo; .\install.ps1
> ```
>
> If Git is not installed yet, use GitHub's **Code → Download ZIP**, extract it, open a terminal in the folder, and run the platform command above. The installer checks Python 3.11+ and Git and offers guided setup with the normal platform path: a verified Python package and Apple's Command Line Tools on macOS, common system package managers on Linux, or winget on Windows.

When Codex is selected, setup also verifies Codex's own native sandbox before
calling it ready: `bwrap`/seccomp on Linux and WSL2, Seatbelt on macOS, and the
native Windows sandbox from PowerShell. Failures stop with instructions for that
platform; Manageroo does not apply Linux fixes to macOS or Windows and does not
silently turn the sandbox off.
>
> **2. Follow the guided setup**
>
> Manageroo checks for Codex, Claude Code, and Gemini CLI. If it finds one, it uses it automatically. If it finds several, you can keep automatic selection or choose your preferred tool. If it finds none, it offers to install Codex and its Node.js/npm requirement. It does not guess or replace the account or model configured inside your coding tool. The installer then walks through the portable skill pack, optional supporting tools, token style, project discovery, and a read-only stack check.
>
> Project discovery itself is read-only. Manageroo shows what it found and asks which projects to enroll. Only selected projects receive the context bundle; everything else is left alone.
>
> **3. Point Manageroo at a project**
>
> Open a new terminal and run:
>
> ```bash
> manageroo solo /absolute/path/to/your-project
> ```
>
> Answer the questions in plain English: what you want built or fixed, who it is for, what must not change, and what proof should count. If you are ever unsure what comes next, run `manageroo next`.
>
> You do **not** have to create or fill agent context files yourself. `solo` safely creates or updates `AGENTS.md`, `CONTEXT.md`, `.manageroo/PROJECT-MEMORY.md`, `.manageroo/PRODUCT-BRIEF.md`, the current intent lock, Manageroo configuration, and the repo-local Manageroo skill. Existing human-written `AGENTS.md` and `CONTEXT.md` content is preserved.
>
> **Manageroo for beginners:** Think of Manageroo as the project foreman above your coding agent. You describe the result you want; Manageroo records the mission, maps the repository, gives the coding agent bounded jobs in an isolated workspace, runs the project's checks, performs separate review, and produces evidence and a patch. It does not treat the worker saying “done” as proof. Use `manageroo run --apply` when you want a successfully verified patch applied to your project. Use `manageroo status RUN_ID --repo .` to check a run and `manageroo report RUN_ID --repo .` to read what happened.

---

# What Manageroo is

Manageroo is a local project controller for AI coding agents working on real Git repositories.

The problem is simple: one giant AI chat should not be expected to remember an entire project, discover every hidden risk, write all the code, review itself, verify itself, repair itself, and then decide that its own work is finished.

Manageroo puts a controller above the workers.

```text
YOU DESCRIBE WHAT YOU WANT
        ↓
MANAGEROO CAPTURES THE MISSION
        ↓
PROJECT DISCOVERY + REPOSITORY MAPPING
        ↓
BOUNDED JOBS FOR CODING AGENTS
        ↓
REAL CHECKS + INDEPENDENT REVIEW
        ↓
BOUNDED REPAIR WHEN SOMETHING FAILS
        ↓
EVIDENCE + DELIVERY
```

The coding agents do the work. Manageroo owns the mission, state, boundaries, review, proof, and definition of done.

# Who it is for

Manageroo is for people whose projects have outgrown the normal "paste everything into one chat and hope" workflow.

It is especially useful for:

- large, old, or messy repositories;
- long-running AI-assisted projects;
- work spread across multiple agent sessions;
- requirements that cannot safely disappear during context compaction;
- changes where blast radius matters;
- projects where the agent that wrote the code should not be the only thing reviewing it;
- repair work that needs budgets and stop conditions instead of endless autonomous thrashing;
- solo builders tired of manually saying "keep going, check the rest, test it, are you sure?";
- teams that want evidence instead of "the model says it is done."

Manageroo keeps important project truth outside the worker so a model change, terminal restart, failed run, or new chat does not erase the mission.

# What Manageroo actually does

Manageroo can:

- read and inventory a Git repository;
- capture the requested outcome, must-not rules, and proof expectations;
- preserve an intent lock so important requirements survive long runs and context compaction;
- perform discovery before implementation and surface important unknowns;
- map the repository before assigning implementation work;
- split large work into bounded worker jobs;
- route those jobs to compatible coding-agent CLIs;
- keep job, attempt, retry, and run state on disk;
- isolate worker attempts from the operator's source repository;
- verify changed-file scope and repository state;
- run deterministic project checks;
- bind requested outcomes to required proof;
- perform review separately from implementation;
- run bounded repair loops when work fails verification or review;
- stop and surface high-impact decisions instead of guessing them;
- resume interrupted work from durable state;
- produce reports, evidence, and a patch for delivery.

Manageroo is not an IDE, model host, deployment platform, cloud scheduler, memory database, or code-graph database. It can work with tools that provide those capabilities without handing them control over Manageroo's definition of done.

# The controller is the boss

Built-in worker paths cover:

- Codex;
- Claude Code;
- Gemini;
- compatible generic CLIs.

The default worker mode is provider-neutral `auto`.

```bash
manageroo agent list
```

Workers are intentionally replaceable. The project truth is not.

A worker can write code, investigate a problem, review a change, or repair a failure. It does not get to certify its own work just because it returned a confident answer.

# How Manageroo keeps a project from forgetting itself

Manageroo keeps controller-owned run state under:

```text
.manageroo/runs/<run-id>/
```

That run state records what happened, what is still pending, what failed, what was retried, and what evidence exists.

Project continuity also uses repository-local files such as:

```text
.manageroo/PROJECT-MEMORY.md
.manageroo/intent/INTENT-LOCK.json
.manageroo/intent/INTENT-LOCK.md
```

The point is not to create another giant memory dump. The point is to preserve the pieces of project truth that must survive outside a temporary conversation.

# Discovery before implementation

Before large implementation work, Manageroo looks beyond the literal request and checks areas that commonly get missed, including:

- failure, interruption, rollback, and recovery;
- proof strength;
- scope and non-goals;
- authentication and authorization;
- payments and reconciliation;
- migrations and data preservation;
- deployment and rollback;
- target-project hardware assumptions;
- external services, rate limits, cost, and degraded modes;
- accessibility and user-facing states.

When repository evidence can answer a question, Manageroo uses the evidence. When a genuinely high-impact decision still requires the operator, Manageroo surfaces it explicitly instead of guessing.

# Source isolation and bounded changes

Manageroo performs worker activity in run-owned isolated repositories instead of giving every coding worker unrestricted access to the operator's source tree.

The purpose is simple: workers can work aggressively inside a bounded workspace without casually poisoning the original repository.

Successful work is delivered back through a patch after Manageroo checks that the source repository has not unexpectedly changed underneath the run.

# Proof before "done"

Manageroo reconciles completion against:

- what the user actually requested;
- required proof gates;
- changed-file scope;
- deterministic verification;
- independent review;
- required demonstration evidence.

A passing unit test does not automatically prove a browser flow. A worker saying something was deployed does not prove deployment. A model claiming something is secure does not make it secure.

Claims that require observable evidence remain unproven until matching affirmative evidence exists and records a successful outcome; quoted, negated, or failed-outcome claim text does not count as proof. The compaction audit warns only for affirmative confidence terms, not quoted or negated mentions. Negation is scoped to the local claim clause, so a preceding contrastive clause cannot hide an affirmative confidence claim.

# How to actually use Manageroo

## 1. Point Manageroo at a project

Discover Git repositories on your machine and add them to Manageroo's project list:

```bash
manageroo projects --add
```

For one specific existing repository:

```bash
manageroo solo /absolute/path/to/product
```

`solo` prepares the repository for Manageroo. It safely creates or updates `AGENTS.md`, `CONTEXT.md`, `.manageroo/PROJECT-MEMORY.md`, `.manageroo/PRODUCT-BRIEF.md`, the current intent lock, project configuration, the repo-local Manageroo skill, and readiness state, then tells you the next useful action. You answer normal questions; you do not hand-build or remember these files. Existing human-written instruction and context content is preserved.

For a brand-new project that does not exist yet, or an empty directory:

```bash
manageroo solo /absolute/path/to/new-product \
  --create \
  --want "Describe what should be built first"
```

This creates the starting project structure and captures the initial mission instead of forcing you to hand-build Manageroo's project files first.

## 2. Ask Manageroo what to do next

```bash
manageroo next
```

Use this when you do not remember the workflow or do not know what the current project needs next. Manageroo prints one useful next operator action instead of dumping an enormous checklist on you.

## 3. Run a build or implementation job

```bash
manageroo run --apply
```

This starts a normal Manageroo work run for the current project.

Manageroo reads the project truth, performs discovery and planning, creates bounded worker jobs, sends those jobs to compatible coding agents, checks the resulting changes, runs verification, performs review, and attempts bounded repair when necessary.

`--apply` means Manageroo is allowed to apply a successfully verified delivery patch back to the source repository when its safety checks pass.

Without permission to apply, Manageroo can still perform the run and produce delivery evidence without silently changing the source repository.

## 4. Run an explicit repair job

```bash
manageroo run --mode repair --apply
```

Use repair mode when the mission is specifically to diagnose and fix an existing broken project or failed implementation rather than build a normal new change.

Repair mode still uses bounded work, verification, review, evidence, and controlled retries. It is not a command for endlessly changing files until something happens to pass.

## 5. Check what a run is doing or what happened

Every Manageroo run has a run ID.

See the current state of a run:

```bash
manageroo status RUN_ID --repo .
```

Use `status` for the concise operational view: where the run is, whether it is blocked, whether it failed, and what state it currently holds.

See the fuller human-readable result and evidence:

```bash
manageroo report RUN_ID --repo .
```

Use `report` when you want the explanation of what Manageroo did, what changed, what passed, what failed, what evidence was collected, and what still needs attention.

`--repo .` means "use the repository in my current directory." Replace `.` with an absolute repository path when running the command from somewhere else.

## 6. Continue an interrupted or blocked run

```bash
manageroo run --continue RUN_ID --repo . --apply
```

Use this after a terminal closes, a worker fails, a run pauses for a decision, or another recoverable interruption occurs.

Manageroo reloads the durable state for that exact run and continues from the recorded project truth. It does not pretend the old process kept running in the background.

## 7. Answer a blocking decision

When Manageroo reaches a genuinely high-impact choice that repository evidence cannot safely answer, it can stop instead of making up the answer.

See the decision:

```bash
manageroo decisions show RUN_ID --repo .
```

Record the operator's answer:

```bash
manageroo decisions answer RUN_ID --repo .
```

Then continue the same run:

```bash
manageroo run --continue RUN_ID --repo . --apply
```

The point is to interrupt you only for decisions that actually matter, while letting evidence answer everything else it safely can.

## 8. Inspect project memory and protected intent

Show the current project memory:

```bash
manageroo memory show
```

This is the durable human-readable project continuity Manageroo keeps outside any one agent conversation.

Show the current intent lock:

```bash
manageroo intent show
```

The intent lock protects the important outcomes, constraints, must-not rules, and proof expectations that should not quietly disappear during a long run.

Audit whether a compacted or summarized project description still preserves the important intent:

```bash
manageroo compact audit --summary SUMMARY.md
```

This is useful when a long project history has been summarized and you want to check that the summary did not accidentally throw away something important.

## 9. Run the final Clawpatch release sweep

To run the supervisor directly from a terminal, outside the `manageroo` command tree, use:

```bash
clawpatch-supervise
```

This works in any Git repository; the target does not need Manageroo project
configuration. The command uses the current directory, current branch, verified
pushes after each repair, and the shared 15-minute timeout. It initializes
ClawPatch automatically when the repository is new. When an old stopped
checkpoint remains after its exact owned source paths were already committed,
the supervisor proves that completion from descendant Git history and clears
the obsolete external checkpoint automatically. If the operator deliberately
recreates `.clawpatch`, the supervisor recognizes the newer empty run generation,
restores only the exact stopped-attempt source bytes proven by its checkpoint,
clears that checkpoint, and starts the normal lifecycle. Legacy version-2
checkpoints use the narrower file-timestamp proof available in that schema.
Any changed or additional source path still stops without cleanup. It never requires a
repository-specific cleanup command.
If the stopped checkpoint owns no source paths, a rebuilt generation may already
contain later committed ClawPatch work. The supervisor retires that obsolete
checkpoint only when the worktree is source-clean, the old finding is absent,
and Git proves checkpoint HEAD to generation HEAD to current HEAD ancestry.

Every normal external invocation starts a fresh map, complete review, and current
finding queue. Before rebuilding ClawPatch state, it recovers any recognizable
temporary iteration commit proven by the durable checkpoint. It may discard
dirty source only when the complete dirty path set exactly equals that
checkpoint's owned paths; unrelated work stops the fresh run unchanged.

Exhausting that first queue is not completion. If a review generation found or
recovered any findings, the supervisor preserves committed ClawPatch
configuration, rebuilds only generated ClawPatch run/discovery state, maps the
new HEAD, and performs another complete review. It repeats this fixed-point
cycle without an arbitrary generation cap. `COMPLETE` is emitted only when a
fresh full review generation at the final HEAD finds zero findings and final
closure passes. If a non-clean generation repeats a source-tree state already
seen in the same run, the supervisor stops as nonconvergent instead of claiming
completion or reviewing the same tree forever.

The command preserves committed ClawPatch
configuration, displays the exact current finding as `[current/total] SHOW`,
prints the finding evidence and repair scope, prints each numbered ClawPatch
`fix` attempt before execution, and reports the verified commit. If the target has
`.manageroo/config.toml`, its configured gates run as additional validation. If
it does not, ClawPatch owns validation through its `fix` result and exact-finding
revalidation; the supervisor does not invent test commands. A root PEP 621
project that explicitly configures pytest receives a temporary external virtual
environment containing pytest plus its bounded static runtime and test/dev
dependency declarations. Only ClawPatch children receive that environment, and
it is removed without writing dependency state into the project. External checkpoint
and proof files stay in the Manageroo-owned external-runner state directory
rather than adding files to the target worktree or its Git metadata. A repository
whose root `manageroo-validation.toml` binds `TEST_DATABASE_URL` to one
non-production reset guard used by its tests, with one official versioned PostgreSQL
Compose image, gets a separate owned disposable database automatically. It uses tmpfs,
a random password, and a random loopback-only port; the repository Compose
volume and every existing database remain untouched. The terminal shows service
start, ready, and cleanup, and only ClawPatch children receive its variables.
A heartbeat remains visible every 30
seconds while a long ClawPatch or Codex child is running. The explicit 15-minute
value controls both the outer process watchdog and ClawPatch's Codex provider.
Missing findings, provider failures, timeouts, unsupported revalidation, unsafe
state, or interruption stop with source edits left in place. A ClawPatch
`validation failed after applying fix` result is handled specially as useful
partial progress: exact changed source paths are saved in one local-only
temporary commit and the same finding is run again from a clean tree. The loop
continues only while it produces a new source-tree state.

`--fresh` remains accepted for compatibility, but it is already the normal
external-command default. It never authorizes broad source deletion.

If an older supervisor already stopped with an exact checkpoint-owned repair in
the worktree, preserve and continue that repair once with:

```bash
clawpatch-supervise --resume-stopped
```

That mode does not guess ownership: repository, branch, starting HEAD, finding,
patch attempt, and complete dirty source path set must all match the durable
checkpoint.

Preview the complete closeout lifecycle without changing the repository:

```bash
manageroo clawpatch release-sweep --repo .
```

Execute it on a dedicated branch:

```bash
manageroo clawpatch release-sweep --repo . --apply
```

When Clawpatch runs inside a trusted project and the host already supplies the
required isolation, its Codex worker can be allowed to edit without nested
sandbox failures:

```bash
manageroo clawpatch release-sweep --repo . --apply --trusted-host-codex-sandbox-bypass
```

That flag is deliberately explicit. It disables Codex approval prompts and
sandboxing only for the Clawpatch child processes in this sweep; it is not saved
as a global setting. Do not use it for untrusted code. Manageroo still runs the
project's configured verification gates, requires Clawpatch revalidation, stages
only the exact changed paths, and commits only Clawpatch-owned attempts.

Clawpatch owns finding selection and repair. Manageroo runs `clawpatch status
--json`, clears only proven-stale locks, maps the repository, reviews every
pending feature through Clawpatch, and proves no reviewable feature remains.
Large reviews use ClawPatch's own resumable feature state in bounded worker
waves: a dry-run reports the current worker count and pending features, one
`review --limit <jobs>` child reviews a single parallel wave, and the next
dry-run must show that pending features fell by exactly the reported reviewed
count. This repeats without an arbitrary wave cap until pending is zero. The
900-second watchdog still applies to every child process tree, so one genuinely
stuck feature stops safely while a large healthy repository does not place its
entire review under one 900-second clock.
It then uses `clawpatch next --json` for exactly one current open finding,
records `clawpatch show --json`, and automatically runs Clawpatch's explicit
finding-scoped `fix`. It never builds a queue from a report, substitutes a
Manageroo-written repair, triages a finding as resolved, or hand-repairs source.

The external command's `--timeout-minutes` value controls both the complete
Clawpatch/Codex process-group watchdog and ClawPatch's Codex provider timeout.
Non-fix commands run once. Manageroo does not invent repairs. When `fix` exits
with ClawPatch's validation-failed-after-apply result, it preserves only the
exact changed source paths in one recognizable local iteration commit and calls
`fix` again for that same finding. It stops deterministically on no changes, a
repeated or original source-tree state, history mismatch, or an external error.

The implemented ClawPatch 0.7.2 state machine is:

| Current result | Manageroo transition |
|---|---|
| `next` returns an open finding | Record `show`, then run only that finding's `fix` |
| `fix` changes source but reports validation failed after applying | Save only those exact paths in a local temporary iteration commit; do not push; rerun the same finding from the clean combined tree |
| `fix` is applied and project gates pass | Run `revalidate --finding` |
| Read-only revalidation is `uncertain` | Revalidate the same repair with workspace-write, guarded by an exact source fingerprint; the external supervisor makes one final child-scoped trusted-host pass if workspace-write is still blocked |
| Open queue is empty but `report --status uncertain` is nonempty | Select each item through `next --status uncertain`, rerun exact-finding revalidation with the same guarded workspace-write escalation, accept `fixed` without a source commit, and send an `open` outcome back through the normal same-finding repair loop |
| Revalidation is `open` | Add the exact new patch paths to the same local temporary iteration commit and rerun the same finding; do not push |
| Revalidation is exactly `fixed` | If this finding changed source, amend/squash the combined repair into exactly one normal commit above its start HEAD and verify any authorized push. If an overlapping prior finding already supplied the repair and this finding leaves HEAD and source unchanged, record `no source commit required`. Then call `next`. |
| An iteration changes nothing, repeats a seen tree, or cycles to the original tree | Unwind the temporary commit to visible source edits at the original HEAD, checkpoint exact ownership, and stop without advancing |
| Provider/timeout/missing-finding errors, gates fail, or revalidation remains `uncertain` or `false-positive` | Stop with combined source edits in place and the queue unchanged |
| A selected finding is missing or state is contradictory | Stop; do not remap, review, skip, or triage automatically |
| A stopped checkpoint matches the branch, finding, current dirty paths, exact source fingerprint, and recognizable temporary iteration commit | Accept the latest matching applied or validation-failed attempt at the original/temporary Git boundary, resume the combined repair at project gates, and continue the same finding without discarding partial work |
| An older supervisor stopped after exact `fixed` because an overlapping repair produced no new source | Require a source-clean tree, unchanged checkpoint HEAD, the same finding still `fixed`, and an applied zero-file attempt at that HEAD; clear only the checkpoint and continue at `next` without a commit or push |
| An interrupted `planned` attempt has no source changes, belongs to the same open finding, and matches current HEAD | Preserve ClawPatch state, clear only the external checkpoint, require `next` to return that same finding, then continue through `show` and `fix` |
| A stopped checkpoint's exact owned source paths already appear as one exact descendant source commit and the worktree is source-clean | Clear that completed stale checkpoint automatically and continue normally |
| A clean branch advanced from the checkpoint's original HEAD on history that does not contain its temporary iteration commit | Prove both ancestry facts, retire only the dangling external checkpoint, and preserve the current commit and files unchanged |
| `.clawpatch` was deliberately rebuilt after a stopped attempt | When the new generation is empty, branch and HEAD still match, and the exact dirty source fingerprint still matches, restore only those checkpoint-owned files and continue normally; preserve everything on any mismatch |
| A rebuilt generation supersedes a zero-path checkpoint and HEAD later advances | Require a source-clean worktree, absent old finding, newer generation on the same branch, and checkpoint-to-generation-to-current Git ancestry; clear only the obsolete external checkpoint |
| A prior checkpoint is missing or fails any ownership check | Refuse cleanup or continuation; both fresh lanes require exact checkpoint ownership before discarding source |
| A complete review generation found or recovered one or more findings | Finish that generation's exact-finding repairs and closure, rebuild generated ClawPatch state while preserving committed configuration, then map and completely review the resulting HEAD again |
| A fresh full review generation finds zero findings | Run final closure and emit `COMPLETE` with every review generation recorded in the proof |
| A non-clean fresh generation repeats a previously seen source tree | Stop as nonconvergent; do not claim completion and do not begin another generation |

After each validated fix, Manageroo requires the matching patch-attempt record,
runs every configured project gate, revalidates the same finding, and stages
only exact source paths. Partial iterations remain local and are amended into
one temporary commit so ClawPatch always sees a clean combined tree. There is
no arbitrary attempt cap: only a genuinely new Git tree permits another same-
finding attempt. A finding is counted complete only after exact `fixed`
revalidation and either one final combined commit with required push verification,
or proof that HEAD and source remained unchanged because no additional repair was needed.
Clawpatch state metadata is never mixed into a source commit.

After a stopped process is relaunched, Manageroo resumes only when the durable
checkpoint's branch, finding, exact dirty path set, source fingerprint, original
HEAD, and recognizable temporary iteration commit agree. A partial-progress chain
may contain several `failed` patch-attempt records because ClawPatch uses that
status when validation fails after applying useful source changes. Manageroo
selects the latest matching attempt at the recorded original/temporary Git
boundary and resumes the combined repair at project gates. A `fixed` result
creates the final exact-path commit; an `open` result becomes a local-only
iteration commit and continues the same finding without pushing partial work.
Any ambiguity leaves the checkpoint and edits untouched.
For compatibility with a checkpoint written by an older supervisor after an
overlapping finding was already fixed, a zero-path checkpoint is retired only
when the worktree is source-clean, HEAD is unchanged, the same finding is
currently `fixed`, and ClawPatch records an applied zero-file attempt at that
HEAD. Relaunch records no source commit required and advances through `next`.
Stopped checkpoints include an exact source-content fingerprint. A newer, empty
`.clawpatch` generation is treated as an intentional reset only when that
fingerprint, branch, HEAD, owned path set, and generation timestamps all agree.

Clawpatch's `show` output ends with a human triage template. That template is
not an executable workflow command. Manageroo preserves the inspection output
for the audit record and applies its explicit release policy: every current
open finding is sent to `clawpatch fix`; findings are never automatically
hidden or marked resolved. Revalidation starts read-only. If that pass is
`uncertain`, Manageroo reruns revalidation with controlled workspace-write
access so targeted tests can create temporary files, while an exact source-state
fingerprint prevents that validation pass from changing the repair. For the
installed external supervisor, a workspace-write result that is still
`uncertain` gets one final child-scoped trusted-host revalidation so tools such
as Gradle can use local sockets and file locks. A result that remains
`uncertain` after that pass, or any source-mutating validation, is stopped with
the repair left visible; it does not trigger another source fix.

Release sweeps default every Clawpatch child command and the Codex worker to a
shared 15-minute timeout. `clawpatch-supervise --timeout-minutes N` changes both
limits together, so the terminal never advertises a different timeout from the
one actually enforced.

Before each finding-scoped fix, Manageroo writes durable progress. The external
`clawpatch-supervise` command stores it beside its Manageroo-owned installation; the
Manageroo project command stores it under `.manageroo/cache`. On a handled
failure or interruption it records the exact
source paths that appeared while that one owned fix was active. A later ordinary
run resumes an exact applied attempt, or clears a completed stale checkpoint
only when descendant Git history contains one commit whose non-ClawPatch paths
exactly equal those owned paths. When the operator explicitly uses
`--fresh` through the Manageroo project command, source is discarded only when
the current dirty-path set exactly matches that checkpoint ownership record.
The portable external supervisor uses the same exact-ownership reset contract:
unrelated dirty source blocks unchanged. It removes old run/discovery state and
initializes ClawPatch again only after owned interrupted work has been proven
and recovered. The external runner also migrates a validated version-2 checkpoint from the old
`.manageroo/cache` location into its Manageroo-owned state directory before
cleanup. Manageroo does not install an operating-system restart daemon.

At closure, Manageroo proves no mapped feature remains pending and revalidates
all open findings. If the open report is empty but ClawPatch still has
`uncertain` findings, Manageroo selects them with ClawPatch's documented
`next --status uncertain` transition and revalidates each exact finding. A
`fixed` result needs no source commit; an `open` result returns to the normal
same-finding `fix` loop; a still-`uncertain` result is a real blocker. Closure
then requires both open and uncertain reports to be empty, requires zero open
findings and locks in status, reruns every project gate, and requires a clean
Git worktree.
Tracked `.clawpatch/**` state is never mixed
into a source-repair commit. To publish tracked state after closure, explicitly
add `--publish-clawpatch-state` together with a push mode; Manageroo creates one
separate final state-only commit and verifies the live remote SHA. Without that
option, successful closure removes generated ClawPatch runtime state and restores
the repository's committed `.clawpatch` files byte-for-byte, so committed
configuration is preserved and the worktree finishes clean. That terminal
cleanup is available only after a fresh zero-finding review generation. A
generation that contained findings performs intermediate closure and starts a
new map and complete review from the resulting source tree. The external proof
records every generation's HEAD, source tree, mapped/reviewed feature counts,
finding count, and whether it was the clean terminal generation.

Dry-run is the default. `--apply` explicitly authorizes fixes and exact-path
source commits. Nothing is pushed unless you add `--push each` or `--push final`.
On `main` or `master`, `--branch auto` creates a timestamped
`clawpatch/release-sweep-*` branch; use `--branch current` only deliberately.

To make the normal release gate require that proof, use:

```bash
manageroo release-ready --require-clawpatch
```

Or set `require_clawpatch_release_sweep = true` under `[project]` in `.manageroo/config.toml`.

# Hardware compatibility

Manageroo core is hardware-agnostic.

It does not require a specific GPU, VRAM amount, CPU tier, or RAM class. A target project or explicitly selected local AI tool may have its own hardware requirements, but those belong to that project or tool.

Inspect the current host:

```bash
manageroo capacity
manageroo capacity --json
```

The hardware profile is informational context. Manageroo does not silently rewrite worker concurrency based on one developer machine.

# Skills: exactly what is included

Users do not need to remember or type skill names. Before every worker job,
Manageroo indexes installed skill metadata locally, matches the normal-language
assignment, and injects only the strongest relevant full instructions into a
bounded task packet. The route is automatic and never asks the operator to
choose implementation machinery. The operator's original brief controls which
skills are eligible; an implementation task may only rerank that approved set,
so model-generated plan text cannot activate a new capability.

The installer's **normal**, **Caveman**, and **Caveman Curse** choice is a
separate saved communication preference. It is selected once during setup and
applied automatically; those modes do not compete in task routing.

This repository currently contains **54 bundled skill packages**.

That does **not** mean Manageroo installs all 54 by default.

The boundary is:

- **22 portable core skills** are the recommended/default Manageroo-owned pack;
- **32 additional bundled skills** ship in the repository as optional capabilities;
- **host-installed skills** can also be discovered and used when relevant, but Manageroo does not claim ownership of the user's entire skill environment.

Before installing a core skill, setup checks the standard agent skill roots. It
reuses an existing same-name skill instead of creating another copy, and it does
not overwrite a differing host-owned skill. Manageroo updates only skill trees
recorded in its ownership ledger and still unchanged since Manageroo installed
them; a user edit revokes that ownership automatically.

## 22 portable core skills installed by default

1. `uncle-matts-project-manageroo`
2. `use-installed-skills-first`
3. `skill-vetter`
4. `pimp-my-prompt`
5. `setup-matt-pocock-skills`
6. `to-spec`
7. `to-tickets`
8. `grill-me`
9. `grilling`
10. `grill-with-docs`
11. `domain-modeling`
12. `codebase-design`
13. `diagnosing-bugs`
14. `tdd`
15. `testing`
16. `security-review`
17. `handoff`
18. `writing-for-agents`
19. `edit-skill`
20. `skillify`
21. `caveman`
22. `uncle-matts-caveman-curse`

These are the small portable core Manageroo installs as its own default skill pack.

## 32 additional bundled optional skills

These ship with the repository but are **not installed as Manageroo-owned defaults**:

- `academic-verify`
- `article-enrichment`
- `autoreview`
- `book-mirror`
- `brain-ops`
- `brain-pdf`
- `citation-fixer`
- `cross-modal-review`
- `data-research`
- `exact-text-replacement`
- `find-skills`
- `fix-my-bad-website`
- `functional-area-resolver`
- `idea-ingest`
- `improve-codebase-architecture`
- `ingest`
- `media-ingest`
- `minion-orchestrator`
- `open-design`
- `pdf`
- `perplexity-research`
- `plain-web-copy`
- `playwright`
- `playwright-interactive`
- `query`
- `repo-architecture`
- `reports`
- `skillpack-check`
- `strategic-reading`
- `subagent-orchestrator`
- `voice-note-ingest`
- `web-design-guidelines`

Optional means exactly that: available in the bundled library, not silently installed as part of the portable core.

## Host skills are a separate boundary

A user's machine may already contain additional skills. Manageroo can inventory them without taking ownership of them:

```bash
manageroo host-skills
manageroo host-skills --json
```

Automatic capability routing is native controller behavior. `use-installed-skills-first` remains a portable compatibility policy for work that happens outside a Manageroo-controlled run. Manageroo does not copy, delete, upgrade, or pretend it owns the whole host skill environment.

Advanced diagnostics can explain the same decision without changing it:

```bash
manageroo skills explain "describe the job normally"
```

`skill-vetter` exists so third-party skills can be reviewed before adoption instead of being treated as trusted just because somebody put a `SKILL.md` in a folder.

# Optional surrounding tool stack

Manageroo is the controller. It can also work with optional tools that add specialized capabilities:

```text
Manageroo
├── GitNexus   → repository and code-graph intelligence
├── GBrain     → external durable knowledge and retrieval
├── TruffleHog → local secret scanning required by AUTOREVIEW
├── AUTOREVIEW → structured external review
├── Clawpatch  → evidence-driven findings and repair loops
└── Obsidian   → human-readable Markdown knowledge
```

These integrations add capabilities. They do not become the authority over Manageroo completion.

Inspect what is installed and configured:

```bash
manageroo stack-status
```

Check the surrounding stack for configuration or health problems:

```bash
manageroo stack-doctor
```

Preview supported updates without changing anything:

```bash
manageroo stack-update
```

Apply supported updates explicitly:

```bash
manageroo stack-update --apply
```

For npm/pnpm command-line tools, Manageroo updates through the package manager proven to own the active executable and tries the other supported manager only when ownership is verified there. It refuses ambiguous installations instead of guessing.

AUTOREVIEW requires TruffleHog. When the recommended stack is selected, Manageroo reuses an existing `trufflehog` command or installs the release-pinned official binary for Linux, macOS, or Windows after SHA-256 verification. Manageroo records ownership only for the copy it installed, so stack updates and uninstall planning do not overwrite or remove a user-managed copy.

GitNexus is treated as a first-class recommended repository-intelligence integration when selected during installation. Manageroo can still operate when optional surrounding tools are intentionally skipped or unavailable.

# Credits and influences

Manageroo did not appear from nowhere. It deliberately combines ideas from people and projects across the agent ecosystem while keeping its own controller as the authority over the run.

## Peter Yang / [@petergyang](https://x.com/petergyang) — The Skill Smith

Credit for the skill-hygiene direction: tighter reusable skills, self-improving skill loops, and the `edit-skill` idea.

## Matthew Berman / [@MatthewBerman](https://x.com/MatthewBerman) and Forward Future / [@ForwardFuture](https://x.com/ForwardFuture) — Captain Looplight

Credit for the plain-language framing of bounded agent work: a task, verifier, budget, stopping rule, and evidence. Manageroo implements its own orchestration and has no Loop Library runtime dependency.

Loop Library: https://signals.forwardfuture.com/loop-library/

## Garry Tan / [@garrytan](https://x.com/garrytan) — GBrain / The Memory Architect

Credit for GBrain's local durable-memory and retrieval direction: useful knowledge should survive outside the immediate prompt instead of forcing every agent session to rediscover the world.

GBrain: https://github.com/garrytan/gbrain

## Abhigyan Patwari — GitNexus / The Graph Cartographer

Credit for code-graph and impact-analysis direction: repositories have relationships and blast radius, not just flat piles of files.

No X handle is listed here because one has not been confidently verified.

GitNexus: https://github.com/abhigyanpatwari/GitNexus

## OpenClaw / [@OpenClaw](https://x.com/OpenClaw) — Agent Skills, AUTOREVIEW, and Clawpatch / The Patch Council

Credit for agent-skill packaging, structured review, and explicit evidence-to-fix loops.

Agent Skills: https://github.com/openclaw/agent-skills

Clawpatch: https://github.com/openclaw/clawpatch

## OpenAI / [@OpenAI](https://x.com/OpenAI) — Codex skill ecosystem / The Skill Forge

Credit specifically for Codex-oriented skill routing, skill-creator guidance, and agent-readable skill packaging. This is **not** a claim that OpenAI invented the general concept of skills.

Codex: https://developers.openai.com/codex/

## Obsidian / [@obsdmd](https://x.com/obsdmd) — The Vault Keeper

Credit for the human-readable Markdown knowledge direction: important project context should remain understandable and editable by the person who owns the project.

Obsidian: https://obsidian.md/

Together, these influences cover different parts of the problem: skills shape specialized work, loops bound the mission, memory preserves useful knowledge, graphs reveal code relationships, review catches failures, repair closes the loop, and Markdown keeps a human-readable trail.

Manageroo's contribution is the controller above those pieces: the layer that owns the mission, durable run state, decisions, boundaries, verification, evidence, and definition of done.

# Documentation

- [`docs/00_START_HERE.md`](docs/00_START_HERE.md)
- [`docs/INSTALLATION.md`](docs/INSTALLATION.md)
- [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md)
- [`docs/AGENT_PROTOCOL.md`](docs/AGENT_PROTOCOL.md)
- [`docs/CONTEXT_COMPILER.md`](docs/CONTEXT_COMPILER.md)
- [`docs/DISCOVERY_AND_CAPACITY.md`](docs/DISCOVERY_AND_CAPACITY.md)
- [`docs/EVIDENCE_RETRIEVAL.md`](docs/EVIDENCE_RETRIEVAL.md)
- [`docs/HOST_SKILL_ECOSYSTEM.md`](docs/HOST_SKILL_ECOSYSTEM.md)
- [`docs/REVIEW_REPAIR_LANES.md`](docs/REVIEW_REPAIR_LANES.md)
- [`docs/LIMITATIONS.md`](docs/LIMITATIONS.md)
- [`docs/CREDITS.md`](docs/CREDITS.md)

# License

See [`LICENSE`](LICENSE).
