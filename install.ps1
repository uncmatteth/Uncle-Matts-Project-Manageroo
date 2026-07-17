[CmdletBinding()]
param(
    [switch]$SkipCodex,
    [switch]$InstallCodex,
    [switch]$InstallStack,
    [switch]$SkipStack,
    [switch]$SkipTests,
    [switch]$SkipSkillPack,
    [switch]$NoMusic,
    [switch]$NoAnimation,
    [string]$Prefix = "",
    [string]$BinDir = "",
    [ValidateSet("ask", "off", "caveman", "curse")]
    [string]$TokenMode = "ask",
    [ValidateSet("ask", "install", "skip")]
    [string]$SkillPack = "ask",
    [ValidateSet("ask", "skip", "install")]
    [string]$Stack = "ask",
    [ValidateSet("ask", "local", "official", "skip")]
    [string]$GBrainLane = "ask",
    [ValidateSet("ask", "pick", "add", "skip")]
    [string]$ProjectDiscovery = "ask",
    [ValidateSet("ask", "run", "skip")]
    [string]$StackDoctor = "ask",
    [ValidateSet("ask", "run", "skip")]
    [string]$ClawpatchCodexLogin = "ask",
    [ValidateSet("auto", "guide", "flatpak", "snap", "brew", "winget")]
    [string]$ObsidianMethod = "auto",
    [ValidateSet("codex", "cursor", "claude-code")]
    [string[]]$LoopLibraryAgent = @()
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
if ($InstallCodex) { $InstallArgs += "--install-codex" }
if ($InstallStack) { $InstallArgs += "--install-stack" }
if ($SkipStack) { $InstallArgs += "--skip-stack" }
if ($SkipTests) { $InstallArgs += "--skip-tests" }
if ($SkipSkillPack) { $InstallArgs += "--skip-skill-pack" }
if ($Prefix) { $InstallArgs += @("--prefix", $Prefix) }
if ($BinDir) { $InstallArgs += @("--bin-dir", $BinDir) }
if ($TokenMode) { $InstallArgs += @("--token-mode", $TokenMode) }
if ($SkillPack) { $InstallArgs += @("--skill-pack", $SkillPack) }
if ($Stack) { $InstallArgs += @("--stack", $Stack) }
if ($GBrainLane) { $InstallArgs += @("--gbrain-lane", $GBrainLane) }
if ($ProjectDiscovery) { $InstallArgs += @("--project-discovery", $ProjectDiscovery) }
if ($StackDoctor) { $InstallArgs += @("--stack-doctor", $StackDoctor) }
if ($ClawpatchCodexLogin) { $InstallArgs += @("--clawpatch-codex-login", $ClawpatchCodexLogin) }
if ($ObsidianMethod) { $InstallArgs += @("--obsidian-method", $ObsidianMethod) }
foreach ($Agent in $LoopLibraryAgent) { $InstallArgs += @("--loop-library-agent", $Agent) }
if ($NoMusic) { $InstallArgs += "--no-music" }
if ($NoAnimation) { $InstallArgs += "--no-animation" }

& $PythonExe @PythonPrefixArgs @InstallArgs
if ($LASTEXITCODE -ne 0) {
    throw "MANAGEROO installer failed with exit code $LASTEXITCODE"
}
