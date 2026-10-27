# M1 工程基础实施与验收报告

日期：2026-10-26。依据：用户最新M1实施任务书及后续“使用.env环境测试数据”指令。设计v0.2与Q03已获批准；授权仅限M1。**工程基础已实施，当前验收部分通过，不能标记M1整体完成；未进入M2。**

> 上述为首轮历史结论，§1—8保留原证据。第二轮补全结论见§9：MySQL8.4、隔离Core运行/持久化、MinIO最小权限及最终回归均已实际通过，提交M1完成候选，等待用户评审，不进入M2。

## 1. 检查摘要与保留内容

- 开始时工作区包含AGENTS.MD、8份设计文档及image.png，无Git仓库、前后端代码或依赖；检查Git返回not a repository后才初始化。未覆盖既有应用修改、删除文件、提交代码或更改全局Git配置；所有原有内容保留，设计文档仅同步最新批准状态及实际进度。
- 用户随后提供根目录.env，按要求只读使用。该文件含数据库、存储及后续供应商配置；不复制秘密到报告/示例/提交，不进行真实模型调用，不改写源文件。
- 环境实测：Python3.12.7、Node24.21.0、npm11.19.0、uv0.12.13、Docker CLI29.7.2、Compose5.3.1。PowerShell禁止npm.ps1，使用npm.cmd；沙箱启动器随后持续helper_unknown_error，必要命令在获准后运行。
- 原.env数据库可连接，实际版本MySQL8.0.26、已有52张表，不是8.4。本次没有对该库运行迁移、创建业务表、清理或写入测试用户。
- Docker引擎检查的权限请求被用户拒绝；之后只单独申请并执行不连接引擎的Compose语法校验，未尝试绕过拒绝、启动引擎或容器。

## 2. 实际完成内容与文件清单

| 类别 | 新增/修改文件 | 内容 |
| --- | --- | --- |
| 工程 | .gitignore、.dockerignore、.gitattributes、.python-version、.nvmrc | 秘密/缓存/构建排除、脚本LF、运行时版本；初始化Git，未创建提交 |
| 后端依赖 | backend/pyproject.toml、uv.lock | Python3.12、精确解析锁文件、开发工具；uv frozen安装 |
| 后端基础 | app/main.py、db.py、core/config.py、errors.py、logging.py及包初始化文件 | 工厂入口、集中配置、短事务、统一错误与结构化日志、存活/就绪/能力检查 |
| 认证 | auth/models.py、schemas.py、security.py、service.py、dependencies.py、router.py | 用户/会话/共享限流、Argon2id、登录/me/logout、CSRF/Origin、四角色及管理员探针 |
| 适配骨架 | app/storage.py、ai.py、worker.py、bootstrap.py | 真实桶可用性、明确Mock边界、可启停Worker心跳、交互式开发账号初始化 |
| 迁移 | backend/alembic.ini、alembic/env.py、script.py.mako、versions/0001_auth.py | 仅users/sessions/auth_throttles基础表；已有非空未管理库拒绝迁移，不使用create_all |
| 后端测试 | tests/conftest.py、test_unit.py、test_mysql.py、test_storage.py | 配置、连接失败、认证、安全、角色、真实事务/池释放与存储故障 |
| 验证工具 | tools/prepare_compose.py、prepare_native.py、probe_env.py、live_validation.py、test_existing.py、proxy_validation.py | 新建隔离命名空间、只读探测、真实数据库/存储测试、临时代理/浏览器验收 |
| 前端依赖 | frontend/package.json、package-lock.json、tsconfig.json、vite.config.ts、index.html | React/TS/Vite、服务端代理、Query/Form/Zod、锁文件 |
| 前端界面 | src/main.tsx、App.tsx、api.ts、components.tsx、styles.css | 原创侧栏/顶部/工作台、登录、身份状态、加载/错误/空态；业务菜单明确禁用，无伪造Pipeline |
| 前端测试 | src/test-setup.ts、App.test.tsx、api.test.ts、playwright.config.ts、e2e/auth.spec.ts | 7项组件/API测试、1项真实浏览器认证流程；trace关闭 |
| 部署 | compose.yaml、backend/Dockerfile、frontend/Dockerfile、infra/nginx.conf、minio-business-policy.json、init-minio.sh | core及一次性迁移/桶初始化、内部网络/持久卷/健康检查、同源入口、专用存储权限 |
| CI | .github/workflows/ci.yml | 后端锁安装/Ruff/语法/真实MySQL8.4迁移与测试，前端锁安装/类型/测试/构建；尚未在远端执行 |
| 文档 | README.md、8份设计文档的实施状态、本文 | 实际命令、配置映射、Q03批准、M1范围收窄、验收缺口 |

