# Bob's Turtle Tank Windows supervisor follow-up

Observed on native Windows on 2026-08-04. This report follows the original
installer verification in this directory and records the first real
`bobsturtletank` baseline and live-review attempt after installation.

## Executive state

- Bob repository: `C:\Users\david\Documents\Codex\repos\bobsturtletank`
- Bob repository HEAD and `origin/main` at the observation point:
  `5c5c983db71ea6311118d728490e405e5d6d3c1f`
- Installed Manageroo source pin:
  `4f666568bdc0727d643ac92c41e8b2a19d915742`
- ClawPatch: `0.7.2`
- Codex CLI: `0.144.4`
- Node selected by the repaired launcher: `24.19.0`
- npm selected by the repaired launcher: `11.17.0`
- Installed supervisor `--help`: exit `0`
- Vision runtime on this computer: off. No `BobVisionRuntime` scheduled task is
  installed, and no Vision publisher/runtime process was present before the
  ClawPatch supervisor was started.

At 2026-08-04 17:50 America/New_York, a user-started live supervisor was
active with:

```text
clawpatch-supervise.exe --repo . --branch current --push each --fresh
```

The baseline gate had exited `0` and the process tree had advanced to:

```text
clawpatch review --limit 8 --json
codex exec --cd C:/Users/david/Documents/Codex/repos/bobsturtletank \
  --output-schema <temporary schema> --output-last-message <temporary output> \
  --sandbox read-only -
```

Do not start a second queue or modify the Bob checkout while that process tree
is active.

## Failure chronology and repairs

### 1. Windows gate allowlist rejected `npm.cmd`

The Bob Manageroo gate is intentionally configured as:

```toml
argv = ["npm.cmd", "run", "verify"]
```

The installed Manageroo default safety list admitted `npm` but rejected the
Windows executable spelling `npm.cmd`:

```text
Command program is not allowlisted: npm.cmd
```

Permanent Bob-side repair: commit
`03cb397d714cf1e481b25b3a0920cc840f72d8aa` adds an explicit project safety
allowlist containing both `npm` and `npm.cmd`. The installed Manageroo policy
then accepted the exact gate.

Upstream consideration: either admit the canonical Windows npm shim by
default or document that every Windows repository using `npm.cmd` must add it
to `[safety].allowed_programs`.

### 2. The generated launcher selected an old Node runtime

After reinstall, the generated launcher no longer pinned the verified WinGet
Node installation. PATH resolution selected Node 20/npm 9 even though Node 24
was installed and required by the Bob repository.

Local machine repair applied to
`C:\Users\david\.local\bin\clawpatch-supervise.cmd`:

```bat
set "NODE_RUNTIME=C:\Users\david\AppData\Local\Microsoft\WinGet\Packages\OpenJS.NodeJS.LTS_Microsoft.Winget.Source_8wekyb3d8bbwe\node-v24.19.0-win-x64"
if not exist "%NODE_RUNTIME%\node.exe" (
  echo ClawPatch supervisor Node runtime is missing: %NODE_RUNTIME%\node.exe 1>&2
  exit /b 1
)
set "PATH=%SUPERVISOR_VENV%\Scripts;%NODE_RUNTIME%;C:\Users\david\AppData\Roaming\npm;C:\Users\david\AppData\Local\Programs\bin;%PATH%"
```

This is a local mitigation, not a Manageroo source fix. A future installer run
can overwrite it. The Windows installer/launcher template should persist the
Node runtime it actually verified.

### 3. Windows subprocess output used cp1252 instead of UTF-8

Manageroo's project-gate reader encountered UTF-8 test output and failed with
a Windows `UnicodeDecodeError` on byte `0x8f`; the missing decoded stdout then
led to an `AttributeError` while sanitizing output.

Local launcher mitigation:

```bat
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
```

After this change the installed Manageroo gate runner captured the complete
Bob validation output. This should be fixed in the Windows launcher template
and/or by explicitly decoding child output as UTF-8 with a safe error policy.
The secondary sanitizer path should also tolerate missing stdout/stderr.

### 4. Bob validation dependencies were absent

The full Bob gate requires its ignored local Python environment and Playwright
Chromium. They were installed locally for repository validation only:

- Python 3.12 `.venv` from `services\vision\requirements.lock.txt`
- Playwright Chromium via `npx playwright install chromium`

These installations did not enable the Vision runtime, open a camera, publish
frames, or install a Vision scheduled task.

### 5. Two runtime black-box fixtures were stale after Fireball Season

Production Fireball Season intentionally forces Night mode all day while the
scheduled Day/Vision path remains implemented and tested for rollback.

Commit `03cb397d714cf1e481b25b3a0920cc840f72d8aa` repaired two test-only
contracts:

1. `tools/runtime-blackbox-worker.mjs` now exposes a black-box-only
   `configureDayMode` control that disables the season and selects Day mode
   before exercising the preserved Vision path.
2. `services/vision/runtime_blackbox.py` keeps the Vision-authority lease alive
   with heartbeats while advancing Worker time far enough to prove rejection
   of a frame older than 15 seconds. Previously the 5-second authority lease
   expired before the stale-frame assertion could test frame age.

No production game or Vision-runtime behavior changed.

