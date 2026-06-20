# Security and threat model

## Protected assets

- operator source repository;
- Git history;
- credentials and local environment;
- locked product requirements;
- verification evidence;
- final delivery integrity.

## Principal threats

1. Prompt or repository content instructs the agent to ignore UMSMFBURASBOFE.
2. An agent changes files outside task scope.
3. An agent commits, pushes, or alters Git metadata.
4. A reviewer changes the code it reviews.
5. A planning agent invents a destructive verification command.
6. A stale packet causes edits against old code.
7. A source repository changes while an isolated run is active.
8. An optional third-party skill or integration executes unexpected code.
9. Secrets are copied into logs or evidence.
10. Path traversal escapes the run workspace.

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
- no automatic installation of optional integrations;
- fixed repair limits;
- source freshness check before application.

## Out of scope

UMSMFBURASBOFE is not a hardened container runtime, malware sandbox, secrets manager, or authorization layer. A malicious executable already installed on the host can exceed these controls. Use a disposable OS/container boundary for untrusted code.
