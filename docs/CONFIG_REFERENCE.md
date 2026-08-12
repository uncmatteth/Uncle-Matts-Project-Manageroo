# Configuration reference

Project configuration lives at:

```text
.manageroo/config.toml
```

Agents are forbidden from editing it during a run.

`policy_version = 2` marks a current configuration whose explicitly chosen
phase caps must be preserved. A pre-version config containing the exact old
generated `2` repair, `4` plan-review, and `2` worker-attempt defaults is treated
as legacy and uses the current `0` defaults in memory. Manageroo does not rewrite
that project file during loading.

## `[project]`

- `apply_on_success`: apply the verified patch to the exact source snapshot.
- `max_repair_cycles`: optional fixed limit for review-triggered repair loops.
  Default: `0`, meaning no separate phase limit; the run continues until review
  approves, a concrete non-retryable failure occurs, or the whole-run budget is
  exhausted.
- `max_plan_review_cycles`: optional fixed limit for pre-code plan repair loops.
  Default: `0`, with the same whole-run budget and concrete-failure boundary.
- `require_demonstration`: require demonstration evidence when the plan marks it required.
- `require_clawpatch_release_sweep`: require `release-ready` to find a complete zero-open Clawpatch sweep proof tied to the current Git HEAD. Default: `false`.

## `[agent]`

- `adapter`: `codex`, `mock`, or explicitly configured `generic`.
- `executable`: executable name or absolute path.
- `model`: optional provider model override.
- `timeout_seconds`: maximum time for one fresh role process.
- `argv_template`: required for `generic` agents. Supported placeholders are
  `{prompt}`, `{schema}`, `{output}`, `{cwd}`, `{role}`, and `{sandbox}`.

Built-in presets:

```bash
manageroo agent list
manageroo agent preset codex
manageroo agent preset generic
```

`mock` exists only for deterministic harness validation. Non-Codex presets are
non-runnable extension templates until an independently verified host filesystem
boundary is implemented; editing `argv_template` alone does not satisfy it.

## Token Mode

Global token-reduction mode is managed outside the project config:

```bash
manageroo token-mode status
manageroo token-mode set off
manageroo token-mode set caveman
manageroo token-mode set curse
```

The setting lives under the current user's config directory and is recorded in
`install-lock.json` during installation.

## `[context]`

- `max_input_tokens`: total assumed provider input window available to a packet.
- `reserve_output_tokens`: capacity withheld for reasoning and structured output.
- `chars_per_token`: conservative estimator.
- `max_single_file_tokens`: largest permitted required file slice.
- `map_chunk_tokens`: maximum deterministic repository map chunk.

Required context exceeding a limit is not truncated; the plan must decompose.

## `[orchestration]`

- `max_parallel_agent_calls`: maximum fresh agent calls for independent chunks.
- `max_worker_attempts`: optional fixed attempt limit for one disposable worker
  job. Default: `0`, meaning retry recoverable failures until success, a concrete
  non-retryable failure, or whole-run budget exhaustion.
- `parallel_mapping`: run repository-mapper chunks concurrently when possible.
- `parallel_review`: run isolated reviewer chunks concurrently when possible.

Implementation tasks still run in dependency order in one integration workspace.

## `[capabilities]`

- `enabled`: automatically route relevant installed capabilities into every worker packet. Default: `true`. Setting it to `false` disables selection, but Codex workers still require bounded catalog discovery so unselected global skills can be hidden for that process.
- `max_selected`: hard maximum number of selected task capabilities. Default: `4`.
- `max_prompt_chars`: hard character ceiling for complete selected skill entrypoints. A skill is omitted rather than partially loaded. Default: `24000`.

The operator is never asked to select a skill. `manageroo skills explain
"normal-language task"` is a diagnostic view of the same automatic decision,
not a required workflow step. Saved token mode is separate.

Optional skill frontmatter can narrow automatic use with
`manageroo_roles: [reviewer]`, `manageroo_sandboxes: [read-only]`,
`manageroo_interactive: true`, `manageroo_external_actions: true`,
`manageroo_required_commands: [tool-name]`, or `mutating: true`. An explicit
skill request that conflicts with these limits,
host-disabled state, a duplicate-name conflict, or a capsule budget exits
blocked before a worker launches.

