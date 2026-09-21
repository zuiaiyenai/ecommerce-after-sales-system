param([switch]$KeepInfrastructure)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$projectRoot = Split-Path -Parent $PSScriptRoot
$runtimeDir = Join-Path $projectRoot '.runtime\dev'
. (Join-Path $PSScriptRoot 'Import-DotEnv.ps1')
. (Join-Path $PSScriptRoot 'DevRuntime.ps1')
Import-DotEnv -Path (Join-Path $projectRoot '.env')

foreach ($name in @('review-consumer', 'frontend', 'backend', 'agent')) {
    Stop-ManagedProcess -Name $name -ProjectRoot $projectRoot
}

if (-not $KeepInfrastructure) {
    $modeFile = Join-Path $runtimeDir 'infra-mode.txt'
    $mode = if (Test-Path -LiteralPath $modeFile) { (Get-Content -LiteralPath $modeFile -Raw).Trim() } else { 'Existing' }
    if ($mode -eq 'Docker') {
        Set-Location -LiteralPath $projectRoot
        & docker.exe compose --profile local-ai stop reranker ollama kafka postgres redis mysql
        if ($LASTEXITCODE -ne 0) { throw 'Docker Compose infrastructure stop failed.' }
    } elseif ($mode -eq 'Vm') {
        $kafkaHost = ($env:KAFKA_BOOTSTRAP_SERVERS.Split(',')[0].Split(':')[0]).Trim()
        $vmHost = if ([string]::IsNullOrWhiteSpace($env:VM_INFRA_HOST)) { $kafkaHost } else { $env:VM_INFRA_HOST }
        $vmUser = if ([string]::IsNullOrWhiteSpace($env:VM_INFRA_USER)) { 'codex' } else { $env:VM_INFRA_USER }
        $vmComposeDir = if ([string]::IsNullOrWhiteSpace($env:VM_INFRA_COMPOSE_DIR)) { '/opt/ecommerce-after-sales-system' } else { $env:VM_INFRA_COMPOSE_DIR }
        $vmKey = if ([string]::IsNullOrWhiteSpace($env:VM_INFRA_SSH_KEY)) { Join-Path $projectRoot '.runtime\vm\id_ed25519' } else { Join-Path $projectRoot $env:VM_INFRA_SSH_KEY }
        $knownHosts = if ([string]::IsNullOrWhiteSpace($env:VM_INFRA_KNOWN_HOSTS)) { Join-Path $projectRoot '.runtime\vm\known_hosts' } else { Join-Path $projectRoot $env:VM_INFRA_KNOWN_HOSTS }
        & ssh.exe -i $vmKey -o "UserKnownHostsFile=$knownHosts" -o StrictHostKeyChecking=yes `
            "$vmUser@$vmHost" "cd $vmComposeDir && docker compose --profile local-ai stop grafana prometheus reranker ollama kafka postgres"
        if ($LASTEXITCODE -ne 0) { throw 'VM infrastructure stop failed.' }
        & (Join-Path $PSScriptRoot 'stop-windows-infra.ps1')
    }
    Remove-Item -LiteralPath $modeFile -ErrorAction SilentlyContinue
}

Write-Host 'Development stack stopped.'
