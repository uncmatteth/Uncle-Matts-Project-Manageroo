# Give this to your IDE agent

Use this when another AI tool is doing the install for you.

---

You are installing **Uncle Matt's Super Mega Forward Build Ultimate Remix All-Star Booty of Fire Edition**.

This is an install task. Do not rename the project, rewrite the docs, swap the
architecture, or get creative.

## Inputs

- `UMSMFBURASBOFE_SOURCE`: the extracted `Uncle-Matts-Super-Mega-Forward-Build-Ultimate-Remix-All-Star-Booty-of-Fire-Edition` directory.
- `TARGET_REPO`: the existing product Git repository.

Find both paths from the workspace. If either path is missing, stop and say
which one is missing. Do not guess.

## Required sequence

```bash
cd "$UMSMFBURASBOFE_SOURCE"
python3 scripts/verify_release.py
./install.sh
export PATH="$HOME/.local/bin:$PATH"
umsmfburasbofe --version
umsmfburasbofe self-test
umsmfburasbofe token-mode status
git -C "$TARGET_REPO" rev-parse --show-toplevel
cd "$TARGET_REPO"
umsmfburasbofe init --agent codex
umsmfburasbofe doctor --json
```

Use `--agent codex` only when Codex is the selected runtime. Use
`--agent generic` for another CLI and configure `[agent].argv_template` in
`.umsmfburasbofe/config.toml`.

PowerShell users can run `.\install.ps1`; it starts the same installer.

If the operator requests token reduction, use one of:

```bash
umsmfburasbofe token-mode set caveman
umsmfburasbofe token-mode set curse
```

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
