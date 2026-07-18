# External integrations

Manageroo is the controller. GBrain, GitNexus, Obsidian, AUTOREVIEW, and
Clawpatch are optional surrounding tools. Current repository truth, Manageroo's
locked run artifacts, deterministic gates, and evidence remain authoritative.

## Safe maintenance

Preview the current supported update plan without changing anything:

```bash
manageroo stack-update
```

Apply only the supported updates Manageroo can safely identify:

```bash
manageroo stack-update --apply
```

The command is intentionally explicit and fail-visible. It does not silently add
new third-party products or treat an unavailable update method as success.

## GBrain

GBrain is optional external memory and retrieval. Manageroo's own
`.manageroo/PROJECT-MEMORY.md` remains the normal repo-local continuity lane.
GBrain becomes relevant when the operator explicitly wants GBrain or another
external knowledge source.

Current upstream maintenance path:

```bash
gbrain upgrade
gbrain doctor --json
```

`gbrain upgrade` is GBrain's supported updater and handles schema migrations and
post-upgrade prompts. Fresh local installs can still use:

```bash
bun install -g github:garrytan/gbrain
gbrain init --pglite
gbrain doctor
```

For the full agent-supervised setup, use the upstream
`INSTALL_FOR_AGENTS.md` protocol instead of Manageroo guessing API keys,
embedding choices, integrations, recurring jobs, or source mapping.

Manageroo never reinitializes an existing brain merely to update it.

Project: https://github.com/garrytan/gbrain

## GitNexus

GitNexus is optional code-graph context. Its current upstream normal-use path is:

```bash
npx gitnexus analyze
npx gitnexus setup
```

A permanent global install is optional. When a global `gitnexus` binary already
exists, `manageroo stack-update --apply` can refresh it with
`npm install -g gitnexus@latest`. When only `npx` is available, there is no
persistent Manageroo-owned binary to update.

Manageroo may consume configured GitNexus output as supplementary context, but
Git files and current command output still win when graph data is stale.

Project: https://github.com/abhigyanpatwari/GitNexus

## Obsidian

Obsidian is optional human-readable Markdown context. Manageroo does not require
an Obsidian plugin and does not treat the GUI application as a source of truth.

`manageroo stack-update --apply` uses a detected operating-system package manager
when a safe update command is available:

- Windows: Winget
- macOS: Homebrew cask
- Linux: Flatpak, or Snap when that is the detected installation lane

When no safe package-manager update can be identified, Manageroo leaves Obsidian
alone and reports the boundary instead of inventing an updater.

Official download: https://obsidian.md/download

## AUTOREVIEW

AUTOREVIEW is an optional command-owned closeout review lane. The canonical
source is `openclaw/agent-skills`.

Current upstream provides its own `scripts/install-skills` workflow. Manageroo's
stack updater refreshes an existing AUTOREVIEW installation from the canonical
`skills/autoreview` tree, rejects symlinked downloaded content, and preserves a
backup of the previous installed copy before replacement.

AUTOREVIEW findings do not become freehand AI repair prompts. When configured as
a Manageroo command-owned lane, its command owns its result and Manageroo
scope-checks any resulting edits.

Project: https://github.com/openclaw/agent-skills/tree/main/skills/autoreview

## Clawpatch

Clawpatch is an optional command-owned review and repair lane.

For an existing pnpm-managed installation, Manageroo's supported update path is:

```bash
pnpm add -g clawpatch@latest
clawpatch doctor
```

Manageroo does not claim Clawpatch is healthy merely because the executable
exists. The post-update doctor remains part of the update result.

Clawpatch findings remain command-owned: Manageroo must not hand them to a worker
for unconstrained freehand repair.

Project: https://github.com/openclaw/clawpatch

## Failure and trust boundary

External tools are optional context or explicitly configured command-owned lanes.
Their absence must not silently change Manageroo's controller semantics.

For any external tool:

1. current repo truth beats external cached context;
2. update failure is reported, not hidden;
3. credentials and authentication remain user-owned;
4. Manageroo does not auto-install unrelated dependencies to chase an optional
   integration;
5. a successful external-tool update is not proof that a target product is ready
   for production.
