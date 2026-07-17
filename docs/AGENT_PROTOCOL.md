# Manageroo Agent Protocol

Manageroo owns the control protocol. Coding agents are interchangeable workers.

The controller does not change its completion standard based on whether the worker is Codex, Claude Code, Gemini, or another CLI added later. Every worker receives a complete bounded assignment, returns data that Manageroo normalizes into the required schema, and remains subject to the same scope, verification, review, retry, evidence, budget, and completion gates.

## Automatic worker selection

The normal Manageroo setup is provider-neutral:

```toml
[agent]
adapter = "auto"
candidates = ["codex", "claude-code", "gemini"]
```

Manageroo uses installed candidates as interchangeable workers. Provider execution or protocol failure may fall through to another compatible worker. Controller safety failures do not trigger provider fallback and remain blocking.

After one worker succeeds, the pool prefers that healthy worker for later roles while retaining the remaining workers as fallbacks. An explicit agent preset remains available when the operator wants to pin a provider.

## Adapter contract

Every adapter must provide two operations:

- `doctor`: report whether the configured worker command is available.
- `run`: execute one complete `AgentRequest` and return one schema-valid `AgentResponse`.

The response is not trusted merely because the model says it succeeded. Manageroo validates the returned data and then independently applies its controller-owned gates.

## Universal CLI transport

The generic adapter supports three explicit prompt transports:

### `file_path`

The CLI receives the path to a complete Manageroo protocol packet.

The command template must contain `{prompt}` or `{prompt_path}`.

```toml
prompt_transport = "file_path"
argv_template = ["my-agent", "--prompt-file", "{prompt}"]
```

### `argument`

Manageroo passes the complete protocol packet as a command argument.

The command template must contain `{prompt_text}`. This mode is appropriate only when prompt sizes are safely below operating-system command-line limits.

```toml
prompt_transport = "argument"
argv_template = ["my-agent", "-p", "{prompt_text}"]
```

### `stdin`

Manageroo sends the complete protocol packet to the worker process on standard input.

This avoids command-line length limits and is the preferred transport for CLIs that support stdin cleanly.

```toml
prompt_transport = "stdin"
argv_template = ["my-agent", "--structured"]
```

## Exact output protocol

Generic workers do not receive an underspecified instruction to "return JSON." Manageroo builds a protocol packet containing:

1. the complete bounded role assignment;
2. the compiled repository context selected for that role;
3. the exact JSON Schema required for that role's response.

The worker output is then independently parsed and validated by Manageroo. Provider-native structured-output features may be used later as an optimization, but they never replace controller validation.

## Permission and sandbox mapping

`AgentRequest.sandbox` is a Manageroo-level permission contract. Generic presets may map it to provider-native permission arguments:

- `read-only` for analysis, mapping, planning, and independent review;
- `workspace-write` for bounded implementation and verified repair.

The built-in Claude Code and Gemini presets map these modes to their provider permission/sandbox controls. Manageroo still checks repository mutations, scope, commits, gates, and review evidence afterward. Provider enforcement is an additional prevention layer, not the source of truth.

## Response normalization

Regardless of transport or provider, the adapter obtains the worker response from the configured output file when one exists, otherwise from stdout. Manageroo then:

1. extracts the structured JSON response;
2. validates it against the exact schema for that worker role;
3. records the worker identity, command, and evidence;
4. continues through controller-owned verification and review.

A provider does not get a weaker completion rule because its CLI behaves differently.

## Controller budgets

Manageroo can bound autonomous work independently of provider-specific controls:

```toml
[budget]
max_total_worker_calls = 80
max_runtime_minutes = 240
```

Exhausting a configured controller budget blocks further worker launches. Provider-specific budget controls can be layered on later but do not replace the Manageroo budget.

## Outcome-specific completion proof

A green test suite is not proof of every product promise.

Every product acceptance outcome must have one explicit proof binding in the locked task plan. The binding names the configured gate IDs that genuinely prove that exact outcome. Observable browser, user-journey, authentication, security, deployment, and visual outcomes must include an actual demonstration-lane gate.

An unrelated passing gate cannot prove a different outcome. A missing, ambiguous, or failing binding prevents `COMPLETE`.

## Built-in presets

- `auto` is the normal provider-neutral worker pool.
- Codex currently uses an optimized native adapter.
- Claude Code and Gemini use the universal schema-aware stdin protocol with provider permission mappings.
- The generic preset is the extension point for future CLIs.
- Mock remains a deterministic test double and cannot satisfy live product certification.

The implementation detail is intentionally not a product-level distinction. All live workers remain disposable labor under the same Manageroo controller truth.

## Certification

`manageroo prove` requires a real disposable coding-agent run in addition to the adversarial controller and regression lanes. The vendor name is not the proof. The successful adapter configuration and resulting machine-checked evidence are the proof.
