# Configuration reference

Project configuration lives at:

```text
.umsmfburasbofe/config.toml
```

Agents are forbidden from editing it during a run.

## `[project]`

- `apply_on_success`: apply the verified patch to the exact source snapshot.
- `max_repair_cycles`: maximum review-triggered repair loops.
- `max_plan_review_cycles`: maximum pre-code plan repair loops.
- `require_demonstration`: require demonstration evidence when the plan marks it required.

## `[agent]`

- `adapter`: `codex`, `mock`, or explicitly configured `generic`.
- `executable`: executable name or absolute path.
- `model`: optional provider model override.
- `timeout_seconds`: maximum time for one fresh role process.
- `argv_template`: required for `generic` agents. Supported placeholders are
  `{prompt}`, `{schema}`, `{output}`, `{cwd}`, `{role}`, and `{sandbox}`.

Built-in presets:

```bash
umsmfburasbofe agent list
umsmfburasbofe agent preset codex
umsmfburasbofe agent preset gemini
umsmfburasbofe agent preset generic
```

`mock` exists only for deterministic harness validation. Non-Codex presets are
starter command templates; edit `argv_template` when your agent CLI needs a
different invocation.

## Token Mode

Global token-reduction mode is managed outside the project config:

```bash
umsmfburasbofe token-mode status
umsmfburasbofe token-mode set off
umsmfburasbofe token-mode set caveman
umsmfburasbofe token-mode set curse
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
- `parallel_mapping`: run repository-mapper chunks concurrently when possible.
- `parallel_review`: run isolated reviewer chunks concurrently when possible.

Implementation tasks still run in dependency order in one integration workspace.

## Learning lane

Learning cards do not have a config switch that permits silent mutation. Cards
are saved under `.umsmfburasbofe/cache/learning/pending/` and applied only
through `umsmfburasbofe learning apply CARD_ID --approve`.

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

Stack integration commands are argv arrays, never shell strings. Empty arrays mean disabled. Core delivery still belongs to UMSMFBURASBOFE state, scope, gates, and evidence.

GBrain and GitNexus commands are optional intelligence, not hard dependencies.
They run with bounded timeouts, write redacted output artifacts, and do not
block the core run if they fail.

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
gitnexus_analyze_command = ["gitnexus", "analyze", "{repo}", "--json"]
gitnexus_query_command = ["gitnexus", "query", "{query}", "--json"]
autoreview_command = []
clawpatch_command = []
```
