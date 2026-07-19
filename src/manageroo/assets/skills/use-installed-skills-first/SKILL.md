---
name: use-installed-skills-first
description: Use before starting any non-trivial local agent task. Inspect and use relevant installed skills before inventing a custom process.
---

# Use Installed Skills First

Before doing work:

1. Identify which installed skills directly apply to the task.
2. Read only the relevant `SKILL.md` files before planning or editing.
3. Use those skills throughout the task, not only once at the start.
4. Prefer Manageroo's portable core when it covers the job.
5. Treat every other installed skill as host-owned capability: it may be used when relevant, but Manageroo does not own, copy, upgrade, or delete it implicitly.
6. Do not search a public skill marketplace merely because no installed skill matches. Use the normal task process unless the operator explicitly asks for skill discovery.
7. If a skill references unavailable tools, use only the applicable principles and state the missing capability clearly.

Manageroo core defaults:

- Use `pimp-my-prompt` when rough operator intent needs to become exact scope and proof.
- Use `to-prd`, `grill-me`, or `grill-with-docs` when product requirements need pressure before implementation.
- Use `diagnose` before changing code when the failure is not understood.
- Use `tdd`, `testing`, and `security-review` when executable or security proof is relevant.
- Use `handoff` for durable continuation context.
- Use `write-a-skill`, `edit-skill`, and `skillify` only when the task is actually about reusable skill behavior.

Host integration:

- Additional skills installed by tOS, Codex, OpenClaw, a user, or another local system remain owned by that host environment.
- Use a host skill when its trigger clearly matches the task and its required tools are available.
- An installed competing orchestrator does not replace Manageroo's controller for a Manageroo run.

Boundaries:

- Do not run live external actions, post, spend, mint, delete, or move data unless the task explicitly approves it.
- Do not use OpenClaw Gateway unless the task is specifically about the OpenClaw action lane.
- Do not claim completion from intent, memory, or partial logs. Verify with files, commands, browser proof, or current task evidence.
