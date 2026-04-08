[CmdletBinding()]
param(
    [switch]$InstallServy
)

$ErrorActionPreference = "Stop"

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot = Resolve-Path (Join-Path $scriptDir "..")
$venvDir = Join-Path $repoRoot ".venv"
$pythonExe = Join-Path $repoRoot ".venv\Scripts\python.exe"
$envFile = Join-Path $repoRoot ".env"
$commonScript = Join-Path $scriptDir "common.ps1"
$requirementsFile = Join-Path $repoRoot "requirements.txt"
$pyprojectFile = Join-Path $repoRoot "pyproject.toml"

if (-not (Test-Path -LiteralPath $commonScript)) {
    throw "Common script not found at $commonScript"
}

. $commonScript

function Resolve-SystemPython {
    $pyLauncher = Get-Command "py.exe" -ErrorAction SilentlyContinue
    if ($pyLauncher) {
        return @{
            FilePath = $pyLauncher.Source
            Arguments = @("-3")
            DisplayName = "py -3"
        }
    }

    $pythonCommand = Get-Command "python.exe" -ErrorAction SilentlyContinue
    if ($pythonCommand) {
        return @{
            FilePath = $pythonCommand.Source
            Arguments = @()
            DisplayName = $pythonCommand.Source
        }
    }

    Fail "Python was not found on PATH. Install Python 3 and rerun this script."
}

function Ensure-Venv {
    if (Test-Path -LiteralPath $pythonExe) {
        Write-Success "Python virtual environment found."
        return $false
    }

    $systemPython = Resolve-SystemPython
    Write-Info "Python virtual environment not found. Creating .venv with $($systemPython.DisplayName)."

    & $systemPython.FilePath @($systemPython.Arguments + @("-m", "venv", $venvDir))
    if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $pythonExe)) {
        Fail "Could not create the Python virtual environment at $venvDir"
    }

    Write-Success "Python virtual environment created at $venvDir."
    return $true
}

function Install-PythonDependencies {
    $installArgs = @()
    if (Test-Path -LiteralPath $requirementsFile) {
        $installArgs = @("-m", "pip", "install", "-r", $requirementsFile)
    }
    elseif (Test-Path -LiteralPath $pyprojectFile) {
        $installArgs = @("-m", "pip", "install", $repoRoot)
    }
    else {
        Fail "No Python dependency manifest was found. Expected requirements.txt or pyproject.toml in $repoRoot"
    }

    Write-Info "Ensuring pip is available in the virtual environment."
    & $pythonExe -m ensurepip --upgrade
    if ($LASTEXITCODE -ne 0) {
        Fail "Could not prepare pip inside the virtual environment."
    }

    Write-Info "Installing Python dependencies into .venv."
    & $pythonExe @installArgs
    if ($LASTEXITCODE -ne 0) {
        Fail "Could not install the Python dependencies into the virtual environment."
    }

    Write-Success "Python dependencies are installed in .venv."
}

Write-Section "Projeto OS IT Doctor"

$venvWasCreated = Ensure-Venv
if ($venvWasCreated) {
    Install-PythonDependencies
}
else {
    Write-Info "Skipping Python dependency installation because .venv already exists."
}

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

$missingKeys = @($requiredKeys | Where-Object { -not $envMap.ContainsKey($_) -or [string]::IsNullOrWhiteSpace($envMap[$_]) })
if ($missingKeys.Count -gt 0) {
    Fail "Missing required .env values: $($missingKeys -join ', ')"
}
Write-Success "Environment variables are configured in .env."

foreach ($key in $requiredKeys) {
    [Environment]::SetEnvironmentVariable($key, $envMap[$key], "Process")
}

& $pythonExe -c "import importlib.util, sys; required=('dotenv','fastapi','sqlalchemy','fdb','uvicorn','jinja2','itsdangerous'); missing=[m for m in required if importlib.util.find_spec(m) is None]; sys.exit(0 if not missing else (print('Missing Python packages: ' + ', '.join(missing)) or 1))"
if ($LASTEXITCODE -ne 0) {
    Fail "Required Python packages are missing from the virtual environment."
}
Write-Success "Required Python packages are installed."

& $pythonExe -c "import os,fdb; conn=fdb.connect(host=os.environ['FIREBIRD_HOST'], port=int(os.environ['FIREBIRD_PORT']), database=os.environ['FIREBIRD_FILE'], user=os.environ['FIREBIRD_USER'], password=os.environ['FIREBIRD_PASSWORD'], charset='NONE'); conn.close()"
if ($LASTEXITCODE -ne 0) {
    Fail "Could not connect to the Firebird database using the current .env settings."
}
Write-Success "Firebird database connection succeeded."

if ($InstallServy) {
    $servyCli = Ensure-ServyInstalled
    Write-Success "Servy is ready: $servyCli"
}
else {
    $servyCli = Resolve-ServyCliPath
    if ($servyCli) {
        Write-Success "Servy CLI found at $servyCli"
        Write-Success "Servy is ready: $servyCli"
    }
    else {
        Fail "Servy CLI is not installed. Run .\\start.ps1 to install it automatically or install Servy manually."
    }
}
