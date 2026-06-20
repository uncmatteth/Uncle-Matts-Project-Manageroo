& (Join-Path $PSScriptRoot "..\install.ps1") @args
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
