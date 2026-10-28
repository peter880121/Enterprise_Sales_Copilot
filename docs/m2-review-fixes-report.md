# M2 提交前审查修复报告

日期：2026-10-27。本轮仅修复用户批准的 1 项 P1、4 项 P2；不进入 M3，不恢复客户/联系人停用，不批准新业务决策。原审查及 `m2-acceptance-report.md`、M2/M2-A/M1 历史执行记录保持原样。本报告不是已批准提交或 M2 全范围完成声明。

## 1. 起点、资源与保护

实际检查 HEAD 为 `bc425b6e5d3eb923711502c61bb571996e3ec9a7`，master 分支、暂存区为空；所有已有 M2 修改和未跟踪源码均保留。先读取实际源码、认证/数据库/测试结构、决策、实施计划及验收报告，再实施。

本轮证据目录：`.local/m2-review-fixes-20261027-94336a99/`。保存任务开始的 111 个工作文件指纹和 229 个既有本地证据指纹。私密连接及合成用户密码只保存在忽略目录，不公开完整连接字符串。

另建本轮专用 Compose 项目 `esc-m2-core-425fe123ab`，远端目录 `/home/zht/esc-m2-core-425fe123ab`，数据库 `esc_m1_test_m2core_425fe123ab`，使用独立网络、MySQL/MinIO 卷、随机密码和回环入口。没有重启或迁移原 M1、此前 `esc-m2-core-14837bf2c7` 或其他业务资源。

实际验证为 MySQL **8.4.8**；后端 Python 3.12.7。浏览器访问真实 NGINX、API、MySQL、MinIO，使用合成客户、用户及 PDF；没有调用真实 AI Provider。

## 2. 五项修复与取舍

| 原问题 | 最终修复 | 验证 |
| --- | --- | --- |
| P1 三种数据库身份可能同名 | `runtime_grants.py` 显式校验管理连接用户名、`MYSQL_MIGRATION_USER`、`MYSQL_RUNTIME_USER`；非空、合法、三者互异，在创建 engine 或执行任何 SQL 前拒绝错误配置。Compose 只向一次性授权任务传递迁移身份名称 | 三种相等组合、各身份缺失/非法/超长负例，断言 engine 从未创建；真实失败启动门禁 |
| P2 泛化运行权限 | 12 张表的显式操作白名单，无 schema-wide INSERT、无任何 DELETE；用户、原件、核验表进一步限制 UPDATE 列 | 51 项真实 SQL 允许/拒绝检查，拒绝必须是 MySQL 1142/1143；并用真实业务 API 验证持续写入 |
| P2 审计遍历全部 ORM 列 | 新增 `sales/audit.py`，分别列出 Opportunity、Activity、CloseEvidence 的字段；所有审计 before/after 使用该集合，响应序列化独立保留 | 模拟新增内部 ORM 列，不迁移真实模型；响应辅助函数可见该合成列，审计不可见；金额/日期/空值/版本口径保留，真实事务回滚仍通过 |
| P2 选择器仅前 100 条 | 新增共享选择器，服务端搜索、25 条分页、选中对象独立读取；联系人列表限定 Account；切换客户清空旧联系人 | 单元测试 125 客户/125 联系人；真实浏览器翻至第 5 页选择第 125 项、提交并重新编辑；无结果、错误、原版本和输入保留 |
| P2 浏览器覆盖旧截图 | 两个测试文件共用唯一输出配置；截图通过 testInfo.outputPath；默认或 E2E_OUTPUT_DIR 均创建 UUID 子目录，不复用旧运行目录；禁止 CLI --output 绕过安全父目录 | 默认 5 项真实浏览器通过，显式目录的超过 100 条场景复验；旧截图及 229 个历史证据指纹不变 |

选择器的搜索、翻页、后台刷新只改变查询状态，不重新设置 RHF 表单默认值或 `expected_version`。编辑时父客户仍不可改；已选联系人即使不在当前结果中仍有独立选项。查询失败显示独立错误和重试按钮，不冒充空结果。没有引入前端依赖。

审计字段保持当前业务所需的来源、客户/联系人关联、负责人、金额/币种、阶段/概率、版本、关闭/归档、活动和核验信息；Decimal 仍为两位小数字符串、日期 ISO、时间 UTC、空值 null。未修改任何历史审计记录，没有为模拟内部字段添加真实列或迁移。

## 3. 最终运行账户权限矩阵

