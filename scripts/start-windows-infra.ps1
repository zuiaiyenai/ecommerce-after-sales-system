$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$projectRoot = Split-Path -Parent $PSScriptRoot
$runtimeDir = Join-Path $projectRoot '.runtime'
$managedDir = Join-Path $runtimeDir 'dev'
. (Join-Path $PSScriptRoot 'Import-DotEnv.ps1')
. (Join-Path $PSScriptRoot 'DevRuntime.ps1')
Import-DotEnv -Path (Join-Path $projectRoot '.env')

New-Item -ItemType Directory -Force -Path $managedDir | Out-Null
$mysqlPort = if ([string]::IsNullOrWhiteSpace($env:MYSQL_HOST_PORT)) { 3307 } else { [int]$env:MYSQL_HOST_PORT }
$redisPort = if ([string]::IsNullOrWhiteSpace($env:REDIS_HOST_PORT)) { 6380 } else { [int]$env:REDIS_HOST_PORT }
$mysqlConfig = Join-Path $runtimeDir 'mysql-local.ini'
$redisConfig = Join-Path $runtimeDir 'redis-local.conf'

if (-not (Test-TcpEndpoint -HostName '127.0.0.1' -Port $mysqlPort)) {
    if ([string]::IsNullOrWhiteSpace($env:WINDOWS_MYSQLD_PATH) -or -not (Test-Path -LiteralPath $env:WINDOWS_MYSQLD_PATH)) {
        throw 'WINDOWS_MYSQLD_PATH must point to mysqld.exe when native Windows infrastructure is used.'
    }
    if (-not (Test-Path -LiteralPath $mysqlConfig)) {
        throw "MySQL local config is missing: $mysqlConfig"
    }
    $mysql = Start-Process -FilePath $env:WINDOWS_MYSQLD_PATH `
        -ArgumentList "--defaults-file=$mysqlConfig" -WindowStyle Hidden -PassThru
    Set-Content -LiteralPath (Join-Path $managedDir 'mysql.pid') -Value $mysql.Id
    Wait-TcpEndpoint -HostName '127.0.0.1' -Port $mysqlPort -TimeoutSeconds 30
}

if (-not (Test-TcpEndpoint -HostName '127.0.0.1' -Port $redisPort)) {
    if ([string]::IsNullOrWhiteSpace($env:WINDOWS_REDIS_SERVER_PATH) -or -not (Test-Path -LiteralPath $env:WINDOWS_REDIS_SERVER_PATH)) {
        throw 'WINDOWS_REDIS_SERVER_PATH must point to redis-server.exe when native Windows infrastructure is used.'
    }
    if (-not (Test-Path -LiteralPath $redisConfig)) {
        throw "Redis local config is missing: $redisConfig"
    }
    $redis = Start-Process -FilePath $env:WINDOWS_REDIS_SERVER_PATH `
        -ArgumentList $redisConfig -WindowStyle Hidden -PassThru
    Set-Content -LiteralPath (Join-Path $managedDir 'redis.pid') -Value $redis.Id
    Wait-TcpEndpoint -HostName '127.0.0.1' -Port $redisPort -TimeoutSeconds 30
}

Write-Host "Windows infrastructure is ready: MySQL $mysqlPort, Redis $redisPort."
