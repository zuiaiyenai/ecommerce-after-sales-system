Set-StrictMode -Version Latest

function Test-TcpEndpoint {
    param(
        [Parameter(Mandatory = $true)][string]$HostName,
        [Parameter(Mandatory = $true)][int]$Port,
        [int]$TimeoutMilliseconds = 1000
    )

    $client = New-Object System.Net.Sockets.TcpClient
    try {
        $result = $client.BeginConnect($HostName, $Port, $null, $null)
        return $result.AsyncWaitHandle.WaitOne($TimeoutMilliseconds, $false) -and $client.Connected
    } catch {
        return $false
    } finally {
        $client.Close()
    }
}

function Wait-TcpEndpoint {
    param(
        [Parameter(Mandatory = $true)][string]$HostName,
        [Parameter(Mandatory = $true)][int]$Port,
        [int]$TimeoutSeconds = 120
    )

    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        if (Test-TcpEndpoint -HostName $HostName -Port $Port) {
            return
        }
        Start-Sleep -Seconds 1
    }
    throw "Timed out waiting for ${HostName}:$Port."
}

function Test-HttpEndpoint {
    param([Parameter(Mandatory = $true)][string]$Uri)

    try {
        $response = Invoke-WebRequest -UseBasicParsing -Uri $Uri -TimeoutSec 5
        return $response.StatusCode -ge 200 -and $response.StatusCode -lt 400
    } catch {
        return $false
    }
}

function Start-ManagedScript {
    param(
        [Parameter(Mandatory = $true)][string]$Name,
        [Parameter(Mandatory = $true)][string]$ScriptPath,
        [Parameter(Mandatory = $true)][string]$ReadyUri,
        [Parameter(Mandatory = $true)][string]$ProjectRoot,
        [int]$TimeoutSeconds = 120
    )

    if (Test-HttpEndpoint -Uri $ReadyUri) {
        Write-Host "$Name is already ready: $ReadyUri"
        return
    }

    $runtimeDir = Join-Path $ProjectRoot '.runtime\dev'
    $logDir = Join-Path $runtimeDir 'logs'
    New-Item -ItemType Directory -Force -Path $logDir | Out-Null
    $stdout = Join-Path $logDir "$Name.out.log"
    $stderr = Join-Path $logDir "$Name.err.log"
    $process = Start-Process -FilePath 'powershell.exe' `
        -ArgumentList @('-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', $ScriptPath) `
        -WorkingDirectory $ProjectRoot `
        -WindowStyle Hidden `
        -RedirectStandardOutput $stdout `
        -RedirectStandardError $stderr `
        -PassThru
    Set-Content -LiteralPath (Join-Path $runtimeDir "$Name.pid") -Value $process.Id

    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        if (Test-HttpEndpoint -Uri $ReadyUri) {
            Write-Host "$Name is ready: $ReadyUri"
            return
        }
        if ($process.HasExited) {
            $details = Get-Content -LiteralPath $stderr -Tail 40 -ErrorAction SilentlyContinue
            throw "$Name exited before becoming ready.`n$($details -join [Environment]::NewLine)"
        }
        Start-Sleep -Seconds 1
    }
    throw "$Name did not become ready within $TimeoutSeconds seconds. See $stderr."
}

function Stop-ManagedProcess {
    param(
        [Parameter(Mandatory = $true)][string]$Name,
        [Parameter(Mandatory = $true)][string]$ProjectRoot
    )

    $runtimeDir = [IO.Path]::GetFullPath((Join-Path $ProjectRoot '.runtime\dev'))
    $pidFile = [IO.Path]::GetFullPath((Join-Path $runtimeDir "$Name.pid"))
    if (-not $pidFile.StartsWith($runtimeDir, [StringComparison]::OrdinalIgnoreCase)) {
        throw "Refusing to read PID outside project runtime: $pidFile"
    }
    if (-not (Test-Path -LiteralPath $pidFile)) {
        Write-Host "$Name has no managed PID file; leaving external processes unchanged."
        return
    }

    $managedPid = [int](Get-Content -LiteralPath $pidFile -Raw).Trim()
    try {
        $rootProcess = Get-CimInstance Win32_Process -Filter "ProcessId = $managedPid" -ErrorAction Stop
    } catch {
        throw "Cannot inspect managed PID $managedPid for $Name. Run dev-stop.ps1 from an elevated PowerShell."
    }
    if ($null -eq $rootProcess) {
        Remove-Item -LiteralPath $pidFile
        Write-Host "$Name is already stopped."
        return
    }
    $commandLine = [string]$rootProcess.CommandLine
    if ($commandLine.IndexOf($ProjectRoot, [StringComparison]::OrdinalIgnoreCase) -lt 0) {
        throw "Refusing to stop PID $managedPid because its command line is outside this project."
    }

    $ordered = New-Object System.Collections.Generic.List[int]
    function Add-Descendants([int]$ParentPid) {
        $children = Get-CimInstance Win32_Process -Filter "ParentProcessId = $ParentPid" -ErrorAction Stop
        foreach ($child in $children) {
            Add-Descendants -ParentPid ([int]$child.ProcessId)
            $ordered.Add([int]$child.ProcessId)
        }
    }
    Add-Descendants -ParentPid $managedPid
    $ordered.Add($managedPid)
    foreach ($processId in $ordered) {
        Stop-Process -Id $processId -Force -ErrorAction SilentlyContinue
    }
    Remove-Item -LiteralPath $pidFile
    Write-Host "$Name stopped."
}