| 表 | SELECT | INSERT | UPDATE | DELETE |
| --- | --- | --- | --- | --- |
| alembic_version | 是 | 否 | 否 | 否 |
| users | 是 | 否 | 仅 password_hash（认证重哈希） | 否 |
| sessions | 是 | 是 | 是（会话更新/撤销） | 否 |
| auth_throttles | 是 | 是 | 是（登录计数/时间窗） | 否 |
| accounts | 是 | 是 | 是 | 否 |
| contacts | 是 | 是 | 是 | 否 |
| opportunities | 是 | 是 | 是（含 CAS/阶段/归档） | 否 |
| activities | 是 | 是 | 是（编辑/完成） | 否 |
| audit_events | 是 | 是 | 否 | 否 |
| idempotency_records | 是 | 是 | 否 | 否 |
| stored_objects | 是 | 是 | 仅 status、storage_version_id | 否 |
| close_evidence | 是 | 是 | 仅 status、reviewed_by、reviewed_at、verification_note、approval_basis、version、updated_at | 否 |

授权只针对这些明确表；新表不会自动取得运行权限。管理连接只用于隔离实例的授权初始化；迁移身份负责 Alembic 和明确授权的合成夹具准备；API/Worker 环境只有运行数据库凭据及业务 MinIO 凭据，没有管理或迁移密码。

测试准备通过 `TEST_SEED_DATABASE_URL` 使用同一隔离库的另一身份，`TEST_DATABASE_URL` 始终是实际受限运行身份。夹具的用户创建、改角色/失活等设置不再扩大运行账户权限；审计权限、业务 CAS、事务回滚仍使用运行身份测试。CI 与 `m2_validation.py` 同步使用这套授权器；旧测试配置没有独立迁移身份时明确停止，保留旧配置，需选择新的 `--evidence-dir`。

开发账号 bootstrap 改由一次性 migrate 服务执行，API/Worker 不取得 users INSERT 权限。仅在获授权的独立开发环境使用，仍保留原有开发模式和密码要求。

**仍由服务层执行的不可变规则**：核验结果从 PENDING 转出后不可覆盖；列级授权本身不能表达行状态约束；商机终态冻结、证据所属对象/上传人、核验职责分离、唯一选定证据、CAS 和幂等请求摘要仍由服务层及既有数据库约束共同保证。MinIO 业务凭据的既有对象写权限没有被宣称为 WORM；随机对象键、无覆盖 API、版本引用与下载 hash 校验仍保留。本轮不引入 Object Lock 保留期限、触发器、存储过程或自动清理政策。

## 4. 实际失败、修正与最终回归

首次真实数据库回归为 **274 passed / 10 failed**，未计作成功：收紧后的 idempotency_records 只有 SELECT/INSERT，但旧 replay 使用 FOR UPDATE；真实 MySQL 8.4.8 返回 1142。`locking-probe.log` 实际对比普通 SELECT 成功、FOR UPDATE 被拒绝。replay 已有同事务操作者行锁、唯一键且结果不可改删，故移除冗余的记录锁定读取，没有放宽权限。新增同操作者同键并发回归，证明只产生一份结果、一次版本增加及一次业务审计。原 20 轮版本冲突测试保留。

初次 Ruff 有两处行长问题，修正后通过；额外输出保护探针曾错误要求 CLI 解析器拒绝短参数时也必须包含配置层提示，实际 CLI 已拒绝该参数，修正的是探针判断，没有运行或覆盖旧证据。

