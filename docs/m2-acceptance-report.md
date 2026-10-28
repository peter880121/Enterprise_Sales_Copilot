# M2 剩余验收与必要修复（2026-10-27）

本报告记录本轮实际执行结果，不替代或改写 M1、M2-A、原 M2 报告的历史记录。M1 基线为 `bc425b6e5d3eb923711502c61bb571996e3ec9a7`，M2 工作仍未提交。客户/联系人停用继续 **DEFERRED**；没有进入 M3。

## 1. 环境、隔离与证据

- Windows 验证端：Python 3.12.7、Node 24.21.0、npm 11.19.0；本机 Docker Linux 引擎不可用。
- 实际部署端：Linux x86_64、8 个逻辑 CPU、约 7.7 GiB RAM，Docker 29.7.2、Compose 5.4.0。共享宿主机；测量时根分区可用约 6.9 GiB，非独占性能实验室。
- 本轮独立 Compose 项目：`esc-m2-core-14837bf2c7`，目录 `/home/zht/esc-m2-core-14837bf2c7`。数据库 `esc_m1_test_m2core_14837bf2c7`，独立 MySQL/MinIO 卷与网络；入口仅绑定远端回环 `49273`，经 SSH 回环转发到本机 `4886`。
- 实际服务版本：MySQL **8.4.8**、Python 3.12.7、NGINX 1.28.0、MinIO RELEASE.2025-09-07T16-13-09Z（沿用固定官方摘要）。没有更换锁文件中的依赖版本。
- 另建本轮旧 schema 探针库 `esc_m1_test_m2core_14837bf2c7_old`，仅迁移到 `0001_auth`；授权失败探针项目 `esc-m2-core-14837bf2c7-grant-failure`，使用主测试项目网络，无独立数据卷，初始化在连接数据库前即失败。
- 所有写入使用合成 `example.test` 用户、客户、商机及生成 PDF。没有使用真实客户数据或真实 Provider；知识服务关闭。
- 证据根目录：`.local/m2-acceptance-20261027-fb5bff01/`。私密连接和密码只在该忽略目录及远端权限受限配置中；本报告不公开秘密。`source-manifest.json` 记录上传源文件 SHA-256，`start-fingerprints.json` 记录任务开始时的文件指纹。
- 原 M1、旧 M2 MinIO 及其他数据库/容器不作为本轮启动、重启或迁移目标。没有删除卷、数据库、对象或旧证据。

## 2. 实施变更与语义

| 文件 | 本轮职责 |
| --- | --- |
| `backend/app/sales/service.py` | Pipeline 改为 MySQL 按币种/阶段汇总，减少 ORM 全量加载；不改变金额、权限、筛选或时间窗口口径 |
| `backend/tests/test_sales_mysql.py` | 新增真实 MySQL 汇总边界回归，保留原 20 轮并发及审计回滚测试 |
| `infra/nginx.conf` | Docker DNS 动态解析 API 上游，显式关闭上游自动重试 |
| `compose.yaml` | 迁移/运行账户分离；迁移后一次性授权成功才启动 API/Worker；可配置回环入口与同源地址 |
| `backend/app/runtime_grants.py` | 本实例专用运行账户初始化；审计表只允许 SELECT/INSERT，无 UPDATE/DELETE |
| `backend/tools/prepare_compose.py`、`.env.example` | 新生成的独立配置包含运行账户及随机密码；模板仅占位，保留既有配置 |
| `backend/tools/m2_acceptance.py` | 显式连接隔离资源的真实 HTTP/MySQL/MinIO 负例验收；无默认数据库回退 |
| `frontend/e2e/m2-acceptance.spec.ts` | 双页面 409、真实 PDF 核验成交、响应丢失同键重试三个浏览器测试 |
| `README.md`、`docs/implementation-plan.md`、`docs/m2-report.md` | 追加本轮报告入口及独立运行配置说明，保留历史事实 |
| `docs/m2-acceptance-report.md` | 本轮结果及限制 |

Pipeline 保持以下规则，实际 MySQL 回归通过：

