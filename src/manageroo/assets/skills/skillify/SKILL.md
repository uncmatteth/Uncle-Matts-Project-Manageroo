---
name: skillify
description: Turn a repeated feature, workflow, or local habit into a properly scoped agent skill with tests or proof. Use when the user says skillify, make this a skill, make this reusable, or check skill completeness.
---

# Skillify

Use this when a one-off workflow has become important enough to package.

## Should It Be A Skill?

Skillify only when at least one is true:

- The user will run it more than once.
- The behavior has enough steps that agents keep rediscovering it.
- It needs specific triggers, safety rules, scripts, references, or proof.

If not, make a small script or write normal docs instead.

## Checklist

- `SKILL.md` exists with clear frontmatter.
- The description says what triggers it.
- Deterministic logic lives in a script when that would prevent repeated code generation.
- Tests or a smoke proof cover the important branches.
- The skill is not duplicate, stale, vague, or bloated.
- The output contract tells the agent what to return.
- Any expensive eval or external model call is opt-in and clearly explained.

## Workflow

1. Audit the raw workflow: job, trigger phrases, inputs, outputs, proof.
2. Create or update the skill using `$write-a-skill`.
3. Tighten it with `$edit-skill`.
4. Run the smallest useful proof: validation, script test, or realistic dry run.
5. Report what is ready, what is partial, and what still needs real-world testing.

## Output

Return:

- `Skill:` path or proposed path.
- `Triggers:` exact phrases.
- `Proof:` command or dry-run evidence.
- `Gaps:` anything not proven yet.
