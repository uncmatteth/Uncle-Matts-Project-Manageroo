# Matt Pocock skill subset

Manageroo vendors a reviewed subset of [mattpocock/skills](https://github.com/mattpocock/skills). The current import is upstream version 1.2.2 at commit `8b36d4fb2635b3c21998dcd8144439c9e5ba7302`, fetched and reviewed on 2026-08-06. The upstream license is MIT. Every imported skill directory includes `SOURCE.md`, `LICENSE.txt`, and Codex metadata at `agents/openai.yaml`.

## Imported graph

- Flow: `setup-matt-pocock-skills` -> `grill-with-docs` -> `to-spec` -> `to-tickets`.
- Shared references: `grilling`, `domain-modeling`, and `codebase-design`.
- Engineering: `diagnosing-bugs`, `tdd`, and `improve-codebase-architecture`.
- Productivity: `grill-me`, `handoff`, and `writing-for-agents`.

The upstream breaking renames are applied: `to-prd` became `to-spec`, `to-issues` became `to-tickets`, `diagnose` became `diagnosing-bugs`, and `write-a-skill` was replaced by `writing-for-agents`. On core-pack upgrade, Manageroo retires an old-name tree only when its ownership ledger and current digest prove the tree is unchanged and Manageroo-owned. A user-edited or host-owned old-name tree is preserved and removed from Manageroo ownership.

Manageroo's `caveman` token mode is a separate Manageroo feature. Upstream's removal of its unrelated `caveman` skill does not remove Manageroo's token mode.

## Review result

Risk: **medium**, accepted for this bundled local subset.

- The skill files are instructions and Markdown references. The only bundled shell file is `diagnosing-bugs/scripts/hitl-loop.template.sh`, a non-executable human-in-the-loop reproduction template that reads terminal responses and prints them locally.
- `setup-matt-pocock-skills` can write `docs/agents/*.md` and update an existing `AGENTS.md` or `CLAUDE.md`, but its procedure requires showing drafts and receiving confirmation first.
- `to-spec` and `to-tickets` can publish to the configured issue tracker. Those writes remain subject to the active agent's authorization and Manageroo scope controls.
- `improve-codebase-architecture` can create and open a temporary HTML report and references Tailwind and Mermaid CDNs. It does not add those libraries to Manageroo's stdlib-only runtime.
- No compiled binaries, package-install commands, secret readers, persistence hooks, or automatic network fetches are shipped by this subset.

## Update procedure

1. Fetch the upstream default branch and record its exact commit and package version.
2. Read the changelog and every file in the proposed skill directories, including scripts, references, licenses, and `agents/openai.yaml` metadata.
3. Rebuild the complete dependency graph; do not copy a delegating skill without its referenced shared skill.
4. Copy the reviewed files exactly, update per-skill provenance, and update the core/optional inventories and breaking-name migration together.
5. Run the focused skill, installation, package, and routing tests, then the full unit suite and `python scripts/verify_release.py`.

Manageroo never updates this subset from the network at runtime. A new upstream release changes Manageroo only through another reviewed source commit.