| 状态 | 本轮实际检查 | 结果与证据（均在本轮 .local 目录） |
| --- | --- | --- |
| PASS | 配置及前后端实际构建、启动 | `compose-config.log`、`compose-build.log`、`compose-up.log`；新项目独立启动，后续受影响 API/Worker/前端重新构建 |
| PASS | 主服务健康及部署代码一致性 | 五个长期服务 healthy、三个主初始化任务 exit 0；runtime_grants、sales/audit、sales/service 及前端入口、NGINX 文件与本地 SHA 一致，`deployed-source-integrity.json` |
| PASS | 后端完整单元及真实 MySQL 集成 | **285 passed**，1 个既有 Starlette/httpx 弃用提示，`pytest-final.log`；含新身份/审计测试、20 轮并发及同键并发重放 |
| PASS | 表/列权限正反例 | **51 项全部通过**，`permissions-real.json`；实际执行 SQL，所有探针事务回滚；INSERT/UPDATE 探针用空行集确认权限，实际持久化另由下列 API 检查证明 |
| PASS | 真实 API/MySQL/MinIO | **118 项通过**，`api-final.log`、`api-checks.json`；含真实上传完成、核验、成交、幂等、审计 INSERT 及越权拒绝 |
| PASS | 初始化失败门禁及凭据隔离 | `runtime-isolation.json`；独立失败项目运行身份故意等于迁移身份，init exit 1，API/Worker 维持 created，不能伪就绪；正常项目 API/Worker 无管理/迁移密码 |
| PASS | 默认浏览器运行 | **5 passed**，`browser-default.log`；原 4 项关键流程加 125 客户/125 联系人的真实选择提交/重新编辑 |
| PASS | 显式浏览器证据父目录 | 超过 100 条场景再次实际通过，最终配置复验见 `browser-explicit-final.log`；生成新的 UUID 子目录 |
| PASS | 旧证据保护及覆盖参数拒绝 | `evidence-integrity.json`：229 个既有证据无变化/缺失；旧截图 hash 不变；`browser-output-override-rejected.log`、`browser-output-guard-*.log` 记录拒绝 CLI 覆盖 |
| PASS | 前端单元与交互 | **95 passed**，`frontend-test.log` |
| PASS | TypeScript、生产构建 | `frontend-typecheck.log`、`frontend-build.log`；Zod 注释优化提示保留，未升级依赖 |
| PASS | Python 静态与语法 | Ruff check、format --check：52 文件通过；AST 解析 56 文件，无语法错误 |
| PASS | 迁移一致性 | `model-check.log`：No new upgrade operations detected；没有新增迁移或手工改表 |
| PASS | 既有资源与日志 | `resource-protection.json` 原容器/卷无缺失及运行状态改变；`log-scan.json` 本轮容器日志未匹配到已配置秘密 |
| NOT RUN | GitHub 远端 CI、本机 MySQL 8.4.13 最终回归 | 不用此前版本的结果替代本轮验证；本轮实际数据库是 8.4.8 |
| NOT RUN | 本轮性能及 restart/stop/start 复测、全冷缓存/离线构建 | 未无理由重复与此次修改无关的性能实验；没有将上一轮结果标成本轮通过 |
| NOT RUN | 单独执行 m2_validation 的新建资源 CLI | 本轮使用明确隔离的 Compose 编排；共享 CLI 的修改经静态检查，未操作其旧连接/历史目录 |
| DEFERRED | 客户/联系人停用及对应验收 | 不恢复实现；Q05-A、Q07—Q10、Q11/Q12 其余范围仍待确认 |

## 5. 实际命令与证据方式

项目根目录的私有编排器在创建资源前验证 SSH 主机指纹，使用既有授权控制入口；连接参数不在命令或日志中回显。实际执行：

```powershell
uv run --no-project --with paramiko --with python-dotenv python .local/m2-review-fixes-20261027-94336a99/control.py deploy
uv run --no-project --with paramiko --with python-dotenv python .local/m2-review-fixes-20261027-94336a99/control.py tunnel --command pytest --log pytest-final.log
uv run --no-project --with paramiko --with python-dotenv python .local/m2-review-fixes-20261027-94336a99/control.py tunnel --command permissions.py --log permissions-real.json
uv run --no-project --with paramiko --with python-dotenv python .local/m2-review-fixes-20261027-94336a99/control.py tunnel --command api --log api-final.log
uv run --no-project --with paramiko --with python-dotenv python .local/m2-review-fixes-20261027-94336a99/isolation_checks.py
uv run --no-project --with paramiko --with python-dotenv python .local/m2-review-fixes-20261027-94336a99/control.py tunnel --command browser --log browser-default.log
uv run --no-project --with paramiko --with python-dotenv python .local/m2-review-fixes-20261027-94336a99/control.py tunnel --command browser-explicit --log browser-explicit-final.log
```

子进程实际为后端 `python -B -m pytest -q -p no:cacheprovider`、`python -B -m tools.m2_acceptance`、`tools.check_runtime_permissions.main()`；前端 Playwright 运行两个销售测试文件，显式目录复验使用 `--grep "selects and persists"`。新运行目录由安全配置自行生成，不使用 CLI --output。`permissions.py` 只是调用共享权限探针的本地入口。

Compose 实际运行 config --quiet、build、up -d --wait、ps；迁移一致性使用本项目独立的一次性 migrate 任务执行 alembic check。没有对原配置业务库迁移，没有删除数据库、对象、容器或卷。

本机还执行 backend 下 `ruff check app tests tools`、`ruff format --check app tests tools` 及 AST 解析；frontend 下 `npm test -- --reporter=dot`、`npm run typecheck`、`npm run build`。这些静态检查不冒充数据库或浏览器测试。

## 6. 本轮文件职责与剩余边界