1. 全未知预计金额返回 `null`；已知零计入 known；空集合金额返回 `0.00`、胜率 `null`。
2. CNY/USD/EUR/HKD 分组，不换汇、不混加；币种过滤后只返回指定币种。
3. `SUM(weighted_amount)` 汇总数据库逐笔舍入后的生成列；三笔 `0.03 × 20%` 得 `0.03`，不改成对总金额统一舍入。
4. 仅通过 `Opportunity.close_evidence_id` 连接当前选定且 VERIFIED 的证据；不连接全部候选，不使用 `SUM(DISTINCT amount)`。两笔各有 `230000.00` 实际金额的 CNY 商机返回 `460000.00`，另一个 USD 商机独立返回 `230000.00`，各自另有 `999.00` 已核验候选不计入。
5. 保留账户、负责人、阶段、优先级、名称、币种等过滤；关闭窗口两端包含，只影响关闭指标，阶段库存统计不被关闭窗口截断。没有匹配记录的币种/阶段仍按原契约返回。

没有新增迁移、改变已有模型或清理已有业务数据。本轮运行的新库执行已有 `0001_auth → 0002_accounts_contacts → 0003_sales` 链；DDL 非事务性，未来升级既有部署仍需事前备份、检查和授权，不能直接套用本次隔离验证。

## 3. Core Compose、账户与恢复

| 状态 | 验收项 | 实际证据 |
| --- | --- | --- |
| PASS | 配置语法及实际镜像构建 | `compose-config.log`、`compose-build.log`；前后端及新增运行模块构建成功 |
| PASS | 依赖启动及健康 | `compose-up.log`、`compose-status.json`；MySQL、MinIO、API、Worker、前端健康，migrate/storage-init/db-runtime-init 退出 0 |
| PASS | schema 门禁 | `old-schema-probe.log`：仅 0001_auth 的可连接库 `ready=false`；当前库 0003_sales 才就绪 |
| PASS | 模型一致性 | 实际执行 Alembic check，无新增升级操作；最终证据见 `model-check-final.log` |
| PASS | API/Worker 凭据隔离 | `runtime-isolation.json`：DB_USER 为专用运行账户；环境不含迁移或 root 数据库密码、不含 MinIO root 密码 |
| PASS | 数据库审计权限 | 真正 INSERT 成功，运行账户 UPDATE/DELETE 由 MySQL 权限错误拒绝；不是网络错误或应用隐藏按钮 |
| PASS | 授权初始化失败门禁 | `runtime-isolation.json`：独立失败项目 init 退出 1，API/Worker 均为 created、未启动；这是预期故障测试成功，不是主部署失败 |
| PASS | MinIO 业务账户 | 真实上传/下载；业务身份创建未授权桶收到实际 HTTP 403/AccessDenied |
| PASS | 知识服务关闭 | 实际容器 KNOWLEDGE_ENABLED=false；仍完成 CRM 与成交证据流程 |
| PASS | restart 持久化 | 1 客户、8 商机、关联活动、11 份原件的内容/版本及 SHA-256 均与重启前一致；`persistence-before.json`、`persistence-restart.json`、`persistence-restart-final.log` |
| PASS | stop/start 持久化与会话 | 五个专用长期容器全部停止后启动并恢复健康，容器 ID 不变；旧会话仍有效、登出后 401、重新登录成功；同样 11 份原件及业务数据匹配，`persistence-stop-start-final.log`、`persistence-stop-start.json` |
| PASS | 全量容器日志秘密扫描 | 最终 4,400,403 字节主测试项目日志，已配置原始/本轮密码、密钥及当前浏览器密码精确匹配为 0；`log-scan.json`，不宣称可检测未知秘密 |

账户职责：`esc_migrate` 仅供迁移；`esc_runtime` 供 API/Worker；数据库 root 仅在私有网络中的 MySQL 与一次性授权任务出现。授权器只重申本 Compose 实例专用身份的权限，不可用于共享业务身份。启动依赖门禁并不等于运行时持续权限监控。

### NGINX 动态 DNS 的实际故障与修复

原配置在 API 重建后继续连接旧 IP，真实登录返回 502，见 `nginx-recreate-failure.log`。修复使用 NGINX 1.28 的共享上游区和 `server api:8000 resolve`，Docker DNS `127.0.0.11 valid=5s`；`proxy_next_upstream off` 不会自动重发写请求。

