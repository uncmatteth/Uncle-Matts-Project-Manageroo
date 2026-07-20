# Host Skill Ecosystem

Manageroo is a portable control plane, not the owner of every skill installed on a machine.

The project now recognizes the real host environments surveyed during hardening:

- Windows Codex roots under `~/.codex/skills`, including nested vendor skill libraries.
- Windows agent roots under `~/.agents/skills`, including Cloudflare-focused capabilities.
- Mac skill candidates including the GitNexus family, retrieval workflows, engineering workflow helpers, writing skills, and Obsidian/Chronicle integrations.

## Important capability families

### GitNexus

The surveyed Mac environment included:

- `gitnexus-cli`
- `gitnexus-debugging`
- `gitnexus-exploring`
- `gitnexus-guide`
- `gitnexus-impact-analysis`
- `gitnexus-pr-review`
- `gitnexus-refactoring`

Manageroo treats these as host capabilities. GitNexus remains a first-class repository-intelligence integration, but it is not a completion authority.

### Cloudflare

The surveyed Windows agent environment included:

- `agents-sdk`
- `cloudflare`
- `cloudflare-email-service`
- `cloudflare-one`
- `cloudflare-one-migrations`
- `durable-objects`
- `sandbox-sdk`
- `turnstile-spin`
- `web-perf`
- `workers-best-practices`
- `wrangler`

These skills stay host-owned unless explicitly imported through a reviewed installation path.

### Engineering and orchestration

The surveyed environments also contained useful skills such as `autoreview`, `codebase-design`, `decision-mapping`, `diagnosing-bugs`, `domain-modeling`, `handoff`, `implement`, `qa`, `review`, `tdd`, `triage`, `request-refactor-plan`, `to-prd`, and `to-issues`.

### Retrieval and writing

The Mac survey included `retrieval-reflex`, `chronicle`, `obsidian`, `edit-article`, `ubiquitous-language`, `writing-beats`, `writing-fragments`, and `writing-shape`.

These are useful context capabilities, but they do not replace current repository truth or deterministic proof.

## Discovery behavior

`manageroo host-skills` recursively inspects selected host skill roots for `SKILL.md` files. This matters because vendor libraries may be nested several directories deep instead of being direct children of the skill root.

The report:

- preserves the exact location of every discovered skill;
- reports duplicate skill names without silently choosing one;
- separates Manageroo core, known optional skills, and host-owned/external skills;
- groups surveyed skills into capability families such as GitNexus, Cloudflare, orchestration, engineering quality, retrieval, web/UI, and writing/domain work.

## Ownership rule

Manageroo may use relevant host skills when the active agent environment exposes them and the task requires them.

Manageroo does **not** implicitly copy, delete, upgrade, flatten, or claim ownership of those skills.

Bundling a host skill into Manageroo requires an explicit reviewed import. This keeps the public portable core clean while still allowing richer machines to contribute capabilities.
