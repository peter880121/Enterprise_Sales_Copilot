# M3-B：受控执行与保留策略预览交付报告

日期：2026-10-28。依据：用户对 Q07/Q10 具体方案回复“计划通过”，限定范围见 [决策记录](decisions.md) 与 [实施计划](m3-b-plan.md)。本报告是新增交付记录，不替换 M1、M2、M3-A 历史证据。Git HEAD 仍为 `1cf537eefceb2cf2922eaa1476ac7d432bba18c3`，本轮未暂存、提交或推送。

## 1. 实际范围与边界

**PASS**：合成纪要冻结可执行变更及逐字段原文依据；前端默认不选中，明确确认后执行选定子集。允许 amount/currency 成组、expected_close_date、priority、source、同客户已有有效 primary_contact_id，以及追加 NOTE/TASK。预算不自动作为预计金额；未知不转零，缺失不清空。TASK 必须有明确合法负责人和截止时间。相对日期只在已知会议日期/时区下规范化，显示依据与转换说明；模糊、缺参或冲突标签不擅自补齐。

**PASS**：后端重新验证当前用户/会话、Q03 对象权限、草稿版本、商机版本、冻结活动上下文、客户及联系人关联和开放状态。商机 CAS、活动追加、白名单业务审计、草稿执行状态、唯一执行回执及幂等记录同事务提交。实际审计异常及执行回执外键失败均完整回滚。并发确认只有一次执行；响应丢失重试返回原回执，不重复增加版本/活动/审计；更换幂等键也不能再次执行同一草稿。未选变更不能在执行后补执行，需生成新草稿。

**PASS**：阶段、负责人、客户归属、概率、加权/实际成交金额、证据、成交/丢单/重开和删除不进入 AI 执行白名单。原人工状态命令不变。原始纪要与草稿继续独立鉴权；REP 全企业 CRM 可读不等于能读取其他负责人原文或执行其草稿。

**PASS**：ADMIN 可通过 GET 预览 Q10 的 90 天原文/派生引文、30 天已结束 Job/AIRun 详细材料、7 天完整幂等响应缓存候选。UTC 完整经过时间，边界包含等于截止点；运行中、待审核、执行引用或缺少必要引用阻断相应清理候选。返回计数、阻断原因和至多 20 个候选 ID，不返回原文。审计、成交证据、执行记录、身份及永久去重受保护。

**DEFERRED**：实际删除、归档、定时清理及缓存裁剪均未实现，本轮期限是只读政策预览，不能称为已实施自动到期。已确认写入 CRM/活动的业务记录不随纪要清理。Q11 草稿有效期未批准，expires_at 继续 null。客户/联系人停用仍延期。Q09 真实 Provider 和真实数据传输、知识库及其他未批准决策保持原状态。本轮使用 Mock 与合成数据，没有外发真实客户资料。

## 2. 文件及职责

以下包含未跟踪源码，全部仍留在工作区：

