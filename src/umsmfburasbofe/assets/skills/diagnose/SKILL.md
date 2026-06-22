---
name: diagnose
description: Use when something is broken, failing, flaky, slow, or confusing and the agent needs a disciplined debugging loop before editing.
triggers:
  - "diagnose"
  - "debug this"
  - "something is broken"
  - "test is failing"
---

# Diagnose

Use this when the job is a bug, failure, flake, crash, regression, or confusing behavior.

Build a feedback loop first. A fix is not real until there is a fast way to see the failure and then see it stop.

## Rules

- Reproduce the symptom before editing when possible.
- Make the loop as small as practical: one command, one failing test, one script, one browser check, or one captured fixture.
- Confirm the loop matches the user's reported problem, not a nearby different failure.
- Form one hypothesis at a time.
- Instrument or inspect enough evidence to prove the cause.
- Patch the smallest ownership boundary that fixes the cause.
- Add or update a regression check so the same bug is harder to bring back.
- If no loop can be built, say exactly what evidence is missing and what artifact would unblock the work.

## Output

Report:

- `Loop:` command or proof used.
- `Cause:` the specific cause found.
- `Fix:` files changed and why.
- `Proof:` command output or manual check.
- `Still risky:` anything not fully proven.
