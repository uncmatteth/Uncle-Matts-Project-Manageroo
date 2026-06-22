---
name: tdd
description: Use when building or fixing behavior where a test-first loop can prevent drift and prove the result.
triggers:
  - "tdd"
  - "test first"
  - "red green"
  - "add coverage"
---

# TDD

Use this when a feature, fix, or refactor needs proof through tests.

Write one behavior test at a time. Do not write a giant imagined test suite before the first useful behavior works.

## Loop

1. Pick one externally visible behavior.
2. Write the smallest test that fails for that behavior.
3. Run the focused test and confirm it fails for the expected reason.
4. Implement only enough code to pass that test.
5. Run the focused test again.
6. Repeat for the next behavior.
7. Run the broader suite before calling the work done.

## Test Quality

- Test public behavior, not private implementation names.
- Prefer integration-style tests that survive refactors.
- Keep fixtures small and readable.
- Do not weaken or delete existing tests to get green.
- If a behavior cannot be tested automatically, write down the exact manual proof.

## Output

Report:

- `Red:` failing test command and failure.
- `Green:` passing command.
- `Coverage:` what behavior is now protected.
- `Remaining:` important behavior not covered yet.
