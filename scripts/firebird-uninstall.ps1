[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$commonScript = Join-Path $scriptDir "common.ps1"

if (-not (Test-Path -LiteralPath $commonScript)) {
    throw "Common script not found at $commonScript"
}

. $commonScript

$containerName = "projetoosit-firebird-helper"
$volumeName = "projetoosit-firebird-system"

function Assert-DockerReady {
    if (-not (Get-Command "docker" -ErrorAction SilentlyContinue)) {
        Fail "Docker CLI was not found. Install Docker Desktop and try again."
    }

    docker version | Out-Null
    if ($LASTEXITCODE -ne 0) {
        Fail "Docker is not available right now. Make sure Docker Desktop is running."
    }
}

function Get-ManagedByLabelValue {
    param([Parameter(Mandatory = $true)][string]$Name)

    $inspectJson = docker inspect $Name
    if ($LASTEXITCODE -ne 0) {
        Fail "Could not inspect existing container '$Name'."
    }

    $inspectData = $inspectJson | ConvertFrom-Json
    if (-not $inspectData -or $inspectData.Count -lt 1) {
        Fail "Container inspection for '$Name' returned no data."
    }

    return $inspectData[0].Config.Labels.'com.projetoosit.managed-by'
}

Write-Section "Firebird Docker Helper Uninstall"
Assert-DockerReady

$containerExists = docker ps -a --filter "name=^${containerName}$" --format "{{.Names}}"
if ($LASTEXITCODE -ne 0) {
    Fail "Could not query Docker containers."
}

if ($containerExists -contains $containerName) {
    $labelValue = Get-ManagedByLabelValue -Name $containerName
    if ($labelValue -ne "firebird-install.ps1") {
        Fail "Container '$containerName' exists but is not managed by this project script, so it was not removed."
    }

    Write-ActionBanner "Removendo container opcional do Firebird"
    docker rm -f $containerName | Out-Null
    if ($LASTEXITCODE -ne 0) {
        Fail "Could not remove container '$containerName'."
    }

    Write-Success "Container '$containerName' removido."
}
else {
    Write-Info "Container '$containerName' nao existe. Nada para remover."
}

$volumeExists = docker volume ls --filter "name=^${volumeName}$" --format "{{.Name}}"
if ($LASTEXITCODE -ne 0) {
    Fail "Could not query Docker volumes."
}

if ($volumeExists -contains $volumeName) {
    docker volume rm $volumeName | Out-Null
    if ($LASTEXITCODE -ne 0) {
        Fail "Could not remove Docker volume '$volumeName'."
    }

    Write-Success "Volume '$volumeName' removido."
}
else {
    Write-Info "Volume '$volumeName' nao existe. Nada para remover."
}

Write-Info "Se quiser voltar ao Firebird local ou da rede, ajuste o .env novamente depois do uninstall."
