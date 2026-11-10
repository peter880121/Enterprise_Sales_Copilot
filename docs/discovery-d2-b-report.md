# D2-B 网页公开搜索闭环交付报告

日期：2026-11-05。用户要求继续D2，并明确批准向192.168.10.150的 `/home/zht/esc-m2-core-7a29a22f3f/` 部署独立验收资源，允许仅向后端私有配置传入既有Tavily密钥。未上传根.env、.local或image.png，未操作旧M2/M3/D1资源。

## 1. 实际交付

已完成：公开查询预览与显式确认、签名有效期、持久化任务、同请求回执、数据库串行额度保留、Worker派发和未知结果保护、查询历史分页与结果展示。客户关联仍沿用D1人工评审流程；搜索摘要不自动转为线索、客户、商机或成交证据。

Tavily使用现有官方MCP配置，basic、每次最多5条，关闭自动深度、生成答案、原文与图片。不调用项目真实LLM，不抓取结果网页，不发送私有画像/上传资料。公共词由用户单独填写，预览不外发。权限、字段和错误详见 [搜索API契约](discovery-search-api.md)。

每个请求最多派发一次：受理事务保留额度并写审计；派发标记先持久提交再调用Provider，调用不持数据库锁；结果与审计同事务。超时/崩溃未知状态不重发，保留额度，不假定供应商未计费或自动退款。相同token重试返回同任务，不增加版本、审计或额度；更换意图必须重新确认。

空间ACL沿用D1。REP可读TEAM原始搜索数据，但只有本人空间或明确授权评审者可写；经理/管理员不隐式读PRIVATE。READ_ONLY只保留既有已发布摘要能力，不开放搜索原始任务/资料。

## 2. 环境与资源隔离

| 项目 | 实际值 |
| --- | --- |
| Compose | `esc-m2-core-7a29a22f3f`，新MySQL/MinIO卷，未删除任何卷 |
| 原始回归库 | `esc_m1_test_m2core_7a29a22f3f`，保留全部合成测试数据 |
| 专用演示/浏览器库 | `esc_m1_test_m2core_7a29a22f3f_live` |
| MySQL实际版本 | **8.4.8**，未作为8.4.13的测试结果 |
| 演示身份 | 独立迁移 `esc_live_migrate`、运行 `esc_live_runtime`；与管理root及原测试运行账户不同 |
| schema | `0009_search`，接在0008后，只新增两表及配额guard初始行 |
| 新手动入口 | `http://localhost:13300/discovery`，需本机专用SSH转发 |
| 本轮私有证据 | `.local/discovery-d2-b-7a29a22f3f/` |

最初回归使用新建项目的隔离数据库。发现回归夹具会占用搜索日受理统计后，**保留该库及证据**，另建live库和不同的迁移/运行身份用于浏览器与手动测试，没有删除夹具、倒改时间或提升已批准的演示额度。控制器后续将pytest明确路由回测试库；API/浏览器/权限检查路由到live库。证据：`separate_live.py`、`manifest.json`、`compose-live-up.log`。

演示按批准配置每人每日5次、全局15次，按UTC日受理记录计数。默认源码配置关闭，通用默认10/50；这些都是技术次数上限，不是货币费用限制。根.env未改。Tavily账户自身费用上限未由本项目配置；不声称已实现账单对账或货币硬限制。

## 3. 最终版本实际验收

