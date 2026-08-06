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

The surveyed environments also contained useful skills such as `autoreview`, `codebase-design`, `decision-mapping`, `diagnosing-bugs`, `domain-modeling`, `handoff`, `implement`, `qa`, `review`, `tdd`, `triage`, `request-refactor-plan`, `to-spec`, and `to-tickets`.

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

## Automatic routing behavior

Every Manageroo worker call runs through local automatic capability routing.
The controller indexes installed frontmatter, repository-local `.agents/skills`,
and enabled Codex plugin skill roots; scores controller-owned assignment intent
deterministically; tolerates rough spelling; excludes saved communication modes;
and injects only complete selected entrypoints under hard count and character
ceilings. Repository content, diffs, evidence, and generated packet boilerplate
do not make capabilities eligible. Generated implementation-task text may only
rerank capabilities already approved by the operator's original brief. No
skill-selection prompt is shown to the operator.

Ordinary mentions participate in automatic matching; they are not treated as
hard requirements. Explicit fail-closed handling is reserved for recognizable
invocation syntax such as `use $diagnosing-bugs` or a hyphenated `$skill-name`, so shell
variables and template placeholders remain ordinary task text. Unknown explicit
skill invocations block before launch instead of disappearing silently.

Each durable job and packet records the selected names, source paths, raw
entrypoint hashes, full skill-tree hashes, scores, and reasons. Explicit requests
fail closed when a skill is disabled, conflicting, interactive, incompatible
with the worker role/sandbox, or too large for the capsule. Non-explicit
conflicting copies are ignored. For Codex workers, Manageroo creates a bounded
ephemeral layered profile that disables the discovered eager global catalog by
both canonical name and source path for that process. Name filtering also covers
repository skills after their source paths move into the isolated mirror. Only
the opaque profile name enters the command log, and the profile is removed after
launch. Selected instructions are already inside the bounded packet. No user
Codex config is rewritten.

Installed host and plugin skills are operator-trusted inputs, not a hostile-code
sandbox. Repository-local skills are project-owned instructions and remain
subordinate to the controller packet, current repository truth, scope, role, and
sandbox restrictions. Manageroo validates encoding, streams files under hard
tree limits, rejects symlinked support trees, hashes the complete skill directory
for durable replay, rejects invalid UTF-8 text support files, scans support text
for interactive and external-action instructions, and rehashes selected trees
before every concrete provider launch. It will not
turn an interactive or external-action workflow into an unattended worker action.
Every provider packet also forbids external resource mutation; capability text
cannot grant that authority.

Symlinked capability roots, skill directories, and entrypoints fail closed.
Manageroo does not follow them because a linked package can expose additional
nested skills absent from the bounded isolation catalog.

Catalog discovery has a global entry ceiling and is refreshed from live Codex
disable state and enabled-plugin identity before each route and each concrete
Codex launch. A mid-run config or installed-skill change therefore cannot bypass
the next process's isolation profile.

## Ownership rule

Manageroo may use relevant host skills when the active agent environment exposes them and the task requires them.

Manageroo does **not** implicitly copy, delete, upgrade, flatten, or claim ownership of those skills.

Bundling a host skill into Manageroo requires an explicit reviewed import. This keeps the public portable core clean while still allowing richer machines to contribute capabilities.

During import, Manageroo snapshots source identity and metadata, copies from held
file descriptors with platform no-follow protection when available, and
revalidates the source tree before replacing the installed skill. A source
change aborts staging and leaves the active skill unchanged.
