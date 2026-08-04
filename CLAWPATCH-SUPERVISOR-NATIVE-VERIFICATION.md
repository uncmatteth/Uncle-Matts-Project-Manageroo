# Native ClawPatch supervisor verification

This package verifies the repaired external ClawPatch supervisor on native
Windows and native macOS. It does not authorize a live project queue.

## Fixed source contract

- Repository: `https://github.com/uncmatteth/Uncle-Matts-Project-Manageroo.git`
- Branch: `fix/clawpatch-partial-progress-loop`
- Supervisor source pin: `c038fdee0a34d8b77f11e90465eec41e88d9fb8a`
- ClawPatch: `0.7.2`
- Codex CLI: `0.144.4`
- Child watchdog and provider timeout: `900` seconds
- Windows installer SHA-256: `e2bed805da93538eb7a1202720087bf8e9371595660ed24c0640a11b00dc9b44`
- macOS installer SHA-256: `4746212d917ddc1d58fbba2df75bd82cdd8431f6c14d403d95709600c4ce9c20`

The handoff commit that adds these installer and instruction files is allowed to
be newer than the supervisor source pin. The supervisor implementation installed
by both scripts must remain pinned to the source commit above.

## Rules for both native agents

Execute these rules literally:

1. Run on the named native operating system. Windows Subsystem for Linux does
   not count as native Windows.
2. Do not use, add, or trigger GitHub Actions.
3. Do not run `clawpatch-supervise` against a real project.
4. Do not run a live ClawPatch finding queue.
5. Use only disposable temporary Git repositories for installation and
   behavioral proof.
6. Do not manually repair, triage, skip, hide, or advance a finding.
7. Do not change the state machine merely to make a platform test pass.
8. Do not use `git add -A` for repair commits.
9. Do not push temporary iteration commits.
10. If a native platform defect is found, make the smallest source fix on a new
    local branch, add a regression test, and rerun all proof. Do not push that
    fix unless the operator separately requests it.
11. Preserve the raw terminal transcript. Do not summarize a failed command as
    passing.

## Required behavior

The native tests must prove all of these behaviors in disposable repositories:

1. A validation-failed partial repair is staged only by its exact safe source
   paths and saved as one recognizable local-only temporary commit.
2. The same finding runs again from a clean combined source tree.
3. A later successful pass produces exactly one final repair commit above the
   finding's original HEAD, containing every partial improvement.
4. No temporary iteration commit reaches the remote.
5. A validation-failed attempt with no new source state stops after exactly two
   fix calls, returns HEAD to the original commit, leaves the partial repair
   visible, and does not advance the queue.
6. Repeated states and cycles to the original source tree stop deterministically
   without an arbitrary attempt cap.
7. An interrupted temporary commit is recovered only when the durable
   checkpoint proves repository, branch, starting HEAD, finding, temporary
   commit, and exact owned paths.
8. If clean current history advances from the recorded starting HEAD without
   containing the temporary commit, fresh startup retires only that dangling
   checkpoint and preserves current HEAD and files exactly.
9. Unrelated dirty source causes a safe refusal and remains untouched.
10. Command shims resolve without `shell=True`.
11. Timeout and interruption cleanup terminate and reap the complete process
    tree, with the configured 900-second watchdog passed to the child.
12. Progress output distinguishes a numbered fix attempt from a heartbeat and
    shows the active phase, exact command, elapsed time, and watchdog.
13. Exact-path commits, branch synchronization, push verification, fresh-start
    ownership, and visible `[current/total]` phases remain enforced.
14. A review generation that found or recovered findings cannot emit
    `COMPLETE`; it must preserve committed configuration, rebuild generated
    ClawPatch state, map the repaired HEAD, and completely review it again.
15. A two-generation simulation proves that the first generation repairs its
    finding and the second fresh generation finds zero findings before
    `COMPLETE`; the proof records both generations and terminal output displays
    `fresh_review_generations=2`.