最终验证用本轮无凭据占位容器占住已释放的旧地址，确保 API 重建真的换地址；操作仅限本轮独立网络。`dns-recreation.json`：API 从 **172.21.0.4 → 172.21.0.7**；NGINX 容器 `93dc91c961da…` 及启动时间完全未变，未重启 NGINX。`dns-http.json` 连续采样记录 17 次 502（首个约 1.328 秒、最后约 5.390 秒），随后恢复 200；不把该过程称为零中断部署。

恢复后同一会话的 me、一次创建 POST、含 q/page_size 的查询、真实 PDF 上传和代理下载均成功；并行的完整回归另行覆盖重新登录。首次探针因地址未变化及探针误读列表 envelope 失败，保留 `dns-recreation.json.attempt1`、`dns-probe.log.attempt1`，纠正探针后实际重新验证，未修改 API 契约来迁就测试。

## 4. 最终测试与负例矩阵

| 状态 | 检查 | 实际结果/证据 |
| --- | --- | --- |
| PASS | 最终后端，MySQL 8.4.8 | **264 passed**，1 个既有 Starlette/httpx 弃用警告；`mysql848-pytest-final.log` |
| PASS | 本轮早期后端，MySQL 8.4.13 | 262 passed，`native-pytest.log`；在最终 SQL 修改之前执行，**不代表最终版本在 8.4.13 回归通过** |
| PASS | 最终 NGINX/API/MySQL/MinIO | **118 项检查通过**；关闭代理重试后的再次运行 `api-complete-final.log`、`api-checks.json` |
| PASS | 最终 NGINX 配置后的浏览器回归 | **4 passed**：三个新增测试及一个既有销售流程；`browser-final-run.log` |
| PASS | 前端单元/交互测试 | 最终 92 passed；`npm test -- --reporter=dot`，`frontend-test-final.log` |
| PASS | TypeScript 与生产构建 | 最终独立 `npm run typecheck` 及 `npm run build`（含 tsc --noEmit）均 exit 0；`frontend-final-checks.json`、`frontend-run-final.log`，Zod 注释优化告警保留 |
| PASS | Python 静态检查 | `ruff check app tests tools`，`ruff format --check app tests tools`：49 文件通过；AST 解析 53 文件 |
| NOT RUN | GitHub 远端 CI | 没有执行远端工作流；本地运行不能替代 |
| DEFERRED | 客户/联系人停用及其验收 | 用户明确延期，未恢复实现 |

| 状态 | 业务验收场景 | 验证方式与核心断言 |
| --- | --- | --- |
| PASS | REP 全企业读取 | 真实 API 列表/详情/搜索/Pipeline/关联联系人查询；本人写允许，他人写拒绝 |
| PASS | READ_ONLY 写入及 REP 越权修改 | 直接 API 拒绝；版本、业务字段及成功审计数量不变 |
| PASS | 非法状态与覆盖概率 | 后端拒绝，固定 20/60/40/100/0；真实数据库 CHECK 也拒绝错误值 |
| PASS | 两页面同版本编辑 | 实际浏览器第二页 409、保留输入、不自动覆盖；数据库仍是第一页值 |
| PASS | 自核验与 REP 核验 | 经理及 ADMIN 自核验为 EVIDENCE_REVIEWER_CONFLICT，REP 为 FORBIDDEN；不当成会话失效 |
| PASS | 独立核验人 | 实际 API/浏览器核验，记录提交人、另一核验人、时间、结果、说明 |
| PASS | 未核验/币种不符关闭 | 拒绝，无部分成功；成功审计与版本不变 |
| PASS | 预计未知、零或与实际不同 | 真实 PDF+独立核验后可成交，预计不被改写 |
| PASS | 多候选、相同实际金额 | 当前选定证据只计一次；两笔同金额仍分别计入；真实 MySQL 新增回归 |
| PASS | 重复确认及响应丢失 | API 同键重放不加版本/审计；浏览器真实提交成功后丢弃响应、重试同键，版本及历史不重复 |
| PASS | WON 重开、终态普通编辑 | 真实 API 拒绝 |
| PASS | LOST 合法重开 | NEGOTIATION、60%、独立审计 |
| PASS | PDF 类型/大小/页数 | 真实 NGINX 上传 2 MiB 以上合法 PDF 成功；错误类型、无效 PDF、101 页、单文件 >20 MiB、整包 >21 MiB 明确拒绝，不产生可成交证据 |
| PASS | 无会话与损坏原件下载 | 分别 401、503 STORAGE_UNAVAILABLE；只损坏本轮合成原件并在 finally 恢复 |
| PASS | OTHER_APPROVED | 合法候选可 PENDING；未批准审批政策不能 VERIFY/WON |
| PASS | 并发与事务回滚 | 原 20 轮独立 Session 每轮一成功一409；审计故障回滚原业务变更。使用真实 MySQL，存储适配器的部分单测是 synthetic；核心证据流程另有真实 MinIO 检查 |