没有删除文件。AGENTS.MD未修改；实施前后SHA256一致：`850DD9BA280E8D472149B3263496E3C6837D6216B953BB39FC3039B905728764`。

`.local/compose.env`、`.local/native.env`、截图、虚拟环境、node_modules均为忽略的本地产物，不纳入源文件或Docker构建上下文。

## 3. 关键技术决策

1. Python依赖用uv.lock，Node依赖用package-lock.json；未引入Prisma、第二ORM/迁移、微服务或业务Agent。SQLAlchemy2.0同步Engine/PyMySQL，READ COMMITTED、pre-ping、pool_size=5/max_overflow=5、pool_timeout=5s、网络超时有上限，每工作单元独占Session并显式提交/回滚/关闭，退出dispose。
2. 数据库不因测试方便换SQLite。源.env只用来连接同一服务实例；迁移/测试在新建`esc_m1_test_*`库，原生开发另建`esc_dev_*`库。8.0结果是补充证据，不冒充8.4。
3. 数据库不透明会话：随机256-bit token，仅SHA256入库；HttpOnly/SameSite=Lax/path=/api，开发HTTP可非Secure，生产强制Secure及HTTPS。空闲30min/绝对8h、重登录轮换、登出撤销、停用和角色变化每次生效。
4. Argon2id为64MiB/time_cost3/parallelism2；未知用户执行同类密码校验避免明显时序差异。15分钟10次账号+直接来源登录尝试预算在MySQL共享状态持久化（成功也计数）；无账号枚举响应，不信任任意Forwarded身份。
5. CSRF=HMAC(会话ID+nonce)，仅内存保存；所有已有写接口验证精确Origin，登出额外校验CSRF。角色来自DB，extra输入拒绝，管理员探针只允许ADMIN；完整对象级CRM授权留M2。
6. 浏览器只访问相对/api/v1；Vite保留Origin/Host转发到本机API，Nginx用于容器同源入口。生产HTTPS需部署方单独配置，当前Compose不是生产就绪声明。
7. Core包含前端、API、MySQL8.4.8、Worker、业务MinIO和一次性任务；不部署Milvus/etcd/MinerU。专用本地Compose秘密独立生成，不挪用远程.env服务。MinIO root仅初始化，业务账户策略限业务桶，无管理员/CreateBucket权限；实际权限负例尚未验证。
8. Mock仅为明确标识的适配骨架，不实现会议解析、embedding、RAG或CRM写入。real模式在M1明确不可用，不因为缺模型Key阻止CRM基础启动；真实模型调用次数为0。

## 4. 实际执行命令与结果

以下均为实际运行的关键命令；路径以项目根目录或标注目录为准，不含秘密参数。

