# Windows 本地开发环境

本文以 Windows PowerShell 为主，目标是让项目配置与其他项目的系统环境变量隔离。

## 1. 端口约定

| 服务 | 本机端口 | 容器端口 |
| --- | ---: | ---: |
| MySQL | 3307 | 3306 |
| Redis | 6380 | 6379 |
| PostgreSQL + pgvector | 5432 | 5432 |
| Kafka | 9092 | 9092 |
| Ollama | 11434 | 11434 |
| TEI Reranker | 8081 | 80 |
| Java API | 8080 | 8080 |
| Python Agent | 8000 | 8000 |
| 客服/管理前端 | 5173 | 5173 |
| Prometheus | 9090 | 9090 |
| Grafana | 3000 | 3000 |

Java API 的上下文路径是 `/api`，例如：

```text
http://127.0.0.1:8080/api/actuator/health
```

## 2. 必需软件

- JDK 21
- Python 3.11 或 3.12
- Node.js 20
- Docker Desktop 与 WSL2，或专用 Ubuntu VMware，用于 PostgreSQL/pgvector、Kafka 和本地模型

本机 Maven Wrapper 会依次读取：

1. `AFTERSALES_JAVA_HOME`
2. 项目根 `.java-home.local`
3. `JAVA_HOME`

选中的 JDK 必须是 21。

## 3. 首次配置

在项目根目录执行：

```powershell
Copy-Item .env.example .env
Copy-Item python_agent/.env.example python_agent/.env
Copy-Item src/main/resources/application-local.example.yml src/main/resources/application-local.yml
Set-Content .java-home.local 'D:\java21'
```

然后编辑本地文件：

- `.env`：数据库、Redis、Kafka、Agent 和共享内部 Token。
- `python_agent/.env`：LLM、Embedding、Vision、Reranker、pgvector DSN。
- `application-local.yml`：只放本机 Spring 覆盖项。

这些文件均被 `.gitignore` 排除。不得把真实密码、API Key 或 Token 写入可提交文件。

`AGENT_INTERNAL_TOKEN` 必须在项目根 `.env`、`python_agent/.env` 和 Java 本地配置中一致。

## 4. 配置优先级与环境隔离

Spring Boot 的外部环境变量优先级高于 `application.yml`。如果父 PowerShell 继承了其他项目的以下变量，Java 会被重定向到错误端口或数据库：

```text
SPRING_CONFIG_ADDITIONAL_LOCATION
SPRING_DATASOURCE_*
SPRING_DATA_REDIS_*
SPRING_KAFKA_BOOTSTRAP_SERVERS
SERVER_PORT
MANAGEMENT_SERVER_PORT
```

请使用项目脚本启动：

```powershell
.\scripts\start-backend.ps1
```

该脚本执行以下操作：

1. 只在当前子进程清除上述继承变量。
2. 从项目根 `.env` 重新加载配置，并覆盖同名进程变量。
3. 固定 `SPRING_PROFILES_ACTIVE=local`。
4. 将项目变量映射到 Spring 标准变量。
5. 使用 JDK 21 Maven Wrapper 启动应用。

脚本不会修改 User 或 Machine 级 Windows 环境变量。

Python Agent 使用：

```powershell
.\scripts\start-agent.ps1
```

它先加载项目根 `.env`，再加载 `python_agent/.env`；Agent 专用配置优先。

## 5. 基础设施启动

完整环境使用仓库现有 Compose：

```powershell
docker compose config
docker compose up -d mysql redis postgres kafka
docker compose --profile local-ai up -d ollama reranker
docker compose ps
```

Compose 从项目根 `.env` 读取本机映射端口。容器之间仍使用 MySQL 3306、Redis 6379、Kafka 29092 和 PostgreSQL 5432。

`local-ai` profile 提供完全本地的模型链路：

- `qwen2.5:3b`：文本生成、结构化输出和原生 Tool Calling；
- `bge-m3`：OpenAI compatible Embedding，固定输出 1024 维；
- `BAAI/bge-reranker-v2-m3`：Hugging Face TEI `/rerank` 精排服务。

Ollama 默认允许文本模型与 Embedding 模型同时驻留，避免 RAG 请求在两个模型之间反复换载。当前 4 vCPU 环境使用单并发，并将本地 CPU 推理读取超时设为 240 秒、单次总超时设为 300 秒。TEI 将批处理令牌限制为 4096，Agent 每次精排 5 个 RRF 候选并等待 30 秒，以适配 8 GB 内存的 CPU 虚拟机。

在 4 vCPU 的纯 CPU 验收环境中，Java 网关需要给完整文本链路预留 300 秒：

