# Enterprise Sales Copilot

面向 B2B 销售团队的企业 AI 助手。当前实现 **M1 工程基础**：React 工作台、FastAPI、MySQL 认证会话、角色授权、MinIO 连接、Alembic、Core Compose 与 CI。客户、商机、状态机、会议解析和 RAG 尚未实现，界面明确显示后续阶段。

**M1 已正式验收通过**，依据用户后续明确验收结论及本次首次 Git 基线准备任务书；MySQL 8.4、Core Compose 与 MinIO 的实际验收结果、历史失败和限制以[M1 报告§9](docs/m1-report.md)及[当前状态补充§10](docs/m1-report.md#10-当前状态补充2026-10-27)为准。本地测试实例为 MySQL 8.4.13/InnoDB，服务器隔离 Core 为 8.4.8，替换过程见[替换记录](docs/mysql84-replacement.md)。Q03、Q04、Q05、Q06 已批准；Q05-A、Q07—Q12 仍待确认，详见[决策记录§13](docs/decisions.md)。M2 尚未开始，代码开发仍须单独明确授权；GitHub 远端 CI 等未运行检查不因 M1 验收通过而变为已通过。

## 环境与目录

- Python 3.12；uv 0.12.13（`backend/uv.lock`）。
- Node.js 24.21.0、npm 11（`frontend/package-lock.json`）。PowerShell 使用 `npm.cmd`，不需要改变系统执行策略。
- Core 容器环境需要 Docker Engine 与 Compose v2+。MySQL 目标版本 8.4.8/InnoDB。
- `backend/app`：配置、DB/UoW、auth、基础 storage/AI adapter、Worker；`backend/alembic`：显式迁移；`backend/tests`：单元及真实 MySQL 测试；`backend/tools`：隔离环境与验收工具。
- `frontend/src`：API client、路由、登录/布局、组件测试；`frontend/e2e`：浏览器认证验收。
- `infra`：同源 Nginx、MinIO 初始化及策略；`docs`：设计与执行证据。

## 配置约定

保留你现有的 `.env`。程序只读取本项目需要的配置，忽略其中后续阶段的供应商/向量服务变量。**M1 不调用真实 AI**，默认 `AI_MODE=mock`；即使设为 real，能力接口也明确标为尚未实现。

必要配置：`DATABASE_URL`、`SESSION_SECRET`（或 `CSRF_SIGNING_KEY`，至少32字符）、`MINIO_ENDPOINT`、`MINIO_ACCESS_KEY`、`MINIO_SECRET_KEY`；`MINIO_PORT`、`MINIO_USE_SSL`、`MINIO_BUCKET`控制存储连接。空 `MINIO_BUCKET`采用 `esc-evidence`，不存在时能力状态为不可用，不自动占用既有桶。

`DATABASE_URL`支持 `mysql://`及`mysql+pymysql://`。URL中的密码需要百分号编码；Compose使用独立 `DB_HOST/DB_PORT/DB_USER/DB_PASSWORD/DB_NAME`字段，避免特殊字符拼接问题。会话密钥与数据库密码均使用秘密类型，异常不回显输入。

默认读取当前目录或父目录 `.env`；可用 `ESC_ENV_FILE`显式选择忽略目录下的配置。`.env`、`.local/`、缓存和虚拟环境均被 Git 与构建上下文排除；不要运行会把解析后秘密打印出来的 Compose `config`，使用 `config --quiet`。

生产必须设置 `APP_ENV=production`、HTTPS `ALLOWED_ORIGIN`及 `COOKIE_SECURE=true`，禁止开发 seed。本机 HTTP 开发允许 `COOKIE_SECURE=false`；两种环境均保留 Origin/CSRF 防护。提供的 Compose 仅用于本地开发，生产 TLS 入口需部署方配置，不能直接当作生产部署完成。

## Core Compose（独立本地服务）

本机Windows没有可用Linux Docker引擎；本轮Core实际运行在192.168.10.150，用户zht，项目`esc-m1-accept-e12675a59e`，目录`/home/zht/esc-m1-accept-e12675a59e`。通用命令应在有Linux Docker的环境执行，不需要为了本项目升级本机Docker服务。

复核本轮运行环境（服务器专用目录中）：

```sh
docker compose -p esc-m1-accept-e12675a59e --env-file test.env -f compose.yaml -f acceptance.yaml --profile core ps -a
```

入口仅绑定服务器回环36095。在本机建立SSH转发后访问`http://localhost:36095`；主机公钥文件来自本轮已核验指纹，位于忽略的证据目录，不修改系统信任库：

```powershell
ssh -o UserKnownHostsFile=.local/m1-acceptance/20261026-completion/known_hosts -L 36095:127.0.0.1:36095 -p 22 zht@192.168.10.150
```

账号需在隔离环境中按下文bootstrap方式自行设置密码；不存在公开默认管理员密码。测试Core的MinIO与根.env指定的既有9000服务相互独立，原生开发仍按原.env实际Bucket状态显示能力。

MinIO固定到经版本核验的官方镜像摘要，镜像内也包含所需mc。Quay曾返回401；首次部署机器需能获取或预加载该固定摘要，不能以其他版本静默替代。uv构建工具固定0.12.13，使用官方PyPI；运行依赖仍以uv.lock为准。

从项目根目录执行：

```powershell
python backend/tools/prepare_compose.py
docker compose --env-file .local/compose.env --profile core config --quiet
docker compose --env-file .local/compose.env --profile core up -d --build
docker compose --env-file .local/compose.env --profile core ps
```

生成器仅创建不存在的 `.local/compose.env`，随机生成专用本地密码，不覆盖 `.env`，重复执行保留文件。这一路径启动本地新 MySQL/MinIO，不连接 `.env`中的既有数据库。

服务：MySQL、业务 MinIO、一次性桶/策略初始化、一次性 Alembic migration、API、Worker、Frontend。API/Worker仅在迁移与桶初始化完成后启动；只有浏览器入口 `http://localhost:5173`绑定宿主机回环地址，数据库/MinIO/console/API均不公开端口。

MinIO root只进入存储服务和一次性初始化任务；API/Worker使用 `esc_business`专用账户，限四个业务桶的必要对象操作，无管理员/CreateBucket权限，不访问未来Milvus内部桶。初始化可重复运行，不启用知识服务。Worker只有生命周期/心跳，没有队列或业务任务处理器，能力接口不会声称后台业务已就绪。

迁移可再次显式执行（同一 Alembic 权威，不自动 `create_all`）：

```powershell
docker compose --env-file .local/compose.env --profile core run --rm migrate
```

创建开发账号，不存在默认账号或固定密码：

```powershell
docker compose --env-file .local/compose.env --profile core exec -e ENABLE_DEV_SEED=true api python -m app.bootstrap --email admin@example.test --name "Demo Admin" --role ADMIN
```

命令交互式读取至少12字符密码，不显示、不记录、不覆盖同名账号。用自行输入的邮箱/密码登录。`APP_ENV=production`始终拒绝该开发初始化方式。

## 使用现有 `.env` 的原生开发

本轮服务替换后，根.env已能连接新8.4服务，M1基础迁移已执行。当前本机请使用根.env；旧`.local/native.env`中的开发库保留在旧8.0服务中。下面为本机现阶段的启动方式：

```powershell
Set-Location backend
Remove-Item Env:ESC_ENV_FILE -ErrorAction SilentlyContinue
$env:ENABLE_DEV_SEED = 'true'
uv run python -m app.bootstrap --email admin@example.test --name "Demo Admin" --role ADMIN
Remove-Item Env:ENABLE_DEV_SEED
uv run uvicorn app.main:create_app --factory --host 127.0.0.1 --port 8000 --no-access-log
```

首次创建时自行输入密码，已有账号不会被覆盖。以下隔离环境准备流程适用于新环境；生成器不会覆盖以前的`.local/native.env`。

先安装后端并只读探测依赖（不打印连接秘密）：

```powershell
Set-Location backend
uv sync --frozen
uv run python -m tools.probe_env
```

**不要对已有业务库直接执行迁移。** 首轮8.0实例中发现52张表，未对其运行Alembic；用户后来明确批准的新8.4实例使用全新目录，旧表保留在旧目录。以下工具用于新环境的隔离准备：使用.env同一实例新建esc_dev_*库并生成.local/native.env，不覆盖已存在文件。当前本机优先使用上方根.env启动方式；缺少建库权限时应提供新空库，不能改用SQLite。

```powershell
uv run python -m tools.prepare_native
$env:ESC_ENV_FILE = '../.local/native.env'
uv run alembic upgrade head
uv run python -m app.bootstrap --email admin@example.test --name "Demo Admin" --role ADMIN
uv run uvicorn app.main:create_app --factory --host 127.0.0.1 --port 8000 --no-access-log
```

新终端启动前端：

```powershell
Set-Location frontend
npm.cmd ci
npm.cmd run dev
```

浏览器访问 `http://localhost:5173`。Vite在服务端把 `/api`代理到 `http://127.0.0.1:8000`，保留浏览器Origin和Host；Cookie由同源响应设置，前端从login/me读取CSRF token，仅存内存，在写请求中传`X-CSRF-Token`。浏览器代码没有API容器地址。生产构建通过Nginx同源代理，部署时再由HTTPS入口保护。

原生Worker（另一个终端，设置相同 `ESC_ENV_FILE`）：

```powershell
uv run python -m app.worker
# 一秒后主动正常退出的生命周期检查：
uv run python -m app.worker --smoke
```

## 认证、安全与状态

- Argon2id：64MiB、time_cost=3、parallelism=2；后续按部署硬件校准，登录支持rehash。
- 256-bit随机会话token只在HttpOnly/SameSite=Lax Cookie中，数据库存SHA-256摘要；空闲30分钟、绝对8小时；登出撤销，角色和停用状态每次从DB复核。
- CSRF由会话ID/随机nonce与服务端密钥HMAC派生；写请求精确校验Origin及CSRF。登录同样要求可信Origin。无开放CORS、localStorage凭据或伪造角色权限。
- 登录按账号和直接来源的带密钥摘要共享限流，15分钟最多10次尝试（成功也计数）；不信任任意客户端转发头。
- 认证失败统一响应；参数错误不反射请求内容；日志只含request_id/method/status/duration等白名单操作字段，无密码、Cookie、CSRF、原始SQL或供应商密钥。

接口：

| 接口 | 用途 |
| --- | --- |
| `GET /api/v1/health/live` | 进程存活，不证明依赖可用 |
| `GET /api/v1/health/ready` | 真实DB连接和迁移版本检查；失败503 |
| `POST /api/v1/auth/login` | 登录，要求Origin |
| `GET /api/v1/auth/me` | 当前身份、CSRF、到期时间 |
| `POST /api/v1/auth/logout` | 撤销会话，要求Origin和CSRF |
| `GET /api/v1/admin/access-check` | M1管理员授权验证，不是用户管理模块 |
| `GET /api/v1/capabilities` | 登录后查看DB、存储、Mock、知识/Worker实际阶段状态 |
| `/docs` | API进程的OpenAPI文档；开发时使用API内部入口 |

每个DB工作单元独占Session，显式事务上下文提交/异常回滚/关闭；外部存储不在业务DB事务内调用。连接池pre-ping、回收及等待/网络超时有上限。应用退出释放Engine。非空且未受当前迁移管理的数据库被迁移前置检查拒绝。

## 测试与CI

后端：

```powershell
Set-Location backend
uv run ruff check .
uv run ruff format --check .
uv run python -m compileall -q app alembic
uv run pytest -q -m 'not integration'
# 真实数据库测试：同一.env实例新建esc_m1_test_*库，不触碰原库；保留合成数据便于复核。
uv run python -m tools.live_validation
# 复用输出的、属于本任务的测试库；将名字替换为实际输出：
uv run python -m tools.test_existing --database esc_m1_test_REPLACE
# 临时启动API/Vite，验证HTTP代理及真实浏览器；结束后关闭启动的进程：
uv run python -m tools.proxy_validation --database esc_m1_test_REPLACE --browser
```

真实集成测试只接受 `TEST_DATABASE_URL`且库名以`esc_m1_test_`开头，无配置则显式skip。单元测试不声称证明MySQL事务；集成测试使用真实连接验证登录、撤销、过期、CSRF、四角色、限流、回滚及池释放。数据库版本单独报告，8.0通过不能算8.4验收通过。

前端：

```powershell
Set-Location frontend
npm.cmd ci
npm.cmd run typecheck
npm.cmd test
npm.cmd run build
npm.cmd audit --audit-level=moderate
# 首次无Chromium时才安装；不会安装系统依赖或更改系统策略：
npx.cmd playwright install chromium
```

E2E由上述后端代理验收工具传入临时合成账号，无硬编码测试登录凭据；不记录trace，工作台截图输出到忽略目录 `.local/m1-workspace.png`。CI包括锁文件安装、Ruff、语法、pytest、真实MySQL8.4迁移/模型检查，以及前端类型、组件测试和构建。CI配置已创建，本地执行不等于远端CI已运行。

## 停止、保留与清理

停止并保留数据：`docker compose --env-file .local/compose.env --profile core stop`。

移除容器和网络但保留卷：`docker compose --env-file .local/compose.env --profile core down`。

`down --volumes`会永久删除本地MySQL/MinIO卷，只有明确决定清空且已备份时才手动使用；本次没有执行。不要把整个Compose项目的down当作停止未来knowledge模块的方式。

外部验证工具保留其输出命名的 `esc_m1_test_*`库与 `esc-m1-test-*`桶及合成文件，不自动清理，避免误删既有数据。需要清理时先根据执行报告核对具体名称与归属。不得清理其他库、用户、桶或共享卷。