浏览器与 API 的范围明确区分：4 项 Playwright 测试覆盖交付 UI 的关键链路；其余权限、PDF 和业务负例以真实 API 验证，不宣称全部为浏览器通过。

## 5. 性能基线与局限

使用合成 bulk seed（每条商机配一条创建审计）保留 10,000 商机；同一账户过滤、20 条分页、搜索 `synthetic 09`，四币种、未知金额及 20/60/40 概率交替。数据全部保留，不清理。每接口预热 3 次、正式 30 次，HTTP 包含 NGINX 和 SSH 转发；随后 10 工作者混合列表/搜索/Pipeline，连续 300 秒。不是生产 SLA。

| 规模 | 列表修改前 p95 ms | 搜索修改前 p95 ms | Pipeline 修改前 p95 ms |
| --- | ---: | ---: | ---: |
| 1,000 | 39.58 | 30.54 | 91.61 |
| 5,000 | 85.33 | 83.20 | 236.29 |
| 10,000 | 147.97 | 157.35 | 472.94 |

同一保留的 10,000 条数据、同一过滤和测量方法，SQL 修改后 p95：列表 **149.23 ms**、搜索 **152.81 ms**、Pipeline **178.89 ms**；详情另测 **16.65 ms**。上述各 30 次均无错误。前后 SELECT 数分别仍为列表 5、匹配搜索 5、Pipeline 1（不含 HTTP 认证查询）；空搜索结果可只需 2 个查询。SELECT 计数是服务调用层实际 instrumentation，非整个 HTTP 请求总查询数。

`performance-before.json`、`performance-after.json` 保存 p50/p95/max、错误数、查询数及每条 SELECT 的真实 EXPLAIN。账户过滤走 account 外键索引，列表/搜索仍需 filesort，证据按主键 eq_ref；SQL 汇总使用临时分组，返回至多 20 个币种/阶段组。原 Pipeline 在 Python 线性加载全部 ORM 对象；修复减少传输和对象成本，SQL 本身仍扫描匹配数据。

修改前 10 并发 300 秒：2,756 请求、0 错误，混合 p50 **977.86 ms**、p95 **1977.66 ms**，未达到测试计划中 500 ms 的实验目标。最终修改后同样测试：**10,817 请求、0 错误，p50 266.34 ms、p95 362.85 ms（PASS）**。单并发与混合并发结果分别记录，不用前者替代后者；没有测量生产 SLA 或多机吞吐上限。测量期间 MySQL 容器曾约 670% CPU、549 MiB RSS，API 约 61% CPU、95 MiB RSS；详见 `hardware.log`、`resource-sample.log`。共享主机、单 API 进程及 SSH 开销均限制结果外推；混合 p95 不是每一接口单独的并发 p95。

## 6. 实际命令、构建复现与失败记录

本轮编排器位于忽略目录 `control.py`，仅针对以上明确项目；SSH 指纹核验，私密参数通过受限文件/进程环境传递，所有日志先脱敏。以下从项目根目录运行的命令已实际执行：

