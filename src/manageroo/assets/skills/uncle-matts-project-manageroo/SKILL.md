---
name: uncle-matts-project-manageroo
description: Use MANAGEROO when an AI agent needs to build, repair, refactor, or rescue a repo without drifting away from the brief, files, checks, review, and final proof.
---

# Uncle Matt's Project Manageroo

The local `manageroo` command owns the run. This skill tells an AI agent how to participate without freelancing.

## Mandatory operating model

1. Read the exact packet path supplied by the controller.
2. Treat locked artifacts and task boundaries as immutable.
3. Use only the context and repository evidence relevant to the assigned role.
4. Return JSON matching the supplied schema.
5. Do not commit, push, switch branches, modify `.git`, or edit `.manageroo/config.toml`.
6. Do not weaken tests or redefine acceptance criteria.
7. Do not claim global completion. Only the controller may mark a run `COMPLETE`.
8. When scope is insufficient, return `scope_expansion_requested`; do not expand it yourself.
9. Report possible future features as ideas; do not silently build them.
10. Every factual review finding must cite current file evidence.
11. Read `.manageroo/PROJECT-MEMORY.md` before broad product work and preserve `What Must Not Break`.
12. Run `manageroo intent show --json` before trusting compacted chat, handoffs, or old summaries; use its validated `lock`, not the generated `INTENT-LOCK.md` directly.
13. Do not apply learning cards without explicit operator approval.

## Context rule

No role receives or relies on the full prior conversation. The packet is the complete authority for that role. Read its `manifest.json` when provenance or omissions matter.

If a compacted summary, handoff, or resumed chat drops the locked ask, must-not rules, rejected ideas, latest corrections, proof, or scope boundaries, stop and run:

```bash
manageroo compact audit --summary SUMMARY.md
```

Do not call a plan best, perfect, ready, or 100% complete unless current evidence proves that exact claim.

## Operator communication

Report to the operator in plain everyday English by default. Say what happened,
what it means for the requested work, and what to do next. Do not lead with
process IDs, internal role names, state-file paths, hashes, stack traces, or
implementation jargon. Keep technical details in saved evidence unless the
operator explicitly asks for them or requests diagnostic or JSON output.

## First-install request policy

Manageroo's first installation is intentionally human-first because the installer presents meaningful choices about the local setup.

When a user asks an AI or IDE agent to install Manageroo, do not silently guess those choices and run an unattended end-to-end installation by default.

First explain that:

- the user should preferably run the installer themselves the first time;
- this lets them see what is happening and choose optional components intentionally;
- the agent can provide the exact command and explain every choice;
- if the user still wants agent-assisted installation, gather their selections instead of guessing.

Recommended starting commands:

```bash
./install.sh
```

Windows PowerShell:

```powershell
.\install.ps1
```

Meaningful choices include the recommended surrounding stack, GBrain lane, core skill installation, token-reduction mode, stack doctor, Clawpatch/Codex login assistance, music, and animation.

Project discovery is automatic and read-only. Installation must not ask the operator to select or enroll a project. The interactive installer finishes by opening bare `manageroo`, which scans the usual project folders and prints `Hi! I'm Manageroo! Let's do!` before accepting the work request. Manageroo asks which project only after the request and only when automatic matching is ambiguous.

Do not invent selections or bypass explicit choices.

## Core skill routing

Manageroo owns a small portable 22-skill core. Do not load the whole pack for every job. Route only to relevant helpers.

- Manageroo-controlled workers receive automatic capability capsules. Do not ask the operator to choose or remember skills.
- Outside a Manageroo-controlled run, use `$use-installed-skills-first` before non-trivial local work when the host supports skills.
- Use `$skill-vetter` before adopting or installing third-party skills from external sources.
- Use `$pimp-my-prompt` when a rough or overloaded request needs exact scope, acceptance criteria, proof, and stop rules.
- Use `$setup-matt-pocock-skills` once per repo before the tracker-aware engineering flow.
- Use `$to-spec`, `$to-tickets`, `$grill-me`, or `$grill-with-docs` for product definition, ticket breakdown, and requirement pressure.
- Use `$diagnosing-bugs` before editing when something is broken, flaky, slow, or confusing.
- Use `$tdd` for behavior that should be protected by tests.
- Use `$testing` for broader test-suite and conformance work.
- Use `$security-review` for auth, secrets, deployments, custody, data loss, public readiness claims, and production-risk review.
- Use `$handoff` when a fresh agent needs to continue from durable evidence rather than chat memory.
- Use `$writing-for-agents`, `$edit-skill`, and `$skillify` for reusable agent instructions and skill cleanup.
- Use `$caveman` or `$uncle-matts-caveman-curse` only when the selected token mode or user explicitly asks for token reduction.

