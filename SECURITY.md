# Security policy

MANAGEROO is an alpha coding-agent control plane. Do not report security-sensitive details in a public issue.

Before public deployment or use on sensitive repositories:

- review `docs/SECURITY_THREAT_MODEL.md` and `docs/LIMITATIONS.md`;
- use a disposable clone, branch, worktree, container, or VM;
- keep credentials out of product briefs and run artifacts;
- verify the configured command allowlist and project gates;
- require human approval for authentication, authorization, billing, destructive data operations, regulated data, and production deployment.

The controller's policies reduce accidental drift. They are not a substitute for an operating-system sandbox or hostile-code isolation.