16. A simulation in which a non-clean fresh generation repeats a source tree
    stops as nonconvergent without another review, an arbitrary generation cap,
    or a false completion claim.
17. A large-review simulation uses the job count returned by ClawPatch dry-run
    as the next review limit, continues in bounded worker waves until pending is
    zero, and stops if a successful wave does not reduce pending features by its
    exact reported reviewed count. The 900-second watchdog remains unchanged
    for every child process tree.
18. A supported PostgreSQL validation contract creates a separately owned,
    tmpfs-backed, loopback-only disposable database, scopes credentials and the
    reset guard only to ClawPatch children, and removes the container on every
    exit path. Untrusted images and foreign same-named containers remain
    untouched.
19. A continued durable product-analysis job reuses its locked capacity and
    unknown-unknowns-preflight artifacts even when live free disk space changes.
20. The Windows launcher preserves the exact supported Node directory selected
    by the installer, fails if that executable disappears, and enables UTF-8
    Python I/O. `npm.cmd` is accepted by generated default safety policy.
21. Child output containing malformed UTF-8 remains bounded and readable, absent
    output is safely sanitized, and a green baseline that changes project source
    stops before map or review with the exact changed paths.

## Windows agent instructions

Use native Windows PowerShell.

### Pull the verification package

```powershell
$Branch = "fix/clawpatch-partial-progress-loop"
$RepoUrl = "https://github.com/uncmatteth/Uncle-Matts-Project-Manageroo.git"
$Checkout = Join-Path $env:TEMP "manageroo-clawpatch-windows-proof"

if (Test-Path -LiteralPath $Checkout) {
    throw "Refusing to reuse an existing proof directory: $Checkout"
}

git clone --branch $Branch --single-branch $RepoUrl $Checkout
Set-Location $Checkout
git pull --ff-only origin $Branch
git status --short --branch
git rev-parse HEAD
```

Confirm the branch is clean and tracks
`origin/fix/clawpatch-partial-progress-loop`.

### Verify the Windows installer

```powershell
$ExpectedInstallerHash = "e2bed805da93538eb7a1202720087bf8e9371595660ed24c0640a11b00dc9b44"
$ActualInstallerHash = (Get-FileHash -Algorithm SHA256 .\Install-ClawPatch-Supervisor-Windows.ps1).Hash.ToLowerInvariant()
if ($ActualInstallerHash -ne $ExpectedInstallerHash) {
    throw "Windows installer hash mismatch: $ActualInstallerHash"
}

$InstallerText = Get-Content -Raw .\Install-ClawPatch-Supervisor-Windows.ps1
if ($InstallerText -notmatch "c038fdee0a34d8b77f11e90465eec41e88d9fb8a") {
    throw "Windows installer does not pin the repaired supervisor commit."
}
```

### Run the native Windows source proof

```powershell
$env:PYTHONPATH = (Join-Path $PWD "src")
py -3 -m unittest discover -s tests -v
if ($LASTEXITCODE -ne 0) { throw "Complete Windows unit suite failed." }

py -3 scripts\verify_release.py
if ($LASTEXITCODE -ne 0) { throw "Windows release verifier failed." }

py -3 -m unittest tests.test_clawpatch_partial_progress tests.test_clawpatch_release_sweep tests.test_disposable_validation_services tests.test_external_clawpatch_supervisor tests.test_final_clawpatch_regressions -v
if ($LASTEXITCODE -ne 0) { throw "Windows supervisor regression suite failed." }
```

### Install without starting a queue

Create a disposable repository. The invalid example remote is deliberate: the
installer only verifies that an origin exists and must not push during install.