### 6. Two realtime room-loop tests also omitted scheduled Day mode

The first live supervisor baseline after the earlier repairs stopped on:

```text
interrupts and requeues safely when the real room loop step fails
retries room loop recovery by alarm after interruption persistence fails
```

Both tests sent two Vision frames and expected one `runStarted`, but Fireball
Season initialized the real room in Night mode. The suite already had the
correct `useScheduledDayMode()` fixture helper; these two older recovery tests
were simply missed by the season migration.

Permanent repair in commit
`5c5c983db71ea6311118d728490e405e5d6d3c1f`: call
`await useScheduledDayMode()` in both tests before queueing the player. The
exact two failures passed three consecutive targeted runs, then passed the
complete integration and repository gates.

## Verification evidence

The repaired Bob repository passed all of the following under Node 24:

- affected room-loop tests: `2/2`, three consecutive targeted runs
- realtime integration files: `2/2`, `39/39` tests
- Vitest unit files: `108/108`, `574/574` tests
- Node test runner: `76/76`
- Python unit suite: `98/98`
- PowerShell runtime-manager tests: `25/25`, repeatedly
- Playwright: `23/23`
- repository contract audit: `1793` checks, zero failures
- runtime black-box integration: two successful passes
- TypeScript checks, Next production build, and Wrangler dry-run: passed
- complete `npm.cmd run verify`: exit `0`

The live supervisor's persisted baseline log is:

```text
C:\Users\david\Documents\Codex\repos\bobsturtletank\.manageroo\cache\clawpatch-release-logs\gate-bobsturtletank-verify.json
```

It records `exit_code: 0`, `timed_out: false`, start
`2026-08-04T21:47:02.504720+00:00`, and finish
`2026-08-04T21:50:17.705566+00:00`.

## Unresolved post-validation cleanliness hazard

The successful Bob gate changes tracked `apps/web/next-env.d.ts` from:

```ts
import "./.next/types/routes.d.ts";
```

to:

```ts
import "./.next/dev/types/routes.d.ts";
```

This is generated by the Next build/dev test sequence. During manual proof it
was restored before committing. During the live run, Manageroo completed the
baseline and entered `clawpatch review --limit 8 --json` with this one tracked
source diff present. At the observation point there were also 124 modified or
deleted `.clawpatch` state paths, which are expected runtime state and excluded
from Manageroo source ownership.

Do not silently stage the generated `next-env.d.ts` change. The Bob gate should
be made source-clean, and Manageroo should consider checking source cleanliness
again immediately after required baseline gates so validation side effects
cannot become accidental finding input or block a later fix.

## Exact operator command

The user starts the live queue from PowerShell with only these lines (without
copying the `PS C:\...>` prompt):

```powershell
Set-Location "C:\Users\david\Documents\Codex\repos\bobsturtletank"
& "$env:USERPROFILE\.local\bin\clawpatch-supervise.cmd" --repo . --branch current --push each --fresh
```

`--push each` authorizes the supervisor to push each completed repair.
`--fresh` is required because prior failed starts left old `.clawpatch` runtime
state and the Bob source HEAD advanced through the prerequisite repairs.

## Copy-paste handoff to the next agent

Use this as the complete operational handoff:

> Work on the Windows ClawPatch/Manageroo supervisor follow-up for
> `C:\Users\david\Documents\Codex\repos\bobsturtletank`. Installed Manageroo
> is pinned to `4f666568bdc0727d643ac92c41e8b2a19d915742`; ClawPatch is `0.7.2`;
> Codex CLI is `0.144.4`. Bob `main` and `origin/main` were synchronized at
> `5c5c983db71ea6311118d728490e405e5d6d3c1f`. Permanent Bob fixes are
> `03cb397d714cf1e481b25b3a0920cc840f72d8aa` and
> `5c5c983db71ea6311118d728490e405e5d6d3c1f`. The local launcher at
> `C:\Users\david\.local\bin\clawpatch-supervise.cmd` was manually repaired
> to pin WinGet Node `24.19.0`, fail if that runtime is absent, and set
> `PYTHONUTF8=1` plus `PYTHONIOENCODING=utf-8`; do not reinstall over it unless
> the installer source contains equivalent fixes. The repo explicitly allows
> `npm.cmd`. The full `npm.cmd run verify` gate passes: 574 Vitest, 76 Node,
> 98 Python, 39 realtime integration, 23 Playwright, runtime black-box twice,
> typechecks/build/dry-run/audit. Vision remains off on this machine: do not
> start a camera, publisher, Vision supervisor, or scheduled task. At
> 2026-08-04 17:50 ET, a user-started live supervisor was active and had moved
> from a green baseline into `clawpatch review --limit 8 --json` with a
> read-only Codex child. Do not start a second queue and do not edit/stage the
> Bob checkout while that process is active. The green validation itself
> changes tracked `apps/web/next-env.d.ts` from `.next/types/routes.d.ts` to
> `.next/dev/types/routes.d.ts`; treat this as generated noise, not a repair,
> and fix the post-validation cleanliness contract before allowing it into a
> commit. Preserve `.clawpatch` runtime state unless the user explicitly asks
> otherwise. Report exact process/checkpoint evidence rather than assuming the
> queue is still running or complete.