| 状态 | 实际命令/动作 | 结果与证据 |
| --- | --- | --- |
| PASS | `control.py deploy`，后续独立live库`up --wait` | config/build成功，迁移0001→0009成功，5常驻服务健康、初始化任务成功；`compose-build-final.log`、`compose-up.log`、`compose-live-up.log` |
| PASS | `deployed_checks.py` / `alembic check` | 容器60个app Python文件与本地SHA一致；live库模型比对无升级差异；`deployed-source-check.json`、`alembic-check-final.log` |
| PASS | 最终前端部署产物SHA比对 | 实际HTTP返回的index.html、CSS和两份JS均与本地最终dist一致；`frontend-artifact-check.json` |
| PASS | `pytest -q -p no:cacheprovider -m "not integration"` | 342 passed；初始非数据库回归，最终完整回归见下一行 |
| PASS | `control.py tunnel --command regression.py --log backend-regression-final.log` | **499 passed，1 deselected**，125.12秒；真实MySQL运行账户、独立夹具准备身份；测试期间仅停止本轮Worker并恢复 |
| PASS | 新增两个MySQL测试文件定向回归 | **14 passed**，10.07秒；`backend-targeted.log`。Provider故障/竞争使用合成适配器，数据库事务和锁是真实MySQL，不冒充真实Provider故障演练 |
| PASS | `npm test` | **138 passed / 11 files**，最终7.06秒；`frontend-final-v2.log`，保留初次137项记录 |
| PASS | `npm run build`（含tsc --noEmit） | TypeScript/构建通过；`frontend-build-final-v2.log`；主JS498.32kB，发现模块24.81kB |
| PASS | `ruff check .`、`ruff format --check .` | 通过，103个Python文件格式一致；静态检查不是运行测试 |
| PASS | `control.py tunnel --command api --log api-final.log` | **118项真实API检查**，失败0；MySQL8.4.8；`api-checks.json` |
| PASS | `control.py tunnel --command browser --log browser-final.log` | **14项真实浏览器测试**，59.2秒；包含1项真实Tavily和原M2/M3/D1关键流程。末次仅前端刷新修订后，另定向复测搜索1项，11.7秒，通过；`browser-search-final.log` |
| PASS | `permissions.py` | **137项真实SQL权限正反例**全部通过；`permissions-final.log` |
| PASS | `isolation_checks.py` | 管理/迁移/运行身份分离；故意身份冲突使初始化exit1，API/Worker停留created；`runtime-isolation.json` |
| PASS | `isolation_extra.py` | Tavily仅API/Worker持有；前端、迁移、授权初始化及迁移检查容器不持有；私有配置0600；`tavily-isolation.json` |
| PASS | `persistence.py` | 专用MySQL/MinIO/API/Worker/前端restart及stop/start后就绪、会话有效；9张发现表含原文字节和搜索结果哈希不变；原请求回执仍相同、版本不增；`discovery-persistence.json` |
| PASS | `receipt_summary.py` | live库2条实际搜索任务（全套及末次定向浏览器各1次），均SUCCEEDED、版本4、各5条结果；每条ACCEPTED/DISPATCHED/COMPLETED审计各1条，无查询正文；`receipt-summary.json` |
| PASS | `final_runtime.py` | 原始容器日志在内存扫描本轮已知密码、密钥/API key，匹配0；`container-log-scan.json`，不是对未知秘密的保证 |

真实浏览器输入仅“超声 医疗器械 采购意向”。画像另有合成私有关键词，断言未进入受理请求。测试通过真实NGINX/API/Worker/Tavily/MySQL完成：预览→确认→真实受理后丢失响应→同请求手动重试→读取同一个SUCCEEDED任务。结果是搜索摘要，未宣称采购事实或资质核验。截图/回执位于 `.local/browser-runs/run-1793865912915-5dfc7652-04fc-4f2f-bbfb-ee797dbf8709/`。

截图复核发现详情终态后历史仍停留QUEUED；已补终态自动刷新并增加回归，额度标签也改为“预览时受理统计”。末次前端138项通过，重建并仅更新专用前端，真实搜索定向复测同时断言历史自动显示SUCCEEDED，额外一次搜索仍在批准额度内。末次证据位于 `.local/browser-runs/run-1793867846070-016a2453-e69d-482d-8ce9-8f87931c4a05/`。后端未再修改，不无理由重复其全部回归；持久化检查为界面修订前执行、同一后端版本的结果。

真实MySQL覆盖同请求并发、不同用户/空间争抢最后全局额度、个人额度、角色/空间拒绝、签名篡改/开关关闭、过期租约、晚到结果、画像变更前不派发、权限撤销后不发布、真实FK审计失败回滚、历史第二页及不写CRM。单元覆盖签名绑定、期限和客户端输入/错误/刷新失败；前端失联后保留同一请求，成功后不因刷新失败再次POST。

验收辅助器曾因将多个一次性迁移容器ID当作一个ID而失败，改为逐容器检查；持久化辅助器也曾在任何容器操作前因索引/UTF-8读取错误失败，修正后实际完成全部检查。没有因此修改应用权限、断言或清理历史证据。保留现有Starlette、工具依赖及Rollup提示，未升级依赖或系统服务。

## 4. 数据库变化和运行权限

新增 `discovery_search_runs` 及 `discovery_search_guard`。冻结DDL、外键RESTRICT，不更新既有业务表；guard单行在迁移内初始化。降级拒绝破坏性删除回执，故升级前仍需部署方备份和评审向前修复。旧schema不满足新就绪版本。

