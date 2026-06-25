# Configuration reference

Project configuration lives at:

```text
.manageroo/config.toml
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
manageroo agent list
manageroo agent preset codex
manageroo agent preset gemini
manageroo agent preset generic
```

`mock` exists only for deterministic harness validation. Non-Codex presets are
starter command templates; edit `argv_template` when your agent CLI needs a
different invocation.

## Token Mode

Global token-reduction mode is managed outside the project config:

```bash
manageroo token-mode status
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
- `max_worker_attempts`: maximum attempts for one disposable worker job before
  the job becomes failed.
- `parallel_mapping`: run repository-mapper chunks concurrently when possible.
- `parallel_review`: run isolated reviewer chunks concurrently when possible.

Implementation tasks still run in dependency order in one integration workspace.

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

Stack integration commands are argv arrays, never shell strings. Empty GBrain
or GitNexus arrays are readiness failures. Core delivery still belongs to
MANAGEROO state, scope, gates, and evidence.

GBrain and GitNexus commands are required repo-intelligence lanes. They run
with bounded timeouts, write redacted output artifacts, and block the core run
if they are missing or fail.

`document_analysis_command` is conditional command-owned intelligence. The
controller writes `document-manifest.json` for prose, PDFs, transcripts, and
other document-like inputs, runs the configured argv if present, and records the
result in `document-intelligence.json`. Passive repo documents can stay
non-blocking inventory context; explicit document/prose/exact-text requests make failure blocking. It
is never an AI freehand repair prompt.

AUTOREVIEW and Clawpatch commands are required command-owned review/repair lanes
for normal runs. The controller runs the configured command inside the isolated workspace, captures
the result in `review/external-review-repair.json`, scope-checks any edits, and
blocks on command failure. The AI repairer must not freehand fixes from those
tool findings.

Discovery command placeholders:

```text
{repo}
{workspace}
{source_repo}
{run_root}
{query}
{gbrain_query_payload}
{brief_file}
{inventory_file}
{obsidian_context_file}
{external_context_file}
{document_manifest_file}
{document_intelligence_file}
{document_state_dir}
```

`gitnexus_analyze_command` and `gitnexus_status_command` are forced to run from
a disposable GitNexus copy of the isolated workspace, and for those lanes
`{repo}` is also resolved to `{workspace}`. Use `{source_repo}` only for custom
read-only discovery commands that intentionally need the original checkout path.
Required GBrain and GitNexus command executables must be operator-owned outside
the target repo; repo-local wrappers are rejected before readiness or runtime
execution. If you need `gbrain_readiness_probe_command` or
`gitnexus_readiness_probe_command` for custom operator-owned commands, the probe
executable must also be outside the target repo; repo-local probe scripts are
not executed by readiness.

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
gbrain_search_command = ["gbrain", "call", "query", "{gbrain_query_payload}"]
gbrain_capture_command = ["gbrain", "capture", "--file", "{report_file}"]
gbrain_readiness_probe_command = []
gitnexus_analyze_command = ["gitnexus", "analyze", "{workspace}", "--skip-agents-md", "--skip-skills"]
gitnexus_status_command = ["gitnexus", "status"]
gitnexus_readiness_probe_command = []
document_analysis_command = ["python3", "scripts/document_intel.py", "{document_manifest_file}", "{document_state_dir}"]
autoreview_command = ["autoreview", "--mode", "local"]
clawpatch_command = ["clawpatch", "review", "--limit", "3", "--jobs", "3", "--state-dir", "{external_state_dir}/clawpatch"]
```
