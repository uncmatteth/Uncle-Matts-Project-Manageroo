[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$Repo
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

# Exact versions from the verified supervisor source.
$SupervisorCommit = "52fbcd1a2079f0e4b33a8bffb4f5ecad0c55ebda"
$SupervisorSource = "git+https://github.com/uncmatteth/clawpatch-supervise.git@$SupervisorCommit"
$CodexPackage = "@openai/codex@0.144.4"
$ClawPatchPackage = "clawpatch@0.7.2"

$InstallRoot = Join-Path $env:LOCALAPPDATA "ManagerooClawPatchSupervisor"
# Keep the existing environment path so upgrades do not create another venv.
$Venv = Join-Path $InstallRoot "venv-f59afab"
$BinDir = Join-Path $env:USERPROFILE ".local\bin"
$NpmBin = Join-Path $env:APPDATA "npm"
$ProgramsBin = Join-Path $env:LOCALAPPDATA "Programs\bin"
$script:NodeRuntime = $null

function Refresh-ProcessPath {
    $machinePath = [Environment]::GetEnvironmentVariable("Path", "Machine")
    $userPath = [Environment]::GetEnvironmentVariable("Path", "User")
    $parts = @(
        $script:BinDir,
        $script:NodeRuntime,
        $script:NpmBin,
        $script:ProgramsBin,
        $machinePath,
        $userPath
    ) |
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

function Resolve-NativeCommands([string[]]$Names, [string[]]$KnownPaths = @()) {
    $resolved = [System.Collections.Generic.List[string]]::new()
    foreach ($name in $Names) {
        $commands = @(Get-Command $name -CommandType Application -ErrorAction SilentlyContinue)
        foreach ($command in $commands) {
            if ($command.Source -and -not $resolved.Contains([string]$command.Source)) {
                $resolved.Add([string]$command.Source)
            }
        }
    }
    foreach ($candidate in $KnownPaths) {
        if ($candidate -and (Test-Path -LiteralPath $candidate -PathType Leaf)) {
            $path = (Resolve-Path -LiteralPath $candidate).Path
            if (-not $resolved.Contains([string]$path)) { $resolved.Add([string]$path) }
        }
    }
    return @($resolved)
}

function Resolve-NativeCommand([string[]]$Names, [string[]]$KnownPaths = @()) {
    $commands = @(Resolve-NativeCommands $Names $KnownPaths)
    if ($commands.Count -gt 0) { return [string]$commands[0] }
    return $null
}

function Find-NodeKnownPaths {
    $paths = [System.Collections.Generic.List[string]]::new()
    foreach ($candidate in @(
        (Join-Path $env:ProgramFiles "nodejs\node.exe"),
        (Join-Path $env:LOCALAPPDATA "Programs\nodejs\node.exe")
    )) {
        if ($candidate -and (Test-Path -LiteralPath $candidate -PathType Leaf)) {
            $paths.Add((Resolve-Path -LiteralPath $candidate).Path)
        }
    }
    $wingetRoot = Join-Path $env:LOCALAPPDATA "Microsoft\WinGet\Packages"
    if (Test-Path -LiteralPath $wingetRoot -PathType Container) {
        Get-ChildItem -LiteralPath $wingetRoot -Directory -Filter "OpenJS.NodeJS.LTS_*" -ErrorAction SilentlyContinue |
            ForEach-Object {
                Get-ChildItem -LiteralPath $_.FullName -File -Filter "node.exe" -Recurse -ErrorAction SilentlyContinue |
                    ForEach-Object {
                        if (-not $paths.Contains($_.FullName)) { $paths.Add($_.FullName) }
                    }
            }
    }
    return @($paths)
}

function Select-CompatibleNode {
    $candidates = @(Resolve-NativeCommands @("node.exe", "node") @(Find-NodeKnownPaths))
    $compatible = @()
    foreach ($path in $candidates) {
        try {
            $versionText = [string](& $path -p "process.versions.node")
            if ($LASTEXITCODE -ne 0) { continue }
            $version = [version]$versionText.Trim()
            $candidate = [pscustomobject]@{
                Path = [string]$path
                Version = $version
                Major = $version.Major
            }
            if ($candidate.Major -ge 22) { $compatible += $candidate }
        }
        catch {
            continue
        }
    }
    return $compatible | Sort-Object -Property Version -Descending | Select-Object -First 1
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

$NodeSelection = Select-CompatibleNode
if (-not $NodeSelection) {
    Install-WingetPackage "OpenJS.NodeJS.LTS" "Node.js LTS"
    $NodeSelection = Select-CompatibleNode
}
if (-not $NodeSelection) {
    throw "ClawPatch requires Node.js 22 or newer. Install it, open a new PowerShell window, and rerun this installer."
}
$NodeExe = [string]$NodeSelection.Path
$NodeRuntime = Split-Path -Parent $NodeExe
$script:NodeRuntime = $NodeRuntime
Refresh-ProcessPath

$NpmBesideNode = Join-Path (Split-Path -Parent $NodeExe) "npm.cmd"
$NpmExe = Resolve-NativeCommand @() @($NpmBesideNode)
if (-not $NpmExe) { $NpmExe = Resolve-NativeCommand @("npm.cmd") }
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
Write-Host "Installing standalone clawpatch-supervise at $SupervisorCommit..."
& $VenvPython -m pip install --disable-pip-version-check --no-cache-dir --upgrade --force-reinstall $SupervisorSource
if ($LASTEXITCODE -ne 0) { throw "The clawpatch-supervise installation failed (exit $LASTEXITCODE)." }
if (-not (Test-Path -LiteralPath $SupervisorExe -PathType Leaf)) {
    throw "clawpatch-supervise installed without creating clawpatch-supervise.exe."
}

$Launcher = Join-Path $BinDir "clawpatch-supervise.cmd"
$launcherLines = @(
    "@echo off",
    "setlocal",
    "set `"SUPERVISOR_VENV=$Venv`"",
    "set `"NODE_RUNTIME=$NodeRuntime`"",
    "if not exist `"$NodeExe`" (",
    "  echo ClawPatch supervisor Node runtime is missing: $NodeExe 1>&2",
    "  exit /b 1",
    ")",
    "set `"PYTHONUTF8=1`"",
    "set `"PYTHONIOENCODING=utf-8`"",
    "set `"PATH=%SUPERVISOR_VENV%\Scripts;%NODE_RUNTIME%;$NpmBin;$ProgramsBin;%PATH%`"",
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
    supervisorCommit = $SupervisorCommit
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
