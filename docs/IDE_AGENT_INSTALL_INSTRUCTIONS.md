# Give this to your IDE agent

Use this when another AI tool is doing the install for you.

---

You are installing **Uncle Matt's Project Manageroo**.

This is an install task. Do not rename the project, rewrite the docs, swap the
architecture, or get creative.

## Inputs

- `MANAGEROO_SOURCE`: the extracted `Uncle-Matts-Project-Manageroo` directory.
- `TARGET_PROJECT`: the existing product Git repository, or the missing/empty folder to create.
- `OPERATOR_REQUEST`: what the operator wants built or fixed.
- `CREATE_PROJECT`: `yes` only when `TARGET_PROJECT` is allowed to be created if missing or empty.

Find the paths from the workspace and the request from the operator. Inspect
current files and infer every value that current files and the operator request make clear.
Do not make the operator restate known information. Ask only if two materially
different target repositories remain equally plausible or creation would
overwrite existing non-Git work.

## Required sequence

```bash
cd "$MANAGEROO_SOURCE"
python3 scripts/verify_release.py
./install.sh --skip-stack --skill-pack install --gbrain-lane skip --token-mode off --stack-doctor skip --clawpatch-codex-login skip --agent auto --no-music --no-animation
export PATH="$HOME/.local/bin:$PATH"
manageroo --version
manageroo self-test
manageroo skills list
manageroo token-mode status
manageroo stack-status --json
manageroo repair-install --no-apply --json
if [ "$CREATE_PROJECT" = "yes" ]; then
  manageroo solo "$TARGET_PROJECT" --create --agent codex --want "$OPERATOR_REQUEST" --force
  cd "$TARGET_PROJECT"
else
  git -C "$TARGET_PROJECT" rev-parse --show-toplevel
  cd "$TARGET_PROJECT"
  manageroo solo --agent codex --want "$OPERATOR_REQUEST" --force
fi
manageroo memory show
manageroo ready --json
manageroo next --json
```

After the installer changes Codex hooks, tell the operator to open `/hooks` once
in Codex, review the Manageroo entries, and trust them. This is Codex's one-time
security confirmation and must not be faked or bypassed. After trust, Manageroo's
global controller hook is event-driven in ordinary Codex sessions; the operator
does not need to invoke the Manageroo skill by name.

Use `--agent codex` only when Codex is the selected runtime. Use
`manageroo agent list` to see presets for another CLI. The non-Codex
presets are command templates; configure `[agent].argv_template` in
`.manageroo/config.toml` when the default flags are wrong.

Use `./install.sh` from Linux, macOS, or a WSL2 terminal. Native Windows and the
PowerShell launcher intentionally stop with WSL2 guidance because the secure
artifact backend is not supported by native Windows CPython.

The local core skill pack is required for automatic routing. Let the installer
add it; if it was skipped, restore it with `manageroo skills reconcile --apply`
before normal product work. The pack includes helper lanes for rough prompts, memory lookup,
source ingest, media/PDF handling, long prose, exact text, debugging, tests,
review, public copy, website cleanup, skill creation, skill cleanup, and token
reduction. Do not load the whole pack into context. Read only the helper skill
or skills that match the current job. Manageroo-run workers receive that bounded
selection automatically; the operator must not be asked to remember or choose a
skill name.

If the operator requests token reduction, use one of:

```bash
manageroo token-mode set caveman
manageroo token-mode set curse
```

This is one token-reduction feature with two styles. `caveman` is clean.
`curse` is the same compression with appropriately placed profanity.

If the operator's product request is rough, overloaded, or frustrated, use the
bundled `$pimp-my-prompt` skill to turn it into exact scope, proof, and stop
rules before filling the product brief.

Do not make the operator hand-author agent files. Project init writes or updates
`AGENTS.md`, `CONTEXT.md`, `.manageroo/PROJECT-MEMORY.md`, and the
repo-local MANAGEROO skill. Read those files after setup and preserve any
existing human content around the managed blocks.

If the operator wants to provide the full request non-interactively, run:

```bash
manageroo solo \
  --want "OPERATOR_REQUEST_HERE" \
  --outcome "VISIBLE_RESULT_HERE" \
  --must-not "OUT_OF_SCOPE_OR_DO_NOT_TOUCH_HERE" \
  --proof "CHECK_OR_DEMO_HERE" \
  --force
manageroo ready --json
manageroo next --json
```

If readiness says no checks are configured, first let the controller add the
first detected repo-aware proof command:

```bash
manageroo checks suggest --apply-first
manageroo checks list
manageroo ready --json
```

If GBrain should know this repo, map only the selected target repository:

```bash
manageroo gbrain-setup --source-id target-repo --path "$TARGET_PROJECT" --apply --sync
```

If a local skill is getting long, repetitive, or stale, use the bundled
`$edit-skill` skill before adding more instructions.

## Continuation policy

- If a safe prerequisite is missing, execute the safe next action instead of
  handing the command to the operator.
- If `ready.ok` is false, follow `next.command` when it is local, reversible,
  and inside the requested scope, then recheck readiness.
- Build `.manageroo/PRODUCT-BRIEF.md` from `OPERATOR_REQUEST`; do not wait for the
  operator to hand-edit it.
- Before broad product work, read `.manageroo/PROJECT-MEMORY.md` and preserve its
  `What Must Not Break` section.
- Stop only for a concrete release failure that cannot be repaired in scope, a
  real destructive collision, a missing credential, or genuinely ambiguous target.

## Do not

- Do not weaken or skip tests.
- Do not silently install stack integrations during core setup.
- Do not create IDE-specific configuration.
- Do not invent verification commands.
- Do not run a product build with the template brief.
- Do not claim readiness when a required check fails.

## Required final report

Report in plain English: what was installed, whether the self-test and project
checks passed, what work was delivered, and the one concrete blocker only if
something truly could not be completed. Keep full JSON and paths in saved
evidence unless the operator asks for diagnostics.

---
