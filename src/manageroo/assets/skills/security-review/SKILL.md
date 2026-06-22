---
name: security-review
description: Use when reviewing code, deployments, secrets, auth, permissions, custody, public security claims, or production-readiness risk.
triggers:
  - "security review"
  - "audit secrets"
  - "production readiness risk"
---

# Security Review

Use this skill for security work across repositories. It is a review discipline,
not an audit stamp.

## Start Here

1. Check repo state with `git status --short --branch`.
2. Read any repo-local security, operations, deployment, or threat-model docs.
3. Prefer current files and command output over older summaries.
4. Treat local tests and dry runs as useful evidence, not audit clearance.

## Review Priority

Focus first on bugs that can lose funds, corrupt data, bypass authority checks,
leak secrets, break randomness or settlement, create stale deployments, or make
false public-facing claims.

Prioritize:

- authentication and authorization boundaries;
- account, owner, signature, role, and custody validation;
- fund movement, token accounting, rounding, and insolvency paths;
- untrusted input parsing, replay, and front-running paths;
- secret handling and deploy environment leakage;
- production configuration, monitoring, rollback, and incident response;
- public claims that overstate security, audit status, readiness, guarantees, or
  live deployment state.

## Required Gates

Run the repo's relevant cheap gates before saying the review is clean:

```bash
git status --short --branch
```

Then use the project-native gates when present:

- lint
- typecheck
- unit tests
- integration tests
- build
- security/static checks
- deployment dry run

If a required tool is missing, report the missing tool and the exact command
that would run after it is installed. Do not silently downgrade the review.

## Finding Format

Lead with findings, not praise.

For each issue:

- `Severity`: critical, high, medium, low.
- `Path`: exact file path.
- `Evidence`: quote or command output.
- `Impact`: what can go wrong.
- `Fix`: constrained action.
- `Proof`: test, check, or inspection needed after the fix.

## Boundaries

- Do not expose secrets in chat.
- Do not move funds, rotate credentials, deploy, or change production systems
  unless the user explicitly asks for that exact action.
- Do not call a project secure, audited, production-ready, or safe unless the
  evidence proves that exact claim.
