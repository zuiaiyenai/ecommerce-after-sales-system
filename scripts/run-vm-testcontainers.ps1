param(
    [ValidateSet('All', 'Java', 'PythonRedis')]
    [string]$Suite = 'All',
    [string]$MavenTest = ''
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$projectRoot = Split-Path -Parent $PSScriptRoot
. (Join-Path $PSScriptRoot 'Import-DotEnv.ps1')
Import-DotEnv -Path (Join-Path $projectRoot '.env')

function Resolve-ProjectPath([string]$Value, [string]$DefaultRelativePath) {
    $candidate = if ([string]::IsNullOrWhiteSpace($Value)) { $DefaultRelativePath } else { $Value }
    if ([IO.Path]::IsPathRooted($candidate)) { return $candidate }
    return Join-Path $projectRoot $candidate
}

$vmHost = $env:VM_INFRA_HOST
$vmUser = if ([string]::IsNullOrWhiteSpace($env:VM_INFRA_USER)) { 'codex' } else { $env:VM_INFRA_USER }
$vmKey = Resolve-ProjectPath -Value $env:VM_INFRA_SSH_KEY -DefaultRelativePath '.runtime\vm\id_ed25519'
$knownHosts = Resolve-ProjectPath -Value $env:VM_INFRA_KNOWN_HOSTS -DefaultRelativePath '.runtime\vm\known_hosts'
$proxySource = Join-Path $PSScriptRoot 'docker-api-loopback-proxy.py'
$remoteProxy = '/tmp/ecommerce-after-sales-system-docker-api-proxy.py'
$remotePid = '/tmp/ecommerce-after-sales-system-docker-api-proxy.pid'
$localPort = 23750

if ([string]::IsNullOrWhiteSpace($vmHost)) { throw 'VM_INFRA_HOST is required.' }
foreach ($path in @($vmKey, $knownHosts, $proxySource)) {
    if (-not (Test-Path -LiteralPath $path)) { throw "Required file not found: $path" }
}
if (Get-NetTCPConnection -LocalPort $localPort -State Listen -ErrorAction SilentlyContinue) {
    throw "Local port $localPort is already in use."
}

$sshOptions = @('-i', $vmKey, '-o', "UserKnownHostsFile=$knownHosts", '-o', 'StrictHostKeyChecking=yes')
$target = "$vmUser@$vmHost"
$proxyStarted = $false
$tunnel = $null
$previousDockerHost = $env:DOCKER_HOST
$previousHostOverride = $env:TESTCONTAINERS_HOST_OVERRIDE
$previousSocketOverride = $env:TESTCONTAINERS_DOCKER_SOCKET_OVERRIDE

try {
    & scp.exe @sshOptions $proxySource "${target}:$remoteProxy"
    if ($LASTEXITCODE -ne 0) { throw 'Failed to copy the Docker API loopback proxy to the VM.' }

    $startProxy = 'if [ -f /tmp/ecommerce-after-sales-system-docker-api-proxy.pid ] && kill -0 "$(cat /tmp/ecommerce-after-sales-system-docker-api-proxy.pid)" 2>/dev/null; then echo "Managed Docker proxy is already running" >&2; exit 20; fi; nohup python3 /tmp/ecommerce-after-sales-system-docker-api-proxy.py >/tmp/ecommerce-after-sales-system-docker-api-proxy.log 2>&1 & proxy_pid=$!; echo "$proxy_pid" >/tmp/ecommerce-after-sales-system-docker-api-proxy.pid; sleep 1; kill -0 "$proxy_pid"'
    & ssh.exe @sshOptions $target $startProxy
    if ($LASTEXITCODE -ne 0) { throw 'Failed to start the VM Docker API loopback proxy.' }
    $proxyStarted = $true

    $tunnelArguments = @(
        '-N', '-L', "127.0.0.1:${localPort}:127.0.0.1:${localPort}",
        '-i', $vmKey,
        '-o', "UserKnownHostsFile=$knownHosts",
        '-o', 'StrictHostKeyChecking=yes',
        '-o', 'ExitOnForwardFailure=yes',
        '-o', 'ServerAliveInterval=15',
        $target
    )
    $tunnel = Start-Process -FilePath 'ssh.exe' -ArgumentList $tunnelArguments -WindowStyle Hidden -PassThru

    $deadline = (Get-Date).AddSeconds(20)
    $dockerReady = $false
    while ((Get-Date) -lt $deadline) {
        if ($tunnel.HasExited) { throw 'The Docker SSH tunnel exited before becoming ready.' }
        try {
            $response = Invoke-WebRequest -UseBasicParsing -Uri "http://127.0.0.1:$localPort/_ping" -TimeoutSec 2
            if ($response.StatusCode -eq 200 -and $response.Content.Trim() -eq 'OK') {
                $dockerReady = $true
                break
            }
        } catch {
            Start-Sleep -Milliseconds 500
        }
    }
    if (-not $dockerReady) { throw 'Timed out waiting for the tunneled Docker API.' }

    $env:DOCKER_HOST = "tcp://127.0.0.1:$localPort"
    $env:TESTCONTAINERS_HOST_OVERRIDE = $vmHost
    $env:TESTCONTAINERS_DOCKER_SOCKET_OVERRIDE = '/var/run/docker.sock'

    Set-Location -LiteralPath $projectRoot
    if ($Suite -in @('All', 'PythonRedis')) {
        & (Join-Path $projectRoot '.venv\Scripts\python.exe') -m pytest `
            'python_agent\tests\contract\test_redis_idempotency.py' -q -m integration -rs
        if ($LASTEXITCODE -ne 0) { throw 'Python Redis Testcontainers test failed.' }
    }
    if ($Suite -in @('All', 'Java')) {
        $mavenArguments = @('test')
        if (-not [string]::IsNullOrWhiteSpace($MavenTest)) {
            $mavenArguments = @("-Dtest=$MavenTest", 'test')
        }
        & (Join-Path $projectRoot 'mvnw.cmd') @mavenArguments
        if ($LASTEXITCODE -ne 0) { throw 'Java Testcontainers test suite failed.' }
    }
} finally {
    $env:DOCKER_HOST = $previousDockerHost
    $env:TESTCONTAINERS_HOST_OVERRIDE = $previousHostOverride
    $env:TESTCONTAINERS_DOCKER_SOCKET_OVERRIDE = $previousSocketOverride

    if ($null -ne $tunnel -and -not $tunnel.HasExited) {
        Stop-Process -Id $tunnel.Id -Force -ErrorAction SilentlyContinue
    }
    if ($proxyStarted) {
        $stopProxy = 'if [ -f /tmp/ecommerce-after-sales-system-docker-api-proxy.pid ]; then proxy_pid=$(cat /tmp/ecommerce-after-sales-system-docker-api-proxy.pid); if kill -0 "$proxy_pid" 2>/dev/null && tr "\0" " " < "/proc/$proxy_pid/cmdline" | grep -Fq /tmp/ecommerce-after-sales-system-docker-api-proxy.py; then kill "$proxy_pid"; fi; rm -f /tmp/ecommerce-after-sales-system-docker-api-proxy.pid /tmp/ecommerce-after-sales-system-docker-api-proxy.py; fi'
        & ssh.exe @sshOptions $target $stopProxy
    }
}
