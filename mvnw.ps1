$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path

function Get-ProjectJavaHome {
    $candidates = @()

    if ($env:AFTERSALES_JAVA_HOME) {
        $candidates += $env:AFTERSALES_JAVA_HOME
    }

    $localConfig = Join-Path $projectRoot ".java-home.local"
    if (Test-Path $localConfig) {
        $candidates += (Get-Content $localConfig -TotalCount 1).Trim()
    }

    if ($env:JAVA_HOME) {
        $candidates += $env:JAVA_HOME
    }

    foreach ($candidate in $candidates) {
        if (-not $candidate) {
            continue
        }

        $normalized = $candidate.Trim('"').Trim()
        $javaExe = Join-Path $normalized "bin\java.exe"
        $releaseFile = Join-Path $normalized "release"

        if (-not (Test-Path $javaExe) -or -not (Test-Path $releaseFile)) {
            continue
        }

        $releaseLine = Get-Content $releaseFile | Where-Object { $_ -like "JAVA_VERSION=*" } | Select-Object -First 1
        if (-not $releaseLine) {
            continue
        }

        $javaVersion = ($releaseLine -split "=", 2)[1].Trim('"')
        if ($javaVersion -like "21*") {
            return $normalized
        }
    }

    return $null
}

function Get-JavaVersion {
    param(
        [Parameter(Mandatory = $true)]
        [string]$JavaHome
    )

    $releaseFile = Join-Path $JavaHome "release"
    if (-not (Test-Path $releaseFile)) {
        return $null
    }

    $releaseLine = Get-Content $releaseFile | Where-Object { $_ -like "JAVA_VERSION=*" } | Select-Object -First 1
    if (-not $releaseLine) {
        return $null
    }

    return (($releaseLine -split "=", 2)[1]).Trim('"')
}

$resolvedJavaHome = Get-ProjectJavaHome
if (-not $resolvedJavaHome) {
    Write-Error "JDK 21 is not configured for this project. Create .java-home.local in the project root or set AFTERSALES_JAVA_HOME."
    exit 1
}

$javaVersion = Get-JavaVersion -JavaHome $resolvedJavaHome
if (-not $javaVersion) {
    Write-Error "Cannot detect JAVA_VERSION from $resolvedJavaHome."
    exit 1
}

if ($javaVersion -notlike "21*") {
    Write-Error "This project requires JDK 21, but found $javaVersion."
    exit 1
}

$env:JAVA_HOME = $resolvedJavaHome
$env:Path = "$resolvedJavaHome\bin;$env:Path"

$mavenCmd = Get-Command mvn.cmd -ErrorAction SilentlyContinue
if ($mavenCmd) {
    & $mavenCmd.Source @args
} else {
    & mvn @args
}

exit $LASTEXITCODE
