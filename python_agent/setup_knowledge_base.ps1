# 售后知识库初始化脚本 (Windows PowerShell)

Write-Host "==========================================" -ForegroundColor Cyan
Write-Host "售后知识库初始化" -ForegroundColor Cyan
Write-Host "==========================================" -ForegroundColor Cyan

$pgHost = $env:PGVECTOR_HOST
if ([string]::IsNullOrWhiteSpace($pgHost)) { $pgHost = "127.0.0.1" }
$pgPort = $env:PGVECTOR_PORT
if ([string]::IsNullOrWhiteSpace($pgPort)) { $pgPort = "5432" }
$pgDatabase = $env:PGVECTOR_DATABASE
if ([string]::IsNullOrWhiteSpace($pgDatabase)) { $pgDatabase = "after_sales_rag" }
$pgUser = $env:PGVECTOR_USERNAME
if ([string]::IsNullOrWhiteSpace($pgUser)) { $pgUser = "postgres" }
$pgPassword = $env:PGVECTOR_PASSWORD
if ([string]::IsNullOrWhiteSpace($pgPassword)) { $pgPassword = "local-dev-password" }
$psqlConnectionArgs = @("-h", $pgHost, "-p", $pgPort, "-U", $pgUser, "-d", $pgDatabase)
$env:PGPASSWORD = $pgPassword

# 检查PostgreSQL连接
Write-Host ""
Write-Host "检查PostgreSQL连接..." -ForegroundColor Yellow
$testConnection = & psql @psqlConnectionArgs -c "SELECT 1;" 2>&1
if ($LASTEXITCODE -ne 0) {
    Write-Host "❌ 无法连接到PostgreSQL，请检查：" -ForegroundColor Red
    Write-Host "  1. PostgreSQL服务是否启动" -ForegroundColor Red
    Write-Host "  2. 数据库$pgDatabase是否存在" -ForegroundColor Red
    Write-Host "  3. 用户$pgUser权限是否正确" -ForegroundColor Red
    exit 1
}
Write-Host "✓ PostgreSQL连接正常" -ForegroundColor Green

# 步骤1: 导入知识库数据
Write-Host ""
Write-Host "步骤1: 导入知识库文档..." -ForegroundColor Yellow
& psql @psqlConnectionArgs -f ..\sql\seed_knowledge_base.sql
if ($LASTEXITCODE -eq 0) {
    Write-Host "✓ 知识库文档导入完成" -ForegroundColor Green
} else {
    Write-Host "❌ 知识库文档导入失败" -ForegroundColor Red
    exit 1
}

# 步骤2: 检查DASHSCOPE_API_KEY
Write-Host ""
Write-Host "步骤2: 检查Embedding配置..." -ForegroundColor Yellow
if (-not (Test-Path "db.local.env")) {
    Write-Host "❌ 未找到db.local.env文件" -ForegroundColor Red
    exit 1
}

$envContent = Get-Content "db.local.env" -Raw
if ($envContent -notmatch "DASHSCOPE_API_KEY\s*=\s*sk-") {
    Write-Host "⚠️  警告：DASHSCOPE_API_KEY未配置或被注释" -ForegroundColor Yellow
    Write-Host "   请在db.local.env中配置：DASHSCOPE_API_KEY=sk-your-key" -ForegroundColor Yellow
    Write-Host ""
    Write-Host "是否继续？(将跳过向量生成) [y/N]" -ForegroundColor Yellow
    $continue = Read-Host
    if ($continue -ne "y" -and $continue -ne "Y") {
        exit 0
    }
    $skipEmbedding = $true
} else {
    $skipEmbedding = $false
}

# 步骤3: 生成向量embeddings
if (-not $skipEmbedding) {
    Write-Host ""
    Write-Host "步骤3: 生成向量embeddings..." -ForegroundColor Yellow
    Write-Host "   这可能需要几分钟，请耐心等待..." -ForegroundColor Gray
    python ingest_pgvector_knowledge.py
    if ($LASTEXITCODE -eq 0) {
        Write-Host "✓ 向量embeddings生成完成" -ForegroundColor Green
    } else {
        Write-Host "❌ 向量embeddings生成失败" -ForegroundColor Red
        exit 1
    }
} else {
    Write-Host ""
    Write-Host "步骤3: 跳过向量生成" -ForegroundColor Yellow
}

# 步骤4: 查看结果
Write-Host ""
Write-Host "步骤4: 查看知识库统计..." -ForegroundColor Yellow
Write-Host ""
Write-Host "知识库文档统计：" -ForegroundColor Cyan
& psql @psqlConnectionArgs -c "
SELECT
    source_type as 类型,
    COUNT(*) as 文档数
FROM knowledge_document
WHERE status = 1
GROUP BY source_type
ORDER BY source_type;
"

if (-not $skipEmbedding) {
    Write-Host ""
    Write-Host "向量chunk统计：" -ForegroundColor Cyan
    & psql @psqlConnectionArgs -c "
    SELECT COUNT(*) as 总chunk数 FROM knowledge_chunk;
    "
}

Write-Host ""
Write-Host "==========================================" -ForegroundColor Cyan
Write-Host "知识库初始化完成！" -ForegroundColor Green
Write-Host "==========================================" -ForegroundColor Cyan

if ($skipEmbedding) {
    Write-Host ""
    Write-Host "⚠️  提醒：向量embeddings未生成，AI将无法检索知识库" -ForegroundColor Yellow
    Write-Host "   请配置DASHSCOPE_API_KEY后重新运行此脚本" -ForegroundColor Yellow
}
