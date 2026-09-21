param(
    [string]$AgentBaseUrl = 'http://127.0.0.1:8000/api'
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$projectRoot = Split-Path -Parent $PSScriptRoot
. (Join-Path $projectRoot 'scripts\Import-DotEnv.ps1')

Import-DotEnv -Path (Join-Path $projectRoot '.env')
Import-DotEnv -Path (Join-Path $PSScriptRoot '.env')

if ([string]::IsNullOrWhiteSpace($env:AGENT_INTERNAL_TOKEN)) {
    throw 'AGENT_INTERNAL_TOKEN is required in the project or Python Agent .env file.'
}

$baseUrl = $AgentBaseUrl.TrimEnd('/')
Write-Host 'Checking Python Agent health...' -ForegroundColor Yellow
$health = Invoke-RestMethod -Method Get -Uri "$baseUrl/health" -TimeoutSec 10
if ($health.ok -ne $true) {
    throw 'Python Agent health check did not return ok=true.'
}

Write-Host 'Building embeddings before replacing published chunks...' -ForegroundColor Yellow
$result = Invoke-RestMethod `
    -Method Post `
    -Uri "$baseUrl/knowledge/reindex" `
    -Headers @{ 'X-Agent-Internal-Token' = $env:AGENT_INTERNAL_TOKEN } `
    -ContentType 'application/json; charset=utf-8' `
    -Body '{}' `
    -TimeoutSec 900

if ($result.ok -ne $true) {
    throw 'Knowledge reindex did not return ok=true.'
}

Write-Host (
    'Knowledge index is ready: {0} documents, {1} chunks.' -f `
        $result.documents, $result.chunks
) -ForegroundColor Green
