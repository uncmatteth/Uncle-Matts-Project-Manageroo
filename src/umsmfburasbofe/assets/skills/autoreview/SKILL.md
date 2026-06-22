---
name: autoreview
description: Use as a closeout code review after non-trivial edits, before commit, release, or handoff.
triggers:
  - "autoreview"
  - "auto review"
  - "review the diff"
  - "closeout review"
---

# AUTOREVIEW

Use this for closeout code review. The job is to find real bugs, regressions, missing proof, and scope drift before the work ships.

## Rules

- Review the current diff against the original request, repo rules, and tests.
- Findings must be concrete and tied to current file evidence.
- Prioritize correctness, data loss, security, broken workflows, and missing verification.
- Do not report vague style preferences as review findings.
- Verify every accepted finding before changing code.
- If an external `autoreview` command or richer local skill exists, use it as the review engine; otherwise do the review directly from the diff and relevant files.
- If review-triggered changes are made, rerun focused tests and review the changed diff again.

## Output

Lead with findings:

- `Severity:` blocker, high, medium, low.
- `File:` path and line when possible.
- `Issue:` what breaks.
- `Fix:` what should change.

If no issues are found, say that clearly and list remaining test gaps.
