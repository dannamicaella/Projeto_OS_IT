[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot = Resolve-Path (Join-Path $scriptDir "..")
$pythonExe = Join-Path $repoRoot ".venv\Scripts\python.exe"
$envFile = Join-Path $repoRoot ".env"

function Write-Success {
    param([string]$Message)
    Write-Host "[OK] $Message" -ForegroundColor Green
}

function Fail {
    param([string]$Message)
    throw $Message
}

function Get-EnvMap {
    param([string]$Path)

    if (-not (Test-Path -LiteralPath $Path)) {
        Fail ".env file not found at $Path"
    }

    $map = @{}
    foreach ($rawLine in Get-Content -LiteralPath $Path) {
        $line = $rawLine.Trim()
        if (-not $line -or $line.StartsWith("#")) {
            continue
        }

        $separatorIndex = $line.IndexOf("=")
        if ($separatorIndex -lt 1) {
            continue
        }

        $key = $line.Substring(0, $separatorIndex).Trim()
        $value = $line.Substring($separatorIndex + 1).Trim()

        if (($value.StartsWith('"') -and $value.EndsWith('"')) -or ($value.StartsWith("'") -and $value.EndsWith("'"))) {
            $value = $value.Substring(1, $value.Length - 2)
        }

        $map[$key] = $value
    }

    return $map
}

if (-not (Test-Path -LiteralPath $pythonExe)) {
    Fail "Python virtual environment not found at $pythonExe"
}
Write-Success "Python virtual environment found."

$envMap = Get-EnvMap -Path $envFile
$requiredKeys = @(
    "PORT",
    "SECRET_KEY",
    "FIREBIRD_HOST",
    "FIREBIRD_PORT",
    "FIREBIRD_FILE",
    "FIREBIRD_USER",
    "FIREBIRD_PASSWORD"
)

$missingKeys = $requiredKeys | Where-Object { -not $envMap.ContainsKey($_) -or [string]::IsNullOrWhiteSpace($envMap[$_]) }
if ($missingKeys.Count -gt 0) {
    Fail "Missing required .env values: $($missingKeys -join ', ')"
}
Write-Success "Environment variables are configured in .env."

foreach ($key in $requiredKeys) {
    [Environment]::SetEnvironmentVariable($key, $envMap[$key], "Process")
}

& $pythonExe -c "import importlib.util, sys; required=('dotenv','sqlalchemy','fdb'); missing=[m for m in required if importlib.util.find_spec(m) is None]; sys.exit(0 if not missing else (print('Missing Python packages: ' + ', '.join(missing)) or 1))"
if ($LASTEXITCODE -ne 0) {
    Fail "Required Python packages are missing from the virtual environment."
}
Write-Success "Required Python packages are installed."

& $pythonExe -c "import os,fdb; conn=fdb.connect(host=os.environ['FIREBIRD_HOST'], port=int(os.environ['FIREBIRD_PORT']), database=os.environ['FIREBIRD_FILE'], user=os.environ['FIREBIRD_USER'], password=os.environ['FIREBIRD_PASSWORD'], charset='NONE'); conn.close()"
if ($LASTEXITCODE -ne 0) {
    Fail "Could not connect to the Firebird database using the current .env settings."
}
Write-Success "Firebird database connection succeeded."
