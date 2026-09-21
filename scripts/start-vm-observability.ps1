$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$projectRoot = Split-Path -Parent $PSScriptRoot
. (Join-Path $PSScriptRoot 'Import-DotEnv.ps1')
. (Join-Path $PSScriptRoot 'DevRuntime.ps1')
Import-DotEnv -Path (Join-Path $projectRoot '.env')
Import-DotEnv -Path (Join-Path $projectRoot 'python_agent\.env')

if ($env:AGENT_HOST -in @('127.0.0.1', 'localhost')) {
    throw 'VM Prometheus cannot scrape an Agent bound to loopback. Set AGENT_HOST=0.0.0.0 in python_agent/.env and restart the Agent.'
}
if ([string]::IsNullOrWhiteSpace($env:AGENT_INTERNAL_TOKEN)) {
    throw 'AGENT_INTERNAL_TOKEN is required.'
}

$vmHost = if ([string]::IsNullOrWhiteSpace($env:VM_INFRA_HOST)) { '192.168.100.130' } else { $env:VM_INFRA_HOST }
$vmUser = if ([string]::IsNullOrWhiteSpace($env:VM_INFRA_USER)) { 'codex' } else { $env:VM_INFRA_USER }
$vmComposeDir = if ([string]::IsNullOrWhiteSpace($env:VM_INFRA_COMPOSE_DIR)) { '/opt/ecommerce-after-sales-system' } else { $env:VM_INFRA_COMPOSE_DIR }
$windowsHostIp = if ([string]::IsNullOrWhiteSpace($env:VM_WINDOWS_HOST_IP)) { '192.168.100.1' } else { $env:VM_WINDOWS_HOST_IP }
$vmKey = if ([string]::IsNullOrWhiteSpace($env:VM_INFRA_SSH_KEY)) { Join-Path $projectRoot '.runtime\vm\id_ed25519' } else { Join-Path $projectRoot $env:VM_INFRA_SSH_KEY }
$knownHosts = if ([string]::IsNullOrWhiteSpace($env:VM_INFRA_KNOWN_HOSTS)) { Join-Path $projectRoot '.runtime\vm\known_hosts' } else { Join-Path $projectRoot $env:VM_INFRA_KNOWN_HOSTS }
$sshOptions = @('-i', $vmKey, '-o', "UserKnownHostsFile=$knownHosts", '-o', 'StrictHostKeyChecking=yes')
$vmTarget = "$vmUser@$vmHost"

$tokenPath = Join-Path $projectRoot 'observability\prometheus\agent-token.txt'
[IO.File]::WriteAllText($tokenPath, $env:AGENT_INTERNAL_TOKEN + "`n", [Text.UTF8Encoding]::new($false))

& scp.exe @sshOptions (Join-Path $projectRoot 'compose.yml') (Join-Path $projectRoot 'compose.vm-observability.yml') "${vmTarget}:$vmComposeDir/"
if ($LASTEXITCODE -ne 0) { throw 'Failed to copy Compose files to the VM.' }
& scp.exe @sshOptions -r (Join-Path $projectRoot 'observability') "${vmTarget}:$vmComposeDir/"
if ($LASTEXITCODE -ne 0) { throw 'Failed to copy observability configuration to the VM.' }

$remoteCommand = "cd $vmComposeDir && VM_WINDOWS_HOST_IP=$windowsHostIp docker compose -f compose.yml -f compose.vm-observability.yml up -d --no-deps --force-recreate prometheus grafana"
& ssh.exe @sshOptions $vmTarget $remoteCommand
if ($LASTEXITCODE -ne 0) { throw 'VM observability startup failed.' }

Wait-TcpEndpoint -HostName $vmHost -Port 9090 -TimeoutSeconds 180
Wait-TcpEndpoint -HostName $vmHost -Port 3000 -TimeoutSeconds 180

$expectedJobs = @('ecommerce-java', 'ecommerce-python-agent', 'ecommerce-review-consumer')
$targetDeadline = (Get-Date).AddSeconds(90)
$targets = @()
$healthyJobs = @()
do {
    try {
        $targets = @((Invoke-RestMethod -Uri "http://${vmHost}:9090/api/v1/targets" -TimeoutSec 5).data.activeTargets)
        $healthyJobs = @($targets | Where-Object { $_.health -eq 'up' } | ForEach-Object { $_.labels.job })
        if (@($expectedJobs | Where-Object { $_ -notin $healthyJobs }).Count -eq 0) { break }
    } catch {
        $targets = @()
    }
    Start-Sleep -Seconds 5
} while ((Get-Date) -lt $targetDeadline)

$missingJobs = @($expectedJobs | Where-Object { $_ -notin $healthyJobs })
if ($missingJobs.Count -gt 0) {
    throw "Prometheus targets are not healthy: $($missingJobs -join ', ')."
}
Write-Host "Prometheus is ready: http://${vmHost}:9090"
Write-Host "Grafana is ready: http://${vmHost}:3000"
