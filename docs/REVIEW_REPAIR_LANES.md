# AUTOREVIEW and Clawpatch lanes

AUTOREVIEW and Clawpatch are command-owned repair lanes. They are not vague
advice for the AI agent to reinterpret.

When `autoreview_command` or `clawpatch_command` is configured in
`.manageroo/config.toml`, MANAGEROO does this:

1. Runs the configured AUTOREVIEW command exactly as an argv array.
2. Runs the configured Clawpatch command exactly as an argv array.
3. Runs those commands inside the isolated run workspace, not directly against
   the user's source repo.
4. Captures stdout, stderr, exit code, timeout state, changed paths, and policy
   errors in `review/external-review-repair.json`.
5. Scope-checks any file edits against the locked plan.
6. Re-runs the deterministic gates if either command changed files.
7. Blocks the run if a configured command fails, times out, changes `HEAD`, or
   edits outside the locked scope.

Use `{external_state_dir}` for tool state when the external tool supports it.
For Clawpatch, that means prefer `--state-dir {external_state_dir}/clawpatch`
in configured commands so `.clawpatch/` does not become part of the delivered
patch.

The controller and AI agents must not freehand fixes from AUTOREVIEW or
Clawpatch findings. If one of those tools has a repair/apply mode, configure
that exact tool command. If the tool cannot repair something, MANAGEROO
reports the exact command output and stops.

That is the point: AUTOREVIEW owns its lane. Clawpatch owns its lane.
MANAGEROO owns orchestration, scope, evidence, gates, and final delivery.
