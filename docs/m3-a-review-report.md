# M3-A 可靠性修复与历史分页

2026-10-28。继续已批准的 Mock/合成解析与草稿审核范围，保留 Q07/Q10 待确认；不新增 apply、自动过期、清理或真实 Provider。原 [M3-A 报告](m3-a-report.md) 不改写。

## 本轮修复

1. **重复发布不能篡改终态 AIRun。** 原 publish 在核对租约前更新 ended_at/latency，并把已完成 Job 对应的运行改成 DISCARDED。同一已成功/失败回调再次进入会改坏历史运行结论。现在锁定 Job/AIRun 后先检查运行仍为 RUNNING；已有 SUCCEEDED/FAILED/DISCARDED 均原样保留，重复调用返回 false，不改时间、延迟、版本、业务数据或审计。
2. **租约接管即收尾遗留 RUNNING。** 原 Worker 消失后，新 Worker 可接管 Job，但旧 AIRun 永久显示运行中。现在在领取已可恢复任务的同一事务内，将遗留 RUNNING 标记 DISCARDED/LEASE_EXPIRED 并记录发现结束时间；实际执行耗时未知，不伪造 latency。旧回调晚到也不能改写该结论。它是原租约恢复的状态收尾，不是数据保留期限或删除机制；没有清理/修复已有终态历史。
3. **会议分析历史完整分页。** 接入已有服务端 page/page_size=20、上一页/下一页、总数及显式刷新；按商机和页缓存，切换商机重置历史页。不把失败当作空列表。历史浏览只执行 GET，不清空未提交纪要，不提高商机基准版本，不自动新建解析任务。

## 实际测试与部署

复用明确归属的专用 M3 项目 `esc-m2-core-254955627b`、库 `esc_m1_test_m2core_254955627b`，实际 **MySQL 8.4.8**。只使用合成数据。确定性数据库测试期间暂停该项目 Worker，测试后通过重建/启动恢复；没有操作 M2 Worker、原业务库、其他项目或任何持久化卷。

新增三项真实 MySQL 回归：成功后重复发布、失败后重复发布、租约接管且旧回调晚到。断言完整 AIRun 原字段、草稿版本、审计数量、商机版本；不是仅 Mock 一个 rollback 或返回值。**修复前 3 项全部失败，修复后 3 项全部通过。**复现产生的记录保留；一项等待恢复的隔离合成任务通过正常 Mock 处理器完成，没有删除或直接改写终态数据。

| 状态 | 实际命令/检查 | 结果及本轮证据 |
|---|---|---|
| PASS | `control.py tunnel --command targeted.py --log after-fix.log` | 3 passed、13 deselected；before-fix.log 为相同三测试实际失败证据 |
| PASS | `control.py tunnel --command regression.py --log backend-final.log`，内部 `pytest -q -p no:cacheprovider -k 'not last_admin_global_guard'` | **346 passed、1 deselected**，73.30 秒，真实 MySQL |
| PASS | `npm.cmd --prefix frontend test -- --reporter=dot` | **111 passed / 7 files**，新增分页/选择旧记录/错误重试测试 |
| PASS | `npm.cmd --prefix frontend run build` | TypeScript/Vite 成功，已有依赖 PURE 注释警告保留 |
| PASS | `ruff check backend` / `ruff format --check backend` | 通过，75 文件格式符合 |
| PASS | `control.py deploy` | 专用项目实际构建/健康启动通过，Worker 恢复；没有新增迁移或数据库授权改动 |
| PASS | `deployed_checks.py` | 46 个后端 app 文件与工作区 SHA-256 一致，alembic check 无新增差异 |
| PASS | `control.py tunnel --command api --log api-final.log` | 118 项真实 API 检查通过，MySQL 8.4.8/隔离 MinIO；同时准备独立新合成浏览器账号 |
| PASS | `control.py tunnel --command browser --log browser-fresh-actors.log` | 全部 10 项真实浏览器测试通过，36.6 秒；原 9 项及新增历史第二页/输入保留/零 POST 场景 |
| PASS | `protection.py`、Git diff/index 检查 | 保护文件及全部前轮正式报告不变，原文件均存在；无已知秘密命中；暂存区空，私有文件不在索引 |
| PASS | 本机 GET 14757/api/v1/health/ready、5909/api/v1/health/ready | 均 200；保留已有独立 Web 隧道，没有覆盖旧日志或启动第二个同端口转发 |
| NOT RUN | 最后管理员独立空库场景 | 显式 deselect 1 项；不冒用历史通过，不复用旧非空库 |
| NOT RUN | 本轮重新运行 75 权限专项、持久化全套/性能/真实 Provider/托管 CI | 授权/模型契约未修改；不把前轮数字计作本轮结果 |
| DEFERRED | Q07 受控 CRM 执行、Q10 保留与清理、Q09 真实资料、客户/联系人停用等 | 原批准边界及延期状态保持 |

