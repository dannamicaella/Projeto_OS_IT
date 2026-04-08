[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot = Resolve-Path (Join-Path $scriptDir "..")
$doctorScript = Join-Path $scriptDir "doctor.ps1"
$pythonExe = Join-Path $repoRoot ".venv\Scripts\python.exe"
$mainFile = Join-Path $repoRoot "main.py"

if (-not (Test-Path -LiteralPath $doctorScript)) {
    throw "Doctor script not found at $doctorScript"
}

if (-not (Test-Path -LiteralPath $pythonExe)) {
    throw "Python virtual environment not found at $pythonExe"
}

Push-Location $repoRoot
try {
    & $doctorScript
    if ($LASTEXITCODE -ne 0) {
        throw "Health check failed."
    }

    Write-Host "Starting application with $pythonExe $mainFile" -ForegroundColor Cyan
    & $pythonExe $mainFile
    exit $LASTEXITCODE
}
finally {
    Pop-Location
}