| 命令/操作 | 实际结果 |
| --- | --- |
| Get-Content AGENTS.MD及8份设计文档、rg --files、Get-ChildItem | 文件存在，初始无应用代码；保留现有内容 |
| git status --short --branch | 初始not a repository；没有可覆盖的暂存/已修改应用文件 |
| python --version、node --version、npm.cmd --version、uv --version、docker --version、docker compose version | 版本见§1；npm.ps1失败后改npm.cmd成功 |
| git init | 成功；后续使用单次-c safe.directory处理沙箱所有权差异，不改全局设置 |
| uv lock（backend） | 初始默认缓存访问失败；获准后指定项目缓存完成锁定 |
| uv sync --frozen --cache-dir ..\.cache\uv | 安装成功，使用Python3.12.7，锁定40个安装依赖 |
| npm.cmd install --cache ..\.cache\npm --no-fund --ignore-scripts | 初次工具链审计发现漏洞，随后显式升级Vitest至5.0.5并重新锁定 |
| npm.cmd audit --json | 初次报告1中危/2严重；不使用force自动破坏性升级 |
| npm.cmd audit --audit-level=moderate | 修复后0漏洞；不是永久安全保证 |
| python -m tools.probe_env（backend虚拟环境） | 真实MySQL8.0.26可连接，源库52表；默认esc-evidence桶不可访问，AI=mock/0调用 |
| python -m tools.live_validation | 新建隔离库/桶；Alembic upgrade head、pytest、alembic check退出0；真实MinIO put/get/stat成功 |
| ruff check . --fix / ruff format . | 首轮有长行/导入及格式问题，修正；最终check和format --check通过 |
| python -m compileall -q app alembic tools | 通过；非完整Python静态类型证明 |
| python -m pytest -q -m 'not integration' | 早期14项通过；后续加入存储测试；最终全套28项见下行 |
| python -m tools.test_existing --database esc_m1_test_63354e0c2baf | 最终28项通过（15单元+13真实MySQL集成），upgrade/check退出0 |
| npm.cmd ci --cache ..\.cache\npm --no-fund | 从锁文件重装成功，审计0漏洞；有esbuild安装脚本策略提示，构建仍实际成功 |
| npm.cmd run typecheck / npm.cmd test / npm.cmd run build | 类型通过，2文件7项测试通过，生产构建成功 |
| python -m tools.proxy_validation --database esc_m1_test_63354e0c2baf | 临时API+Vite真实HTTP：未登录401、登录/me/admin探针、跨站拒绝、CSRF登出、旧会话401通过，进程已停止 |
| 同上追加 --browser | 1项Playwright真实浏览器验收通过：登录、状态、刷新保持、登出及重新访问保护；报告.last-run为passed，截图已人工查看 |
| python -m app.worker --smoke | 输出started_no_business_handlers和stopped，正常退出，不宣称业务处理完成 |
| python -m tools.prepare_compose | 生成忽略目录下独立随机本地配置，未覆盖.env |
| docker compose --env-file .local/compose.env --profile core config --quiet | 退出0；只证明配置语法，不证明镜像存在、引擎可用或服务能启动 |
| python -m tools.prepare_native | 同.env实例新建esc_dev_6ac432897cdf，写忽略目录native.env，未输出凭据 |
| 设置ESC_ENV_FILE后alembic upgrade head / alembic check | 新原生开发库首次迁移成功，模型一致，无新增操作 |
| git check-ignore .env、AGENTS.MD Get-FileHash、git diff --check | .env被忽略、AGENTS哈希未变；空白检查不覆盖未跟踪文件，最终另做源文件扫描 |
| docker info / image ls | 请求被拒绝，未获得执行结果；未执行Compose up/build或数据卷删除 |

## 5. 真实测试数据与保留范围

- 原始业务库：只读SELECT版本和information_schema表数；没有迁移或业务写入。
- 认证测试库：`esc_m1_test_63354e0c2baf`，迁移/合成用户/会话/限流记录保留，未自动DROP。
- MinIO测试桶：`esc-m1-test-0641b49585c2`，合成`probe.txt`保留；两次ensure-bucket及写/读/stat完成，无既有桶/用户/策略更改。该测试**不能证明**Compose的mc初始化脚本或专用业务账户权限隔离。
- 原生开发库：`esc_dev_6ac432897cdf`，仅M1基础迁移，没有创建固定默认管理员；README引导交互式创建用户。
- 本地Compose卷/数据：未启动，未修改远程数据库或对象存储配置。

## 6. 安全检查

已实现并测试：密码hash非明文、未知用户/错密码统一响应、未登录拒绝、extra角色字段拒绝、四角色可信来源、过期及登出撤销、跨站与缺CSRF拒绝、生产Secure/HTTPS/seed配置约束、请求校验不反射密码、日志白名单、.env忽略。

真实密钥未用于模型调用，未写入代码、示例、Git提交或前端产物。会话/CSRF不存localStorage，不输出请求头/正文；命令参数不含密码。新账号由交互式密码输入创建，无默认弱密码。专用Compose生成的存储root和业务账号分离；现有.env凭据是否具备过宽权限未验证，不能据实际连接成功声称最小权限已通过。

## 7. M1逐项验收表