```powershell
$ProofRepo = Join-Path $env:TEMP ("clawpatch-installer-proof-" + [guid]::NewGuid().ToString("N"))
New-Item -ItemType Directory -Path $ProofRepo | Out-Null
git -C $ProofRepo init --initial-branch=main
git -C $ProofRepo config user.name "Native Windows Proof"
git -C $ProofRepo config user.email "windows-proof@example.invalid"
Set-Content -LiteralPath (Join-Path $ProofRepo "baseline.txt") -Value "baseline" -Encoding utf8
git -C $ProofRepo add -- baseline.txt
git -C $ProofRepo commit -m "baseline"
git -C $ProofRepo remote add origin https://example.invalid/clawpatch-proof.git

.\Install-ClawPatch-Supervisor-Windows.ps1 -Repo $ProofRepo
if ($LASTEXITCODE -ne 0) { throw "Windows installer failed." }
```

The installer may run `clawpatch init` and `clawpatch doctor` in this disposable
repository. It must finish with `INSTALLATION VERIFIED` and must not start
`clawpatch-supervise`.

### Verify the installed Windows copy

```powershell
$InstallRoot = Join-Path $env:LOCALAPPDATA "ManagerooClawPatchSupervisor"
$VenvPython = Join-Path $InstallRoot "venv-f59afab\Scripts\python.exe"
$Supervisor = Join-Path $InstallRoot "venv-f59afab\Scripts\clawpatch-supervise.exe"

& $Supervisor --help
if ($LASTEXITCODE -ne 0) { throw "Installed Windows supervisor help failed." }

clawpatch --version
codex --version

$InstalledRelease = (& $VenvPython -c "import manageroo.clawpatch_release as m; print(m.__file__)").Trim()
$InstalledExternal = (& $VenvPython -c "import manageroo.clawpatch_external as m; print(m.__file__)").Trim()
$InstalledServices = (& $VenvPython -c "import manageroo.validation_services as m; print(m.__file__)").Trim()

$SourceReleaseHash = (Get-FileHash -Algorithm SHA256 .\src\manageroo\clawpatch_release.py).Hash.ToLowerInvariant()
$InstalledReleaseHash = (Get-FileHash -Algorithm SHA256 $InstalledRelease).Hash.ToLowerInvariant()
$SourceExternalHash = (Get-FileHash -Algorithm SHA256 .\src\manageroo\clawpatch_external.py).Hash.ToLowerInvariant()
$InstalledExternalHash = (Get-FileHash -Algorithm SHA256 $InstalledExternal).Hash.ToLowerInvariant()
$SourceServicesHash = (Get-FileHash -Algorithm SHA256 .\src\manageroo\validation_services.py).Hash.ToLowerInvariant()
$InstalledServicesHash = (Get-FileHash -Algorithm SHA256 $InstalledServices).Hash.ToLowerInvariant()

if ($SourceReleaseHash -ne $InstalledReleaseHash) { throw "Installed clawpatch_release.py does not match source." }
if ($SourceExternalHash -ne $InstalledExternalHash) { throw "Installed clawpatch_external.py does not match source." }
if ($SourceServicesHash -ne $InstalledServicesHash) { throw "Installed validation_services.py does not match source." }

Get-Content -Raw (Join-Path $InstallRoot "installed.json")
```

Do not run the installed supervisor without `--help` during this verification.

## macOS agent instructions

Use native Terminal on macOS.

### Pull the verification package

```bash
set -euo pipefail
branch="fix/clawpatch-partial-progress-loop"
repo_url="https://github.com/uncmatteth/Uncle-Matts-Project-Manageroo.git"
checkout="$(mktemp -d "${TMPDIR:-/tmp}/manageroo-clawpatch-macos-proof.XXXXXX")/repo"

git clone --branch "${branch}" --single-branch "${repo_url}" "${checkout}"
cd "${checkout}"
git pull --ff-only origin "${branch}"
git status --short --branch
git rev-parse HEAD
```

Confirm the branch is clean and tracks
`origin/fix/clawpatch-partial-progress-loop`.

### Verify the macOS installer

```bash
set -euo pipefail
expected_installer_hash="4746212d917ddc1d58fbba2df75bd82cdd8431f6c14d403d95709600c4ce9c20"
actual_installer_hash="$(shasum -a 256 Install-ClawPatch-Supervisor-macOS.sh | awk '{print $1}')"
test "${actual_installer_hash}" = "${expected_installer_hash}"
grep -F "c038fdee0a34d8b77f11e90465eec41e88d9fb8a" Install-ClawPatch-Supervisor-macOS.sh >/dev/null
```

