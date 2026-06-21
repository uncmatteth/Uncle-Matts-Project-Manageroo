---
name: edit-skill
description: Use when an existing agent skill needs to be tightened, shortened, deduplicated, or cleaned of stale rules and AI slop without losing the behavior that actually matters.
triggers:
  - "edit skill"
  - "tighten this skill"
  - "remove skill slop"
---

# Edit Skill

Use this skill when a skill file has become too long, repetitive, vague, stale,
or hard for an agent to trigger reliably.

The goal is not to make the skill sound polished. The goal is to make the skill
fire at the right time and change agent behavior with less text.

## Operating Rules

- Preserve the skill's real job, user voice, trigger intent, and hard safety boundaries.
- Cut duplicate instructions, stale references, vague quality rules, and filler.
- Keep rules that are observable, testable, or tied to repeated failures.
- Prefer concrete examples over abstract scolding.
- Keep the frontmatter description clear enough for routing.
- Do not add new capabilities unless the user explicitly asks.
- Do not rewrite deliberate weirdness into generic assistant prose.

## Pass Order

1. Identify what the skill is for and when it should trigger.
2. Mark must-keep rules: safety, scope, file paths, output contracts, and known failure fixes.
3. Remove repeated rules that say the same thing in different words.
4. Replace vague rules with concrete behavior.
5. Move rare detail into a reference file only when the host supports bundled references.
6. Check that the description says "Use when..." and names the trigger surface.
7. Return a short change summary and any remaining risk.

## Output Shape

For a review-only request, return:

- `Keep:` rules that must stay.
- `Cut:` duplicate, stale, or vague rules to remove.
- `Tightened version:` the edited skill text or patch.
- `Risk:` what behavior might change.

For an edit-in-repo request, patch the skill file directly, then report the
changed file and the verification performed.

## Anti-Patterns

- Do not make every skill tiny if it loses necessary behavior.
- Do not remove examples that teach a subtle judgment.
- Do not turn a voice-specific skill into generic corporate copy.
- Do not keep a rule just because it sounds important.
- Do not add memory/evals files unless they will actually be read or run.
