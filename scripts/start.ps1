[CmdletBinding()]
param(
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$PassthroughArgs = @()
)

$ErrorActionPreference = "Stop"

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot = Resolve-Path (Join-Path $scriptDir "..")
$doctorScript = Join-Path $scriptDir "doctor.ps1"
$commonScript = Join-Path $scriptDir "common.ps1"
$pythonExe = Join-Path $repoRoot ".venv\Scripts\python.exe"
$envFile = Join-Path $repoRoot ".env"
$logsDir = Join-Path $repoRoot "logs"
$servyInstallMarker = Join-Path $logsDir ".servy-installed-by-projetoosit"
$serviceName = "ProjetoOSIT"
$displayName = "Projeto OS IT"
$serviceDescription = "Projeto OS IT FastAPI application managed by Servy."

if (-not (Test-Path -LiteralPath $doctorScript)) {
    throw "Doctor script not found at $doctorScript"
}

if (-not (Test-Path -LiteralPath $commonScript)) {
    throw "Common script not found at $commonScript"
}

if (-not (Test-Path -LiteralPath $pythonExe)) {
    throw "Python virtual environment not found at $pythonExe"
}

. $commonScript

Invoke-SelfElevated -ScriptPath $PSCommandPath -ArgumentList $PassthroughArgs -Action "configure and start the Projeto OS IT Windows service"

Push-Location $repoRoot
try {
    $servyCliBeforeDoctor = Resolve-ServyCliPath

    & $doctorScript -InstallServy
    if ($LASTEXITCODE -ne 0) {
        throw "Health check failed."
    }

    Assert-IsAdministrator "install and start the Windows service"

    $servyCli = Resolve-ServyCliPath
    if (-not $servyCli) {
        throw "servy-cli.exe was not found after doctor completed."
    }

    if ((-not $servyCliBeforeDoctor) -and (-not (Test-Path -LiteralPath $servyInstallMarker))) {
        Set-Content -LiteralPath $servyInstallMarker -Value "installed-by=start.ps1" -Encoding ASCII
    }

    $envMap = Get-EnvMap -Path $envFile
    $port = $envMap["PORT"]

    if (-not (Test-Path -LiteralPath $logsDir)) {
        New-Item -ItemType Directory -Path $logsDir | Out-Null
    }

    & $pythonExe -c "import uvicorn" | Out-Null
    if ($LASTEXITCODE -ne 0) {
        throw "uvicorn is missing from the virtual environment."
    }

    $stdoutLog = Join-Path $logsDir "servy-stdout.log"
    $stderrLog = Join-Path $logsDir "servy-stderr.log"
    $serviceExists = Get-Service -Name $serviceName -ErrorAction SilentlyContinue

    Write-Section "Configuring Servy service"

    if ($serviceExists) {
        Write-Info "Refreshing existing service '$serviceName' so the configuration stays in sync."
        & $servyCli stop "--name=$serviceName" --quiet
        & $servyCli uninstall "--name=$serviceName" --quiet
        if ($LASTEXITCODE -ne 0) {
            throw "Could not uninstall the existing Servy service '$serviceName'."
        }
    }

    $installArgs = @(
        "install",
        "--quiet",
        "--name=$serviceName",
        "--displayName=$displayName",
        "--description=$serviceDescription",
        "--path=$pythonExe",
        "--startupDir=$repoRoot",
        "--params=-m uvicorn main:app --host=0.0.0.0 --port=$port",
        "--startupType=Automatic",
        "--priority=Normal",
        "--stdout=$stdoutLog",
        "--stderr=$stderrLog",
        "--enableSizeRotation",
        "--rotationSize=10",
        "--enableHealth",
        "--heartbeatInterval=30",
        "--maxFailedChecks=3",
        "--recoveryAction=RestartProcess",
        "--maxRestartAttempts=999999"
    )

    & $servyCli @installArgs
    if ($LASTEXITCODE -ne 0) {
        throw "Servy failed to install the '$serviceName' service."
    }

    Write-Success "Servy service installed."

    & $servyCli start "--name=$serviceName" --quiet
    if ($LASTEXITCODE -ne 0) {
        throw "Servy failed to start the '$serviceName' service."
    }

    $service = Get-Service -Name $serviceName -ErrorAction Stop
    Write-Success "Service '$($service.Name)' is $($service.Status)."
    Write-Info "Logs: $stdoutLog"
    Write-Info "Logs: $stderrLog"
}
finally {
    Pop-Location
}