| 表 | SELECT | INSERT | UPDATE | DELETE |
| --- | --- | --- | --- | --- |
| discovery_search_guard | 是 | 否 | version | 否 |
| discovery_search_runs | 是 | 是 | status、provider_attempted、lease_token、lease_until、started_at、completed_at、error_code、result、version、updated_at | 否 |

查询、画像基准、操作者、端点、请求token/hash不可由运行账户修改。没有扩大既有表权限；审计仍SELECT/INSERT，迁移版本仅SELECT。结果终态不变与合法流转由服务层租约/状态检查执行，不宣称数据库列权限独立实现全部状态机。

Worker增加独立搜索handler，网络调用有界且不持事务锁；心跳线程独立更新，避免长搜索阻塞循环造成假失活。心跳证明进程存活，不是Provider可用性或任务完成保证。单Worker仍串行处理handler，高负载隔离/性能尚未验收。

## 5. 本轮文件清单

新增：`backend/alembic/versions/0009_search.py`；`backend/app/discovery/search_service.py`、`search_processor.py`；`backend/tests/test_search_runs_unit.py`、`test_search_runs_mysql.py`、`test_search_runs_extra_mysql.py`；`frontend/e2e/discovery-search.spec.ts`；本报告及`docs/discovery-search-api.md`。

修改：`backend/app/core/config.py`（开关/额度）；`discovery/models.py`、`schemas.py`、`router.py`（模型和契约）；`runtime_grants.py`、`schema.py`、`worker.py`（白名单/就绪/handler）；`tools/check_runtime_permissions.py`（SQL拒绝探针）；`compose.yaml`、`.env.example`（仅API/Worker搜索配置，默认关闭/占位密钥）；`frontend/src/discovery-search-preview.tsx`、其测试、`discovery.tsx`、`App.tsx`（执行、历史、重试和D2入口）；`frontend/e2e/discovery.spec.ts`（兼容阶段导航）；README、决策、实施计划（本轮入口）。完整本轮清单见`d2-b-files.json`。

没有新增依赖、真实LLM/AI会议规则、知识库、自动营销或商机阶段改动。保留全部已有M3/D1/D2-A工作及历史报告。Git保护与敏感扫描见本轮`protection-final.json`；不暂存、提交或推送。

## 6. 剩余范围与结论

- **NOT RUN**：最后管理员专库并发测试（完整回归明确deselect1项）、远端CI、生产TLS、真实来源质量评测/召回率、负载性能、真实REST端点、Tavily真实429/额度耗尽及网络故障演练。没有沿用历史通过数字填补。
- **NOT RUN**：供应商账单对账、货币费用硬限制；当前仅限制受理次数。供应商可能在错误/未知结果时计费，跨日队列也不能解释为当日账单上限。
- **DEFERRED**：自动获取网页全文、站点/来源许可白名单与完整SSRF获取链、搜索摘要导入人工线索的受控流程、PDF/RAG/知识库、正式商机转换、客户/联系人停用、自动清理/过期。DQ05、Q05-A及其他未批准范围保持待确认。
- 全局受理锁为单实例数据库门禁；若多个部署共享同Tavily账号，各自配额不会自动合并，需要供应商账户级限额或后续统一计量。默认关闭，开启前必须自行配置适当额度。
- 查询预览及任务结果按当前空间ACL共享；用户确认仅是显式外发声明，不是患者信息/秘密自动检测。

本轮网页公开搜索、可靠受理和隔离验收范围无未解决FAIL。**可供用户在新入口手动测试；不将本轮通过扩大为整个D2/D3或知识库全部完成。**

## 7. 手动验收

打开 `http://localhost:13300/discovery`，使用本轮`.local/discovery-d2-b-7a29a22f3f/browser-private.json`内合成账号。创建PRIVATE画像，单独填写公开品类词；预览完整外发文本及剩余额度，勾选确认后开始搜索。查看历史和结果；刷新/重开页面应读取旧任务，不应自动再次搜索。明确“编辑下一次查询”后仍需重新预览/确认，算新请求并可能计费。

遇到OUTCOME_UNKNOWN时先核对任务和供应商账单，不把网络问题当作权限拒绝，也不自动反复提交新请求。本轮末尾13300的`/login`及`/api/v1/health/ready`实际均200；旧1883、7034、14757、5909本机请求均URLError，不能宣称旧入口当前可用，也未将其当权限拒绝。未操作那些旧部署或重新启动旧转发，见`manual-readiness.json`。
