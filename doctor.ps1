[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"

$target = Join-Path $PSScriptRoot "scripts\doctor.ps1"

if (-not (Test-Path -LiteralPath $target)) {
    throw "Script not found at $target"
}

& $target
exit $LASTEXITCODE
