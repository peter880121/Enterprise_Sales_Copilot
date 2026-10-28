# M2.1 用户注册、管理与角色授权交付报告

日期：2026-10-27。用户批准方案后实施。当前仍在 M2 基础业务完善阶段；M1 已验收，不进入 M3。

## 交付结论

本轮用户基础能力已实现并通过下列本轮实测，可进入代码及人工验收评审，尚未暂存或提交。不据此宣称整个产品、M2 全范围或生产上线验收完成。

- 公开注册：姓名、邮箱、密码与确认密码；后端创建待审批账户，不自动登录。重复邮箱返回通用受理信息，防止公开账户枚举；来源节流。
- ADMIN 用户管理：搜索、分页、角色/状态筛选、创建、详情、编辑、审批、固定四角色授权、启用/禁用、逻辑删除/恢复、密码重置及用户历史。
- 本人账号：个人姓名/邮箱修改、验证当前密码后更改密码。变更撤销全部本人会话，要求重新登录。
- 安全：后端 ADMIN 校验、写入 Origin/CSRF、版本 CAS、同事务白名单审计、目标会话撤销、最后有效管理员保护、密码重置幂等。
- 保留原 CRM、Pipeline、活动、证据及成交规则；客户/联系人停用继续 **DEFERRED**。

## 本轮环境与隔离

Windows 开发端 Python 3.12、本地项目虚拟环境与 Node/npm；远端 Linux Docker 29.7.2、Compose 5.4.0。真实数据库版本 **MySQL 8.4.8**，未将其表述为 8.4.13 或其他版本通过。

专用 Compose 项目 `esc-m2-core-33bee69cd6`，目录 `/home/zht/esc-m2-core-33bee69cd6`，主测试库 `esc_m1_test_m2core_33bee69cd6`。独立 MySQL/MinIO、随机测试凭据及合成业务数据。容器内部数据库/对象存储不对公网暴露；Web 仅远端回环 46363，当前本机 SSH 转发至 `http://localhost:5909`。

最后管理员测试另建空场景库 `esc_m1_test_m2core_33bee69cd6_lastadmin_d7c89b`，采用单独数据准备与运行身份；不删除测试行以强行复用空库断言。迁移保留验证另建 `esc_m1_test_m2core_33bee69cd6_upgrade_a2ac85`。旧 M1/M2 项目、库、对象和卷均未迁移或清理。新资源及各轮证据保留。

本轮敏感配置及控制脚本仅在忽略的 `.local/m2-users-20261027-b94f9cc3/`。报告不记录密码、会话、完整连接字符串。该目录不是拟提交材料。

## 关键实现与迁移

`0004_users` 为新增迁移，接续既有 `0003_sales`。增加用户注册状态、逻辑删除时间、约束和索引，并插入 `system_guards.active_admin` 行。已有用户默认 APPROVED，原启用状态不变，不改变 ID、密码、版本、历史关联或审计。

管理员写操作先锁共享 guard，再按 ID 锁用户，核对服务端当前角色和会话，再以 ID+expected_version 原子更新。禁用、删除或降级最后有效管理员返回 409；两管理员并发互禁用/自降级已通过真实数据库测试。锁等待后再次核对会话，已被撤销的会话不能继续写入。

用户变更、版本递增、目标会话撤销、USER 审计及重置幂等记录在同一事务；审计失败回滚业务和会话。审计仅显式字段，不含密码/哈希/会话。用户历史仅 ADMIN 可查，销售业务审计不扩大到用户安全审计。

重置密码要求 Idempotency-Key，摘要使用服务端密钥 HMAC，避免保存可离线猜解的普通密码摘要。同键同内容重试不增加版本或审计；不同内容拒绝。前端不把成功后刷新失败当成创建失败，也不自动重复 POST。编辑固定提交初始版本，409 保留输入。

