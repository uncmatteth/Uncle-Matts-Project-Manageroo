[CmdletBinding()]
param(
    [switch]$SkipCodex,
    [switch]$SkipTests,
    [switch]$NoMusic,
    [switch]$NoAnimation
)
$ErrorActionPreference = "Stop"
$Root = $PSScriptRoot
$PythonExe = $null
$PythonPrefixArgs = @()

if (Get-Command py -ErrorAction SilentlyContinue) {
    & py -3.11 -c "import sys; raise SystemExit(0 if sys.version_info >= (3,11) else 1)"
    if ($LASTEXITCODE -eq 0) {
        $PythonExe = "py"
        $PythonPrefixArgs = @("-3.11")
    }
}
if (-not $PythonExe -and (Get-Command python -ErrorAction SilentlyContinue)) {
    & python -c "import sys; raise SystemExit(0 if sys.version_info >= (3,11) else 1)"
    if ($LASTEXITCODE -eq 0) {
        $PythonExe = "python"
    }
}
if (-not $PythonExe) {
    if (-not (Get-Command winget -ErrorAction SilentlyContinue)) {
        throw "Python 3.11+ is required and winget is unavailable."
    }
    winget install --id Python.Python.3.12 -e --accept-package-agreements --accept-source-agreements
    $PythonHome = Join-Path $env:LOCALAPPDATA "Programs\Python\Python312"
    $PythonCandidate = Join-Path $PythonHome "python.exe"
    if (Test-Path $PythonCandidate) {
        $PythonExe = $PythonCandidate
        $env:Path = "$PythonHome;$PythonHome\Scripts;$env:Path"
    } elseif (Get-Command py -ErrorAction SilentlyContinue) {
        $PythonExe = "py"
        $PythonPrefixArgs = @("-3.12")
    } else {
        throw "Python installed, but the executable is not visible. Open a new PowerShell window and rerun."
    }
}

if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
    if (-not (Get-Command winget -ErrorAction SilentlyContinue)) {
        throw "Git is required and winget is unavailable."
    }
    winget install --id Git.Git -e --accept-package-agreements --accept-source-agreements
    $GitCmd = Join-Path $env:ProgramFiles "Git\cmd"
    if (Test-Path $GitCmd) { $env:Path = "$GitCmd;$env:Path" }
    if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
        throw "Git installed, but git.exe is not visible. Open a new PowerShell window and rerun."
    }
}

$InstallArgs = @((Join-Path $Root "scripts\install.py"))
if ($SkipCodex) { $InstallArgs += "--skip-codex" }
if ($SkipTests) { $InstallArgs += "--skip-tests" }
if ($NoMusic) { $InstallArgs += "--no-music" }
if ($NoAnimation) { $InstallArgs += "--no-animation" }

& $PythonExe @PythonPrefixArgs @InstallArgs
if ($LASTEXITCODE -ne 0) {
    throw "UMSMFBURASBOFE installer failed with exit code $LASTEXITCODE"
}