```powershell
uv run --no-project --with paramiko --with python-dotenv python .local/m2-acceptance-20261027-fb5bff01/control.py deploy
uv run --no-project --with paramiko --with python-dotenv python .local/m2-acceptance-20261027-fb5bff01/control.py tunnel --command pytest --log mysql848-pytest-final.log
uv run --no-project --with paramiko --with python-dotenv python .local/m2-acceptance-20261027-fb5bff01/control.py tunnel --command api --log api-final-run.log
uv run --no-project --with paramiko --with python-dotenv python .local/m2-acceptance-20261027-fb5bff01/dns_control.py
uv run --no-project --with paramiko --with python-dotenv python .local/m2-acceptance-20261027-fb5bff01/isolation_checks.py
uv run --no-project --with paramiko --with python-dotenv python .local/m2-acceptance-20261027-fb5bff01/control.py tunnel --command performance.py --log performance-run.log
uv run --no-project --with paramiko --with python-dotenv python .local/m2-acceptance-20261027-fb5bff01/control.py tunnel --command performance_after.py --log performance-after-run.log
uv run --no-project --with paramiko --with python-dotenv python .local/m2-acceptance-20261027-fb5bff01/control.py tunnel --command api --log api-complete-final.log
uv run --no-project --with paramiko --with python-dotenv python .local/m2-acceptance-20261027-fb5bff01/control.py tunnel --command browser --log browser-final-run.log
uv run --no-project --with paramiko --with python-dotenv python .local/m2-acceptance-20261027-fb5bff01/lifecycle.py restart
uv run --no-project --with paramiko --with python-dotenv python .local/m2-acceptance-20261027-fb5bff01/lifecycle.py stop-start
uv run --no-project --with paramiko --with python-dotenv python .local/m2-acceptance-20261027-fb5bff01/control.py tunnel --command persistence.py --log persistence-stop-start-final.log
```

`deploy` 实际执行 `docker compose -p esc-m2-core-14837bf2c7 --env-file acceptance.env --profile core config --quiet`、`build`、`up -d --wait --wait-timeout 240`、`ps -a --format json`。测试子进程分别是后端 `python -B -m pytest -q -p no:cacheprovider`、`python -B -m tools.m2_acceptance`，及前端 `node node_modules/@playwright/test/cli.js test sales.spec.ts m2-acceptance.spec.ts`。所有环境连接均显式注入，未从默认 `.env` 取业务数据库来运行测试。

静态与前端命令：backend 中 `.venv/Scripts/ruff.exe check app tests tools`、`format --check app tests tools`；Python AST 解析 app/tests/tools/alembic；frontend 中 `npm test -- --reporter=dot`、`npm run build`。

离线 wheel **未进入正式构建**。依赖下载缓慢时曾在忽略目录尝试下载锁定版本、核验哈希的 wheel；其中一次 HTTPS EOF 失败，没有改 Dockerfile、依赖版本或锁文件，没有上传/安装这些 wheel。原正式构建最终自行联网成功：`backend-original-build.log` 记录标准 `uv sync --frozen --no-dev --no-cache` 在约 1135 秒下载并安装 33 个包。

当前构建采用源文件归档上传，不携带本地 node_modules、虚拟环境、`.env`、`.local`，使用标准 Dockerfile。后续构建命中 Docker 层缓存；**没有宣称空 Docker 缓存、离线、任意机器均已实际复现**。干净副本需要取得本轮全部待审 M2 文件、锁文件及新增模块，运行 `prepare_compose.py` 生成新实例配置，指定独立 Compose 项目，再执行 config/build/up。当前 Git HEAD 仍只有 M1，直接检出该提交不会获得未提交的 M2。网络需要获取固定镜像、PyPI 和 npm 依赖。

旧 `.local/compose.env` 若没有新增 MYSQL_RUNTIME_*，生成器会保留旧文件并停止，Compose 会明确拒绝缺失参数；不要覆盖旧配置或复用原 M1 卷来绕过。应在独立副本生成新配置并使用新的项目名。系统服务、系统依赖及用户 `.env` 均未升级或修改。