| 验收项 | 状态 | 证据/缺口 |
| --- | --- | --- |
| 前后端结构符合M1分层 | 通过 | app/core/auth/db/adapter与前端API/route/components分离，无CRM提前开发 |
| Python/Node可复现安装 | 通过 | uv.lock frozen安装、npm ci及构建 |
| AGENTS.MD未修改 | 通过 | 前后SHA256一致 |
| 未覆盖原有重要修改 | 通过 | 初始无应用，原.env只读、源库不迁移，无删除 |
| MySQL8.4实际可连接 | 未验证/阻塞 | .env为8.0.26；8.4镜像配置未运行 |
| SQLAlchemy连接/Session | 补充验证通过 | 真实8.0连接、事务回滚及checkedout=0；8.4仍需回归 |
| Alembic迁移可执行 | 补充验证通过 | 两个全新隔离8.0库upgrade/check成功；8.4未验证 |
| 事务生命周期清晰 | 通过 | 显式UoW、异常回滚、Session关闭及Engine释放，真实回滚断言 |
| login/me/logout | 通过 | API真实MySQL集成、Vite HTTP与浏览器 |
| Argon2id | 通过 | 编码/验证及错误密码测试；未做生产硬件压力校准 |
| 会话/CSRF/Origin | 通过 | 轮换/空闲与绝对过期/撤销/跨站/缺token |
| 基础角色拒绝越权 | 通过 | 四角色+伪造字段测试；对象级CRM权限未实现 |
| 无生产硬编码秘密/默认密码 | 通过 | SecretStr、忽略规则、bootstrap交互式；CI仅合成临时凭据 |
| 前端构建 | 通过 | Vite7.3.7生产构建 |
| TypeScript检查 | 通过 | tsc --noEmit含测试配置 |
| 基础布局与登录可用 | 通过 | 7项组件/API测试、1项真实浏览器及截图检查 |
| 同源代理路径 | 通过（Vite） | 真实HTTP及浏览器；Nginx容器路径未运行 |
| Core Compose配置有效 | 语法通过 | config --quiet退出0；镜像拉取/运行未验证 |
| 服务配置完整 | 静态完成 | MySQL/API/frontend/worker/MinIO、一次性初始化及健康依赖/卷齐备；容器实际重启持久化未验证 |
| Bucket初始化最小权限/可重复 | 未验证 | 脚本/策略已写；外部桶ensure两次不能替代mc/IAM负例验收 |
| 状态反映实际依赖 | 通过（已测原生路径） | DB就绪失败503、默认桶不可用、Mock与后续模块明确标识 |
| 后端测试已运行 | 通过 | 最终28项；8.0补充而非8.4验收 |
| 前端检查已运行 | 通过 | 类型、7测试、构建、审计及浏览器 |
| 可行Compose/DB/存储验证 | 部分通过 | 语法+8.0迁移+真实存储；8.4/Core/IAM未验证 |
| README启动/测试说明 | 通过（部分运行核验） | 原生新库迁移与Vite认证已实测；Docker命令仅语法验证 |
| 未执行/失败项有记录 | 通过 | 本报告保留首次失败、修复结果及环境缺口 |

## 8. 已知问题与进入M2前的工作

1. **M1仍待最终验收**：在允许的Docker/专用环境运行MySQL8.4、Core build/up、空库迁移、Nginx同源认证、持久化重启、Worker健康及优雅退出。
2. 运行mc初始化两次并验证业务账户只能访问四业务桶，不能创建桶/管理用户/读取其他桶；MinIO故障时核心状态正确。现有.env远程凭据不视为已审查的生产最小权限账号。
3. 镜像使用明确release标签但未拉取验证或固定digest；需核验Python/Node/MySQL/MinIO/mc/Nginx供应链、可用性和安全更新，再锁digest。不得为了环境问题自行替换批准的数据库或存储架构。
4. Python全套测试有1条Starlette对httpx TestClient的弃用提示；前端构建有Zod注释标注被移除的提示；均未导致失败。npm11对esbuild安装脚本给出策略提示，锁安装及实际构建成功；其他环境若执行策略不同应复验，不更改全局策略掩盖差异。
5. 远端CI未运行；当前未做生产性能、Argon2负载、TLS部署、备份恢复或真实模型评测。API文档中未来业务接口没有提前实现。
6. 用户管理/密码变更/最后管理员保护/完整安全审计和清理任务随对应后续范围实施；M1仅提供开发CLI及基础身份权限，不宣称这些模块已完成。
7. 进入M2前确认Q04核验职责、Q05证据/币种细则、Q06概率映射；Q09供应商政策仍未批准。Q03已批准，不再重新申请。完成M1剩余验收后再申请M2，不自动开发CRM。

