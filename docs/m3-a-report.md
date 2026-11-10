# M3-A：合成会议解析与草稿审核

日期：2026-10-28。

## 已提交成果与本轮范围

按用户“提交，然后进入 M3”指示，已创建 M2/M2.1 提交：

- 哈希：`1cf537eefceb2cf2922eaa1476ac7d432bba18c3`
- 信息：`feat: deliver M2 CRM and user management`
- 85 个变更文件，9877 行新增、85 行删除。提交前逐项核验 131 个候选文件，未使用 git add . / -A；image.png 保留未跟踪，真实配置/本地证据未纳入。未推送。
- 提交后暂存区为空。之后的 M3 修改留在工作区，没有创建第二个提交。

用户进一步明确选择“先实现解析与草稿审核，保留 Q07/Q10 待确认”。本轮已实现持久化会议任务、确定性 Mock 解析、依据展示和草稿拒绝/放弃；没有 apply 接口或任何 CRM 执行。完整 M3 设计的人工确认后受控执行仍未完成，不能把本报告作为整个 M3 验收通过。

## 实际功能

- 提交合成纪要：明确 MOCK，非空且不超过 50000 字符、版本检查、UUID request_token 去重；事务写入 Job/Analysis/Suggestion/审计后返回 202。重复 token 同内容返回原资源，不同内容 409；不修改商机或活动。
- 真正的异步 Worker：MySQL 持久化队列，FOR UPDATE SKIP LOCKED 领取，60 秒租约、随机 token，进程重启后可回收过期租约；外部处理在事务外。超时/连接失败至多 3 次，指数延迟；非法输出不重试为假成功。晚到旧租约结果不能覆盖新结果，自己的 AIRun 标为 DISCARDED。
- Mock 仅识别明确的 `需求：/预算：/联系人：/决策人：/成交时间：/待办：/风险：` 标签（也支持半角冒号）。它是确定性演示解析器，不是真实 LLM；未识别字段为 UNKNOWN，不补造金额、日期或决策人。长值超过演示提取上限不伪造提取结果。
- 结构化输出严格校验 extra、类型、七主题唯一性、FACT/INFERENCE/UNKNOWN、原文 quote 与 Unicode 码点位置；FACT 值须出现在所引原文中。FACT 表示原文记载，并非内容经独立核验。Mock 不生成推断；Schema 支持显式 INFERENCE 以保持边界，但没有实际模型质量结论。
- 结果没有可执行变更，proposed_changes 恒空、execution_enabled=false；草稿 expires_at 恒 null。不自动过期、不清理数据，不默认采用原设计 24 小时有效期提案。
- 草稿审核：DRAFT→REJECTED/ABANDONED，原因、版本、同事务审计及幂等结果。并发/旧版本拒绝，响应丢失可用原 key 重试；审核不会改变 CRM。源商机版本改变时只读视图报告 STALE，不把它标为可执行新版本。
- 前端 `/meetings`：服务端搜索/分页选择商机、确认合成数据、提交、真实排队/运行/失败反馈、轮询、历史分析、原文/依据/未知信息及审核。用户输入及提交基准版本不因后台刷新自动变更。网络失败保留同内容 request_token。引用按文本渲染，不执行 HTML/脚本。

## 权限与数据保护

当前有效 ADMIN/SALES_MANAGER 或该商机负责人 REP 才能读取/提交/审核纪要与草稿。全企业 CRM 可读不等于原文可读；READ_ONLY、他人 REP 直接 API 403。Job 的 REP 读取还需为任务创建人；Manager/Admin 仍需对应 AI 权限。

提交/审核事务重新核验服务端用户及会话；Worker 发布重新核验当前用户与负责人权限，角色撤销后结果不可发布为可用草稿。原文、引文、提取结果、审核说明不复制到业务审计/日志；审计显式保存 ID、状态、模式、版本、hash/长度等元信息。供应商异常只保存脱敏稳定错误码。

REAL 模式入口明确返回 AI_PROVIDER_UNAVAILABLE，Worker 也不调用真实模型、不自动降级 Mock。未向任何 AI Provider 发送项目数据，没有使用真实客户资料。未实现知识库、上传解析、受控 CRM 执行、保留期限或自动清理。

## 模型、迁移和授权

