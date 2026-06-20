# Exact IDE-agent installation instructions

Give the extracted folder and the target product repository to the IDE agent with this instruction block.

---

You are installing **Uncle Matt's Super Mega Forward Build Ultimate Remix All-Star Booty of Fire Edition**.

This is an execution task, not a redesign task. Do not rename, rewrite, replace, or re-architect the package.

## Inputs

- `UMSMFBURASBOFE_SOURCE`: the extracted `Uncle-Matts-Super-Mega-Forward-Build-Ultimate-Remix-All-Star-Booty-of-Fire-Edition` directory.
- `TARGET_REPO`: the existing product Git repository.

Resolve both from the supplied workspace. If either is unavailable, stop and report the missing path. Do not guess.

## Required sequence

```bash
cd "$UMSMFBURASBOFE_SOURCE"
python3 scripts/verify_release.py
./install.sh
export PATH="$HOME/.local/bin:$PATH"
umsmfburasbofe --version
umsmfburasbofe self-test
git -C "$TARGET_REPO" rev-parse --show-toplevel
cd "$TARGET_REPO"
umsmfburasbofe init --agent codex
umsmfburasbofe doctor --json
```

Use `--agent codex` only when Codex is the selected runtime. Use `--agent generic` for another CLI and configure `[agent].argv_template` in `.umsmfburasbofe/config.toml`.

PowerShell users can run `.\install.ps1`; it starts the same installer.

## Stop conditions

- Stop on any release-verification failure.
- Stop if the target is not already a Git repository.
- Stop if `doctor.ok` is false and report every failed check exactly.
- Do not run a real build until the operator completes `.umsmfburasbofe/PRODUCT-BRIEF.md`.

## Do not

- Do not weaken or skip tests.
- Do not silently install stack integrations during core setup.
- Do not create IDE-specific configuration.
- Do not invent verification gates.
- Do not run a product build with the template brief.
- Do not claim readiness when a required check fails.

## Required final report

Return:

- operating system;
- UMSMFBURASBOFE version;
- Python version;
- selected agent adapter, version when discoverable, and executable path;
- UMSMFBURASBOFE executable path;
- install-lock path;
- self-test result;
- complete `umsmfburasbofe doctor --json` output;
- target repository path;
- readiness for a real product brief.

---
