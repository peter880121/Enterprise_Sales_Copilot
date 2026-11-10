# M3：显式重生成草稿交付

日期：2026-10-28。用户要求继续推进，本轮按已有API和状态机契约补齐regenerate，不进入M4/M5，不启用真实Provider或实际清理。原M1/M2/M3报告、测试证据和用户批准的摘要更正记录保留。

## 1. 已交付行为

新增 `POST /api/v1/suggestions/{id}/regenerate`，请求只接受expected_version、expected_opportunity_version、request_token。沿用Origin/CSRF、当前会话和AI对象权限。只允许DRAFT（可包含上下文已过期的草稿）；草稿/商机版本必须由用户明确提供并与当前值一致，关闭商机拒绝。终态草稿不能通过此入口复活。

在一个事务中：复制原始合成纪要及会议日期/时区，创建新Job/分析/建议并冻结当前商机与活动上下文；旧建议转SUPERSEDED、版本递增，记录可信操作者；两条白名单审计分别链接来源建议与替代分析。原文、旧提议、执行回执不覆盖，不改变CRM字段、商机版本或活动。新任务失败不恢复旧稿。

同actor/source/request_token及相同body返回同一Job，修改body返回409 IDEMPOTENCY_KEY_REUSED。新token也不能再次替代已经SUPERSEDED的旧稿。与apply竞争时仅一个操作成功。受理202只代表任务持久化，页面继续展示真实Worker状态，不伪装为解析完成。

前端先主动读取基准，再勾选明确确认；请求失败保留同一token和版本供手动重试，不自动POST。受理后的刷新失败保留新分析入口，不能再次生成。旧稿刷新后可通过审计链接恢复“查看新草稿”；新稿默认不选择、不自动执行。需要编辑原文时使用原有新纪要表单。

## 2. 修改文件

| 文件 | 职责 |
| --- | --- |
| `backend/alembic/versions/0007_regenerate.py` | 扩展建议状态CHECK以允许SUPERSEDED，无数据改写 |
| `backend/app/schema.py`、`backend/app/meetings/models.py` | 当前迁移门禁和状态模型 |
| `backend/app/meetings/schemas.py`、`router.py` | 严格请求Schema、鉴权写路由 |
| `backend/app/meetings/service.py` | 复用生成队列、原子替代/去重、版本与状态检查、追加式审计链接及替代入口查询 |
| `backend/tests/test_meetings_unit.py` | 新增4项请求边界校验 |
| `backend/tests/test_regenerate_mysql.py` | 新增17项真实MySQL生成、竞争、权限、故障回滚及失败生命周期测试 |
| `frontend/src/meeting-regenerate.tsx`、`meeting-regenerate.test.tsx` | 独立确认/读取/重试/受理状态与5项交互测试 |
| `frontend/src/meetings.tsx` | 草稿详情集成、替代稿导航与缓存刷新 |
| `frontend/e2e/execution.spec.ts` | 增加真实重生成响应丢失重试、Worker结果和历史数量断言 |
| `docs/api-spec.md`、`data-model.md`、`state-machine.md`、`test-plan.md` | 实际契约、迁移/状态与测试范围 |
| `README.md`、`docs/implementation-plan.md`、本报告 | 当前交付入口与结果 |

不修改AGENTS.MD、根.env、.gitignore、依赖或Compose/NGINX；未扩大运行账户权限。既有M3工作保留，未暂存、提交、推送。

## 3. 迁移与兼容性

0007只删除并重新建立ai_suggestions的状态CHECK，增加SUPERSEDED；没有新增业务数据表/列、DML回填、物理删除或期限策略。现有草稿保持原状态和ID，只有显式regenerate才改变源稿状态。执行、拒绝和放弃继续拒绝SUPERSEDED；原始纪要和旧建议仍按权限读取。来源链接保存在不可UPDATE/DELETE的审计中，响应中的replacement_analysis_id为服务端推导值，不是客户端可写字段。

仅升级本轮已确认归属的 `esc-m2-core-848aae478f` / `esc_m1_test_m2core_848aae478f`，原M2/M3-A数据库未迁移。MySQL实际版本 **8.4.8**。升级前后205份既有纪要的id/input_sha256逐项一致，当前版本0007、Alembic check无差异。该校验不等同于全库备份恢复或每列逐字节比对。

DDL可能持有元数据锁且MySQL会隐式提交，不能当作可随意回滚的普通事务。自动downgrade明确拒绝，避免丢失SUPERSEDED历史；部署到其他环境前应评审维护窗口与恢复方案。本轮没有对原业务库执行迁移。Q10仍只是只读预览；未来实际清理须纳入重生成的来源/替代引用核验，本轮不执行清理或自行决定跨代原文处置。

## 4. 实际执行与结果

本轮独立证据目录：`.local/m3-regenerate-4ebda8402f/`。私有连接、账号、日志与辅助工具只留忽略目录。控制器前缀：

```powershell
uv run --no-project --with paramiko --with python-dotenv python .local/m3-regenerate-4ebda8402f/
```