新增 `0005_meetings`（接续 0004_users），仅新增 jobs、meeting_analyses、ai_suggestions、ai_runs 四表及索引/约束，不修改既有 CRM 表/数据。原设计中完整 Job/建议能力是后续范围；本轮 Job 专用于会议，没有通用任务 payload 或执行功能。

当前 revision 统一为 0005_meetings；旧 schema 不会被新 API 判就绪。只在新建 M3 隔离项目执行迁移，未迁移原业务库或 M2 演示库。迁移 DDL 非事务性，实际升级须备份、明确维护窗口并运行迁移和授权初始化；破坏性 downgrade 被禁止，不自动删除会议历史。

运行账户仍按表授权，旧表权限不变。新表权限为：

| 表 | SELECT/INSERT | UPDATE 列白名单 | DELETE |
|---|---|---|---|
| jobs | 允许 | status,attempts,available_at,lease_until,lease_token,error_code,updated_at | 拒绝 |
| meeting_analyses | 允许 | status,result,updated_at | 拒绝 |
| ai_suggestions | 允许 | status,reason,reviewed_by,reviewed_at,version,updated_at | 拒绝 |
| ai_runs | 允许 | status,error_code,ended_at,latency_ms | 拒绝 |

管理/迁移/运行身份分离机制保留。真实数据库验证了纪要 input_text、Job request_hash、建议 analysis_id、AIRun input_hash 的 UPDATE 被拒绝。对象权限、Schema、租约和草稿状态机仍由服务层实施，不把 SQL 账户权限当作对象授权。

## 隔离环境及证据

新项目 `esc-m2-core-254955627b`（沿用工具命名前缀，但资源用途为 M3-A），目录 `/home/zht/esc-m2-core-254955627b`，新库 `esc_m1_test_m2core_254955627b`，**MySQL 8.4.8**、独立 MinIO。新 Web 远端回环 58637、本机转发 **http://localhost:14757**。原 M2 环境与 `http://localhost:5909` 保留。

本轮证据/私有控制配置：`.local/m3-drafts-20261028/`；管理员/销售合成凭据仅在该目录 browser-private.json，不显示密码。控制器只注入该隔离库，不应以默认 `.env` 执行测试。

| 状态 | 实际命令/检查 | 结果 |
|---|---|---|
| PASS | `control.py deploy`，实际 config --quiet/build/up --wait | 新环境构建及启动通过；5 个长期服务健康，3 个正常初始化任务退出 0 |
| PASS | `control.py tunnel --command regression.py --log backend-final.log`，内部 `python -B -m pytest -q -p no:cacheprovider -k 'not last_admin_global_guard'` | **343 passed、1 deselected**，70.88 秒；真实 MySQL，包括新租约、权限、并发、输出错误、审核幂等/回滚、权限改变和三次超时失败回归 |
| PASS | `npm.cmd --prefix frontend test -- --reporter=dot` | **109 passed / 7 files** |
| PASS | `npm.cmd --prefix frontend run typecheck` / `run build` | TypeScript 与 Vite 构建通过；已有依赖 PURE 注释警告 |
| PASS | Ruff check / format --check | 全通过，75 个 Python 文件格式符合 |
| PASS | `deployed_checks.py`、隔离迁移身份 `alembic check` | 容器内 46 个后端 app 文件与本地 SHA-256 一致；No new upgrade operations detected |
| PASS | `control.py tunnel --command api --log api-regression.log` | **118 项**原业务 API 回归通过，真实 MySQL/MinIO |
| PASS | `control.py tunnel --command browser --log browser-final.log` | **9 项**真实浏览器测试通过，31.9 秒；原 8 项和新 Mock 会议 Worker/私有资料拒绝/审核/CRM 不变流程 |
| PASS | `control.py tunnel --command permissions.py --log permissions.log` | **75 项**运行账户授权正反例通过，含新表只读来源字段及所有 DELETE 拒绝 |
| PASS | 保护文件/已知秘密扫描、AST、Git diff/索引核验 | 无保护文件改写、无已知秘密命中；M3 未暂存或提交 |
| PASS | 本机 Invoke-WebRequest：14757/login、14757/api/v1/health/ready、5909/api/v1/health/ready | 新 M3 登录/就绪和保留的 M2 就绪均为 200；独立 Web 隧道运行 |
| NOT RUN | 独立空库最后管理员并发 | 本轮 deselect 1 项，不复用旧非空场景，不将历史结果冒充本轮 |
| NOT RUN | 真实 Provider、真实模型质量/成本、生产流量性能、长时间运行/外部调用中续租 | 本轮纯 Mock，单次演示解析短于租约；尚无真实调用，不声称 exactly-once 或真实模型验收 |
| NOT RUN | 托管 CI、MySQL 8.4.13、本轮全套 stop/start 持久化与故障部署门禁 | 保留旧证据，未作为本轮通过；本轮租约故障由真实数据库验证 |
| DEFERRED | Q07 对应 CRM apply/部分选择/执行闭环 | 用户本轮明确排除；完整 M3 I09/I10、E06—E08 执行部分尚未完成 |
| DEFERRED | Q10 保留/清理、Q11 其余期限/预算、Q09 真实资料、M4知识库、客户/联系人停用 | 待确认或此前延期状态保持 |