完整启动与验证步骤见 [README](../README.md)。本轮结束于M1，不继续实现M2。

## 9. M1验收补全记录（2026-10-26，追加，不覆盖历史）

### 9.1 授权与资源边界

- 用户澄清Docker位于192.168.10.150，提供zht/22，并将SSH凭据写入.env；ED25519指纹经用户核验后，客户端每次握手固定校验该指纹，密码仅在进程内存使用。未修改系统SSH信任库。
- 用户随后明确批准“本地都是测试数据，直接替换”，据此将本地8.0测试服务替换为独立的新8.4.13服务。此授权覆盖最初禁止改本地实例的限制；旧安装及数据目录保留，没有原地打开8.0数据文件或删除旧数据。详见[替换记录](mysql84-replacement.md)。
- .env期间由用户添加SSH密码字段；助手未修改它。完整性检查以用户添加后的哈希为准，不能把用户自己的修改归因于助手或声称文件全程字节不变。
- 服务器测试项目：`esc-m1-accept-e12675a59e`，目录`/home/zht/esc-m1-accept-e12675a59e`，网络`esc-m1-accept-e12675a59e_core`。
- 专用库`esc_m1_test_e12675a59e`、专用数据库账号及MinIO业务账号由独立随机测试配置生成；源.env没有上传。原9000端口MinIO、既有容器/卷和原数据库未用于远端写入测试。
- 测试入口仅绑定服务器`127.0.0.1:36095`。MySQL/MinIO/API无宿主机公开端口。持久卷`esc-m1-accept-e12675a59e_mysql-data`和`esc-m1-accept-e12675a59e_minio-data`已核验实际挂载到`/var/lib/mysql`和`/data`。
- 未执行down -v、prune或旧资源删除；本轮一次性验证容器使用--rm。测试Core保持运行供复核，卷和测试对象保留。

### 9.2 实际环境

| 环境 | 实测版本/结果 |
| --- | --- |
| 本地Windows新实例 | MySQL8.4.13/InnoDB，MySQL84_ESC，3306；旧MySQL80停止/手动，旧Data保留 |
| 远端隔离实例 | MySQL8.4.8/InnoDB；实际SQL查询版本，全部基础表InnoDB，迁移0001_auth |
| 远端Docker/Compose | Engine29.7.2，Linux/amd64；Compose5.4.0；无sudo操作 |
| MinIO/mc | RELEASE.2025-09-07T16-13-09Z / RELEASE.2025-08-13T08-35-41Z，实际运行二进制确认 |
| 官方MinIO固定摘要 | minio/minio@sha256:14cea493d9a34af32f524e538b8346cf79f3321eff8e708c1e2960462bd8936e；同镜像内含匹配mc，初始化使用覆盖入口 |
| MySQL8.0历史 | 首轮8.0.26的28项测试仅保留为历史补充，不作为本轮8.4通过证据 |

### 9.3 本轮必要验收结果