| 文件 | 本轮职责 |
| --- | --- |
| `backend/alembic/versions/0006_execution.py` | 增量冻结上下文、执行状态、唯一回执及活动来源去重迁移 |
| `backend/app/meetings/models.py`、`backend/app/sales/models.py` | 执行回执模型、草稿冻结/执行字段、活动来源键 |
| `backend/app/meetings/proposals.py` | 严格白名单、FACT 原文依据、合成标签提议、日期规范化与缺参限制 |
| `backend/app/meetings/context.py` | 冻结业务字段及活动版本摘要 |
| `backend/app/meetings/execution.py` | 重新鉴权、上下文/CAS、事务、唯一回执及永久去重 |
| `backend/app/meetings/retention.py` | ADMIN GET 只读候选统计，无删除入口 |
| `backend/app/meetings/service.py`、`processor.py`、`router.py` | 生成冻结提议、执行/回执路由、过期上下文展示及审核审计 |
| `backend/app/ai.py` | 合成字段标签与原提取结果保持一致，新任务版本标识不改历史行 |
| `backend/app/main.py`、`schema.py` | 预览路由注册及当前迁移门禁 |
| `backend/app/runtime_grants.py`、`backend/tools/check_runtime_permissions.py` | 新表仅 SELECT/INSERT、来源键/冻结摘要不可更新及真实权限探针 |
| `backend/pyproject.toml`、`backend/uv.lock` | 固定 tzdata 2025.2，为 Windows IANA 时区提供数据，不升级其他依赖 |
| `backend/tests/test_execution_unit.py`、`test_execution_mysql.py` | 白名单、边界、真实并发/事务/权限、回执及保留预览测试 |
| `backend/tests/test_meetings_mysql.py` | 已存在 apply 路由后的无效请求拒绝断言，保留负例 |
| `frontend/src/meeting-execution.tsx` | 差异/依据、默认未选、显式确认、固定版本/幂等键、成功与刷新失败分离 |
| `frontend/src/meetings.tsx` | 冻结提议、时间锚点、真实刷新、执行状态与权限失效时隐藏缓存 |
| `frontend/src/retention.tsx`、`App.tsx` | ADMIN 预览页、路由/导航及 M3-B 当前状态 |
| `frontend/src/meeting-execution.test.tsx` | 8 项执行交互及预览权限回归 |
| `frontend/e2e/execution.spec.ts`、`meetings.spec.ts` | 新增两项真实浏览器路径及现有导航回归 |
| `.dockerignore` | 排除额外环境配置与专用失败探针的私密构建材料 |
| `docs/decisions.md`、`technical-design.md`、`data-model.md`、`api-spec.md`、`test-plan.md`、`implementation-plan.md`、`m3-b-plan.md`、本报告、`README.md` | 批准边界、契约、迁移、测试及当前交付入口 |

先前 M3-A 未提交文件仍保留，完整当前候选清单见本地 `git-candidate-files.txt`；本轮没有移除或重新生成历史材料。

## 3. 迁移及运行权限

迁移链：`0004_users → 0005_meetings → 0006_execution`。0006 增加 nullable 字段/索引、执行记录表和状态约束，不删除既有数据；旧草稿新增字段为空，不能因升级自动变成可执行草稿，必须重新生成。DDL 有元数据锁与隐式提交风险，应由迁移身份在维护窗口执行；本轮只迁移新建隔离资源。破坏性 downgrade 明确拒绝，未在旧业务库试运行。

| 对象 | 运行身份权限 |
| --- | --- |
| `suggestion_executions`、`audit_events`、`idempotency_records` | SELECT/INSERT，无 UPDATE/DELETE |
| `ai_suggestions` | SELECT/INSERT；仅状态/审核/版本/发布提议及执行元数据列 UPDATE，冻结 base_snapshot/context_digest 不可 UPDATE |
| `activities` | SELECT/INSERT；仅 subject/content/due_at/status/completed_at/version/updated_at UPDATE，ai_execution_key 不可 UPDATE，无 DELETE |
| `alembic_version` | 仅 SELECT |
| 其他原业务表 | 保留显式逐表/列白名单，详见 runtime_grants.py，无全库授权、无任何 DELETE |

数据库保护不能替代服务层：提议发布后不可任意重写、FACT/依据、合法状态、任务关联、部分选择及业务版本仍由服务层执行。运行身份不是可供用户直连的数据库账户。API/Worker 只持运行身份，无迁移/root/存储管理密钥。初始化身份冲突在 SQL 前失败，并阻止依赖服务启动。

## 4. 环境、实际命令及结果

本轮资源：Linux 主机 `192.168.10.150` 上独立 Compose `esc-m2-core-848aae478f`，目录 `/home/zht/esc-m2-core-848aae478f`，数据库 `esc_m1_test_m2core_848aae478f`，独立 MySQL/MinIO 卷。实际 MySQL **8.4.8**，Docker **29.7.2**，Compose **5.4.0**。Windows 本地 Python 3.12 环境、Playwright Chromium 经 SSH 转发访问真实 NGINX。原 M2/M3-A 资源未迁移、停止或清理。