迁移只在本轮新隔离库执行。MySQL DDL 并非完整事务回滚，实际部署应先备份、安排窗口，迁移成功后重新初始化权限再启动应用；禁止在未确认的业务库运行。迁移明确拒绝破坏性 downgrade，需前向修复评审。就绪检查与授权初始化统一要求 `CURRENT_REVISION=0004_users`，旧 schema 返回未就绪。

## 运行账户最终权限矩阵

| 表 | SELECT | INSERT | UPDATE | DELETE |
|---|---|---|---|---|
| alembic_version | 允许 | 拒绝 | 拒绝 | 拒绝 |
| users | 允许 | 允许 | name,email,email_normalized,password_hash,role,is_active,registration_status,deleted_at,password_changed_at,version,updated_at | 拒绝 |
| system_guards | 允许 | 拒绝 | 仅 version（InnoDB 锁定读所需） | 拒绝 |
| sessions | 允许 | 允许 | 允许 | 拒绝 |
| auth_throttles | 允许 | 允许 | 允许 | 拒绝 |
| accounts | 允许 | 允许 | 允许 | 拒绝 |
| contacts | 允许 | 允许 | 允许 | 拒绝 |
| opportunities | 允许 | 允许 | 允许 | 拒绝 |
| activities | 允许 | 允许 | 允许 | 拒绝 |
| audit_events | 允许 | 允许 | 拒绝 | 拒绝 |
| idempotency_records | 允许 | 允许 | 拒绝 | 拒绝 |
| stored_objects | 允许 | 允许 | 仅 status,storage_version_id | 拒绝 |
| close_evidence | 允许 | 允许 | 仅 status,reviewed_by,reviewed_at,verification_note,approval_basis,version,updated_at | 拒绝 |

没有 schema 级泛化授权。users 的新增 INSERT/角色等 UPDATE 是实际用户管理功能所需；运行账户仍不能改变用户 ID/创建时间或物理删除。角色分配、最后管理员、用户状态流程以及证据核验业务规则仍由服务层实施；数据库权限不等于对象级业务授权。

管理、迁移、运行三身份必须明确配置且互异，错误配置在授权 SQL 之前失败。API/Worker 仅持运行凭据；真实失败门禁探测中初始化退出 1，依赖 API/Worker 保持 created，未伪就绪。

## 实际命令、结果与证据

下表均为最后功能代码的本轮结果。控制器 `control.py` 位于上述本轮私有目录；只连接已核验指纹的专用主机，注入本轮隔离连接，禁止直接用根 `.env` 数据库运行这些命令。

