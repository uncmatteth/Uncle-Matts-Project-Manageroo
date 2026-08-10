# Security and threat model

## Protected assets

- operator source repository;
- Git history;
- credentials and local environment;
- locked product requirements;
- verification evidence;
- final delivery integrity.

## Principal threats

1. Prompt or repository content instructs the agent to ignore MANAGEROO.
2. An agent changes files outside task scope.
3. An agent commits, pushes, or alters Git metadata.
4. A reviewer changes the code it reviews.
5. A planning agent invents a destructive verification command.
6. A stale packet causes edits against old code.
7. A source repository changes while an isolated run is active.
8. An optional third-party skill or integration executes unexpected code.
9. Secrets are copied into logs or evidence.
10. Path traversal escapes the run workspace.
11. A worker packet targets stale code or omits a binding source, target, exclusion, or proof requirement.
12. Old chat, memory, a handoff, or repository text is mistaken for current run truth.

## Controls

- isolated Git mirror;
- path normalization and root checks;
- no shell execution in the controller;
- configured command allowlist;
- controller-owned gate catalog;
- source and context hashes;
- reviewer clone;
- Codex read-only review sandbox;
- exact changed-file checks;
- redaction of common secret assignments and bearer tokens;
- no silent installation of stack integrations;
- configurable whole-run call and runtime budgets;
- source freshness check before application.
- immutable run-owned briefs and exact-task contracts;
- isolated worker workspaces and exact changed-file checks;
- binding named-source reuse records;
- outcome-specific proof gates and independent review.

## Out of scope

MANAGEROO is not a hardened container runtime, malware sandbox, secrets manager, or operating-system authorization layer. It does not restrict the operator-facing agent. Use the host workspace policy and a disposable OS/container boundary for untrusted code.