| 目的/验收项 | 状态 | 实际动作与结果 | 本机证据位置 |
| --- | --- | --- | --- |
| 8.4本机真实连接/迁移/模型 | PASS | 新建专用库和限定账号；upgrade head/check退出0，4表InnoDB/0001_auth | .local/mysql84/mysql84-validation.json及对应日志 |
| 8.4本机后端回归 | PASS | 完整28项通过；独立库esc_m1_test_84_f452dc12f3，不使用SQLite | .local/mysql84/mysql84-pytest.log |
| 本机服务重启持久化 | PASS | UAC重启MySQL84_ESC；版本/路径/引擎一致，重启时13条合成测试用户保留 | .local/mysql84/persistence.json、restart-result.json |
| 8.4.8容器真实迁移/模型 | PASS | 实际SELECT VERSION为8.4.8，API容器alembic check退出0 | .local/m1-acceptance/20261026-completion/remote-alembic-model-check.log |
| 8.4.8同套数据库测试 | PASS | 经临时SSH隧道、专用账号，对隔离库运行28项，28 passed；不是仅看镜像标签 | 同目录/mysql848-full-pytest.log |
| 真实事务/连接池 | PASS | 本机及远端实际回滚、会话释放；28项及core probe均验证，checkedout=0 | 同目录/core-probe-before.log及pytest日志 |
| Core配置及启动 | PASS | config --quiet；up -d --build --wait；5个长期服务healthy，2个一次性任务exit0 | 同目录/core-nonroot-read-permission-fix.log、core-final-health.log |
| 存活/就绪/入口 | PASS | 服务器回环入口/、health/live、health/ready实际HTTP200 | 同目录/remote-loopback-ingress.log |
| Nginx同源认证 | PASS | 登录/me/登出成功；未登录401、缺CSRF/错误Origin403、登出后401 | 同目录/core-probe-before.log |
| Worker生命周期 | PASS | 心跳健康、保持运行；stop时worker_stopped，start后恢复healthy | 同目录/lifecycle-results.json、core-logs-sanitized.log |
| MinIO健康/授权操作 | PASS | 新实例健康，专用业务账号4桶上传/读取/stat成功 | 同目录/minio-s3-before.json |
| 越权读/列表/元数据 | PASS | 未授权对象GET、对象列表、Bucket HEAD均真实HTTP403/AccessDenied | 同目录/minio-s3-before.json |
| 越权创建/删除Bucket | PASS | 固定region避免先做位置探测，直接PUT/DELETE；实际403/AccessDenied | 同目录/minio-s3-before.json |
| Bucket列表范围 | PASS | ListBuckets返回200但只含4个授权桶，两个root测试夹具桶不在结果；不是宣称该接口403 | 同目录/minio-s3-before.json |
| 越权管理 | PASS | 业务账号mc admin user list返回AccessDenied；CLI退出1是预期拒绝，非网络失败 | 同目录/iam-admin-denied.log、iam-denied-admin.log |
| 初始化幂等 | PASS | 多次运行初始化exit0；原测试对象内容/stat不变 | 同目录/iam-initializer-repeat.log、minio-s3-after.json |
| Core停止/重启持久化 | PASS | 仅本项目stop/start，用户marker和4桶对象均保留，健康恢复 | 同目录/core-stop.log、core-start-after-stop.log、core-probe-after.log |
| 知识未启动仍可用 | PASS | 本项目不含Milvus/etcd/MinerU，CRM基础/认证/storage正常，MOCK明确显示 | 同目录/core-probe-before.log、lifecycle-results.json |
| 应用非root/秘密边界 | PASS | uid10001，配置可读；API环境无MINIO_ROOT_USER/PASSWORD | 同目录/api-nonroot-secret-boundary.log |
| 日志及源文件秘密检查 | PASS | 实际容器日志扫描无测试/源.env秘密值，源文件新增/修改范围扫描另存完整性报告 | 同目录/remote-secret-scan.json、final-integrity.json |
| 最终本地回归 | PASS | 后端28项、前端7项、TS、构建、Ruff、格式、语法全部exit0 | 同目录/final-regression-results.json及final-*.log |

### 9.4 重要命令与实际修复

远端命令统一前缀（在专用目录执行）：

```sh
docker compose -p esc-m1-accept-e12675a59e --env-file test.env -f compose.yaml -f acceptance.yaml --profile core
```

实际执行config --quiet、pull、up -d --build --wait、ps -a --format json、run --rm --no-deps storage-init、exec -T api alembic check、stop --timeout 30、start --wait --wait-timeout 180、logs --no-color。所有操作限定本项目；源.env密码没有作为命令参数。

本机实际执行MySQL官方ZIP校验/新实例初始化/临时端口验证，UAC服务切换与Restart-Service，独立测试库Alembic upgrade/check、pytest；最终重跑npm test/typecheck/build和Ruff/语法。具体安装/回退命令及包哈希见mysql84-replacement.md。

保留的失败与处理：