| 状态 | 实际检查/命令 | 结果与证据 |
|---|---|---|
| PASS | `control.py tunnel --command pytest --log pytest-final-current.log`，内部 `python -B -m pytest -q -p no:cacheprovider` | **315 passed**，57.07s，0 skipped；真实 MySQL 8.4.8。包含原业务回归、用户权限/审计失败回滚、会话撤销及独立最后管理员并发。1 条已有 TestClient/httpx 弃用提示 |
| PASS | `npm run typecheck` | TypeScript 通过，终端实际执行 |
| PASS | `npm test -- --reporter=dot` | **6 files / 103 tests passed**，终端实际执行 |
| PASS | `npm run build` | TypeScript + Vite 成功；依赖中 PURE 注释位置警告，无失败 |
| PASS | `backend/.venv/Scripts/ruff.exe check backend` | All checks passed |
| PASS | `backend/.venv/Scripts/ruff.exe format --check backend` | 66 files already formatted |
| PASS | Python AST 解析 | 全部项目后端 Python 文件成功；见 final-checks.json |
| PASS | `control.py deploy` | config --quiet / 实际镜像构建 / up --wait 成功；compose-config.log、compose-build.log、compose-up.log、compose-status.json。5 个长期服务 healthy，3 个正常初始化任务 exit 0 |
| PASS | `deployed_checks.py` | 容器内 40 个 app Python 文件与工作区 SHA-256 一致；deployed-source-check.json |
| PASS | `control.py tunnel --command api --log api-final.log` | **118 项 API 检查通过**，MySQL 8.4.8，真实独立 MinIO；api-final.log |
| PASS | `control.py tunnel --command browser --log browser-final.log` | **7 项浏览器测试通过**，24.6s，真实 NGINX/API/MySQL/MinIO；browser-final.log |
| PASS | `control.py tunnel --command permissions.py --log privileges-final.log` | **55 项数据库授权正反例通过**；SQL 授权探测回滚，实际用户写入另由集成/浏览器测试覆盖 |
| PASS | `isolation_checks.py` | API/Worker 凭据隔离；真实授权失败阻止启动。runtime-isolation.json |
| PASS | `upgrade_probe.py` | 新场景库 0003→0004，2 用户原字段/启用状态、客户 owner、审计 actor 保留；旧 schema 未就绪、新 schema 就绪；upgrade-a2ac85.log |
| PASS | 隔离迁移身份 `alembic check` | No new upgrade operations detected；alembic-check-final.log，迁移场景库也检查通过 |
| PASS | `Invoke-WebRequest http://localhost:5909/login` 及 `/api/v1/health/ready` | 均 200；仅本轮 Web 转发常驻，manual-launch.json |
| PASS | Git diff、索引、保护文件与秘密扫描 | HEAD 不变、无暂存、无私有文件入索引；保护文件及历史报告不变。final-checks.json |
| NOT RUN | GitHub 托管 CI | 已扩充隔离场景配置，未推送，不声称远端 CI 通过 |
| NOT RUN | 本机 MySQL 8.4.13 | 本轮真实测试仅远端 8.4.8 |
| NOT RUN | 本轮重新性能测量、容器持久化 restart/stop-start 全套 | 本轮没有改 Pipeline/存储计算；旧报告保留，本轮未以其数字冒充新验收 |
| NOT RUN | 生产 HTTPS、邮件投递及邮箱真实性验证 | 当前为本地测试部署；邮件未实现，无伪成功 |
| DEFERRED | 客户/联系人停用 | 继续此前约定，不恢复开发 |
| DEFERRED | Q05-A、Q07—Q10、Q11/Q12 其余未批准范围 | 不改变待确认决策 |

本轮最终必需回归无 FAIL/BLOCKED；以上 NOT RUN/DEFERRED 明确保留。中途曾出现前端邮箱提示/CRM 标题回归失败，已恢复一致文案与既有标题后重跑全套通过；没有删除测试或放宽断言。

七项浏览器包括：100 条以后的客户/联系人选择、两页面过期编辑保留输入、NGINX PDF 核验成交、丢失响应同键重试、创建客户/商机并推进阶段、用户完整生命周期、管理员创建用户/角色说明。新用户完整生命周期实际验证注册不可登录、审批、REP 登录、非 ADMIN 管理 API 403、角色改变与旧会话撤销、READ_ONLY 写入拒绝、禁用启用、重置响应丢失重试一次审计、个人资料/密码、逻辑删除恢复及客户 owner 保留。

截图目录 `.local/browser-runs/run-1793103922868-b0f6c7fd-8e48-4291-91ba-767f9de440a7/`，包含 user-lifecycle.png、admin-created-user.png 等，均使用 testInfo.outputPath，未覆盖旧截图。私有密码文件不得提交，浏览器截图仅合成数据。

## 安全与原工作保护

AGENTS.MD、根 `.env`、`.gitignore`、M1/M2-A/M2/验收/审查修复历史报告均与执行前 SHA-256 一致；所有执行前项目文件仍存在。没有 git add/commit/push、reset/clean/restore、删除数据库/对象/卷或更改原业务库。

检查了 281 个旧本地证据文件：280 个哈希不变；旧手动隧道后台进程因 SSH 断开自行追加了 `manual-web-c222ac9da3b9418eab71f7f91a4608f2.err.log`（SSH session not active），该文件哈希发生变化。未由本轮覆盖或清理。旧截图、正式历史报告均保持不变；旧 7200 隧道当前不可视为可用，新功能请使用 5909。

