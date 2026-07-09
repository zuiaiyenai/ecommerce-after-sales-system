# Initialize the local PostgreSQL/pgvector knowledge base.
# Run from the repository root or from python_agent:
#   powershell -ExecutionPolicy Bypass -File python_agent\setup_knowledge_base.ps1

param(
    [string]$ContainerName = $env:PGVECTOR_CONTAINER
)

$ErrorActionPreference = "Stop"

if (-not $ContainerName) {
    $ContainerName = "ecommerce-pgvector"
}

$ProjectRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
$EnvFile = Join-Path $PSScriptRoot "db.local.env"
$SchemaFile = Join-Path $ProjectRoot "sql\pgvector_schema.sql"
$BaseSeedFile = Join-Path $ProjectRoot "sql\seed_knowledge_base.sql"
$ExtendedSeedFile = Join-Path $ProjectRoot "sql\seed_extended_after_sales_knowledge.sql"

function Test-HostPsql {
    return [bool](Get-Command psql -ErrorAction SilentlyContinue)
}

function Test-DockerCli {
    return [bool](Get-Command docker -ErrorAction SilentlyContinue)
}

function Import-LocalEnv {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Path
    )

    if (-not (Test-Path -LiteralPath $Path)) {
        Write-Host "Missing local env file: $Path" -ForegroundColor Red
        exit 1
    }

    foreach ($rawLine in Get-Content -LiteralPath $Path) {
        $line = $rawLine.Trim()
        if (-not $line -or $line.StartsWith("#") -or -not $line.Contains("=")) {
            continue
        }
        $parts = $line.Split("=", 2)
        $key = $parts[0].Trim()
        $value = $parts[1].Trim().Trim('"').Trim("'")
        if ($key) {
            Set-Item -Path "Env:$key" -Value $value
        }
    }
}

function Invoke-PgSqlCommand {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Sql
    )

    $env:PGPASSWORD = "ecommerce_pgvector"
    if (Test-HostPsql) {
        & psql -v ON_ERROR_STOP=1 -h localhost -p 5432 -U ecommerce -d ecommerce_rag -c $Sql
    } elseif (Test-DockerCli) {
        & docker exec $ContainerName psql -v ON_ERROR_STOP=1 -U ecommerce -d ecommerce_rag -c $Sql
    } else {
        Write-Host "Missing psql and docker. Install Docker Desktop or PostgreSQL client first." -ForegroundColor Red
        exit 1
    }

    if ($LASTEXITCODE -ne 0) {
        throw "PostgreSQL command failed."
    }
}

function Invoke-PgSqlFile {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Path
    )

    $env:PGPASSWORD = "ecommerce_pgvector"
    if (Test-HostPsql) {
        & psql -v ON_ERROR_STOP=1 -h localhost -p 5432 -U ecommerce -d ecommerce_rag -f $Path
    } elseif (Test-DockerCli) {
        $containerPath = "/tmp/" + [System.IO.Path]::GetFileName($Path)
        & docker cp $Path "${ContainerName}:$containerPath"
        if ($LASTEXITCODE -ne 0) {
            throw "Failed to copy SQL file into container: $Path"
        }
        & docker exec $ContainerName psql -v ON_ERROR_STOP=1 -U ecommerce -d ecommerce_rag -f $containerPath
    } else {
        Write-Host "Missing psql and docker. Install Docker Desktop or PostgreSQL client first." -ForegroundColor Red
        exit 1
    }

    if ($LASTEXITCODE -ne 0) {
        throw "PostgreSQL file execution failed: $Path"
    }
}

function Invoke-PythonScript {
    param(
        [Parameter(Mandatory = $true)]
        [string]$ScriptPath
    )

    if (Get-Command python -ErrorAction SilentlyContinue) {
        & python $ScriptPath
    } elseif (Get-Command py -ErrorAction SilentlyContinue) {
        & py -3 $ScriptPath
    } else {
        Write-Host "Missing Python. Install Python 3.11+ and make python or py available in PATH." -ForegroundColor Red
        exit 1
    }

    if ($LASTEXITCODE -ne 0) {
        throw "Python script failed: $ScriptPath"
    }
}

Write-Host "==========================================" -ForegroundColor Cyan
Write-Host "After-sales knowledge base initialization" -ForegroundColor Cyan
Write-Host "==========================================" -ForegroundColor Cyan

Write-Host ""
Write-Host "Loading local env: $EnvFile" -ForegroundColor Yellow
Import-LocalEnv -Path $EnvFile

Write-Host ""
Write-Host "Checking PostgreSQL connection..." -ForegroundColor Yellow
Invoke-PgSqlCommand "SELECT 1;"
Write-Host "PostgreSQL connection OK" -ForegroundColor Green

Write-Host ""
Write-Host "Applying pgvector schema..." -ForegroundColor Yellow
Invoke-PgSqlFile $SchemaFile

Write-Host ""
Write-Host "Resetting knowledge tables..." -ForegroundColor Yellow
Invoke-PgSqlCommand "TRUNCATE TABLE knowledge_document CASCADE;"

Write-Host ""
Write-Host "Importing knowledge documents..." -ForegroundColor Yellow
Invoke-PgSqlFile $BaseSeedFile
Invoke-PgSqlFile $ExtendedSeedFile
Write-Host "Knowledge documents imported" -ForegroundColor Green

$hasEmbeddingKey = [bool]$env:DASHSCOPE_API_KEY -or [bool]$env:BAILIAN_API_KEY
if (-not $hasEmbeddingKey) {
    Write-Host ""
    Write-Host "DASHSCOPE_API_KEY/BAILIAN_API_KEY is missing in db.local.env." -ForegroundColor Yellow
    Write-Host "Vector chunks will not be generated. Lexical fallback can still read knowledge_document." -ForegroundColor Yellow
    Write-Host "Continue without embeddings? [y/N]" -ForegroundColor Yellow
    $continue = Read-Host
    if ($continue -ne "y" -and $continue -ne "Y") {
        exit 0
    }
    $skipEmbedding = $true
} else {
    $skipEmbedding = $false
}

if (-not $skipEmbedding) {
    Write-Host ""
    Write-Host "Generating vector embeddings..." -ForegroundColor Yellow
    Push-Location $PSScriptRoot
    try {
        Invoke-PythonScript ".\ingest_pgvector_knowledge.py"
    } finally {
        Pop-Location
    }
    Write-Host "Vector embeddings generated" -ForegroundColor Green
}

Write-Host ""
Write-Host "Knowledge document stats:" -ForegroundColor Cyan
Invoke-PgSqlCommand @"
SELECT source_type, COUNT(*) AS document_count
FROM knowledge_document
WHERE status = 1
GROUP BY source_type
ORDER BY source_type;
"@

if (-not $skipEmbedding) {
    Write-Host ""
    Write-Host "Knowledge chunk stats:" -ForegroundColor Cyan
    Invoke-PgSqlCommand "SELECT COUNT(*) AS chunk_count FROM knowledge_chunk;"
}

Write-Host ""
Write-Host "Knowledge base initialization complete." -ForegroundColor Green
