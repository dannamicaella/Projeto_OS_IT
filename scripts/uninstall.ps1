[CmdletBinding()]
param(
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$PassthroughArgs = @()
)

$ErrorActionPreference = "Stop"

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot = Resolve-Path (Join-Path $scriptDir "..")
$commonScript = Join-Path $scriptDir "common.ps1"
$logsDir = Join-Path $repoRoot "logs"
$servyInstallMarker = Join-Path $logsDir ".servy-installed-by-projetoosit"
$serviceName = "ProjetoOSIT"

if (-not (Test-Path -LiteralPath $commonScript)) {
    throw "Common script not found at $commonScript"
}

. $commonScript

Invoke-SelfElevated -ScriptPath $PSCommandPath -ArgumentList $PassthroughArgs -Action "remove the Projeto OS IT Windows service"

Write-Section "Uninstall Projeto OS IT"
Assert-IsAdministrator "remove the Windows service and uninstall Servy"

Push-Location $repoRoot
try {
    $servyCli = Resolve-ServyCliPath
    $service = Get-Service -Name $serviceName -ErrorAction SilentlyContinue
    $port = $null

    try {
        $envMap = Get-EnvMap -Path (Join-Path $repoRoot ".env")
        $configuredPort = $envMap["PORT"]
        if (-not [string]::IsNullOrWhiteSpace($configuredPort)) {
            $port = [int]$configuredPort
        }
    }
    catch {
        Write-Info "Could not resolve PORT from .env during uninstall: $($_.Exception.Message)"
    }

    if ($service) {
        Write-ActionBanner "Removing Windows service '$serviceName'"
        Stop-ServiceCompletely -ServiceName $serviceName -ServyCliPath $servyCli

        if ($servyCli) {
            & $servyCli uninstall "--name=$serviceName" --quiet
            if ($LASTEXITCODE -ne 0) {
                throw "Servy failed to uninstall the '$serviceName' service."
            }
        }
        else {
            Write-Info "servy-cli.exe was not found. Falling back to Service Control Manager removal."

            sc.exe delete $serviceName | Out-Null
            if ($LASTEXITCODE -ne 0) {
                throw "Fallback service removal failed for '$serviceName'."
            }
        }

        Start-Sleep -Seconds 2
        if (Get-Service -Name $serviceName -ErrorAction SilentlyContinue) {
            throw "The '$serviceName' service is still registered."
        }

        Write-Success "Windows service '$serviceName' removed."
    }
    else {
        Write-Info "Windows service '$serviceName' was not found. Nothing to remove."
    }

    if ($null -ne $port) {
        Stop-ProcessesUsingPort -Port $port
    }
    else {
        Write-Info "PORT was not available in .env, so no port cleanup was attempted."
    }

    $servyCli = Resolve-ServyCliPath
    if ($servyCli -and (Test-Path -LiteralPath $servyInstallMarker)) {
        Uninstall-ServyPackage

        if (-not (Resolve-ServyCliPath) -and (Test-Path -LiteralPath $servyInstallMarker)) {
            Remove-Item -LiteralPath $servyInstallMarker -Force
        }
    }
    else {
        if ($servyCli) {
            Write-Info "Servy CLI is still present, but it was not marked as installed by this project, so it was left in place."
        }
        else {
            Write-Info "Servy CLI is already absent."
        }
    }

    if (Test-Path -LiteralPath $logsDir) {
        Remove-Item -LiteralPath $logsDir -Recurse -Force
        Write-Success "Removed logs directory '$logsDir'."
    }
    else {
        Write-Info "Logs directory was not found. Nothing to clean up."
    }

    if ((Test-Path -LiteralPath $servyInstallMarker) -and (-not (Resolve-ServyCliPath))) {
        Remove-Item -LiteralPath $servyInstallMarker -Force
    }
}
finally {
    Pop-Location
}
