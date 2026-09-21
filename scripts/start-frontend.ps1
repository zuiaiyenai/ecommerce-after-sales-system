$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$projectRoot = Split-Path -Parent $PSScriptRoot
$frontendRoot = Join-Path $projectRoot 'frontend\staff-auth-test-ui'
. (Join-Path $PSScriptRoot 'Import-DotEnv.ps1')

Import-DotEnv -Path (Join-Path $projectRoot '.env')
if ([string]::IsNullOrWhiteSpace($env:VITE_API_BASE_URL)) {
    $env:VITE_API_BASE_URL = 'http://127.0.0.1:8080/api'
}
if (-not (Test-Path -LiteralPath (Join-Path $frontendRoot 'node_modules'))) {
    throw 'Frontend dependencies are missing. Run npm ci in frontend/staff-auth-test-ui first.'
}

Set-Location -LiteralPath $frontendRoot
& npm.cmd run dev:real @args
exit $LASTEXITCODE
