[CmdletBinding()]
param()

Set-StrictMode -Version Latest

function Write-Section {
    param([string]$Message)
    Write-Host ""
    Write-Host ("=" * 72) -ForegroundColor DarkCyan
    Write-Host $Message -ForegroundColor Cyan
    Write-Host ("=" * 72) -ForegroundColor DarkCyan
}

function Write-Success {
    param([string]$Message)
    Write-Host "[OK] $Message" -ForegroundColor Green
}

function Write-Info {
    param([string]$Message)
    Write-Host "[INFO] $Message" -ForegroundColor Gray
}

function Write-WarningBanner {
    param([string]$Message)
    Write-Host ""
    Write-Host $Message -ForegroundColor Yellow
}

function Write-ActionBanner {
    param([string]$Message)
    Write-Host ""
    Write-Host ("#" * 72) -ForegroundColor Magenta
    Write-Host $Message -ForegroundColor Magenta
    Write-Host ("#" * 72) -ForegroundColor Magenta
}

function Fail {
    param([string]$Message)
    throw $Message
}

function Get-EnvMap {
    param([Parameter(Mandatory = $true)][string]$Path)

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

function Test-IsAdministrator {
    $principal = New-Object Security.Principal.WindowsPrincipal([Security.Principal.WindowsIdentity]::GetCurrent())
    return $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

function Assert-IsAdministrator {
    param([string]$Action)

    if (-not (Test-IsAdministrator)) {
        Fail "Administrator privileges are required to $Action. Re-run this script from an elevated PowerShell window."
    }
}

function Get-PowerShellHostPath {
    $currentProcess = Get-Process -Id $PID -ErrorAction Stop
    if (-not [string]::IsNullOrWhiteSpace($currentProcess.Path)) {
        return $currentProcess.Path
    }

    $pwshPath = Join-Path $PSHOME "pwsh.exe"
    if (Test-Path -LiteralPath $pwshPath) {
        return $pwshPath
    }

    $powershellPath = Join-Path $PSHOME "powershell.exe"
    if (Test-Path -LiteralPath $powershellPath) {
        return $powershellPath
    }

    Fail "Could not resolve the current PowerShell executable path."
}

function ConvertTo-ProcessArgumentString {
    param([string]$Value)

    if ($null -eq $Value) {
        return '""'
    }

    if ($Value -eq "") {
        return '""'
    }

    if ($Value -notmatch '[\s"]') {
        return $Value
    }

    $escaped = $Value -replace '(\\*)"', '$1$1\"'
    $escaped = $escaped -replace '(\\+)$', '$1$1'
    return '"' + $escaped + '"'
}

function Invoke-SelfElevated {
    param(
        [Parameter(Mandatory = $true)][string]$ScriptPath,
        [string[]]$ArgumentList = @(),
        [Parameter(Mandatory = $true)][string]$Action
    )

    if (Test-IsAdministrator) {
        return
    }

    $shellPath = Get-PowerShellHostPath
    $processArguments = @(
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        $ScriptPath
    ) + $ArgumentList

    $argumentString = ($processArguments | ForEach-Object { ConvertTo-ProcessArgumentString -Value $_ }) -join " "

    Write-WarningBanner "Administrator privileges are required to $Action. Accept the Windows UAC prompt to continue."

    try {
        $process = Start-Process -FilePath $shellPath -ArgumentList $argumentString -Verb RunAs -WorkingDirectory (Get-Location) -Wait -PassThru -ErrorAction Stop
        exit $process.ExitCode
    }
    catch {
        Fail "Could not obtain administrator privileges for '$Action'. $($_.Exception.Message)"
    }
}

function Invoke-ElevatedExternalStep {
    param(
        [Parameter(Mandatory = $true)][string]$FilePath,
        [Parameter(Mandatory = $true)][string[]]$Arguments
    )

    $argumentString = ($Arguments | ForEach-Object { ConvertTo-ProcessArgumentString -Value $_ }) -join " "

    Write-WarningBanner "Administrator privileges are required to continue. Accept the Windows UAC prompt if it appears."

    try {
        $process = Start-Process -FilePath $FilePath -ArgumentList $argumentString -Verb RunAs -WorkingDirectory (Get-Location) -Wait -PassThru -ErrorAction Stop
        if ($process.ExitCode -ne 0) {
            Fail "Command failed: $FilePath $($Arguments -join ' ')"
        }
    }
    catch {
        Fail "Could not obtain administrator privileges to run '$FilePath'. $($_.Exception.Message)"
    }
}

function Refresh-ProcessPath {
    $machinePath = [Environment]::GetEnvironmentVariable("Path", "Machine")
    $userPath = [Environment]::GetEnvironmentVariable("Path", "User")
    $env:Path = ($machinePath, $userPath | Where-Object { -not [string]::IsNullOrWhiteSpace($_) }) -join ";"
}

function Resolve-ServyCliPath {
    $command = Get-Command "servy-cli.exe" -ErrorAction SilentlyContinue
    if (-not $command) {
        $command = Get-Command "servy-cli" -ErrorAction SilentlyContinue
    }

    if ($command) {
        return $command.Source
    }

    $knownPaths = @(
        "C:\Program Files\Servy\servy-cli.exe",
        "C:\Program Files (x86)\Servy\servy-cli.exe"
    )

    foreach ($candidate in $knownPaths) {
        if (Test-Path -LiteralPath $candidate) {
            return $candidate
        }
    }

    return $null
}

function Get-ServyInstallStrategy {
    if (Get-Command "winget.exe" -ErrorAction SilentlyContinue) {
        return @{
            Name = "winget"
            Steps = @(
                @{ FilePath = "winget.exe"; Arguments = @("install", "--id", "aelassas.Servy", "--exact", "--accept-package-agreements", "--accept-source-agreements") }
            )
        }
    }

    if (Get-Command "choco.exe" -ErrorAction SilentlyContinue) {
        return @{
            Name = "choco"
            Steps = @(
                @{ FilePath = "choco.exe"; Arguments = @("install", "-y", "servy") }
            )
        }
    }

    if (Get-Command "scoop.cmd" -ErrorAction SilentlyContinue) {
        return @{
            Name = "scoop"
            Steps = @(
                @{ FilePath = "scoop.cmd"; Arguments = @("bucket", "add", "extras") ; IgnoreFailure = $true },
                @{ FilePath = "scoop.cmd"; Arguments = @("install", "servy") }
            )
        }
    }

    if (Get-Command "scoop.exe" -ErrorAction SilentlyContinue) {
        return @{
            Name = "scoop"
            Steps = @(
                @{ FilePath = "scoop.exe"; Arguments = @("bucket", "add", "extras"); IgnoreFailure = $true },
                @{ FilePath = "scoop.exe"; Arguments = @("install", "servy") }
            )
        }
    }

    return $null
}

function Get-ServyInstallCommandLines {
    param($Strategy)

    if (-not $Strategy) {
        return @()
    }

    $commands = @()
    foreach ($step in $Strategy.Steps) {
        $parts = @($step.FilePath) + $step.Arguments
        $commands += ($parts | ForEach-Object {
            if ($_ -match '\s') {
                '"' + $_ + '"'
            }
            else {
                $_
            }
        }) -join ' '
    }

    return $commands
}

function Write-ServyInstallHelp {
    param($Strategy)

    $commands = @(Get-ServyInstallCommandLines -Strategy $Strategy)
    if ($commands.Count -eq 0) {
        Write-Info "Install Servy manually from https://github.com/aelassas/servy/releases/latest"
        return
    }

    Write-Host ""
    Write-Host "Run this in an elevated PowerShell window to install Servy:" -ForegroundColor Yellow
    foreach ($command in $commands) {
        Write-Host "  $command" -ForegroundColor Cyan
    }
}

function Get-ServyUninstallStrategies {
    $strategies = @()

    if (Get-Command "winget.exe" -ErrorAction SilentlyContinue) {
        $strategies += @{
            Name = "winget"
            Steps = @(
                @{ FilePath = "winget.exe"; Arguments = @("uninstall", "--id", "aelassas.Servy", "--exact", "--accept-source-agreements") }
            )
        }
    }

    if (Get-Command "choco.exe" -ErrorAction SilentlyContinue) {
        $strategies += @{
            Name = "choco"
            Steps = @(
                @{ FilePath = "choco.exe"; Arguments = @("uninstall", "-y", "servy") }
            )
        }
    }

    if (Get-Command "scoop.cmd" -ErrorAction SilentlyContinue) {
        $strategies += @{
            Name = "scoop"
            Steps = @(
                @{ FilePath = "scoop.cmd"; Arguments = @("uninstall", "servy") }
            )
        }
    }

    if (Get-Command "scoop.exe" -ErrorAction SilentlyContinue) {
        $strategies += @{
            Name = "scoop"
            Steps = @(
                @{ FilePath = "scoop.exe"; Arguments = @("uninstall", "servy") }
            )
        }
    }

    return $strategies
}

function Invoke-ExternalStep {
    param(
        [Parameter(Mandatory = $true)][string]$FilePath,
        [Parameter(Mandatory = $true)][string[]]$Arguments,
        [switch]$IgnoreFailure
    )

    & $FilePath @Arguments
    if ($LASTEXITCODE -ne 0 -and -not $IgnoreFailure) {
        Fail "Command failed: $FilePath $($Arguments -join ' ')"
    }
}

function Invoke-ManagedExternalStep {
    param(
        [Parameter(Mandatory = $true)][string]$FilePath,
        [Parameter(Mandatory = $true)][string[]]$Arguments,
        [switch]$IgnoreFailure,
        [switch]$RequireAdministrator
    )

    if ($RequireAdministrator -and -not (Test-IsAdministrator)) {
        try {
            Invoke-ElevatedExternalStep -FilePath $FilePath -Arguments $Arguments
        }
        catch {
            if (-not $IgnoreFailure) {
                throw
            }
        }
        return
    }

    Invoke-ExternalStep -FilePath $FilePath -Arguments $Arguments -IgnoreFailure:$IgnoreFailure
}

function Ensure-ServyInstalled {
    $servyCli = Resolve-ServyCliPath
    if ($servyCli) {
        Write-Success "Servy CLI found at $servyCli"
        return $servyCli
    }

    $strategy = Get-ServyInstallStrategy
    if (-not $strategy) {
        Write-ServyInstallHelp -Strategy $null
        Fail "Servy CLI is not installed and no supported package manager was found. Install Servy manually from https://github.com/aelassas/servy/releases/latest"
    }

    Write-WarningBanner "Servy CLI is not installed. This project now uses Servy to keep the app running as a Windows service."
    Write-ServyInstallHelp -Strategy $strategy

    if (-not [Environment]::UserInteractive) {
        Fail "Servy CLI is not installed and this shell is non-interactive, so the install prompt cannot be shown. Install Servy first and rerun the script."
    }

    Write-Host "Install Servy now using $($strategy.Name)? " -ForegroundColor Yellow -NoNewline
    Write-Host "(Y/n)" -ForegroundColor Magenta

    $answer = Read-Host
    if ($null -eq $answer) {
        Fail "Servy CLI is not installed and no interactive input was available for the install prompt. Install Servy first or rerun the script in an interactive PowerShell session."
    }

    $answer = $answer.Trim()
    if ($answer -match '^(n|no)$') {
        Fail "Servy installation was declined. Install it later and run the script again."
    }

    Write-ActionBanner "Installing Servy with $($strategy.Name)"
    foreach ($step in $strategy.Steps) {
        $ignoreFailure = $false
        if ($step.ContainsKey("IgnoreFailure")) {
            $ignoreFailure = [bool]$step.IgnoreFailure
        }

        Invoke-ManagedExternalStep -FilePath $step.FilePath -Arguments $step.Arguments -IgnoreFailure:$ignoreFailure -RequireAdministrator
    }

    Refresh-ProcessPath
    $servyCli = Resolve-ServyCliPath
    if (-not $servyCli) {
        Fail "Servy install finished, but servy-cli.exe was not found on PATH. Expected location includes C:\Program Files\Servy\servy-cli.exe"
    }

    Write-Success "Servy CLI installed successfully."
    return $servyCli
}

function Uninstall-ServyPackage {
    $strategies = @(Get-ServyUninstallStrategies)
    if ($strategies.Count -eq 0) {
        Write-Info "No supported package manager was found for uninstalling Servy automatically."
        return
    }

    foreach ($strategy in $strategies) {
        Write-ActionBanner "Attempting to uninstall Servy with $($strategy.Name)"

        $failed = $false
        foreach ($step in $strategy.Steps) {
            try {
                Invoke-ExternalStep -FilePath $step.FilePath -Arguments $step.Arguments
            }
            catch {
                $failed = $true
                Write-Info "Servy uninstall via $($strategy.Name) did not succeed: $($_.Exception.Message)"
                break
            }
        }

        Refresh-ProcessPath
        if (-not (Resolve-ServyCliPath)) {
            Write-Success "Servy appears to be uninstalled."
            return
        }

        if (-not $failed) {
            Write-Info "Servy is still present after running $($strategy.Name). Trying the next available package manager."
        }
    }

    Write-Info "Servy is still installed. Remove it manually if needed."
}

function Get-ServiceProcessId {
    param([Parameter(Mandatory = $true)][string]$ServiceName)

    try {
        $serviceCim = Get-CimInstance -ClassName Win32_Service -Filter "Name='$ServiceName'" -ErrorAction Stop
        return [int]$serviceCim.ProcessId
    }
    catch {
        return 0
    }
}

function Get-ChildProcessIds {
    param([Parameter(Mandatory = $true)][int]$ParentProcessId)

    if ($ParentProcessId -le 0) {
        return @()
    }

    return @(
        Get-CimInstance Win32_Process -Filter "ParentProcessId = $ParentProcessId" -ErrorAction SilentlyContinue |
        Select-Object -ExpandProperty ProcessId
    )
}

function Get-ProcessTreeIds {
    param([Parameter(Mandatory = $true)][int]$RootProcessId)

    if ($RootProcessId -le 0) {
        return @()
    }

    $allIds = New-Object System.Collections.Generic.List[int]
    $pending = New-Object System.Collections.Generic.Queue[int]
    $pending.Enqueue($RootProcessId)

    while ($pending.Count -gt 0) {
        $currentId = $pending.Dequeue()
        if ($allIds.Contains($currentId)) {
            continue
        }

        $allIds.Add($currentId)
        foreach ($childId in Get-ChildProcessIds -ParentProcessId $currentId) {
            if (-not $allIds.Contains([int]$childId)) {
                $pending.Enqueue([int]$childId)
            }
        }
    }

    return @($allIds.ToArray())
}

function Stop-ProcessTree {
    param(
        [Parameter(Mandatory = $true)][int]$RootProcessId,
        [string]$Reason = "cleanup"
    )

    $processIds = @(Get-ProcessTreeIds -RootProcessId $RootProcessId | Sort-Object -Descending)
    if ($processIds.Count -eq 0) {
        return
    }

    foreach ($processId in $processIds) {
        try {
            $proc = Get-Process -Id $processId -ErrorAction SilentlyContinue
            if (-not $proc) {
                continue
            }

            Write-Info "Stopping PID $processId ($($proc.ProcessName)) during $Reason."
            Stop-Process -Id $processId -Force -ErrorAction SilentlyContinue
        }
        catch {
            Write-Info "Could not stop PID ${processId}: $($_.Exception.Message)"
        }
    }
}

function Stop-ProcessesUsingPort {
    param(
        [Parameter(Mandatory = $true)][int]$Port
    )

    if ($Port -lt 1 -or $Port -gt 65535) {
        Fail "Invalid TCP port '$Port'."
    }

    # Use netstat to find all PIDs listening or connected on the port — more reliable than Get-NetTCPConnection
    $processIds = @(
        netstat -ano |
        Select-String ":$Port\s" |
        ForEach-Object {
            $cols = ($_ -replace '\s+', ' ').Trim() -split ' '
            $pid = $cols[-1]
            if ($pid -match '^\d+$' -and [int]$pid -gt 0) { [int]$pid }
        } |
        Sort-Object -Unique
    )

    if ($processIds.Count -eq 0) {
        Write-Info "TCP port $Port is already free."
        return
    }

    Write-ActionBanner "Force freeing TCP port $Port"

    foreach ($processId in $processIds) {
        try {
            $proc = Get-Process -Id $processId -ErrorAction SilentlyContinue
            $name = if ($proc) { $proc.ProcessName } else { "unknown" }
            Write-Info "Force killing PID $processId ($name) holding port $Port."
            taskkill /PID $processId /F | Out-Null
        }
        catch {
            Write-Info "Could not kill PID ${processId}: $($_.Exception.Message)"
        }
    }

    Start-Sleep -Seconds 2

    $stillUsed = @(
        netstat -ano |
        Select-String ":$Port\s" |
        Where-Object { $_ -match '\bLISTENING\b' }
    )
    if ($stillUsed.Count -gt 0) {
        Fail "TCP port $Port is still in use after force cleanup."
    }

    Write-Success "TCP port $Port is free."
}

function Stop-ServiceCompletely {
    param(
        [Parameter(Mandatory = $true)][string]$ServiceName,
        [string]$ServyCliPath
    )

    $service = Get-Service -Name $ServiceName -ErrorAction SilentlyContinue
    if (-not $service) {
        return
    }

    $serviceProcessId = Get-ServiceProcessId -ServiceName $ServiceName

    if ($service.Status -ne [System.ServiceProcess.ServiceControllerStatus]::Stopped) {
        if ($ServyCliPath) {
            & $ServyCliPath stop "--name=$ServiceName" --quiet
        }

        $service.Refresh()
        if ($service.Status -ne [System.ServiceProcess.ServiceControllerStatus]::Stopped) {
            Stop-Service -Name $ServiceName -Force -ErrorAction SilentlyContinue
        }

        try {
            $service.WaitForStatus([System.ServiceProcess.ServiceControllerStatus]::Stopped, [TimeSpan]::FromSeconds(20))
        }
        catch {
            $service.Refresh()
        }
    }

    $service.Refresh()
    if ($service.Status -ne [System.ServiceProcess.ServiceControllerStatus]::Stopped) {
        if ($serviceProcessId -gt 0) {
            Stop-ProcessTree -RootProcessId $serviceProcessId -Reason "service shutdown"
            Start-Sleep -Seconds 2
            $service = Get-Service -Name $ServiceName -ErrorAction SilentlyContinue
        }
    }

    if ($serviceProcessId -gt 0) {
        Stop-ProcessTree -RootProcessId $serviceProcessId -Reason "post-stop cleanup"
    }

    if ($service -and $service.Status -ne [System.ServiceProcess.ServiceControllerStatus]::Stopped) {
        Fail "Could not stop the '$ServiceName' service."
    }
}