所有专用配置/密码及日志留在忽略目录 `.local/m3-execution-20261028/`，不得作为公开提交材料。以下 controller 命令完整前缀为 `uv run --no-project --with paramiko --with python-dotenv python .local/m3-execution-20261028/`；测试连接均由该控制器显式注入专用运行/准备身份，不使用默认 .env 业务连接。

| 状态 | 实际命令/检查 | 本轮结果及证据 |
| --- | --- | --- |
| **PASS** | `control.py tunnel --command regression.py --log backend-final-v2.log`；内部 `python -B -m pytest -q -p no:cacheprovider -k 'not last_admin_global_guard'` | **380 passed，1 deselected**，90.04 秒；真实 MySQL/MinIO，测试期间仅停止本轮 Worker，部署后恢复。`backend-final-v2.log` |
| **NOT RUN** | `test_last_admin_global_guard` 专用新库测试 | 本轮未配置独立 last-admin 数据库，明确排除，历史通过不替代本轮结果 |
| **PASS** | `npm.cmd run typecheck`、`npm.cmd test`、`npm.cmd run build`（frontend） | TypeScript 通过、**119 tests / 8 files passed**、Vite 构建通过；第三方 PURE 注释有非阻断构建警告。原始结果见执行终端，命令及结果摘要另存 `local-check-summary.json`，不冒充独立原始日志 |
| **PASS** | `.venv/Scripts/python.exe -m ruff check .`；`-m ruff format --check .`（backend） | 全部检查通过，82 文件格式符合 |
| **PASS** | `control.py deploy`；真实 `config --quiet`、`build`、`up -d --wait --wait-timeout 240` | 当前源码标准构建并启动，5 个常驻服务健康，3 个正常初始化任务退出 0；`compose-build-final.log`、`compose-up.log`、`compose-status.json` |
| **PASS** | `deployed_checks.py` | 容器中 50 个 app Python 文件 SHA256 与本地一致，`alembic check` 无差异；`deployed-source-check.json`、`alembic-check-final.log` |
| **PASS** | `upgrade_probe.py` | 独立 `..._upgrade6_3df67a` 库从0005升级0006；旧原文/草稿/活动保留，旧 schema 不就绪、新 schema 就绪、模型无差异；`upgrade6-3df67a.log` |
| **PASS** | `control.py tunnel --command permissions.py --log permissions-final.log` | **82 项**真实权限允许/拒绝探针全部符合预期；包含执行回执、冻结摘要及活动来源键保护 |
| **PASS** | `isolation_checks.py` | API/Worker 仅运行凭据；故意冲突身份的独立 `...-grant-failure` 初始化退出 1，API/Worker 均 created 未启动；`runtime-isolation.json` |
| **PASS** | `final_runtime.py` | 对 API/Worker/初始化容器原始日志在内存中扫描本轮已知秘密精确值，命中0，仅保存日志摘要哈希与结果，不输出秘密；`container-log-scan.json` |
| **PASS** | `control.py tunnel --command api --log api-final.log` | **118 项 API 检查**，失败0，MySQL8.4.8；本轮新建合成测试用户 |
| **PASS** | `control.py tunnel --command browser --log browser-final.log` | **12 项浏览器测试**全部通过，45.0秒，真实 NGINX/API/Worker/MySQL/MinIO |
| **PASS** | `python .local/m3-execution-20261028/protection_check.py` | 13 个保护文件哈希一致，无既有文件缺失、索引为空；候选文本秘密扫描无命中，检查范围/限制见第6节 |

浏览器覆盖：部分选择且未选字段保持原值；真实服务器已提交后丢弃响应，手动同键重试只执行一次；ADMIN 仅预览；超过100个客户/联系人选择器；两页面409保留输入；NGINX PDF 上传核验成交；原命令响应丢失重试；Mock Worker/依据及拒绝不写 CRM；历史分页不清输入；销售流程；注册审批/角色/密码/逻辑删除及用户审计分页。截图9张保存在独立 `.local/browser-runs/run-1793160660170-0c3e257f-4290-45f3-813d-e08200b769fe/`，不是合成截图。

