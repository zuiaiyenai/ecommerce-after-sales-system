$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$projectRoot = Split-Path -Parent $PSScriptRoot
. (Join-Path $PSScriptRoot 'Import-DotEnv.ps1')

# Remove higher-priority Spring overrides inherited from unrelated projects.
@(
    'SPRING_APPLICATION_JSON',
    'SPRING_CONFIG_LOCATION',
    'SPRING_CONFIG_ADDITIONAL_LOCATION',
    'SPRING_DATASOURCE_URL',
    'SPRING_DATASOURCE_USERNAME',
    'SPRING_DATASOURCE_PASSWORD',
    'SPRING_DATA_REDIS_HOST',
    'SPRING_DATA_REDIS_PORT',
    'SPRING_DATA_REDIS_PASSWORD',
    'SPRING_KAFKA_BOOTSTRAP_SERVERS',
    'SERVER_PORT',
    'SERVER_SERVLET_CONTEXT_PATH',
    'MANAGEMENT_SERVER_PORT'
) | ForEach-Object {
    [Environment]::SetEnvironmentVariable($_, $null, 'Process')
}

Import-DotEnv -Path (Join-Path $projectRoot '.env')
$env:SPRING_PROFILES_ACTIVE = 'local'
$env:SPRING_DATASOURCE_USERNAME = $env:DB_USERNAME
$env:SPRING_DATASOURCE_PASSWORD = $env:DB_PASSWORD
$env:SPRING_DATA_REDIS_HOST = $env:REDIS_HOST
$env:SPRING_DATA_REDIS_PORT = $env:REDIS_PORT
$env:SPRING_KAFKA_BOOTSTRAP_SERVERS = $env:KAFKA_BOOTSTRAP_SERVERS

Set-Location -LiteralPath $projectRoot
& (Join-Path $projectRoot 'mvnw.ps1') spring-boot:run @args
exit $LASTEXITCODE