1. 本机desktop-linux引擎管道不存在：用户澄清远端位置后，改为已核验SSH控制入口；没有启动本机Docker服务或绕过权限。
2. Quay两个镜像401：改用服务器已缓存、经实际版本核验的官方MinIO固定摘要，产品/客户端版本相同，无降级或第三方替代。
3. GHCR uv层下载停滞：仅中断本项目构建客户端，改用官方PyPI固定uv0.12.13，最终正常构建。临时离线wheel准备遇网络超时，未用于验收镜像；未保留额外源码工具或改变依赖版本，历史脚本/日志留本地。
4. 非root迁移读取配置失败（exit255）：实测uid10001且alembic.ini不可读。Dockerfile对公开源码/迁移文件执行a+rX，保持root所有权，不处理任何秘密文件；重建后迁移exit0、配置可读、API健康。没有重写认证/数据库业务代码。
5. 首次测试错误地要求ListBuckets本身403：保留首次失败证据，进一步核对发现只返回授权桶。最终直接断言未授权桶不可见，显式未授权对象/列表/创建/删除仍要求真实403，没有把网络错误或越权成功改成通过。
6. Compose images辅助汇总命令返回No such image；此命令保留FAIL。按明确镜像名逐个docker image inspect均成功、运行服务健康，元数据另存image-audit-*.log，不声称原汇总命令已成功。

### 9.5 最终文件与安全复核

- 运行配置修改：compose.yaml固定已核验的MinIO摘要；backend/Dockerfile固定uv PyPI版本及非root读取权限；.dockerignore排除test.env/临时包缓存；.gitignore忽略临时wheel产物。
- 文档新增mysql84-replacement.md；README、实施计划、决策记录及本报告同步实际结果。既有backend/app、frontend/src和既有测试内容未改，未开发M2。
- 历史报告副本、最初文件哈希、用户更新.env后的哈希、最终源文件/日志/资源检查均保存在本机.local/m1-acceptance/20261026-completion；该目录被Git忽略，凭据文件不作为公开附件。
- 既有远端容器ID/状态及既有卷名称按前后快照核对；没有删除旧卷或重启旧业务容器。Windows旧实例的服务切换是后续明确授权的独立动作，不能继续声称本轮完全未动本机MySQL服务。
- 没有Git提交；初始文件均未跟踪，因此空git diff不能证明无修改，使用本轮baseline逐文件哈希复核作为补充。

### 9.6 当前结论、未执行项及限制

**M1必要补全项全部PASS，提交M1完成候选，等待用户评审；不进入M2。** 首轮8.0结果继续保留为历史，本轮8.4结果独立报告。

| 项目 | 状态 | 说明 |
| --- | --- | --- |
| MySQL8.4迁移/集成与持久化 | PASS | Windows8.4.13与隔离Linux8.4.8均有真实证据 |
| Core运行/认证/健康/stop-start | PASS | 本项目5个长期服务健康，数据及卷保留 |
| MinIO最小权限及初始化幂等 | PASS | 实际授权操作、拒绝响应及列表范围已核验 |
| 初始镜像/构建/迁移尝试 | FAIL（历史，后续修复通过） | 原始失败日志保留，不能抹掉失败命令 |
| Compose images辅助汇总 | FAIL（非验收阻断） | 名称直接inspect通过；保留CLI汇总兼容性问题 |
| 当前M1必要项 | 无BLOCKED/NOT RUN | 不把范围外事项算作必要项已通过 |
| GitHub远端CI、生产TLS/恢复演练、真实模型、M2 | NOT RUN | 不在本次补全范围；CI配置存在不等于实际执行 |

剩余限制：Quay访问仍401，冷启动机器需能获取或预加载已固定摘要；网络可能导致首次构建较慢；辅助Compose镜像汇总存在兼容性问题，已用直接inspect核验。这里不承诺生产可用性或高可用。Q04/Q05/Q06及真实供应商政策仍待对应里程碑批准。


## 10. 当前状态补充（2026-10-27）

本节仅追加后续状态，不改写以上历史执行、失败与当时待评审记录。当前状态的权威依据为用户后续明确验收结论及本次《首次 Git 基线准备与安全审查》任务书；已批准业务决策见 [decisions.md §13](decisions.md)。

- M1 已正式验收通过；以上“完成候选、等待评审”和 Q04/Q05/Q06 待批准文字属于当时历史状态。
- Q03、Q04、Q05、Q06 已批准；Q05-A、Q07—Q12 等仍待确认。
- MySQL 8.4、Core Compose、MinIO 的实际结果和已知限制仍以 §9 的执行证据为准；本次没有重跑验收，不新增运行成功声明。
- GitHub 远端 CI、生产 TLS/恢复演练、真实模型等未运行或范围外检查，不因 M1 验收通过而标记为通过。
- M2 尚未开始，代码开发仍未获得单独明确授权。本次只准备首次 Git 基线，不执行暂存或提交。
