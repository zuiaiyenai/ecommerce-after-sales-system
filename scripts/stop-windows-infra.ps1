$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$projectRoot = Split-Path -Parent $PSScriptRoot
$managedDir = [IO.Path]::GetFullPath((Join-Path $projectRoot '.runtime\dev'))
. (Join-Path $PSScriptRoot 'Import-DotEnv.ps1')
. (Join-Path $PSScriptRoot 'DevRuntime.ps1')
Import-DotEnv -Path (Join-Path $projectRoot '.env')

foreach ($entry in @(
    @{ Name = 'Redis'; File = 'redis.pid'; Process = 'redis-server'; Port = [int]$env:REDIS_HOST_PORT },
    @{ Name = 'MySQL'; File = 'mysql.pid'; Process = 'mysqld'; Port = [int]$env:MYSQL_HOST_PORT }
)) {
    $pidFile = [IO.Path]::GetFullPath((Join-Path $managedDir $entry.File))
    if (-not $pidFile.StartsWith($managedDir, [StringComparison]::OrdinalIgnoreCase)) {
        throw "Refusing to read PID outside project runtime: $pidFile"
    }
    if (-not (Test-Path -LiteralPath $pidFile)) {
        Write-Host "$($entry.Name) has no managed PID; leaving it unchanged."
        continue
    }
    $managedPid = [int](Get-Content -LiteralPath $pidFile -Raw).Trim()
    $process = Get-Process -Id $managedPid -ErrorAction SilentlyContinue
    if ($null -ne $process -and $process.ProcessName -ne $entry.Process) {
        throw "Refusing to stop PID $managedPid because it is not $($entry.Process)."
    }
    if ($null -ne $process) {
        try {
            $details = Get-CimInstance Win32_Process -Filter "ProcessId = $managedPid" -ErrorAction Stop
        } catch {
            throw "Cannot inspect managed $($entry.Name) PID $managedPid. Run from an elevated PowerShell."
        }
        if ([string]$details.CommandLine -notlike "*$projectRoot*") {
            throw "Refusing to stop PID $managedPid because its command line is outside this project."
        }
    }
    if ($null -ne $process -and $entry.Name -eq 'Redis') {
        if ([string]::IsNullOrWhiteSpace($env:WINDOWS_REDIS_CLI_PATH) -or -not (Test-Path -LiteralPath $env:WINDOWS_REDIS_CLI_PATH)) {
            throw 'WINDOWS_REDIS_CLI_PATH is required for a graceful Redis shutdown.'
        }
        & $env:WINDOWS_REDIS_CLI_PATH -h 127.0.0.1 -p $entry.Port SHUTDOWN
    } elseif ($null -ne $process -and $entry.Name -eq 'MySQL') {
        if ([string]::IsNullOrWhiteSpace($env:WINDOWS_MYSQLADMIN_PATH) -or -not (Test-Path -LiteralPath $env:WINDOWS_MYSQLADMIN_PATH)) {
            throw 'WINDOWS_MYSQLADMIN_PATH is required for a graceful MySQL shutdown.'
        }
        if ([string]::IsNullOrWhiteSpace($env:WINDOWS_MYSQL_SHUTDOWN_USER)) {
            throw 'WINDOWS_MYSQL_SHUTDOWN_USER is required for a graceful MySQL shutdown.'
        }
        $previousPassword = $env:MYSQL_PWD
        try {
            $env:MYSQL_PWD = $env:WINDOWS_MYSQL_SHUTDOWN_PASSWORD
            & $env:WINDOWS_MYSQLADMIN_PATH --protocol=tcp -h 127.0.0.1 -P $entry.Port `
                -u $env:WINDOWS_MYSQL_SHUTDOWN_USER shutdown
        } finally {
            $env:MYSQL_PWD = $previousPassword
        }
    }
    $deadline = (Get-Date).AddSeconds(15)
    while ((Get-Date) -lt $deadline -and (Test-TcpEndpoint -HostName '127.0.0.1' -Port $entry.Port)) {
        Start-Sleep -Milliseconds 250
    }
    if (Test-TcpEndpoint -HostName '127.0.0.1' -Port $entry.Port) {
        throw "$($entry.Name) did not stop gracefully; no forced termination was attempted."
    }
    Remove-Item -LiteralPath $pidFile
    Write-Host "$($entry.Name) stopped."
}
