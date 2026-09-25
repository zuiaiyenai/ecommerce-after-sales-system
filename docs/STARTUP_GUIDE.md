# 本地启动指南

本指南面向第一次拿到仓库的开发者。项目支持 Docker、VMware 混合环境和复用已有基础设施三种模式；实际连接信息统一写入未跟踪的本地配置。

## 1. 环境要求

| 工具 | 建议版本 | 用途 |
| --- | --- | --- |
| JDK | 21 | Spring Boot |
| Maven | 使用仓库 Wrapper | Java 构建与测试 |
| Python | 3.11/3.12 | Agent 与 Review Consumer |
| Node.js | 20 | Vue 与 uni-app |
| Docker | Docker Desktop/WSL2 或 Ubuntu VM | PostgreSQL、Kafka、模型与监控 |
| 微信开发者工具 | 当前稳定版 | 小程序真机/模拟器调试 |

## 2. 本地配置

在仓库根目录执行：

```powershell
Copy-Item .env.example .env
Copy-Item python_agent/.env.example python_agent/.env
Copy-Item src/main/resources/application-local.example.yml src/main/resources/application-local.yml
```

如 `JAVA_HOME` 不是 JDK 21，创建被忽略的 `.java-home.local`：

```powershell
Set-Content .java-home.local 'D:\path\to\jdk-21'
```

需要核对的关键变量：

- MySQL：`MYSQL_HOST_PORT`、`DB_USERNAME`、`DB_PASSWORD`
- Redis：`REDIS_HOST`、`REDIS_PORT`
- PostgreSQL：`PGVECTOR_HOST`、`PGVECTOR_PORT`、DSN
- Kafka：`KAFKA_BOOTSTRAP_SERVERS`
- 模型：`OLLAMA_BASE_URL`、`RERANK_BASE_URL`
- 内部鉴权：根配置、Java 与 Python 使用同一个 `AGENT_INTERNAL_TOKEN`
- 基础设施模式：`LOCAL_INFRA_MODE=Auto|Docker|Vm|Existing`

`.env`、`python_agent/.env`、`application-local.yml` 和 `.java-home.local` 都不能提交。

## 3. 推荐一键启动

```powershell
.\scripts\dev-start.ps1 -InfraMode Auto
```

脚本执行顺序：

```text
1. MySQL / Redis / PostgreSQL / Kafka
2. Ollama / Reranker
3. Python Agent
4. Spring Boot
5. Vue 客服与管理端
6. Python Review Consumer
7. Prometheus / Grafana（VM 模式且已启用）
```

脚本会等待端口和健康端点，再返回成功。PID 与日志写入被忽略的 `.runtime/dev/`。

## 4. 分步启动

### 4.1 基础设施

Docker 模式：

```powershell
docker compose --profile local-ai up -d mysql redis postgres kafka ollama reranker
docker compose ps
```

Windows 原生 MySQL/Redis 加 VMware 模式：

```powershell
.\scripts\start-windows-infra.ps1
.\scripts\dev-start.ps1 -InfraMode Vm
```

`Existing` 模式要求配置中的六个端点已经可达，脚本不会创建这些服务。

### 4.2 Python Agent

首次安装：

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r python_agent\requirements.txt
```

启动：

```powershell
.\scripts\start-agent.ps1
```

成功标志：`GET http://127.0.0.1:8000/api/health` 返回 `ok=true`。

### 4.3 Spring Boot

```powershell
.\scripts\start-backend.ps1
```

启动时 Flyway 对主 MySQL 数据源执行 `src/main/resources/db/migration/`。已有非空库会以版本 `0` 建立基线，再执行后续迁移。

成功标志：`GET http://127.0.0.1:8080/api/actuator/health` 返回 `UP`。

### 4.4 Review Consumer

```powershell
.\scripts\start-review-consumer.ps1
```

成功标志：`GET http://127.0.0.1:8001/metrics` 返回 Prometheus 文本。

### 4.5 客服与管理端

```powershell
.\scripts\start-frontend.ps1
```

访问 `http://127.0.0.1:5173/`。

### 4.6 微信小程序

```powershell
Set-Location frontend\uniapp
npm ci
npm run build:mp-weixin
```

在微信开发者工具中导入：

```text
frontend/uniapp/dist/build/mp-weixin
```

本地开发可以使用 `touristappid`；地图瓦片、上传等平台能力需要正式 AppID 和对应权限才能完整验收。

## 5. 端口与健康检查

基础设施端口以 `.env` 为准；Compose 容器内部仍使用标准端口。

| 服务 | 常用本机端口 | 检查方式 |
| --- | ---: | --- |
| Java | 8080 | `/api/actuator/health` |
| Python Agent | 8000 | `/api/health` |
| Review Consumer | 8001 | `/metrics` |
| Vue | 5173 | 浏览器打开首页 |
| PostgreSQL | 5432 | TCP / `pg_isready` |
| Kafka | 9092 | TCP / topic list |
| Ollama | 11434 | `/api/tags` |
| Reranker | 8081 | `/health` |
| Prometheus | 9090 | `/-/ready` 与 Targets |
| Grafana | 3000 | `/api/health` |

PowerShell 快速检查：

```powershell
Invoke-RestMethod http://127.0.0.1:8080/api/actuator/health
Invoke-RestMethod http://127.0.0.1:8000/api/health
Invoke-WebRequest -UseBasicParsing http://127.0.0.1:8001/metrics
```

## 6. 测试命令

```powershell
# Java
.\mvnw.cmd test

# Python（与 CI 一致）
Set-Location python_agent
..\.venv\Scripts\python.exe -m pytest tests -q
..\.venv\Scripts\python.exe tools\evaluate_agent_safety.py --check

# 客服与管理端
Set-Location frontend\staff-auth-test-ui
npm ci
npm run test:contracts
npm run build

# 小程序
Set-Location ..\uniapp
npm ci
npm run build:mp-weixin
```

## 7. 安全停止

```powershell
.\scripts\dev-stop.ps1
```

只停止应用并保留基础设施：

```powershell
.\scripts\dev-stop.ps1 -KeepInfrastructure
```

脚本只处理项目记录的进程。Windows MySQL 使用 `mysqladmin shutdown` 安全关闭；关闭失败时不会强制终止进程。

## 8. 常见问题

### Java 连到错误数据库

使用 `scripts/start-backend.ps1`。脚本会清理继承自其他项目的 `SPRING_DATASOURCE_*` 等变量，并重新加载本项目 `.env`。

### MySQL 表缺失或 Flyway 失败

先查看 Java 启动日志和 `flyway_schema_history`。不要手工修改已成功执行迁移的 checksum；修复应新增迁移。

### Kafka 能连端口但消费失败

检查 broker 广播地址。VM 模式的 `KAFKA_ADVERTISED_HOST` 必须是 Windows 可访问的 VM NAT 地址。

### Agent 502 或超时

依次检查 Agent health、Ollama 模型、pgvector、Reranker 和 Java 的 `AGENT_TIMEOUT_MILLIS`。模型异常时系统应转人工并持久化状态，不应在前端伪造 AI 响应。

### 微信小程序请求失败

确认 Java 监听 `0.0.0.0:8080`、小程序请求域名/不校验合法域名设置，以及 `frontend/uniapp/src/utils/request.js` 的本地 API 地址与当前机器一致。