```dotenv
# .env
AGENT_TIMEOUT_MILLIS=300000
MINIAPP_AGENT_REQUEST_TIMEOUT_MILLIS=330000
```

客户端超时比 Java 网关多 30 秒，用于接收网关的终态或错误事件；不要把客户端超时设得比网关更短。

聊天入口默认先执行一次 LLM 情绪分类。只验收政策 RAG 时，可在本机 `python_agent/.env` 关闭这次可选的前置调用；独立情绪分析接口和正式环境默认行为不受影响：

```dotenv
CHAT_EMOTION_ANALYSIS_ENABLED=false
```

当前机器的真实政策咨询请求耗时 141.35 秒，其中严格 Embedding + pgvector + Reranker 约 25 秒，其余主要为 `qwen2.5:3b` 回答生成。该数字只代表当前 4 vCPU VM，不是生产容量指标。

Windows 原生 MySQL/Redis 使用被 Git 忽略的 `.runtime` 数据与配置，二进制路径只写入项目 `.env`：

```powershell
.\scripts\start-windows-infra.ps1
```

新电脑优先使用 Docker Compose；原生 Windows 模式要求先准备 `.runtime/mysql-local.ini`、`.runtime/redis-local.conf` 与已有数据目录。完整 AI/RAG 验收仍必须同时提供 PostgreSQL/pgvector、Kafka、Ollama 和 Reranker。

## 6. 应用启动顺序

```text
MySQL / Redis / PostgreSQL / Kafka
→ Python Agent
→ Java
→ Vue 前端
→ Python Kafka Review Consumer
→ Prometheus / Grafana
```

### 一键启动与停止

根 `.env` 设置 `LOCAL_INFRA_MODE=Auto|Docker|Vm|Existing`。当前机器使用 `Vm`，并配置 VM 地址、SSH key 和 Windows MySQL/Redis 可执行文件路径。然后运行：

```powershell
.\scripts\dev-start.ps1
```

脚本会启动或检查 Windows MySQL/Redis，通过 SSH 启动 VM 容器，等待六个基础设施端点，再依次启动 Agent、Java、Vue 和 Review Consumer。PID 与日志写入 `.runtime/dev`。

默认停止应用与本次环境的 Docker/VM 基础设施，但不删除数据卷：

```powershell
.\scripts\dev-stop.ps1
```

只停止应用并保留基础设施：

```powershell
.\scripts\dev-stop.ps1 -KeepInfrastructure
```

停止脚本只处理 `.runtime/dev/*.pid` 记录且命令行属于当前项目的进程树。已经由其他方式启动的 Windows MySQL/Redis 不会被接管或误停。原生数据库只通过 `mysqladmin` / `redis-cli` 正常关闭，失败时不会强杀。VM 启停必须使用拥有 `.runtime/vm/id_ed25519` 的同一 Windows 用户。

分进程启动示例：

```powershell
# Terminal 1
.\scripts\start-agent.ps1

# Terminal 2
.\scripts\start-backend.ps1

# Terminal 3
.\scripts\start-frontend.ps1
```

Python Kafka Consumer：

```powershell
.\scripts\start-review-consumer.ps1
```

该脚本与 Agent 启动脚本使用相同的项目配置隔离：先加载根 `.env`，再加载 `python_agent/.env`，最后使用项目 `.venv` 启动。

### Docker Desktop 不可用时使用 VMware

当前机器的 Docker Desktop Engine 可能因 Windows 残留 Unix socket 无法启动。此时 PostgreSQL/pgvector、Kafka、Ollama 和 TEI Reranker 可运行在专用 Ubuntu 24.04 VMware VM 中，Windows 继续运行 Java、Python、Vue、MySQL 和 Redis。

当前 VM 名称为 `EcommerceAfterSalesInfra`，配置为 4 vCPU、8 GB 内存、60 GB 磁盘。VM 内 Compose 目录是：

```text
/opt/ecommerce-after-sales-system
```

VM 使用 NAT DHCP。每次启动后先确认地址：

```powershell
ssh.exe -i .runtime\vm\id_ed25519 `
  -o UserKnownHostsFile=.runtime\vm\known_hosts `
  -o StrictHostKeyChecking=yes `
  codex@192.168.100.130 "hostname -I"
```

如果地址变化，同时更新项目根 `.env` 和 `python_agent/.env` 中的 PostgreSQL、Kafka DSN/Host；不要修改系统全局环境变量。VM 内启动和检查：

```powershell
ssh.exe -i .runtime\vm\id_ed25519 `
  -o UserKnownHostsFile=.runtime\vm\known_hosts `
  -o StrictHostKeyChecking=yes `
  codex@192.168.100.130 `
  "cd /opt/ecommerce-after-sales-system && docker compose --profile local-ai up -d postgres kafka ollama reranker && docker compose ps"
