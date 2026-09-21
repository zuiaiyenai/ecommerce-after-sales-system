param(
    [int]$TimeoutSeconds = 3600
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$projectRoot = Split-Path -Parent $PSScriptRoot
. (Join-Path $PSScriptRoot 'Import-DotEnv.ps1')
Import-DotEnv -Path (Join-Path $projectRoot '.env')
Import-DotEnv -Path (Join-Path $projectRoot 'python_agent\.env')

$baseUrl = $env:OLLAMA_BASE_URL
if ([string]::IsNullOrWhiteSpace($baseUrl)) {
    throw 'OLLAMA_BASE_URL is required when OLLAMA_AUTO_PULL_MODELS=true.'
}
$baseUrl = $baseUrl.TrimEnd('/')

$models = @(
    $env:OLLAMA_MODEL,
    $env:EMBEDDING_MODEL,
    $env:VISION_MODEL
) | Where-Object { -not [string]::IsNullOrWhiteSpace($_) } | Select-Object -Unique

foreach ($model in $models) {
    $payload = @{ name = $model } | ConvertTo-Json -Compress
    try {
        Invoke-RestMethod -Method Post -Uri "$baseUrl/api/show" -ContentType 'application/json' `
            -Body $payload -TimeoutSec 30 | Out-Null
        Write-Host "Ollama model is available: $model"
        continue
    } catch {
        Write-Host "Ollama model is missing; pulling $model."
    }

    $pullPayload = @{ name = $model; stream = $false } | ConvertTo-Json -Compress
    Invoke-RestMethod -Method Post -Uri "$baseUrl/api/pull" -ContentType 'application/json' `
        -Body $pullPayload -TimeoutSec $TimeoutSeconds | Out-Null
    Write-Host "Ollama model pull completed: $model"
}