对全部拟提交文本扫描根配置及本轮随机秘密值、私钥/Token 形态，并人工核对 14 处密码/Token 字面量，均为测试合成值/CI 隔离占位。固定 `esc_business` 为模板账户标识，非秘密凭据；扫描初始对该标识的命中已分类核实，未将其当成真实密码。未发现真实秘密值进入候选文件。扫描不保证发现所有未知编码/外部秘密，也未扫描依赖二进制与数据库原件。

## 修改文件职责

- `backend/alembic/versions/0004_users.py`：用户状态与 guard 增量迁移。
- `backend/app/schema.py`、`backend/app/db.py`：统一当前 revision 与就绪检查。
- `backend/app/auth/models.py`：用户注册/删除字段及 guard 模型。
- `backend/app/auth/schemas.py`：公开用户字段与 UTC 时间序列化。
- `backend/app/auth/service.py`：拒绝待审批/删除用户登录与会话。
- `backend/app/users/__init__.py`、`schemas.py`、`repository.py`、`service.py`、`router.py`：用户校验、查询/CAS/锁、事务审计、生命周期与 API。
- `backend/app/main.py`：用户路由注册。
- `backend/app/runtime_grants.py`、`backend/tools/check_runtime_permissions.py`：实际用户权限增量及不可变 ID 探测。
- `backend/tests/test_users_unit.py`、`test_users_mysql.py`、`test_users_last_admin_mysql.py`：Schema、服务/权限/事务与真实并发回归。
- `.github/workflows/ci.yml`：CI 中独立最后管理员空场景库与分离身份准备；远端未执行。
- `frontend/src/user-validation.ts`、`users.tsx`、`users.test.tsx`：一致输入规则、注册/管理/个人页及组件回归。
- `frontend/src/App.tsx`：注册/用户/个人路由、角色导航及 M2 当前阶段说明。
- `frontend/e2e/users.spec.ts`：两项真实用户浏览器验收。
- `README.md`、`docs/decisions.md`、`data-model.md`、`api-spec.md`、`implementation-plan.md`、`test-plan.md`、本报告：使用入口、设计增量与实际证据。未重写历史执行报告。

## 人工验收与剩余限制

1. 打开 `http://localhost:5909/register`，使用合成邮箱注册，确认不自动登录、审批前登录失败。
2. 使用本轮私有 browser-private.json 中 ADMIN 测试账号登录；在“用户管理”筛选待审批用户，分配角色并审批。
3. 用新用户登录，检查菜单及直接 API 权限；再由 ADMIN 更改角色/禁用，原会话应失效。
4. 检查管理员创建、搜索筛选、编辑、409 冲突、重置密码、逻辑删除恢复和用户操作历史；不要使用真实密码/客户数据。
5. 在个人账号验证错误当前密码、本人的资料与密码修改、修改后强制重新登录。确认逻辑删除未删除名下客户。

当前采用四种固定角色，不支持自定义权限。注册邮箱只做格式校验，尚无所有权验证；忘记密码联系 ADMIN，管理员应通过可信渠道分发重置密码，不自动发邮件。未增加强制首次改密流程。公开入口生产开放前还需评估审批运维、可信代理/来源限流（当前按服务端观察到的来源地址，代理后可能共享预算）、HTTPS 和反滥用措施。未实现保留期限、自动清理、客户/联系人停用或 AI/M3。

首次 ADMIN 仍由既有 bootstrap 在明确隔离/受控环境建立；没有公开注册自提权通道。共享 guard 串行化管理写入是当前单企业规模的正确性取舍，未承诺未实测的性能 SLA。

等待用户评审与手动验收；本轮没有自动暂存、提交或推送。

## 完整拟提交清单

清单由最终 Git 已跟踪文件与全部未忽略未跟踪文件合并生成，排除用途未批准的 image.png；不包含 `.env`、`.local/`、依赖、缓存或测试生成物。该清单仅供审核，不执行暂存。