数据库测试期间仅停止新隔离 M3 Worker，防止确定性注入与后台消费竞争；随后重建/启动 Worker，浏览器由真实后台 Worker 处理，非浏览器 Mock 拦截。M2 Worker/业务库未操作。

首轮数据库回归 5 项失败保存在 backend-round1.log：新测试错误比较 POST 与 GET 的 capabilities 字段，且错误使用普通 PATCH 修改负责人。改为前后 GET 完整比较、通过既有 assign-owner 命令准备权限后重跑，新增断言及业务标准保留。没有降低既有测试标准。已有 TestClient/httpx 弃用提示仍保留。

浏览器截图位于 `.local/browser-runs/run-1793153073203-494d3f5d-aa9c-4f74-b7f3-e62de249c512/`，新增 mock-meeting-reviewed.png。所有截图使用唯一运行目录/testInfo.outputPath，未覆盖旧截图。最后仅调整首页阶段说明后重新运行前端 109 项与构建；浏览器业务断言对应的功能代码未改变。

## 变更文件职责

- `backend/app/meetings/{models,schemas,service,processor,router}.py` 与 __init__.py：持久化实体、证据校验、权限/事务/幂等、租约处理器及 API。
- `backend/alembic/versions/0005_meetings.py`、`backend/alembic/env.py`、`backend/app/schema.py`：增量迁移、元数据注册、当前 revision。
- `backend/app/ai.py`：显式 Mock 标签解析；Embedding 仍未实现。
- `backend/app/worker.py`：实际任务处理及心跳；Capabilities 不把未提供的实时 Worker 健康监控伪装为可用，任务进度单独可查。
- `backend/app/main.py`：路由及真实 Provider 未启用原因说明。
- `backend/app/runtime_grants.py`、`backend/tools/check_runtime_permissions.py`：新表列白名单与真实拒绝探测。
- `backend/tests/test_meetings_unit.py`、`test_meetings_mysql.py`、`test_unit.py`：新单元/真实数据库测试及 M1 Mock 占位预期随实际功能升级。
- `frontend/src/meetings.tsx`、`meetings.test.tsx`、`App.tsx`、`frontend/e2e/meetings.spec.ts`：页面、路由、当前阶段、组件与端到端回归。
- `docs/m3-plan.md`、本报告、decisions/data-model/api-spec/test-plan/README：本轮已批准范围、契约、结果和局限。历史报告保持原样。

## 手动验收与剩余风险

登录新入口 14757，使用本轮私有文件的 SALES_MANAGER 或 ADMIN 合成账号。先创建开放商机，再进入“会议解析 M3-A”，搜索选择商机、输入明确标签的合成纪要并勾选合成资料确认。观察排队至成功，检查未知与引文，填写审核原因后拒绝或放弃；回到商机核对版本/金额/阶段未变。其他 REP 可以读 CRM，但直接读取该分析应 403。

当前仅确定性标签语法，非通用自然语言理解；无真实模型效果结论。没有再生成/受控执行、自动过期、清理、邮件或知识检索；不能用本轮演示替代后续业务决定。公开生产使用前仍需评估任务预算/反滥用、资料保留、真实 Provider、续租/长调用、运维监控及负载。未实施尚未批准的期限/预算以掩盖这些限制。

本轮 M3-A 子集具备评审与合成演示条件；完整 M3 尚未完成。只提交了开始前的 M2 成果，M3 代码未暂存/提交/推送，等待评审。
