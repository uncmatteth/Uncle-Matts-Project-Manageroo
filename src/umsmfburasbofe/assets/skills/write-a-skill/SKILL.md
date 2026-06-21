---
name: write-a-skill
description: Create a new local agent skill with concise triggers, a small SKILL.md, and only the resources it actually needs. Use when the user wants to create, write, or package a reusable agent skill.
---

# Write A Skill

Use this when a repeated task should become a local skill instead of another long chat.

## Rules

- Make the skill easy to trigger: the description must say what it does and when to use it.
- Keep `SKILL.md` short. Move rare detail into one-level reference files only when needed.
- Add scripts only for deterministic work that would otherwise be rewritten over and over.
- Preserve the user's voice and hard boundaries.
- Do not add broad docs, changelogs, or extra files unless the skill needs them.

## Workflow

1. Name the repeated job in one sentence.
2. List 2-4 real phrases a user would type when they need it.
3. Decide whether it needs only instructions, references, scripts, or assets.
4. Create `SKILL.md` with frontmatter:

```yaml
---
name: short-hyphen-name
description: What this skill does. Use when the user asks for the specific trigger surface.
---
```

5. Add the smallest useful body: contract, steps, output shape, and any hard safety rule.
6. Test the skill on one realistic request before calling it ready.

## Output

Return the skill path, the trigger phrases, what files were created, and the proof run.