保留的中间失败包括：首次旧 schema 探针缺少 PYTHONPATH（未连接数据库即失败，修正后通过）；重复使用一次性 model-check 容器名导致冲突（不删除既有容器，改用新名称只读重跑）；NGINX 旧 IP 502；首次 DNS 探针失败；wheel 下载 EOF；持久化探针遗漏 occurred_at 被 422 拒绝；会话探针丢失 cookie 的 domain/path，导致登出后重新登录的 cookie 选择错误。修正的是本地探针，未放宽应用校验；为重新证明会话存活，保存新会话后完整重复了一次 restart，再实际复验通过。一次自动权限审核超时未执行命令，按工具允许重试后执行。它们不计作成功证据，最终回归独立记录。未使用 remove-orphans、删除卷或清理工作区选项。

## 7. 剩余项与结论

- **PASS**：本轮本地必要项，包括最终 Pipeline 语义、真实动态 DNS 恢复、凭据隔离及失败启动门禁、264 项 MySQL 8.4.8 后端测试、118 项真实 API 检查、4 项浏览器测试、92 项前端测试、类型/构建/静态检查、性能目标与 restart/stop/start 持久化。
- **FAIL**：无未解决的本轮必要项失败；上述中间失败与预期故障已单列，不抹去历史。
- **BLOCKED**：无剩余本轮必要项环境阻塞。
- **NOT RUN**：GitHub 远端 CI；最终 SQL 版本未在本机 MySQL 8.4.13 重新运行完整测试（该版本早期 262 项结果保留，最终验收目标 8.4.8 使用实际 264 项结果）。空 Docker 缓存、完全离线构建未验证。
- **DEFERRED**：客户/联系人停用及对应验收，Q05-A、Q07—Q10、Q11/Q12 未批准范围保持原状态；没有自动保留/清理策略。
- 文件解析仍缺操作系统级资源隔离/恶意文件扫描；上传失败遗留记录/对象需人工对账，不擅自实现未批准的清理期限。HTTP 开发 Compose 不是生产 TLS/HA 部署。
- 文件/资源保护最终结果见收尾记录；不暂存、不提交、不推送。专用测试资源及故意失败的探针容器均保留，不自动清理。

本轮约定的本地验收补全已通过，提交用户评审；**不宣称 M2 所有范围全部完成**。远端 CI 未运行，延期停用继续单列 DEFERRED，未批准业务决策保持原状态，不自动进入 M3。

## 8. 收尾与保护核验

- **PASS**：`deployed-source-integrity.json` 记录最终运行容器中的 `app/sales/service.py`、NGINX `default.conf` 与本地相应文件的 SHA-256 一致；`nginx-final-config-check.log` 为实际 `nginx -t` 成功。`compose-final-status.json` 显示五个长期服务 healthy、三个主初始化任务退出 0；故意失败的独立探针另列，不混入主部署健康结论。
- **PASS**：`resource-protection.json` 对比原容器 ID/名称及运行状态、原卷名，缺失与运行状态改变均为空。所有 restart、stop/start、API 重建均只针对本轮项目；没有操作原 M1 项目或其他业务服务。
- **PASS**：`file-protection-and-scan.json` 对比任务开始指纹；107 个原文件无缺失，只有上表所列 9 个已有文件变化，另新增运行授权模块、API 验收工具、浏览器测试及本报告，共 13 个本轮交付文件。AGENTS.MD、根 `.env`、`.gitignore`、`docs/m1-report.md` 指纹全部一致，原有其他 M2 工作保留。
- **PASS**：扫描 109 个 Git 可见 UTF-8 文本文件，已配置秘密精确匹配和私钥头标记均未发现；`.env.example` 的密码/密钥为空或明确替换占位，不含可用连接凭据。忽略的本地材料、二进制图片不作为公开候选，也不声称通过任意未知秘密检测。
- **PASS**：`git -c safe.directory=C:/project/Enterprise_Sales_Copilot diff --check` 无空白错误；只有既有换行规范提示，未为消除提示重写文件。最终 HEAD 仍为 M1 基线、master 分支；暂存区为空，`.env`、`.local/`、`image.png` 未进入索引。未执行 add、commit、push 或任何清理/回退命令。

本地编排脚本、性能种子工具、受限连接和探针日志均留在上述 `.local/` 目录，包含环境专用信息，不作为共享基线材料。未来若需跨机器复用，应先审阅并参数化这些编排工具；共享 API 验收工具要求显式隔离连接，不能把本机私有配置纳入提交。
