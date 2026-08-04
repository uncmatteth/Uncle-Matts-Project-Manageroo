# Windows verification report for `fix/clawpatch-partial-progress-loop`

Verification was performed on Windows against branch head
`0a1a2d9391c230f5297d7c192fd678eb185d6993`.

No live ClawPatch queue was started.

## Results

- `py -3 -m unittest discover -s tests -v` exited 1 after 785 tests in
  308.565 seconds: 19 failures, 35 errors, and 27 skips. The complete output
  is in `01-unittest-discover.log`.
- `py -3 scripts\verify_release.py` exited 1. Compilation and all structural
  checks passed, but the internal unit-test command reached the verifier's
  300-second timeout. The complete output is in `02-verify-release.log`.
- `clawpatch-supervise --help` exited 0. Its output is in
  `05-clawpatch-supervise-help.log`.
- The installed Manageroo package identifies commit
  `4f666568bdc0727d643ac92c41e8b2a19d915742` in both `installed.json` and
  pip's `direct_url.json`.
- After Git line-ending normalization, the installed `clawpatch_release.py`
  and `clawpatch_external.py` blob hashes exactly match that commit.
- The final executable-level process check found no live ClawPatch queue.

## Installer defect reproduced

The unmodified `Install-ClawPatch-Supervisor-Windows.ps1` does not complete on
this machine when both the system Node installation and the WinGet Node
installation are discoverable. `Resolve-NativeCommand` returns both paths,
and PowerShell then attempts to invoke the two paths as one executable name.
See `04b-installer-bypass.log` and
`04h-unmodified-installer-node24-path-complete.log`.

A verification-only copy of the installer was used to prove the remainder of
the installation flow. That copy selected a single command result and
preferred the WinGet Node 24.19.0 installation. It completed successfully and
reported that the supervisor was installed but not started. Its output is in
`04f-installer-prefer-winget-node.log`. The modified installer itself is not
included in this report branch.

`06b-normalized-provenance-and-process-check.log` supersedes the broad process
detector output in `06-installed-provenance.log`; the broad detector counted
the verification PowerShell process because its command text contained the
word `ClawPatch`.

## Log integrity

The published copies were normalized from PowerShell's UTF-16 capture format
to UTF-8 so GitHub can render them as text. `07-log-inventory.log` records the
byte size, line count, and SHA-256 digest of each published log. The logs were
scanned for common credential formats before publication, and no credential
patterns were found.
