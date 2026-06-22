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

Find the paths from the workspace and the request from the operator. If any
input is missing, stop and say which one is missing. Do not guess.

## Required sequence

```bash
cd "$MANAGEROO_SOURCE"
python3 scripts/verify_release.py
./install.sh
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

Use `--agent codex` only when Codex is the selected runtime. Use
`manageroo agent list` to see presets for another CLI. The non-Codex
presets are command templates; configure `[agent].argv_template` in
`.manageroo/config.toml` when the default flags are wrong.

Same installer, same behavior. Use `./install.sh` from a normal Unix-style
terminal, or `.\install.ps1` from PowerShell. Those are launchers, not separate
products.

The recommended local skill pack is optional but strongly suggested. Let the
installer add it unless the operator explicitly chooses `--skill-pack skip` or
`--skip-skill-pack`; install it later with `manageroo skills reconcile --apply` if it
was skipped. The pack includes helper lanes for rough prompts, memory lookup,
source ingest, media/PDF handling, long prose, exact text, debugging, tests,
review, public copy, website cleanup, skill creation, skill cleanup, and token
reduction. Do not load the whole pack into context. Read only the helper skill
or skills that match the current job.

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

## Stop conditions

- Stop on any release-verification failure.
- Stop if `CREATE_PROJECT` is not `yes` and the target is not already a Git repository.
- Stop if `CREATE_PROJECT` is `yes` but the target is a non-empty non-Git folder.
- Stop if `ready.ok` is false and report every failed or action item exactly, plus the single `next.command`.
- Do not run a real build until the operator completes `.manageroo/PRODUCT-BRIEF.md`.
- Before broad product work, read `.manageroo/PROJECT-MEMORY.md` and preserve its `What Must Not Break` section.

## Do not

- Do not weaken or skip tests.
- Do not silently install stack integrations during core setup.
- Do not create IDE-specific configuration.
- Do not invent verification commands.
- Do not run a product build with the template brief.
- Do not claim readiness when a required check fails.

## Required final report

Return:

- terminal/runtime environment;
- MANAGEROO version;
- Python version;
- selected agent adapter, version when discoverable, and executable path;
- MANAGEROO executable path;
- install-lock path;
- complete `manageroo stack-status --json` output;
- complete `manageroo repair-install --no-apply --json` output;
- self-test result;
- complete `manageroo ready --json` output;
- target repository path;
- readiness for a real product brief.

---
