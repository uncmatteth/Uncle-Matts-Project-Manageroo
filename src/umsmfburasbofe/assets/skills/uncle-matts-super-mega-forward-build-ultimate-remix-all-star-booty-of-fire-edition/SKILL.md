---
name: uncle-matts-super-mega-forward-build-ultimate-remix-all-star-booty-of-fire-edition
description: Use UMSMFBURASBOFE when an AI agent needs to build, repair, refactor, or rescue a repo without drifting away from the brief, files, checks, review, and final proof.
---

# Uncle Matt's Super Mega Forward Build Ultimate Remix All-Star Booty of Fire Edition

The local `umsmfburasbofe` command owns the run. This skill tells an AI agent how
to participate without freelancing.

## Mandatory operating model

1. Read the exact packet path supplied by the controller.
2. Treat locked artifacts and task boundaries as immutable.
3. Use only the context and repository evidence relevant to the assigned role.
4. Return JSON matching the supplied schema.
5. Do not commit, push, switch branches, modify `.git`, or edit `.umsmfburasbofe/config.toml`.
6. Do not weaken tests or redefine acceptance criteria.
7. Do not claim global completion. Only the controller may mark a run `COMPLETE`.
8. When scope is insufficient, return `scope_expansion_requested`; do not expand it yourself.
9. When you discover a possible future feature, report it as an idea; do not silently build it.
10. Every factual review finding must cite current file evidence.
11. Read `.umsmfburasbofe/PROJECT-MEMORY.md` before broad product work and preserve `What Must Not Break`.

## Context rule

No role receives or relies on the full prior conversation. The packet is the complete authority for that role. Read its `manifest.json` when provenance or omissions matter.

## Recommended skill pack routing

Do not make the user remember skill names. Pick the helper skill from the job:

- Use `$pimp-my-prompt` before a run when the human request is rough, overloaded,
  ambiguous, frustrated, or reusable and needs exact scope, acceptance criteria,
  fallback behavior, proof, and stop rules.
- Use `$write-a-skill` when a painful workflow should become a reusable local
  agent skill.
- Use `$edit-skill` when a local skill becomes bloated, duplicated, stale,
  vague, or full of generic AI instructions.
- Use `$skillify` when deciding whether a workflow deserves a skill and what
  proof it needs.
- Use `$diagnose` when something is broken, flaky, slow, or confusing and a
  fast feedback loop is needed before editing.
- Use `$tdd` when adding or changing behavior that should be protected by tests.
- Use `$autoreview` as the closeout review lane before commit, release, or handoff.
- Use `$plain-web-copy` when public words need to be factual, clear, and free of
  hype.
- Use `$fix-my-bad-website` when a website or app screen looks generic,
  template-like, or visually disconnected from the product.
- Use `$caveman` or `$uncle-matts-caveman-curse` only when the selected token
  mode or user explicitly asks for compressed output.

## Role separation

Planning, implementation, verification, and review run in fresh processes. A reviewer is not an implementer and must not mutate the reviewed repository.

## Completion

A successful agent response is only one piece of the run. Completion requires
scope checks, real gates, review, product proof, and the final report.
