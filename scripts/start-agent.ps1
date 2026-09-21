$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$projectRoot = Split-Path -Parent $PSScriptRoot
$agentRoot = Join-Path $projectRoot 'python_agent'
$python = Join-Path $projectRoot '.venv\Scripts\python.exe'
. (Join-Path $PSScriptRoot 'Import-DotEnv.ps1')

Import-DotEnv -Path (Join-Path $projectRoot '.env')
Import-DotEnv -Path (Join-Path $agentRoot '.env')

if (-not (Test-Path -LiteralPath $python)) {
    throw "Project virtual environment not found: $python"
}

Set-Location -LiteralPath $agentRoot
& $python -m after_sales_agent.interface.http_server @args
exit $LASTEXITCODE