~~~text
.dockerignore
.env.example
.gitattributes
.github/workflows/ci.yml
.gitignore
.nvmrc
.python-version
AGENTS.MD
README.md
backend/Dockerfile
backend/alembic.ini
backend/alembic/env.py
backend/alembic/script.py.mako
backend/alembic/versions/0001_auth.py
backend/alembic/versions/0002_accounts_contacts.py
backend/alembic/versions/0003_sales_sales_core.py
backend/alembic/versions/0004_users.py
backend/app/__init__.py
backend/app/ai.py
backend/app/auth/__init__.py
backend/app/auth/dependencies.py
backend/app/auth/models.py
backend/app/auth/router.py
backend/app/auth/schemas.py
backend/app/auth/security.py
backend/app/auth/service.py
backend/app/bootstrap.py
backend/app/core/__init__.py
backend/app/core/config.py
backend/app/core/errors.py
backend/app/core/logging.py
backend/app/crm/__init__.py
backend/app/crm/models.py
backend/app/crm/repository.py
backend/app/crm/router.py
backend/app/crm/schemas.py
backend/app/crm/service.py
backend/app/db.py
backend/app/main.py
backend/app/runtime_grants.py
backend/app/sales/__init__.py
backend/app/sales/audit.py
backend/app/sales/domain.py
backend/app/sales/files.py
backend/app/sales/models.py
backend/app/sales/router.py
backend/app/sales/schemas.py
backend/app/sales/service.py
backend/app/sales/views.py
backend/app/schema.py
backend/app/storage.py
backend/app/users/__init__.py
backend/app/users/repository.py
backend/app/users/router.py
backend/app/users/schemas.py
backend/app/users/service.py
backend/app/worker.py
backend/pyproject.toml
backend/tests/conftest.py
backend/tests/test_crm_mysql.py
backend/tests/test_crm_unit.py
backend/tests/test_m2_review_fixes.py
backend/tests/test_mysql.py
backend/tests/test_sales_mysql.py
backend/tests/test_sales_unit.py
backend/tests/test_storage.py
backend/tests/test_unit.py
backend/tests/test_users_last_admin_mysql.py
backend/tests/test_users_mysql.py
backend/tests/test_users_unit.py
backend/tools/check_runtime_permissions.py
backend/tools/live_validation.py
backend/tools/m2_acceptance.py
backend/tools/m2_validation.py
backend/tools/prepare_compose.py
backend/tools/prepare_native.py
backend/tools/probe_env.py
backend/tools/proxy_validation.py
backend/tools/test_existing.py
backend/uv.lock
compose.yaml
docs/api-spec.md
docs/architecture.md
docs/data-model.md
docs/decisions.md
docs/implementation-plan.md
docs/m1-report.md
docs/m2-a-report.md
docs/m2-acceptance-report.md
docs/m2-report.md
docs/m2-review-fixes-report.md
docs/m2-users-report.md
docs/mysql84-replacement.md
docs/state-machine.md
docs/technical-design.md
docs/test-plan.md
frontend/Dockerfile
frontend/e2e/auth.spec.ts
frontend/e2e/m2-acceptance.spec.ts
frontend/e2e/sales.spec.ts
frontend/e2e/users.spec.ts
frontend/index.html
frontend/package-lock.json
frontend/package.json
frontend/playwright.config.ts
frontend/src/App.test.tsx
frontend/src/App.tsx
frontend/src/api.test.ts
frontend/src/api.ts
frontend/src/components.tsx
frontend/src/crm-selector.test.tsx
frontend/src/crm-selector.tsx
frontend/src/crm.css
frontend/src/crm.test.tsx
frontend/src/crm.tsx
frontend/src/main.tsx
frontend/src/sales.css
frontend/src/sales.test.tsx
frontend/src/sales.tsx
frontend/src/styles.css
frontend/src/test-setup.ts
frontend/src/user-validation.ts
frontend/src/users.test.tsx
frontend/src/users.tsx
frontend/tsconfig.json
frontend/vite.config.ts
infra/init-minio.sh
infra/minio-business-policy.json
infra/nginx.conf
tests/fixtures/crm-validation.json
~~~
