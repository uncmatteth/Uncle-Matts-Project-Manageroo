# Operator output

Manageroo's default output is for a person trying to understand what happened
and what to do next. Machine records remain available through `--json` and saved
run evidence.

## Human-readable contract

Normal output should follow this order:

1. **Outcome:** finished, waiting, or stopped.
2. **What happened:** the relevant event in everyday language.
3. **What it means:** whether work was accepted, preserved, applied, or left incomplete.
4. **Next:** one useful action, when an action is actually required.

Use technical detail only when it helps the operator diagnose or recover the
run. Do not lead with process IDs, internal role names, state-file paths, full
hashes, stack traces, or raw controller records. Do not hide failure behind a
success-looking heading.

## Continuity messages

The continuity feature remains bound to the exact active request. Its normal
prompt update is deliberately short and is displayed to the operator without
being added to model context:

```text
🦘 Manageroo update
🎯 You asked: <one-line goal>
🛠️ Manageroo is doing: <short action summary of the current task>
📍 Status: <active or paused>
```

This is a deterministic display-only projection, not a copy of the full prompt.
The activity line is derived locally from the newest active request using bounded
action wording such as `Fixing`, `Reviewing`, or `Publishing`; it does not call a
model or add the status text to model context. If no clear action verb is present,
it says that the task summarized above is starting instead of inventing work.
Successful tool checks add no reminder to model context. Exact operator wording
remains in private continuity state and returns to agent context only when a
session, subagent, compacted conversation, or premature stop must recover it. A
side question does not become another active work item.

Manageroo adds one small completion handshake to model context per Codex
session, then binds that handshake to the current objective privately when the
agent stops. It is not repeated for later objectives, side questions, duplicate
prompt events, or successful tool checks.

The normal
completion receipt is a short Markdown badge:

```text
🎉 Manageroo: request complete
```

The request hash remains in the badge's link target for the hook to verify; it
is not displayed as a long raw comment. A blocked receipt is accepted only when
the response also includes a concrete blocker with evidence. Older raw HTML
receipts remain accepted during an upgrade so an active session is not lost.

When Manageroo stops an action that violates an explicit operator limit, the
message names:

- the target that was stopped;
- which explicit `only` boundary or exclusion it violated; and
- what the agent should do next.

This feature controls agent behavior. It does not limit the operator's next
request or require the operator to repeat authorization.

Copy inputs are classified by effect: an external `cp` or `shutil.copy` source
is read-only context, while the destination remains a mutation. External
destinations are allowed unless the operator explicitly narrowed or excluded
them.

Continuity messages use a small, stable scan vocabulary:

- `🦘` identifies Manageroo itself;
- `🧭` identifies the active request;
- `🎯` and `➕` distinguish the root request from additions;
- `🏁` identifies the finish contract;
- `🎉` identifies verified completion; and
- `🚧` identifies a concrete external blocker.