- `runtime_grants.py`、Compose、CI、`m2_validation.py`：身份分离、授权白名单及共享初始化路径。
- `sales/audit.py`、`sales/service.py`：显式审计与响应快照分离；去掉不必要的幂等记录锁读取，不改变已有操作者锁与事务边界。
- `tests/conftest.py`、三个 MySQL 测试文件、`test_m2_review_fixes.py`：准备身份分离、身份/审计负例及同键并发回归；原断言和测试保留。
- `tools/check_runtime_permissions.py`、`tools/m2_acceptance.py`：真实权限探针与独立夹具身份，均要求显式隔离测试连接。
- `crm-selector.tsx`、`sales.tsx`、`crm-selector.test.tsx`：分页搜索、选中项保留、关联重置及表单版本保护。
- Playwright 配置和两个销售 E2E 文件：唯一输出、超过 100 条真实浏览器场景、固定截图路径移除。
- README 及本报告：新入口、开发账号准备身份、实际结果及提交候选清单。历史报告不改写。

没有依赖升级、模型变更或新增迁移。SQL 列权限无法替代服务层的行级业务规则；数据库管理身份仍是可信管理边界。新配置的秘密轮换不是本轮实施范围。PDF 解析资源隔离、MinIO 底层凭据边界及更广验收编排可移植性仍按原报告保留，不借本轮修复宣称已解决。

**本轮五项修复可进入 M2 提交审批**，最终提交仍须用户明确批准；不自动 add/commit/push。M2 全范围完成状态不随此结论自动改变，NOT RUN、DEFERRED 和待确认决策保留，不进入 M3。

## 7. 更新后的完整拟提交增量清单

清单包含从 M1 起的所有已修改文件及未跟踪 M2 源码、迁移、测试、配置、锁文件和正式文档。排除根 `.env`、整个 `.local/`、`image.png`、虚拟环境、依赖、构建产物及测试生成物。完整列表在最终核对后附下；不是已执行的暂存操作。

????? **66 ?????**?25 ??????41 ?????????? M1 ??????????????????????

```text
.env.example
.github/workflows/ci.yml
README.md
backend/alembic/env.py
backend/alembic/versions/0002_accounts_contacts.py
backend/alembic/versions/0003_sales_sales_core.py
backend/app/core/errors.py
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
backend/pyproject.toml
backend/tests/conftest.py
backend/tests/test_crm_mysql.py
backend/tests/test_crm_unit.py
backend/tests/test_m2_review_fixes.py
backend/tests/test_mysql.py
backend/tests/test_sales_mysql.py
backend/tests/test_sales_unit.py
backend/tools/check_runtime_permissions.py
backend/tools/m2_acceptance.py
backend/tools/m2_validation.py
backend/tools/prepare_compose.py
backend/uv.lock
compose.yaml
docs/api-spec.md
docs/architecture.md
docs/data-model.md
docs/decisions.md
docs/implementation-plan.md
docs/m2-a-report.md
docs/m2-acceptance-report.md
docs/m2-report.md
docs/m2-review-fixes-report.md
docs/state-machine.md
docs/technical-design.md
docs/test-plan.md
frontend/e2e/m2-acceptance.spec.ts
frontend/e2e/sales.spec.ts
frontend/playwright.config.ts
frontend/src/App.tsx
frontend/src/api.ts
frontend/src/crm-selector.test.tsx
frontend/src/crm-selector.tsx
frontend/src/crm.css
frontend/src/crm.test.tsx
frontend/src/crm.tsx
frontend/src/sales.css
frontend/src/sales.test.tsx
frontend/src/sales.tsx
infra/nginx.conf
tests/fixtures/crm-validation.json
```

## 8. 最终保护与提交准入核对

`final-integrity.json` 实际确认：AGENTS.MD、根 `.env`、`.gitignore`、M1/M2-A/M2 及上一轮验收报告指纹不变；229 个既有本地证据无变化或缺失；原有工作文件无丢失。本轮仅修改 15 个已有文件并新增 6 个相关文件，保留全部其他既有修改。

66 个候选文本未匹配到已配置的真实秘密或私钥头；这不等于可以检测任意未知秘密。`.env`、`.local/`、`image.png` 均不在 Git 索引。Git diff --check 通过，只有换行规范提示；暂存区为空，master 的 HEAD 仍是 M1 基线。CI 内嵌 Python 仅做语法检查通过，远端 CI 仍为 NOT RUN。

本轮要求的五项修复、针对性回归、真实权限与浏览器验证没有剩余 FAIL 或 BLOCKED，可提交用户审批；未运行和延期项继续按上文单列。没有提交、推送、清理原资源，也没有开始 M3。
