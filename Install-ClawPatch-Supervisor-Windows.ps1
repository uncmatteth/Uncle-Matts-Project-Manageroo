[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$Repo
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

# Exact versions from the verified supervisor source.
$ManagerooCommit = "0967a97fecbeb570328628073167321bdcf32102"
$ManagerooSource = "git+https://github.com/uncmatteth/Uncle-Matts-Project-Manageroo.git@$ManagerooCommit"
$CodexPackage = "@openai/codex@0.144.4"
$ClawPatchPackage = "clawpatch@0.7.2"

$InstallRoot = Join-Path $env:LOCALAPPDATA "ManagerooClawPatchSupervisor"
# Keep the existing environment path so upgrades do not create another venv.
$Venv = Join-Path $InstallRoot "venv-f59afab"
$BinDir = Join-Path $env:USERPROFILE ".local\bin"
$NpmBin = Join-Path $env:APPDATA "npm"
$ProgramsBin = Join-Path $env:LOCALAPPDATA "Programs\bin"

function Refresh-ProcessPath {
    $machinePath = [Environment]::GetEnvironmentVariable("Path", "Machine")
    $userPath = [Environment]::GetEnvironmentVariable("Path", "User")
    $parts = @($script:BinDir, $script:NpmBin, $script:ProgramsBin, $machinePath, $userPath) |
        Where-Object { $_ }
    $env:Path = $parts -join ";"
}

function Add-UserPathEntry([string]$PathEntry) {
    $current = [Environment]::GetEnvironmentVariable("Path", "User")
    $items = @($current -split ";" | Where-Object { $_ })
    if ($items -notcontains $PathEntry) {
        [Environment]::SetEnvironmentVariable("Path", ((@($items) + $PathEntry) -join ";"), "User")
    }
}

function Resolve-NativeCommand([string[]]$Names, [string[]]$KnownPaths = @()) {
    foreach ($name in $Names) {
        $command = Get-Command $name -CommandType Application -ErrorAction SilentlyContinue |
            Select-Object -First 1
        if ($command) { return $command.Source }
    }
    foreach ($candidate in $KnownPaths) {
        if ($candidate -and (Test-Path -LiteralPath $candidate -PathType Leaf)) {
            return (Resolve-Path -LiteralPath $candidate).Path
        }
    }
    return $null
}

function Install-WingetPackage([string]$Id, [string]$DisplayName) {
    $winget = Resolve-NativeCommand @("winget.exe")
    if (-not $winget) {
        throw "$DisplayName is missing and winget is unavailable. Install Windows App Installer, then rerun this installer."
    }
    Write-Host "Installing or updating $DisplayName..."
    & $winget install --id $Id --exact --accept-package-agreements --accept-source-agreements
    if ($LASTEXITCODE -ne 0) {
        throw "winget could not install $DisplayName (exit $LASTEXITCODE)."
    }
    Refresh-ProcessPath
}

New-Item -ItemType Directory -Force -Path $InstallRoot, $BinDir | Out-Null
$script:BinDir = $BinDir
$script:NpmBin = $NpmBin
$script:ProgramsBin = $ProgramsBin
Add-UserPathEntry $BinDir
Add-UserPathEntry $NpmBin
Add-UserPathEntry $ProgramsBin
Refresh-ProcessPath

$GitExe = Resolve-NativeCommand @("git.exe", "git") @("$env:ProgramFiles\Git\cmd\git.exe")
if (-not $GitExe) {
    Install-WingetPackage "Git.Git" "Git"
    $GitExe = Resolve-NativeCommand @("git.exe", "git") @("$env:ProgramFiles\Git\cmd\git.exe")
}
if (-not $GitExe) { throw "Git was installed but is not available. Open a new PowerShell window and rerun this installer." }

$NodeExe = Resolve-NativeCommand @("node.exe", "node") @("$env:ProgramFiles\nodejs\node.exe")
$NodeMajor = 0
if ($NodeExe) {
    $NodeMajorText = [string](& $NodeExe -p "process.versions.node.split('.')[0]")
    if ($LASTEXITCODE -eq 0) { [void][int]::TryParse($NodeMajorText.Trim(), [ref]$NodeMajor) }
}
if (-not $NodeExe -or $NodeMajor -lt 22) {
    Install-WingetPackage "OpenJS.NodeJS.LTS" "Node.js LTS"
    $NodeExe = Resolve-NativeCommand @("node.exe", "node") @("$env:ProgramFiles\nodejs\node.exe")
    if ($NodeExe) {
        $NodeMajorText = [string](& $NodeExe -p "process.versions.node.split('.')[0]")
        $NodeMajor = 0
        if ($LASTEXITCODE -eq 0) { [void][int]::TryParse($NodeMajorText.Trim(), [ref]$NodeMajor) }
    }
}
if (-not $NodeExe -or $NodeMajor -lt 22) {
    throw "ClawPatch requires Node.js 22 or newer. Install it, open a new PowerShell window, and rerun this installer."
}

$NpmExe = Resolve-NativeCommand @("npm.cmd") @("$env:ProgramFiles\nodejs\npm.cmd")
if (-not $NpmExe) { throw "Node.js is installed, but npm.cmd could not be found." }

$PythonExe = $null
$PythonPrefix = @()
$PyLauncher = Resolve-NativeCommand @("py.exe", "py")
if ($PyLauncher) {
    $probe = [string](& $PyLauncher -3 -c "import sys; print('OK' if sys.version_info >= (3, 11) else 'OLD')")
    if ($LASTEXITCODE -eq 0 -and $probe.Trim() -eq "OK") {
        $PythonExe = $PyLauncher
        $PythonPrefix = @("-3")
    }
}
if (-not $PythonExe) {
    $candidate = Resolve-NativeCommand @("python.exe", "python") @(
        (Join-Path $env:LOCALAPPDATA "Programs\Python\Python312\python.exe"),
        (Join-Path $env:ProgramFiles "Python312\python.exe")
    )
    if ($candidate) {
        $probe = [string](& $candidate -c "import sys; print('OK' if sys.version_info >= (3, 11) else 'OLD')")
        if ($LASTEXITCODE -eq 0 -and $probe.Trim() -eq "OK") { $PythonExe = $candidate }
    }
}
if (-not $PythonExe) {
    Install-WingetPackage "Python.Python.3.12" "Python 3.12"
    $candidate = Resolve-NativeCommand @("python.exe", "python") @(
        (Join-Path $env:LOCALAPPDATA "Programs\Python\Python312\python.exe"),
        (Join-Path $env:ProgramFiles "Python312\python.exe")
    )
    if ($candidate) {
        $probe = [string](& $candidate -c "import sys; print('OK' if sys.version_info >= (3, 11) else 'OLD')")
        if ($LASTEXITCODE -eq 0 -and $probe.Trim() -eq "OK") { $PythonExe = $candidate }
    }
}
if (-not $PythonExe) {
    throw "Python 3.11 or newer was installed but is not available. Open a new PowerShell window and rerun this installer."
}

Write-Host "Installing the exact Codex and ClawPatch versions used by the working supervisor..."
& $NpmExe install --global --no-fund --no-audit $CodexPackage $ClawPatchPackage
if ($LASTEXITCODE -ne 0) { throw "npm could not install Codex and ClawPatch (exit $LASTEXITCODE)." }
Refresh-ProcessPath

$CodexExe = Resolve-NativeCommand @("codex.cmd", "codex.exe", "codex") @((Join-Path $NpmBin "codex.cmd"))
$ClawPatchExe = Resolve-NativeCommand @("clawpatch.cmd", "clawpatch.exe", "clawpatch") @((Join-Path $NpmBin "clawpatch.cmd"))
if (-not $CodexExe) { throw "Codex installed, but codex.cmd could not be found." }
if (-not $ClawPatchExe) { throw "ClawPatch installed, but clawpatch.cmd could not be found." }

$CodexVersion = ((& $CodexExe --version) | Select-Object -Last 1).Trim()
if ($LASTEXITCODE -ne 0 -or $CodexVersion -notmatch "0\.144\.4") {
    throw "Expected Codex CLI 0.144.4, found: $CodexVersion"
}
$ClawPatchVersion = ((& $ClawPatchExe --version) | Select-Object -Last 1).Trim()
if ($LASTEXITCODE -ne 0 -or $ClawPatchVersion -notmatch "0\.7\.2") {
    throw "Expected ClawPatch 0.7.2, found: $ClawPatchVersion"
}

if (-not (Test-Path -LiteralPath $Venv -PathType Container)) {
    Write-Host "Creating the dedicated supervisor environment..."
    & $PythonExe @PythonPrefix -m venv $Venv
    if ($LASTEXITCODE -ne 0) { throw "Python could not create the supervisor environment." }
}

$VenvPython = Join-Path $Venv "Scripts\python.exe"
$SupervisorExe = Join-Path $Venv "Scripts\clawpatch-supervise.exe"
Write-Host "Installing the repaired Manageroo supervisor at $ManagerooCommit..."
& $VenvPython -m pip install --disable-pip-version-check --no-cache-dir --upgrade --force-reinstall $ManagerooSource "pytest>=8,<10"
if ($LASTEXITCODE -ne 0) { throw "The Manageroo supervisor installation failed (exit $LASTEXITCODE)." }
if (-not (Test-Path -LiteralPath $SupervisorExe -PathType Leaf)) {
    throw "Manageroo installed without creating clawpatch-supervise.exe."
}

$Launcher = Join-Path $BinDir "clawpatch-supervise.cmd"
$launcherLines = @(
    "@echo off",
    "setlocal",
    "set `"SUPERVISOR_VENV=$Venv`"",
    "set `"PATH=%SUPERVISOR_VENV%\Scripts;$NpmBin;$ProgramsBin;%PATH%`"",
    "`"%SUPERVISOR_VENV%\Scripts\clawpatch-supervise.exe`" %*",
    "exit /b %ERRORLEVEL%"
)
Set-Content -LiteralPath $Launcher -Value $launcherLines -Encoding ASCII

& $SupervisorExe --help | Out-Null
if ($LASTEXITCODE -ne 0) { throw "The installed supervisor failed its startup check." }

Write-Host "Checking Codex login..."
& $CodexExe login status
if ($LASTEXITCODE -ne 0) {
    Write-Host "Complete the one-time Codex browser login on this computer."
    & $CodexExe login
    if ($LASTEXITCODE -ne 0) { throw "Codex login did not complete." }
}

$ResolvedRepo = (Resolve-Path -LiteralPath $Repo).Path
& $GitExe -C $ResolvedRepo rev-parse --show-toplevel | Out-Null
if ($LASTEXITCODE -ne 0) { throw "The supplied Repo path is not a Git repository: $ResolvedRepo" }

$GitUserName = ([string](& $GitExe -C $ResolvedRepo config user.name)).Trim()
$GitUserEmail = ([string](& $GitExe -C $ResolvedRepo config user.email)).Trim()
if (-not $GitUserName -or -not $GitUserEmail) {
    throw "Git commit identity is missing. Set git config user.name and user.email, then rerun this installer."
}
& $GitExe -C $ResolvedRepo remote get-url origin | Out-Null
if ($LASTEXITCODE -ne 0) { throw "The repository has no origin remote, so the supervisor cannot push successful fixes." }

$ClawPatchState = Join-Path $ResolvedRepo ".clawpatch"
if (-not (Test-Path -LiteralPath $ClawPatchState -PathType Container)) {
    Write-Host "Initializing ClawPatch in the target repository..."
    Push-Location $ResolvedRepo
    try {
        & $ClawPatchExe init
        if ($LASTEXITCODE -ne 0) { throw "clawpatch init failed (exit $LASTEXITCODE)." }
    }
    finally {
        Pop-Location
    }
}

Push-Location $ResolvedRepo
try {
    & $ClawPatchExe doctor
    if ($LASTEXITCODE -ne 0) { throw "clawpatch doctor failed. Correct the reported problem and rerun this installer." }
}
finally {
    Pop-Location
}

$manifest = [ordered]@{
    installedAt = (Get-Date).ToString("o")
    managerooCommit = $ManagerooCommit
    codexVersion = $CodexVersion
    clawpatchVersion = $ClawPatchVersion
    launcher = $Launcher
    repository = $ResolvedRepo
}
$manifest | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $InstallRoot "installed.json") -Encoding UTF8

$escapedRepo = $ResolvedRepo.Replace('"', '`"')
$runCommand = 'Set-Location "{0}"; & "$env:USERPROFILE\.local\bin\clawpatch-supervise.cmd" --repo . --branch current --push each --fresh' -f $escapedRepo

Write-Host ""
Write-Host "INSTALLATION VERIFIED. The supervisor was installed but was not started." -ForegroundColor Green
Write-Host "Run it with this exact PowerShell command:"
Write-Host ""
Write-Host $runCommand -ForegroundColor Cyan
Write-Host "If an older supervisor already stopped with checkpoint-owned source changes, run the same command with --resume-stopped instead of --fresh." -ForegroundColor Yellow
