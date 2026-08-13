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

The continuity feature remains bound to the exact active request, but routine
prompt capture is silent. It prints no `You asked`, activity, or active/paused
status block and adds no model context. Successful tool checks are silent too.

Exact operator wording remains in private continuity state. A compressed
controller contract appears once at session start, and exact active requests
return only when a session, subagent, or compacted conversation must recover
them. A side question does not become another active work item.

Ordinary operator chat has no Manageroo completion line or `Stop` handshake.
A saved pause is advisory recovery context and does not deny tools. Strict
completion gates and durable receipts exist only inside explicit controlled
Manageroo runs.

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

Diagnostic denials retain compact markers only when
the operator needs to act on them.
