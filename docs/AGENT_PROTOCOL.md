# Manageroo Agent Protocol

Manageroo owns the control protocol. Coding agents are interchangeable workers.

The controller does not change its completion standard based on whether the worker is Codex, Claude Code, Gemini, or another CLI added later. Every worker receives a complete bounded assignment, returns data that Manageroo normalizes into the required schema, and remains subject to the same scope, verification, review, retry, evidence, and completion gates.

## Adapter contract

Every adapter must provide two operations:

- `doctor`: report whether the configured worker command is available.
- `run`: execute one complete `AgentRequest` and return one schema-valid `AgentResponse`.

The response is not trusted merely because the model says it succeeded. Manageroo validates the returned data and then independently applies its controller-owned gates.

## Universal CLI transport

The generic adapter supports three explicit prompt transports:

### `file_path`

The CLI receives the path to the complete Manageroo prompt packet.

The command template must contain `{prompt}` or `{prompt_path}`.

Example:

```toml
prompt_transport = "file_path"
argv_template = ["my-agent", "--prompt-file", "{prompt}"]
```

### `argument`

Manageroo reads the prompt packet and passes its actual contents as a command argument.

The command template must contain `{prompt_text}`.

Example:

```toml
prompt_transport = "argument"
argv_template = ["my-agent", "-p", "{prompt_text}"]
```

### `stdin`

Manageroo sends the complete prompt contents to the worker process on standard input.

This avoids command-line length limits and is the preferred transport for CLIs that support stdin cleanly.

Example:

```toml
prompt_transport = "stdin"
argv_template = ["my-agent", "--structured"]
```

## Response normalization

Regardless of transport or provider, the adapter obtains the worker response from the configured output file when one exists, otherwise from stdout. Manageroo then:

1. extracts the structured JSON response;
2. validates it against the exact schema for that worker role;
3. records the worker command and evidence;
4. continues through controller-owned verification and review.

A provider does not get a weaker completion rule because its CLI behaves differently.

## Built-in presets

- Codex currently uses an optimized native adapter.
- Claude Code and Gemini use the universal generic protocol with explicit prompt-content transport.
- The generic preset is the extension point for any future CLI.

The implementation detail is intentionally not a product-level distinction. All workers remain disposable labor under the same Manageroo controller truth.

## Certification

`manageroo prove` certifies a selected live worker only when that worker actually completes the disposable proof project under Manageroo control. The vendor name is not the proof. The successful adapter configuration and resulting machine-checked evidence are the proof.