## Host and optional skill routing

Additional skills may exist in the host environment or Manageroo's optional source library. Their presence is not guaranteed.

Before invoking one:

1. confirm that the skill is actually installed and relevant;
2. read its current `SKILL.md`;
3. confirm any required tools are available;
4. do not treat a host-owned skill as part of Manageroo's portable core.

Potential specialist categories include research, document handling, design, browser automation, architecture review, external memory, and orchestration helpers. Route to them only when present and useful.

## First-class surrounding integrations

Manageroo remains the controller, but the recommended full setup can include:

- **GitNexus** for repository/code-graph intelligence;
- **GBrain** for external durable knowledge when explicitly relevant;
- **AUTOREVIEW** for external review;
- **Clawpatch** for external review and repair;
- **Obsidian** for human-readable knowledge.

### GitNexus

GitNexus is a first-class recommended repository-intelligence integration, not a completion authority.

When GitNexus is available and the task benefits from code-relationship knowledge, use its current installed capabilities for repository exploration, dependency awareness, impact analysis, debugging, and refactoring. Repository indexing is project-specific.

Do not assume GitNexus is installed merely because Manageroo supports it. Degrade gracefully when it was intentionally skipped or unavailable.

### GBrain

Ordinary Manageroo project continuity belongs in `.manageroo/PROJECT-MEMORY.md` and the intent lock.

Require GBrain only when the task explicitly needs GBrain, a brain page, Obsidian-backed context, or an external knowledge base.

### AUTOREVIEW and Clawpatch

AUTOREVIEW and Clawpatch are command-owned lanes. Run the configured command, capture exact output and artifacts, and let the tool own any supported repair/apply behavior.

Do not convert their findings into untracked AI freehand fixes. If a configured external repair command fails or cannot repair its own finding, preserve the exact evidence and let Manageroo's controller policy decide the next state.

For a final Clawpatch closeout, preview the native cross-platform workflow first:

```bash
manageroo clawpatch release-sweep --repo .
```

Only run it with `--apply` when the operator has authorized repository changes.
Clawpatch owns review, finding selection, and repair. Manageroo reviews every
pending mapped feature, verifies no review work remains, selects one current
open finding with `next --json`, records `show --json`, and automatically invokes
that finding's Clawpatch `fix`. The `show` triage template is human guidance, not
an executable repair. Never build a report-derived queue or hand-repair a
finding. Every Clawpatch child process group uses the supervisor's shared
watchdog, which defaults to 60 minutes. Provider, quota, and timeout failures
stop immediately instead of being mislabeled as uncertain. On a retryable
validation, project-gate, or non-`fixed` revalidation failure, preserve source
edits in a verified named Git stash, reconcile with `show`, reopen through
Clawpatch when necessary, require `next` to return the same finding, and invoke
that finding's Clawpatch `fix` again without an arbitrary attempt cap.
Durable progress under `.manageroo/cache` supports the same reconciliation when
the release sweep is relaunched after interruption. After success, require the
matching patch attempt, complete project validation, and exact `fixed`
revalidation before staging only that attempt's source paths. Pushing requires
`--push each` or `--push final`. A valid final proof requires zero pending review
work, zero open or uncertain findings, zero locks, passing gates, clean Git
state, and an exact final-HEAD binding.

## Role separation

Planning, implementation, verification, and review run in fresh processes. A reviewer is not an implementer and must not mutate the reviewed repository.

Review both:

- **implementation quality**: whether the change follows current repository standards and avoids regressions;
- **requested-outcome fidelity**: whether the change actually satisfies the brief, acceptance criteria, and proof expectations.

Passing one axis does not imply the other passed.

## Evidence rule

Current repository truth beats stale memory, summaries, old plans, or assumptions.

Retrieve current files and command output before making factual claims that depend on repository state. Never claim runtime proof from static inspection.

## Learning card lane

After a run, inspect learning cards when the operator asks what should improve next:

```bash
manageroo learning list
manageroo learning show CARD_ID
```

Applying a supported card still requires:

```bash
manageroo learning apply CARD_ID --approve
```

A card is evidence-backed advice, not permission for silent self-mutation.

## Completion

A successful worker response is only one piece of the run. Completion requires Manageroo-owned scope checks, real gates, review, acceptance evidence, and the final report.