### Run the native macOS source proof

```bash
set -euo pipefail
PYTHONPATH=src python3 -m unittest discover -s tests -v
PYTHONPATH=src python3 scripts/verify_release.py
PYTHONPATH=src python3 -m unittest \
  tests.test_clawpatch_partial_progress \
  tests.test_clawpatch_release_sweep \
  tests.test_disposable_validation_services \
  tests.test_external_clawpatch_supervisor \
  tests.test_final_clawpatch_regressions -v
```

### Install without starting a queue

```bash
set -euo pipefail
proof_repo="$(mktemp -d "${TMPDIR:-/tmp}/clawpatch-installer-proof.XXXXXX")"
git -C "${proof_repo}" init --initial-branch=main
git -C "${proof_repo}" config user.name "Native macOS Proof"
git -C "${proof_repo}" config user.email "macos-proof@example.invalid"
printf '%s\n' baseline > "${proof_repo}/baseline.txt"
git -C "${proof_repo}" add -- baseline.txt
git -C "${proof_repo}" commit -m baseline
git -C "${proof_repo}" remote add origin https://example.invalid/clawpatch-proof.git

chmod 0755 Install-ClawPatch-Supervisor-macOS.sh
./Install-ClawPatch-Supervisor-macOS.sh "${proof_repo}"
```

The installer may run `clawpatch init` and `clawpatch doctor` in this disposable
repository. It must finish with `INSTALLATION VERIFIED` and must not start
`clawpatch-supervise`.

### Verify the installed macOS copy

```bash
set -euo pipefail
install_root="${HOME}/Library/Application Support/ManagerooClawPatchSupervisor"
venv_python="${install_root}/venv/bin/python"
supervisor="${install_root}/venv/bin/clawpatch-supervise"

"${supervisor}" --help
"${install_root}/npm/node_modules/.bin/clawpatch" --version
"${install_root}/npm/node_modules/.bin/codex" --version

installed_release="$("${venv_python}" -c 'import manageroo.clawpatch_release as m; print(m.__file__)')"
installed_external="$("${venv_python}" -c 'import manageroo.clawpatch_external as m; print(m.__file__)')"
installed_services="$("${venv_python}" -c 'import manageroo.validation_services as m; print(m.__file__)')"

test "$(shasum -a 256 src/manageroo/clawpatch_release.py | awk '{print $1}')" = "$(shasum -a 256 "${installed_release}" | awk '{print $1}')"
test "$(shasum -a 256 src/manageroo/clawpatch_external.py | awk '{print $1}')" = "$(shasum -a 256 "${installed_external}" | awk '{print $1}')"
test "$(shasum -a 256 src/manageroo/validation_services.py | awk '{print $1}')" = "$(shasum -a 256 "${installed_services}" | awk '{print $1}')"

cat "${install_root}/installed.json"
```

Do not run the installed supervisor without `--help` during this verification.

## Required report from either agent

Return all of the following:

1. Native OS version and architecture.
2. PowerShell or shell version.
3. Python, Git, Node, Codex, and ClawPatch versions.
4. Checked-out branch and exact HEAD.
5. Installer SHA-256 and pinned Manageroo commit.
6. Complete unit-test totals, failures, errors, and skips.
7. Supervisor-specific regression results.
8. Release-verifier result.
9. Installed source paths and matching SHA-256 values.
10. `clawpatch-supervise --help` result.
11. Confirmation that no GitHub Actions workflow was used.
12. Confirmation that no live queue or real project was touched.
13. Any local diff or local commit created for a native defect.
14. One plain verdict: `VERIFIED ON NATIVE WINDOWS`, `VERIFIED ON NATIVE
    MACOS`, or `NOT VERIFIED`, followed by the exact blocker.

Do not claim cross-platform correctness from Linux results or source inspection.
