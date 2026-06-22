# Give this to your IDE agent

Use this when another AI tool is doing the install for you.

---

You are installing **Uncle Matt's Super Mega Forward Build Ultimate Remix All-Star Booty of Fire Edition**.

This is an install task. Do not rename the project, rewrite the docs, swap the
architecture, or get creative.

## Inputs

- `UMSMFBURASBOFE_SOURCE`: the extracted `Uncle-Matts-Super-Mega-Forward-Build-Ultimate-Remix-All-Star-Booty-of-Fire-Edition` directory.
- `TARGET_PROJECT`: the existing product Git repository, or the missing/empty folder to create.
- `OPERATOR_REQUEST`: what the operator wants built or fixed.
- `CREATE_PROJECT`: `yes` only when `TARGET_PROJECT` is allowed to be created if missing or empty.

Find the paths from the workspace and the request from the operator. If any
input is missing, stop and say which one is missing. Do not guess.

## Required sequence

```bash
cd "$UMSMFBURASBOFE_SOURCE"
python3 scripts/verify_release.py
./install.sh
export PATH="$HOME/.local/bin:$PATH"
umsmfburasbofe --version
umsmfburasbofe self-test
umsmfburasbofe skills list
umsmfburasbofe token-mode status
umsmfburasbofe stack-status --json
umsmfburasbofe repair-install --no-apply --json
if [ "$CREATE_PROJECT" = "yes" ]; then
  umsmfburasbofe solo "$TARGET_PROJECT" --create --agent codex --want "$OPERATOR_REQUEST" --force
  cd "$TARGET_PROJECT"
else
  git -C "$TARGET_PROJECT" rev-parse --show-toplevel
  cd "$TARGET_PROJECT"
  umsmfburasbofe solo --agent codex --want "$OPERATOR_REQUEST" --force
fi
umsmfburasbofe memory show
umsmfburasbofe ready --json
umsmfburasbofe next --json
```

Use `--agent codex` only when Codex is the selected runtime. Use
`umsmfburasbofe agent list` to see presets for another CLI. The non-Codex
presets are command templates; configure `[agent].argv_template` in
`.umsmfburasbofe/config.toml` when the default flags are wrong.

Same installer, same behavior. Use `./install.sh` from a normal Unix-style
terminal, or `.\install.ps1` from PowerShell. Those are launchers, not separate
products.

If the operator requests token reduction, use one of:

```bash
umsmfburasbofe token-mode set caveman
umsmfburasbofe token-mode set curse
```

If the operator's product request is rough, overloaded, or frustrated, use the
bundled `$pimp-my-prompt` skill to turn it into exact scope, proof, and stop
rules before filling the product brief.

If the operator wants to provide the full request non-interactively, run:

```bash
umsmfburasbofe solo \
  --want "OPERATOR_REQUEST_HERE" \
  --outcome "VISIBLE_RESULT_HERE" \
  --must-not "OUT_OF_SCOPE_OR_DO_NOT_TOUCH_HERE" \
  --proof "CHECK_OR_DEMO_HERE" \
  --force
umsmfburasbofe ready --json
umsmfburasbofe next --json
```

If readiness says no checks are configured, ask for the real test, lint, build,
or smoke command and add it through the CLI:

```bash
umsmfburasbofe checks add smoke -- npm test
umsmfburasbofe checks list
umsmfburasbofe ready --json
```

If GBrain should know this repo, map only the selected target repository:

```bash
umsmfburasbofe gbrain-setup --source-id target-repo --path "$TARGET_PROJECT" --apply --sync
```

If a local skill is getting long, repetitive, or stale, use the bundled
`$edit-skill` skill before adding more instructions.

## Stop conditions

- Stop on any release-verification failure.
- Stop if `CREATE_PROJECT` is not `yes` and the target is not already a Git repository.
- Stop if `CREATE_PROJECT` is `yes` but the target is a non-empty non-Git folder.
- Stop if `ready.ok` is false and report every failed or action item exactly, plus the single `next.command`.
- Do not run a real build until the operator completes `.umsmfburasbofe/PRODUCT-BRIEF.md`.
- Before broad product work, read `.umsmfburasbofe/PROJECT-MEMORY.md` and preserve its `What Must Not Break` section.

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
- UMSMFBURASBOFE version;
- Python version;
- selected agent adapter, version when discoverable, and executable path;
- UMSMFBURASBOFE executable path;
- install-lock path;
- complete `umsmfburasbofe stack-status --json` output;
- complete `umsmfburasbofe repair-install --no-apply --json` output;
- self-test result;
- complete `umsmfburasbofe ready --json` output;
- target repository path;
- readiness for a real product brief.

---
