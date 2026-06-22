---
name: use-installed-skills-first
description: Use before starting any non-trivial local agent task. Forces agents to inspect and use available skills instead of inventing custom process.
---

# Use Installed Skills First

Before doing work:

1. Identify which installed skills apply to the task.
2. Read the relevant `SKILL.md` files before planning or editing.
3. Use those skills throughout the task, not only once at the start.
4. Do not invent a custom process when an installed skill directly covers the job.
5. If a skill references tools that are unavailable in this runtime, use the skill's principles and state the missing tool clearly.

Manageroo defaults:

- Use `pimp-my-prompt` for recovering rough operator intent into clear task specs.
- Use `caveman` for compact status, blockers, and handoffs.
- Use `web-game-foundations`, `game-ui-frontend`, `game-studio`, and `game-playtest` for arcade/game work.
- Use `frontend-app-builder`, `react-best-practices`, and `web-design-guidelines` for website and UI work.
- Use `plain-web-copy` for public copy.
- Use `playwright` for rendered browser proof.
- Use `canva-resize-for-all-social-media` for social/media resizing workflows.

Boundaries:

- Do not run live external actions, post, spend, mint, delete, or move data unless the task explicitly approves it.
- Do not use OpenClaw Gateway unless the task is specifically about the OpenClaw action lane.
- Do not claim completion from intent, memory, or partial logs. Verify with files, commands, browser proof, or current task evidence.