| 状态 | 实际命令/检查 | 结果与证据 |
| --- | --- | --- |
| **PASS** | `python -B -m pytest -q -p no:cacheprovider backend/tests/test_execution_unit.py backend/tests/test_meetings_unit.py`（使用backend/.venv解释器） | 定向41项通过 |
| **PASS** | `control.py tunnel --command schema_probe.py --log schema-before.log`，部署后同工具输出schema-after.log | 0006→0007，205份既有纪要哈希保留；`schema-before.json`、`schema-after.json` |
| **PASS** | `control.py deploy` | config --quiet、标准构建、up等待健康成功；5个常驻服务健康，正常初始化任务退出0；`compose-build-final.log`、`compose-up.log`、`compose-status.json` |
| **PASS** | `deployed_checks.py` | 容器50个app源码文件SHA256与本地一致；Alembic模型比对无差异；`deployed-source-check.json`、`alembic-check-final.log` |
| **PASS** | `control.py tunnel --command regression.py --log backend-final-v2.log`；内部 `python -B -m pytest -q -p no:cacheprovider -k 'not last_admin_global_guard'` | **412 passed、1 deselected**，115.77秒，真实隔离MySQL/MinIO；`backend-final-v2.log`。测试时停止本轮Worker，结束后已恢复 |
| **PASS** | `npm.cmd test -- src/meeting-regenerate.test.tsx src/meetings.test.tsx` | 定向13项通过；`frontend-targeted-with-regeneration.log` |
| **PASS** | `npm.cmd test`、`npm.cmd run typecheck`、`npm.cmd run build` | **126项/9文件通过**，类型及构建通过；`frontend-final.log`、`frontend-build.log`；单独typecheck输出见终端 |
| **PASS** | `.venv/Scripts/python.exe -m ruff check .`、`-m ruff format --check .`（backend） | 检查通过，84文件格式符合；实际输出见终端 |
| **PASS** | `control.py tunnel --command api --log api-final.log` | **118项**原有核心API检查通过，失败0；新增重生成正反例另由真实MySQL路由测试及浏览器覆盖 |
| **PASS** | `control.py tunnel --command browser --log browser-final.log` | **12项**真实浏览器测试通过，42.8秒；真实NGINX/API/Worker/MySQL/MinIO |
| **PASS** | `control.py tunnel --command permissions.py --log permissions-final.log` | **82项**真实运行账户权限探针通过；审计/执行回执/去重不可UPDATE/DELETE，白名单未扩大 |
| **PASS** | `final_runtime.py` | 原始容器日志在内存中扫描已知秘密，命中0；`container-log-scan.json`，不保证识别全部未知凭据 |

新增数据库测试覆盖来源复制与最新基准、旧原文/提议保留、审计链接、重复token与改body、相同/不同token并发、与apply竞争、旧版本拒绝、REP本人允许/他人拒绝、ADMIN允许、READ_ONLY/CSRF拒绝、REAL不回退、终态不可复活、新任务失败不恢复旧稿，以及早/晚两处真实审计外键失败全回滚。

浏览器实际将第一次regenerate发送给服务器并取得202后丢弃响应，再以相同token重试；断言历史只有原分析、显式新提交和一份替代分析共3条，旧稿SUPERSEDED，新草稿由真实Worker完成且NOTE未选中，商机版本仍2、没有自动第三次apply。10张截图在唯一目录 `.local/browser-runs/run-1793174764864-c95ba427-1cf9-4af0-98e1-8bf013a14d1e/`，没有复用旧证据目录。

首轮后端结果为410通过/2失败：新增测试注入普通RuntimeError却错误地断言数据库异常503，现有全局约定应返回500。未改变应用错误映射或放宽回滚断言；改为通过测试ORM事件将审计actor_id设为不存在的合成ID，让真实MySQL外键拒绝INSERT，验证503及所有记录回滚。原失败日志保留为 `backend-first-run.log`，最终412通过来自修正后的真实数据库故障测试。初次前端测试文件写入路径错误只跑到了原有测试，修正路径后实际运行新增5项及完整126项，不把前次输出当新增用例通过。

## 5. 保护检查与剩余范围

最终保护记录见本轮 `protection-final.json`：对开始快照比较已有源码/文档（含未跟踪文件），核验保护文件、历史报告、索引及候选文本秘密；临时配置与报告材料只在本轮.local。历史保护摘要更正维持用户已批准的保留现状决定，未复用旧检查器写回旧证据。HEAD仍为 `1cf537eefceb2cf2922eaa1476ac7d432bba18c3`，无暂存/提交/推送，.env/.local/image.png未进入索引。

**NOT RUN**：最后管理员专库测试本轮未重复运行，不将旧通过合并为413；最终0007版本的重启/stop-start持久化专项、全新空库迁移链/空缓存检出构建、性能重测、生产TLS/部署、远端CI与其他MySQL版本未运行。以前的结果仅在原报告中保留。

**DEFERRED / 未批准**：客户/联系人停用、真实Provider与真实客户资料传输、实际清理/归档/自动过期、知识库及其他未批准业务决策。Q07白名单及Q04—Q06成交/概率规则不变，Q11草稿有效期仍未批准。

结论：显式重生成流程及本轮已执行验收 **PASS**，可在 `http://localhost:7034` 手动测试（需本机SSH转发）。本轮不自动提交，不宣称生产或全部后续阶段完成。
