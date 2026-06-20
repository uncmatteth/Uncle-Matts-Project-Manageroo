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

`mock` exists only for deterministic harness validation.

## `[context]`

- `max_input_tokens`: total assumed provider input window available to a packet.
- `reserve_output_tokens`: capacity withheld for reasoning and structured output.
- `chars_per_token`: conservative estimator.
- `max_single_file_tokens`: largest permitted required file slice.
- `map_chunk_tokens`: maximum deterministic repository map chunk.

Required context exceeding a limit is not truncated; the plan must decompose.

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

Optional integration commands are argv arrays, never shell strings. Empty arrays mean disabled. Core delivery must work before optional integrations are enabled.
