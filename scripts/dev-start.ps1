param(
    [ValidateSet('Auto', 'Docker', 'Vm', 'Existing')]
    [string]$InfraMode = 'Auto',
    [int]$TimeoutSeconds = 180
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$projectRoot = Split-Path -Parent $PSScriptRoot
$runtimeDir = Join-Path $projectRoot '.runtime\dev'
. (Join-Path $PSScriptRoot 'Import-DotEnv.ps1')
. (Join-Path $PSScriptRoot 'DevRuntime.ps1')
Import-DotEnv -Path (Join-Path $projectRoot '.env')
Import-DotEnv -Path (Join-Path $projectRoot 'python_agent\.env')
New-Item -ItemType Directory -Force -Path $runtimeDir | Out-Null

function Get-FirstHost([string]$Value, [string]$DefaultHost) {
    if ([string]::IsNullOrWhiteSpace($Value)) { return $DefaultHost }
    return ($Value.Split(',')[0].Split(':')[0]).Trim()
}

$kafkaHost = Get-FirstHost -Value $env:KAFKA_BOOTSTRAP_SERVERS -DefaultHost '127.0.0.1'
$vmHost = if ([string]::IsNullOrWhiteSpace($env:VM_INFRA_HOST)) { $kafkaHost } else { $env:VM_INFRA_HOST }
$vmKey = if ([string]::IsNullOrWhiteSpace($env:VM_INFRA_SSH_KEY)) { Join-Path $projectRoot '.runtime\vm\id_ed25519' } else { Join-Path $projectRoot $env:VM_INFRA_SSH_KEY }
$selectedMode = $InfraMode
if ($InfraMode -eq 'Auto' -and -not [string]::IsNullOrWhiteSpace($env:LOCAL_INFRA_MODE)) {
    $configuredMode = $env:LOCAL_INFRA_MODE.Trim()
    if ($configuredMode -in @('Docker', 'Vm', 'Existing')) {
        $selectedMode = $configuredMode
    }
}
if ($selectedMode -eq 'Auto') {
    if ($vmHost -notin @('127.0.0.1', 'localhost') -and (Test-Path -LiteralPath $vmKey)) {
        $selectedMode = 'Vm'
    } else {
        $docker = Get-Command docker.exe -ErrorAction SilentlyContinue
        if ($null -ne $docker) {
            & $docker.Source info *> $null
        }
        $selectedMode = if ($null -ne $docker -and $LASTEXITCODE -eq 0) { 'Docker' } else { 'Existing' }
    }
}

if ($selectedMode -eq 'Docker') {
    Set-Location -LiteralPath $projectRoot
    & docker.exe compose --profile local-ai up -d mysql redis postgres kafka ollama reranker
    if ($LASTEXITCODE -ne 0) { throw 'Docker Compose infrastructure startup failed.' }
} elseif ($selectedMode -eq 'Vm') {
    & (Join-Path $PSScriptRoot 'start-windows-infra.ps1')
    $requiredVmPorts = @(5432, 9092, 11434, 8081)
    $vmReady = $true
    foreach ($port in $requiredVmPorts) {
        if (-not (Test-TcpEndpoint -HostName $vmHost -Port $port)) { $vmReady = $false }
    }
    if (-not $vmReady) {
        $vmUser = if ([string]::IsNullOrWhiteSpace($env:VM_INFRA_USER)) { 'codex' } else { $env:VM_INFRA_USER }
        $vmComposeDir = if ([string]::IsNullOrWhiteSpace($env:VM_INFRA_COMPOSE_DIR)) { '/opt/ecommerce-after-sales-system' } else { $env:VM_INFRA_COMPOSE_DIR }
        $knownHosts = if ([string]::IsNullOrWhiteSpace($env:VM_INFRA_KNOWN_HOSTS)) { Join-Path $projectRoot '.runtime\vm\known_hosts' } else { Join-Path $projectRoot $env:VM_INFRA_KNOWN_HOSTS }
        & ssh.exe -i $vmKey -o "UserKnownHostsFile=$knownHosts" -o StrictHostKeyChecking=yes `
            "$vmUser@$vmHost" "cd $vmComposeDir && docker compose --profile local-ai up -d postgres kafka ollama reranker"
        if ($LASTEXITCODE -ne 0) { throw 'VM infrastructure startup failed.' }
    }
}
Set-Content -LiteralPath (Join-Path $runtimeDir 'infra-mode.txt') -Value $selectedMode

$checks = @(
    @{ Name = 'MySQL'; Host = '127.0.0.1'; Port = [int]$env:MYSQL_HOST_PORT },
    @{ Name = 'Redis'; Host = $env:REDIS_HOST; Port = [int]$env:REDIS_PORT },
    @{ Name = 'PostgreSQL'; Host = $env:PGVECTOR_HOST; Port = [int]$env:PGVECTOR_PORT },
    @{ Name = 'Kafka'; Host = $kafkaHost; Port = [int]($env:KAFKA_BOOTSTRAP_SERVERS.Split(':')[-1]) },
    @{ Name = 'Ollama'; Host = ([Uri]$env:OLLAMA_BASE_URL).Host; Port = ([Uri]$env:OLLAMA_BASE_URL).Port },
    @{ Name = 'Reranker'; Host = ([Uri]$env:RERANK_BASE_URL).Host; Port = ([Uri]$env:RERANK_BASE_URL).Port }
)
foreach ($check in $checks) {
    Wait-TcpEndpoint -HostName $check.Host -Port $check.Port -TimeoutSeconds $TimeoutSeconds
    Write-Host "$($check.Name) is reachable at $($check.Host):$($check.Port)."
}

if ($env:OLLAMA_AUTO_PULL_MODELS -eq 'true') {
    & (Join-Path $PSScriptRoot 'ensure-ollama-models.ps1') -TimeoutSeconds ([Math]::Max($TimeoutSeconds, 3600))
}

Start-ManagedScript -Name 'agent' -ScriptPath (Join-Path $PSScriptRoot 'start-agent.ps1') `
    -ReadyUri 'http://127.0.0.1:8000/api/health' -ProjectRoot $projectRoot -TimeoutSeconds $TimeoutSeconds
Start-ManagedScript -Name 'backend' -ScriptPath (Join-Path $PSScriptRoot 'start-backend.ps1') `
    -ReadyUri 'http://127.0.0.1:8080/api/actuator/health' -ProjectRoot $projectRoot -TimeoutSeconds $TimeoutSeconds
Start-ManagedScript -Name 'frontend' -ScriptPath (Join-Path $PSScriptRoot 'start-frontend.ps1') `
    -ReadyUri 'http://127.0.0.1:5173/' -ProjectRoot $projectRoot -TimeoutSeconds $TimeoutSeconds
Start-ManagedScript -Name 'review-consumer' -ScriptPath (Join-Path $PSScriptRoot 'start-review-consumer.ps1') `
    -ReadyUri 'http://127.0.0.1:8001/metrics' -ProjectRoot $projectRoot -TimeoutSeconds $TimeoutSeconds

if ($selectedMode -eq 'Vm' -and $env:VM_OBSERVABILITY_ENABLED -eq 'true') {
    & (Join-Path $PSScriptRoot 'start-vm-observability.ps1')
}

Write-Host "Development stack is ready (infrastructure mode: $selectedMode)."