本轮新证据仅写 `.local/m3-review-20261028/`。其控制器使用临时端口连接隔离 MySQL，浏览器复用现有 14757 Web 隧道，未修改根 `.env`。所有私有配置仍为忽略材料。

新增浏览器场景通过真实 API 创建 21 个合成纪要任务，使用真实 Worker，然后在 UI 翻至历史第二页、打开最早分析、刷新，并严格断言未提交输入保持原值、基础版本保持 1、浏览器没有发起额外解析 POST。数据准备属于 API；分页、选中与输入保护属于真实浏览器验证，不混称全程 UI 创建。

浏览器初轮原 9 场景通过，新场景最后的 getByLabel 精确定位失败。页面错误快照显示原输入完整保留；受控 textarea 重渲染影响标签文本定位，改为精确 textbox 角色/名称定位，仍严格断言相同输入值与零 POST，没有移除或放宽功能断言。最终重跑结果另列下方。

随后重复运行因复用测试账号达到现有登录请求预算，4 项在登录页失败、6 项通过。保留 browser-final-rerun.log 与“登录请求过多”页面证据，不误报业务权限拒绝，也没有重置预算、删除节流记录或放宽策略。通过现有隔离 API 验收工具准备全新合成账号，再运行最终浏览器套件；旧账号和证据保留。本轮新账号仅存本轮 browser-private.json，供需要继续手动验收时使用。

最终浏览器复验为 **10 passed（36.6 秒）**，日志 browser-fresh-actors.log。新证据目录 `.local/browser-runs/run-1793154754733-345b63ea-699e-4670-8503-64b8ba3091d2/`，包含 meeting-history-page-two.png；没有覆盖前面失败或成功运行的材料。当前本轮需要复验的项目无遗留 FAIL/BLOCKED，表中 NOT RUN/DEFERRED 保持。

## 变更与保护

- `backend/app/meetings/processor.py`：终态不可重写与遗留运行收尾。
- `backend/tests/test_meetings_mysql.py`：三项真实数据库回归。
- `frontend/src/meetings.tsx`：历史分页、刷新、选中；保持父表单状态。
- `frontend/src/meetings.test.tsx`：两项历史范围及错误交互测试。
- `frontend/e2e/meetings.spec.ts`：21 条历史的浏览器验收。
- README、本报告：本轮入口与独立证据。

没有修改 AGENTS.MD、根 `.env`、`.gitignore`、数据库模型/迁移、运行权限矩阵、原角色/成交/概率/币种规则或历史报告。原 M2/M3 未提交工作保留；HEAD 仍为 M2 提交 `1cf537eefceb2cf2922eaa1476ac7d432bba18c3`，本轮未暂存、提交或推送。秘密扫描仅覆盖已知配置秘密及常见私钥/Token 形态，不代表所有未知秘密绝无遗漏。

手动测试继续使用 `http://localhost:14757/meetings`；合成凭据见既有 M3 私有 browser-private.json。原 `http://localhost:5909` 保留。完整 M3 受控执行仍未交付，等待 Q07 等决定，不自动扩大本轮范围。
