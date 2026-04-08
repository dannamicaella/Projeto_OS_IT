[CmdletBinding()]
param(
    [string]$FdbPath
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot = Resolve-Path (Join-Path $scriptDir "..")
$commonScript = Join-Path $scriptDir "common.ps1"
$envFile = Join-Path $repoRoot ".env"

if (-not (Test-Path -LiteralPath $commonScript)) {
    throw "Common script not found at $commonScript"
}

. $commonScript

$containerName = "projetoosit-firebird-helper"
$volumeName = "projetoosit-firebird-system"
$imageName = "jacobalberty/firebird:2.5-ss"
$managedLabel = "com.projetoosit.managed-by=firebird-install.ps1"
$roleLabel = "com.projetoosit.role=optional-firebird-helper"

function Assert-DockerReady {
    if (-not (Get-Command "docker" -ErrorAction SilentlyContinue)) {
        Fail "Docker CLI was not found. Install Docker Desktop and try again."
    }

    docker version | Out-Null
    if ($LASTEXITCODE -ne 0) {
        Fail "Docker is not available right now. Make sure Docker Desktop is running."
    }
}

function Resolve-ValidFdbPath {
    param([string]$CandidatePath)

    while ($true) {
        $currentCandidate = $CandidatePath
        if ([string]::IsNullOrWhiteSpace($currentCandidate)) {
            Write-Host ""
            $currentCandidate = Read-Host "Digite o caminho completo do arquivo .fdb"
        }

        if ([string]::IsNullOrWhiteSpace($currentCandidate)) {
            Write-WarningBanner "Informe um caminho para um arquivo .fdb."
            $CandidatePath = $null
            continue
        }

        $normalized = $currentCandidate.Trim().Trim('"')
        if (-not (Test-Path -LiteralPath $normalized -PathType Leaf)) {
            Write-WarningBanner "Arquivo nao encontrado: $normalized"
            $CandidatePath = $null
            continue
        }

        $item = Get-Item -LiteralPath $normalized -ErrorAction Stop
        if ($item.Extension -ine ".fdb") {
            Write-WarningBanner "O arquivo precisa ter extensao .fdb."
            $CandidatePath = $null
            continue
        }

        return $item.FullName
    }
}

function Set-OrAddEnvValue {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$Key,
        [Parameter(Mandatory = $true)][string]$Value
    )

    $content = @()
    if (Test-Path -LiteralPath $Path) {
        $content = Get-Content -LiteralPath $Path
    }

    $updated = $false
    for ($i = 0; $i -lt $content.Count; $i++) {
        if ($content[$i] -match "^\s*#\s*$([regex]::Escape($Key))\s*=") {
            $content[$i] = "$Key=$Value"
            $updated = $true
            break
        }

        if ($content[$i] -match "^\s*$([regex]::Escape($Key))\s*=") {
            $content[$i] = "$Key=$Value"
            $updated = $true
            break
        }
    }

    if (-not $updated) {
        $content += "$Key=$Value"
    }

    Set-Content -LiteralPath $Path -Value $content -Encoding ASCII
}

function Test-ManagedContainerExists {
    $existingName = docker ps -a --filter "name=^${containerName}$" --format "{{.Names}}"
    return $LASTEXITCODE -eq 0 -and ($existingName -contains $containerName)
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

function Remove-ManagedContainerIfPresent {
    if (-not (Test-ManagedContainerExists)) {
        return
    }

    $labelValue = Get-ManagedByLabelValue -Name $containerName
    if ($labelValue -ne "firebird-install.ps1") {
        Fail "A container named '$containerName' already exists but is not managed by this script. Remove or rename it manually first."
    }

    Write-ActionBanner "Recriando o helper opcional do Firebird"
    docker rm -f $containerName | Out-Null
    if ($LASTEXITCODE -ne 0) {
        Fail "Could not remove the existing managed container '$containerName'."
    }
}

Write-Section "Firebird Docker Helper Install"

Assert-DockerReady

$resolvedFdbPath = Resolve-ValidFdbPath -CandidatePath $FdbPath
$fdbFile = Get-Item -LiteralPath $resolvedFdbPath -ErrorAction Stop
$fdbDirectory = $fdbFile.Directory.FullName
$containerDatabasePath = "/data/$($fdbFile.Name)"

Write-Success "Arquivo Firebird valido encontrado em '$resolvedFdbPath'."

$envMap = @{}
if (Test-Path -LiteralPath $envFile) {
    $envMap = Get-EnvMap -Path $envFile
}

$firebirdPassword = $envMap["FIREBIRD_PASSWORD"]
if ([string]::IsNullOrWhiteSpace($firebirdPassword)) {
    $firebirdPassword = "masterkey"
}

$hostPort = $envMap["FIREBIRD_PORT"]
if ([string]::IsNullOrWhiteSpace($hostPort)) {
    $hostPort = "3050"
}

if ($hostPort -notmatch '^\d+$') {
    Fail "FIREBIRD_PORT in .env is invalid: '$hostPort'"
}

Remove-ManagedContainerIfPresent

$volumeExists = docker volume ls --filter "name=^${volumeName}$" --format "{{.Name}}"
if ($LASTEXITCODE -ne 0) {
    Fail "Could not query Docker volumes."
}

if (-not ($volumeExists -contains $volumeName)) {
    docker volume create $volumeName | Out-Null
    if ($LASTEXITCODE -ne 0) {
        Fail "Could not create Docker volume '$volumeName'."
    }
}

Write-ActionBanner "Subindo container Docker do Firebird"

$dockerArgs = @(
    "run",
    "-d",
    "--name", $containerName,
    "--hostname", $containerName,
    "--restart", "unless-stopped",
    "--label", $managedLabel,
    "--label", $roleLabel,
    "-e", "ISC_PASSWORD=$firebirdPassword",
    "-p", "${hostPort}:3050",
    "-v", "${fdbDirectory}:/data",
    "-v", "${volumeName}:/firebird",
    $imageName
)

docker @dockerArgs | Out-Null
if ($LASTEXITCODE -ne 0) {
    Fail "Could not create the Firebird helper container."
}

Set-OrAddEnvValue -Path $envFile -Key "FIREBIRD_HOST" -Value "localhost"
Set-OrAddEnvValue -Path $envFile -Key "FIREBIRD_PORT" -Value $hostPort
Set-OrAddEnvValue -Path $envFile -Key "FIREBIRD_FILE" -Value $containerDatabasePath
Set-OrAddEnvValue -Path $envFile -Key "FIREBIRD_PASSWORD" -Value $firebirdPassword

Write-Success "Container '$containerName' criado com restart policy 'unless-stopped'."
Write-Success "Volume '$volumeName' configurado para os arquivos internos do Firebird."
Write-Success ".env atualizado para usar FIREBIRD_FILE=$containerDatabasePath"
Write-Info "Pasta montada no container: $fdbDirectory -> /data"
Write-Info "Para remover depois, execute .\\scripts\\firebird-uninstall.ps1"
