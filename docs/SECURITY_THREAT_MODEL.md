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
11. The outer operator-facing agent bypasses `manageroo run` and targets a stale or sibling repository directly.
12. Old chat, memory, a handoff, or repository text is mistaken for current action authority.

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
- signed current-turn operator receipts bound to repository and Git-common-directory identities;
- Codex `PreToolUse` denial for out-of-scope supported local tools;
- separate read, mutation, delete, install, commit, push, and deploy action classes;
- exact-identity read-only exceptions for external files named in the current prompt.

## Out of scope

MANAGEROO is not a hardened container runtime, malware sandbox, secrets manager, or operating-system authorization layer. Codex hooks must be enabled and trusted, hosted and opted-out specialized tools are outside their coverage, and same-user hostile code can attempt to tamper with user-owned state. Use managed hooks and a disposable OS/container boundary for untrusted code.