```

`.runtime/vm` 包含当前电脑的私钥与 known_hosts，已被 Git 忽略，不应提交。

首次下载本地模型后执行：

```powershell
Invoke-RestMethod http://192.168.100.130:11434/api/tags
Invoke-WebRequest -UseBasicParsing http://192.168.100.130:8081/health
```

VM 只有 8 GB 内存时建议配置 4 GB swap，避免三个 CPU 模型首次加载时因瞬时内存不足退出。

## 7. 基础验证

### MySQL

```powershell
mysql --protocol=tcp -h 127.0.0.1 -P 3307 -u ecommerce -p ecommerce_aftersales
```

期望至少存在 15 张业务表。

### Redis

```powershell
redis-cli -h 127.0.0.1 -p 6380 PING
```

期望返回 `PONG`。

### PostgreSQL 与 pgvector

```powershell
docker compose exec postgres psql -U postgres -d after_sales_rag -c "SELECT extname FROM pg_extension WHERE extname IN ('vector','pg_trgm') ORDER BY extname;"
docker compose exec postgres psql -U postgres -d after_sales_rag -c "SELECT format_type(atttypid, atttypmod) FROM pg_attribute WHERE attrelid='knowledge_chunk'::regclass AND attname='embedding';"
```

期望扩展包含 `vector`、`pg_trgm`，向量列类型为 `vector(1024)`。

### Kafka

```powershell
docker compose exec kafka kafka-topics --bootstrap-server kafka:29092 --list
```

最终验收必须包含真实 producer/consumer 消息，只有端口监听不算通过。

### Java 与 Agent

```powershell
Invoke-WebRequest -UseBasicParsing http://127.0.0.1:8000/api/health
Invoke-WebRequest -UseBasicParsing http://127.0.0.1:8080/api/agent/health
Invoke-WebRequest -UseBasicParsing http://127.0.0.1:8080/api/actuator/health
```

完整依赖启动后，Actuator 应返回 200 与 `UP`。PostgreSQL 未启动时返回 503 是依赖健康检查的真实结果。

### 知识库重建与检索

Agent 健康后运行：

```powershell
.\python_agent\setup_knowledge_base.ps1
```

该脚本调用 Agent 的受保护 reindex API。服务会先生成全部 Embedding，再锁定并校验源文档版本，最后替换对应发布 chunk；不会使用旧脚本的“先清空后逐批生成”流程。

## 8. 构建与测试

```powershell
.\mvnw.cmd test

.\.venv\Scripts\python.exe -m pytest -q python_agent/tests

Set-Location frontend/staff-auth-test-ui
npm run test:contracts
$env:VITE_API_BASE_URL='http://127.0.0.1:8080/api'
npm run build

Set-Location ../uniapp
npm run build:mp-weixin
```

Docker Desktop 不可用且 `.env` 已配置 VM 时，运行完整 Testcontainers 门禁：

```powershell
.\scripts\run-vm-testcontainers.ps1
```

只运行 Java 或 Python Redis 门禁：

```powershell
.\scripts\run-vm-testcontainers.ps1 -Suite Java
.\scripts\run-vm-testcontainers.ps1 -Suite PythonRedis
```

脚本把 VM Docker Unix socket 临时代理到 VM 回环地址，再通过 SSH 映射到 Windows `127.0.0.1:23750`。执行结束后会恢复当前进程环境变量，并清理隧道和代理。定向排查单个 Java 测试可增加 `-MavenTest AfterSalesTicketMapperMySqlTest`。

Testcontainers 被跳过与测试通过是不同证据，验收报告必须分别记录。

## 9. 常见问题

### 应用连接到了 `root@127.0.0.1`

检查是否绕过了 `scripts/start-backend.ps1`，以及父进程是否设置了 `SPRING_CONFIG_ADDITIONAL_LOCATION` 或 `SPRING_DATASOURCE_*`。

### 应用意外启动在 8081/9091

父进程存在 `SERVER_PORT` 或 `MANAGEMENT_SERVER_PORT`。项目脚本会清除并从 `.env` 重新设置为 8080。

### Actuator 返回 503

读取启动日志确认具体 DOWN 组件。当前完整健康检查包含 PostgreSQL，不能用“核心接口 200”替代整体健康状态。

### 前端生产构建拒绝启动

客服前端要求显式 `VITE_API_BASE_URL`，避免生产包静默使用 mock adapter。