Skills cannot self-declare an exception to external-action detection. Safety and
authority remain controller-owned even when third-party frontmatter claims a
skill is unattended-safe.

## Learning lane

Learning cards do not have a config switch that permits silent mutation. Cards
are saved under `.manageroo/cache/learning/pending/` and applied only
through `manageroo learning apply CARD_ID --approve`.

## `[safety]`

- `allowed_programs`: executable basenames permitted for controller-run gates.
- `block_agent_commits`: reject any agent role that changes `HEAD`.
- `require_source_unchanged_before_apply`: compare the source tree to its original manifest before applying delivery.

## `[[verification.gates]]`

Each controller-owned gate has:

```toml
[[verification.gates]]
id = "test"
kind = "test"
required = true
timeout_seconds = 1800
argv = ["npm", "run", "test"]
```

Planning agents may reference gate IDs. They may not introduce argv commands.

## `[integrations]`

Stack integration commands are argv arrays, never shell strings. Empty arrays mean disabled. Core delivery still belongs to MANAGEROO state, scope, gates, and evidence.

GBrain and GitNexus commands are optional intelligence, not hard dependencies.
They run with bounded timeouts, write redacted output artifacts, and do not
block the core run if they fail.

`document_analysis_command` is also optional intelligence. The controller writes
`document-manifest.json` for prose, PDFs, transcripts, and other document-like
inputs, runs the configured argv if present, and records the result in
`document-intelligence.json`. Failure is optional context, not an AI freehand
repair prompt.

AUTOREVIEW and Clawpatch commands are different. When `autoreview_command` or
`clawpatch_command` is configured, it is a command-owned review/repair lane. The
controller runs the configured command inside the isolated workspace, captures
the result in `review/external-review-repair.json`, scope-checks any edits, and
blocks on command failure. The AI repairer must not freehand fixes from those
tool findings.

Discovery command placeholders:

```text
{repo}
{workspace}
{run_root}
{query}
{brief_file}
{inventory_file}
{obsidian_context_file}
{external_context_file}
{document_manifest_file}
{document_intelligence_file}
{document_state_dir}
```

Final capture command placeholders:

```text
{repo}
{run_root}
{report_file}
{result_file}
{patch_file}
{status}
{summary}
{files_changed}
```

AUTOREVIEW/Clawpatch command placeholders:

```text
{repo}
{workspace}
{source_repo}
{run_root}
{query}
{brief_file}
{inventory_file}
{external_state_dir}
{task_plan_file}
{gates_file}
{external_review_repair_input_file}
```

Example:

```toml
[integrations]
gbrain_search_command = ["gbrain", "search", "{query}", "--json"]
gbrain_capture_command = ["gbrain", "capture", "--file", "{report_file}"]
gitnexus_analyze_command = ["gitnexus", "analyze", "{repo}", "--index-only", "--embedding-device", "cpu"]
gitnexus_query_command = ["gitnexus", "query", "{query}", "--repo", "{repo}"]
document_analysis_command = ["manageroo", "document-analyze", "{document_manifest_file}", "{workspace}"]
autoreview_command = ["autoreview", "--mode", "uncommitted", "--engine", "codex", "--no-web-search", "--max-priority", "P1", "--json-output", "{external_state_dir}/autoreview.json"]
clawpatch_command = ["clawpatch", "--root", "{workspace}", "--state-dir", "{external_state_dir}/clawpatch", "--json", "--no-input", "ci", "--limit", "3", "--jobs", "3", "--include-dirty"]
```

Use the explicit full-stack configurator to detect those local commands and an
existing Markdown vault without hand-editing TOML:

```bash
manageroo integrations configure . --full \
  --obsidian-vault /path/to/vault \
  --obsidian-export-folder Existing-Inbox
```

The export folder must already exist beneath the vault. `--full` is explicit
because AUTOREVIEW and ClawPatch run real closeout reviews on controlled runs.
