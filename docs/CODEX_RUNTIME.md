# Codex runtime

Codex is UMSMFBURASBOFE's default execution engine. UMSMFBURASBOFE launches it through the non-interactive CLI interface.

```text
Any terminal or command runner
        ↓
UMSMFBURASBOFE controller
        ↓
fresh codex exec process per role
        ↓
isolated working directory + bounded context + JSON schema
```

The controller can be started from a normal terminal, an IDE terminal, OpenClaw, SSH, or CI. None of those surfaces owns workflow state.