## 5. 初次失败、构建复现及未运行范围

初次 Windows 相对日期测试缺少 IANA 时区数据，新增固定 tzdata 后边界测试通过。初次新增前端测试回调类型不匹配，修正测试辅助函数类型后 TypeScript 通过。数据库最终回归、前端及部署结果均来自修复后版本。

标准线上依赖安装实际准备34个包，耗时12分51秒（`compose-build-online-success.log`，含 tzdata2025.2）。此前误启动的两个重复构建客户端已按专用项目精确匹配停止，未清理容器/数据，记录于 `build-clients-stop.log`，后续串行构建成功。**离线 wheel 方案未进入正式构建，本轮未使用离线回退**；backend Dockerfile 仍执行锁定的标准 uv sync。清洁检出具备源码/锁文件/固定基础镜像构建输入，但本轮未做全新检出且全空缓存复现，网络、镜像源可用性仍是依赖；不能宣称完全离线可复现。

升级探针首次因非root探针进程无法读取0600管理配置退出，尚未创建测试库；仅独立管理探针改用容器root后成功，API/Worker身份未变。首次门禁脚本错误引用镜像摘要，触发镜像源拉取失败而没有创建门禁容器；改为复用已运行服务的本地镜像名并禁止拉取，真实初始化失败门禁通过。失败日志均保留：`upgrade6-60f372.log`、`runtime-isolation-first-failure.log`、`runtime-isolation-image-failure.log`，不能将这些网络/脚本错误算作业务鉴权拒绝。

**NOT RUN**：其他 MySQL版本、远端 GitHub CI、生产 TLS/部署、真实 Provider 质量/费用/网络故障、全新空缓存检出构建、本轮新增执行后的容器重启/stop-start持久化专项、重新进行性能基线测量。此前 M2 性能/持久化数字不复用为本轮结果。本轮新增事务数据已验证提交后真实重新读取，但不将其等同于重启持久化验收。

**DEFERRED**：实际清理/归档及永久去重缓存裁剪机制、草稿自动失效期限、客户/联系人停用。Q05-A、Q08/Q09 及 Q11/Q12 未批准部分保持未批准，不扩展为新增审批/保留/知识库功能。

## 6. 保护检查、手动验收及结论

保护检查比较任务开始快照：AGENTS.MD、根 .env、.gitignore、image.png 和 M1/M2/M3-A 历史报告等13项哈希不变；开始时所有文件仍存在。HEAD未变、暂存区为空，`.env`、`.local/`、image.png 均未被 Git 跟踪。扫描全部 Git 可见候选文本，包括未跟踪源码，检查本轮随机秘密、根配置中可识别秘密的精确值及私钥标记，无命中。此扫描不等于能识别所有未知凭据；未扫描 Git 忽略的私有材料、二进制图片或历史提交内容。真实配置/合成账号只留忽略目录，不输出到报告。

手动入口：`http://localhost:7034`。已实际 GET 就绪接口返回200；原 `14757`（M3-A）、`5909`（M2）仍200。本机独立 SSH 转发需保持运行，关闭会使入口不可用。合成账号取自本地私有 `browser-private.json`，不要公开密码。推荐：经理创建开放商机→会议解析→输入页面列出的合成标签→核查差异/依据→只选部分变更并确认→查看真实商机/活动与执行回执；ADMIN进入保留预览，确认只有读取，没有清理按钮。任务截止或联系人ID需提供现有合法对象。

结论：**本轮限定 M3-B 功能实现及已执行回归通过，可进入用户评审**；不是全部 M3/生产验收通过。最后管理员专库测试等 NOT RUN 项及明确延期项继续列示。不得据此自动启用真实 Provider、实际清理、知识库或其他未授权范围。没有自动暂存、提交、推送。
