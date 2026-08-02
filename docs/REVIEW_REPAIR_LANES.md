# AUTOREVIEW and Clawpatch lanes

AUTOREVIEW and Clawpatch are command-owned repair lanes. They are not vague
advice for the AI agent to reinterpret.

When `autoreview_command` or `clawpatch_command` is configured in
`.manageroo/config.toml`, MANAGEROO does this:

1. Runs the configured AUTOREVIEW command exactly as an argv array.
2. Treats `clawpatch_command = ["clawpatch"]` as activation of the internal,
   sequential Clawpatch controller rather than a one-shot command.
3. Runs every command inside the isolated run workspace, not directly against
   the user's source repo.
4. Gives Clawpatch a run-owned external state directory, maps the repository,
   reviews every feature changed since the run's original source-mirror baseline,
   proves that bounded review queue empty, then repeats
   `next --json` -> exact `show` -> one finding-scoped `fix` -> full Manageroo
   gates -> controller checkpoint -> exact `fixed` revalidation.
5. Scope-checks the current patch-attempt paths against both the actual Git diff
   and the locked plan before accepting any repair.
6. Uses a 15-minute watchdog for each Clawpatch child process. A timeout kills
   the complete child process group, reloads Clawpatch's durable state, follows
   the current `next` command, and retries the same finding. A timeout does not
   end the repair lane.
7. Persists the active finding, command journal, retries, gates, and checkpoints
   in `review/external-state/clawpatch-progress.json`. `run --continue` resumes
   a checkpointed or interrupted attempt instead of starting the queue over.
8. Repeats failed Clawpatch-owned attempts after preserving and rolling back
   only that attempt. Manageroo never substitutes its own code edit.
9. Requires zero open findings, zero uncertain findings, zero locks, and a final
   full gate pass before the Clawpatch lane succeeds.

The controller-scoped environment sets `CLAWPATCH_STATE_DIR` to
`{external_state_dir}/clawpatch`, forces Clawpatch's Codex child to `read-only`
for map/review/revalidation and `workspace-write` only for `fix`, and sets a
default `CLAWPATCH_CODEX_TIMEOUT_MS=900000`. An operator-provided timeout value
is preserved, but a host-level sandbox-bypass environment value is not inherited
by this lane. A Git mirror is not an operating-system security sandbox.

The controller and AI agents must not freehand fixes from AUTOREVIEW or
Clawpatch findings. Clawpatch's own `fix` command remains the only code repairer
in this lane. Manageroo owns supervision, retries, rollback, scope, gates,
checkpoints, and durable continuation.

Manageroo supervises its child processes while the controller is running. It
does not install an operating-system daemon that resurrects a killed Manageroo
process; an external launcher must restart it with `run --continue <run-id>`.
The durable Clawpatch progress and controller checkpoints make that continuation
automatic once the controller is relaunched.

That is the point: AUTOREVIEW owns its lane. Clawpatch owns its lane.
MANAGEROO owns orchestration, scope, evidence, gates, and final delivery.
