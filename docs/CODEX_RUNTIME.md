# Codex adapter

Codex is one supported UMSMFBURASBOFE execution adapter. UMSMFBURASBOFE launches it through the non-interactive CLI interface when the project selects the Codex adapter.

```text
Any terminal or command runner
        ↓
UMSMFBURASBOFE controller
  ↓
fresh codex exec process per selected Codex role
        ↓
isolated working directory + bounded context + JSON schema
```

The controller can be started from a normal terminal, an IDE terminal, OpenClaw, SSH, or CI. None of those surfaces owns workflow state.
