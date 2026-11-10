# 商机发现中心 D1 实施与验收报告

日期：2026-10-28。Git HEAD：`1cf537eefceb2cf2922eaa1476ac7d432bba18c3`；已有 M3 工作保留，本轮没有暂存或提交。

## 1. 交付与授权范围

用户批准商机发现方案，以医疗器械为示例。本轮完成 D1：销售画像、PRIVATE/TEAM 空间、显式评审授权、TXT/Markdown/粘贴资料、持久化发现任务、RULES 标签提取、证据展示、线索人工评审，以及明确确认后的客户创建或关联。新增导航 `/discovery`，位于 CRM 之前。

本轮没有实现真实互联网搜索、真实模型、PDF/MinerU、Embedding/RAG、自动营销、正式 Opportunity 转换或自动清理。卖方能力资料可以保存，但 D1 不执行语义匹配或资质判断；地区仅保存为画像条件，不声称已完成地区资格过滤。

独立部署曾因缺少明确目的地/源码上传授权被自动审批拒绝；用户随后明确批准 `192.168.10.150` 的独立 D1 验收部署，才执行上传与资源创建。未上传根 `.env`、`.local/` 或 `image.png`，未升级或操作既有 M2/M3 项目。

## 2. 实际环境与入口

| 项目 | 实际值 |
| --- | --- |
| 独立 Compose | `esc-m2-core-0ca05438ce` |
| 服务器目录 | `/home/zht/esc-m2-core-0ca05438ce` |
| 隔离数据库 | `esc_m1_test_m2core_0ca05438ce` |
| MySQL 实测 | **8.4.8**；不是本机 8.4.13 的结果 |
| schema | `0008_discovery` |
| 手动入口 | `http://localhost:1883/discovery`，依赖本机专用 SSH 转发 |
| 配置/证据 | `.local/discovery-d1-397f840ec0/`，已忽略，不作为公开提交材料 |

API/Worker 使用专用运行账户；管理、迁移、运行身份分离。MySQL/MinIO 使用新建专用卷与随机凭据。知识服务关闭，AI 保持 Mock；发现提取模式明确为 RULES，未调用任何 Provider。

手动测试凭据仅在该目录的 `browser-private.json`；不要将其复制到文档或提交。该环境包含自动化测试生成的合成对象，不能作为生产环境或真实医学/采购判断使用。

## 3. 数据、权限与事务设计

- 画像默认 PRIVATE；经理/管理员没有隐式私有资料读取权。所有者可指定有效经理/管理员为评审者。TEAM 对销售角色开放资料读取，但普通团队成员不因此取得写权限。
- READ_ONLY 不读取画像、原文、任务或私有评审说明，仅能读 TEAM 空间中已认可且明确发布的线索摘要。分页和计数都在 SQL 中应用同一可见范围。
- 画像可见性创建后固定。编辑为带 `expected_version` 的完整快照，必须明确提交地区、可见性与评审者集合，省略字段不会默默撤销授权。
- 资料目的分 SELLER_CAPABILITY 与 BUYER_DEMAND；任务只能处理同空间采购需求资料。UTF-8 TXT/MD 或粘贴文本上限 64 KiB，文本另限 50,000 字符，请求体预解析上限 128 KiB。
- D1 将小文本原始字节和规范化文本保存在专用 MySQL 表，分别校验原始/文本哈希；这是有界文本入口，不复用成交证据、MinIO 附件或 PDF 的批准范围。没有资料下载、删除或清理接口。
- 上传必须确认不含患者资料，TEAM 上传另需明确共享确认。这是用户声明，并非自动识别患者信息的保证。
- Worker 使用独立任务、租约和 fencing；提取前及发布前重新检查用户与空间权限。批次发布同事务，不把失败包装成空结果成功。任务最多领取三次，无无限重试。
- 规则只处理明确标签及原文位置：采购人、项目、代理、预算、公告类型等。缺少采购人/项目、重复或空标签拒绝；不从自由文章补造事实。不明确的币种/时区保留未知，公告预算不写 CRM 金额，资质保持 NOT_VERIFIED。
- 资料同空间/目的/原始哈希去重；同一来源跨任务复用同一条冻结线索，不按新画像静默重算。不同文件的同项目语义去重尚未实现。
- 评审和客户关联使用原子 CAS。客户预览绑定操作者、线索版本和目标；确认必须明确接受加入全企业 CRM。新客户只投影经确认名称和当前负责人；不复制私有原文、预算或评审说明。关联已有客户不修改其字段，遵守 Q03。
- 客户创建、CRM 白名单审计、线索更新及永久关联回执同事务。相同请求重试返回原结果；一条线索至多一份客户关联回执，不自动建联系人或商机。
- 全局 DISCOVERY 审计仅记录 ID、版本、状态等白名单；私人采购主体/项目名、资料内容及评审理由不进入全局审计。私有理由留在线索记录。

## 4. 新表与运行权限矩阵

`0008_discovery` 接在 `0007_regenerate` 之后，只新增七张表和索引/约束。外键 RESTRICT，不修改既有业务数据；迁移为冻结 DDL，不导入未来 ORM。回退不做破坏性删表，需评审向前修复。运行账户没有建表权限。

| 表 | SELECT | INSERT | 允许 UPDATE 的列 | DELETE |
| --- | --- | --- | --- | --- |
| discovery_profiles | 是 | 是 | name, product, keywords, regions, version, updated_at | 否 |
| discovery_access | 是 | 是 | is_active | 否 |
| discovery_materials | 是 | 是 | 无 | 否 |
| discovery_runs | 是 | 是 | status, attempts, lease_token, lease_until, error_code, result_count, version, updated_at | 否 |
| discovery_run_materials | 是 | 是 | 无 | 否 |
| discovery_leads | 是 | 是 | status, summary_shared, review_note, account_id, version, updated_at | 否 |
| discovery_account_links | 是 | 是 | 无 | 否 |

既有表权限不扩大：`alembic_version` 仅 SELECT，`audit_events` 仅 SELECT/INSERT。完整现行白名单见 `backend/app/runtime_grants.py`。空间授权、有效状态、CAS、哈希关联和合法状态转移仍由服务层执行；数据库列权限不是对象级业务授权的替代。

## 5. 最终版本实际验证

下列脚本均位于本轮证据目录，控制器只连接本轮隔离资源，秘密通过环境/私有文件传入，不在命令行展示完整连接串。

| 状态 | 实际命令或动作 | 结果 / 证据 |
| --- | --- | --- |
| PASS | `control.py deploy`（经 uv、paramiko、python-dotenv 执行） | config/build/up 成功；5 个常驻服务健康、3 个初始化任务成功退出；`compose-*.log`、`compose-status.json` |
| PASS | 新库 `alembic upgrade head`，随迁移服务执行 | 0001→0008 成功；首次部署记录保存在 `initial/` |
| PASS | `deployed_checks.py` | 容器内 57 个 app Python 文件与最终本地源码 SHA 一致；`deployed-source-check.json` |
| PASS | 独立迁移身份执行 `alembic check` | 无新增升级操作；`alembic-check-final.log` |
| PASS | `control.py tunnel --command regression.py --log backend-final-v2.log` | `pytest -q -p no:cacheprovider -k 'not last_admin_global_guard'`：**443 passed, 1 deselected**，134.57 秒；包含 D1 的 13 项单元及 18 项真实 MySQL 测试 |
| PASS | `npm --prefix frontend test` | **132 passed / 10 files**；`frontend-final-v2.log` |
| PASS | `npm --prefix frontend run typecheck` | TypeScript 通过；`typescript-final.log` |
| PASS | `npm --prefix frontend run build` | 构建通过；发现模块按需加载，主 JS 498.32 kB；`frontend-build-final.log` |
| PASS | `backend/.venv/Scripts/ruff.exe check backend`、`ruff.exe format --check backend` | 均通过；`ruff-final.log`、`format-final.log` |
| PASS | `control.py tunnel --command permissions.py --log permissions-final.log` | **121 项真实数据库权限允许/拒绝检查**全部通过，含原文/来源关联/提取结果不可修改，审计 UPDATE/DELETE 拒绝 |
| PASS | `isolation_checks.py` | API/Worker 无管理/迁移凭据；故意身份冲突使初始化 exit 1，API/Worker 留在 created；`runtime-isolation.json` |
| PASS | `control.py tunnel --command api --log api-final.log` | **118 项真实 API 检查**，失败 0；MySQL 8.4.8；`api-checks.json` |
| PASS | `control.py tunnel --command browser --log browser-final.log` | **13 项浏览器测试**通过，含原 M2/M3 关键流程及新增 D1；50.8 秒 |
| PASS | `persistence.py` | 专用 MySQL/MinIO/API/Worker/前端 restart、stop/start 后就绪；7 张发现表全部行数与内容哈希相同（含原始字节），同会话 `/auth/me` 200；`discovery-persistence.json` |
| PASS | `final_runtime.py` | 容器原始日志在内存中扫描已知本轮秘密，匹配 0；`container-log-scan.json`，不是对未知秘密的绝对保证 |

真实 MySQL 回归涵盖：PRIVATE 猜 ID 拒绝、经理无默认私有读取权、授权撤销、TEAM 摘要、跨空间/卖方资料拒绝、超过 100 条的分页、原始字节保存、非法上传/请求大小、CAS 冲突、真实 FK 导致审计失败全事务回滚、相同/不同幂等键并发关联、过期租约与晚到结果拒绝。

新增浏览器场景通过真实 NGINX/API/Worker/MySQL 完成：创建 PRIVATE 画像→上传合成 Markdown→生成 RULES 线索→核对原文→人工评审→客户预览→未默认勾选共享→真实提交后人为丢失响应→同键重试→只存在一个客户，且未创建 Opportunity。浏览器输出为 `.local/browser-runs/run-1793181834461-fccf5c6c-248b-4b86-93da-3094355c1580/`，截图已检查。

初次定向测试有一项测试辅助器重复登录后沿用旧 CSRF 头的失败，修正辅助器后通过；未放宽应用鉴权。另一次持久化脚本因测试 Python 环境缺少 paramiko 在连接前失败，改用带明确工具依赖的独立 uv 进程后完成验证。原失败日志保留。Starlette TestClient 弃用警告和 Rollup 对依赖注释的提示保留，没有借此升级依赖。

## 6. NOT RUN、DEFERRED 与剩余范围

- **NOT RUN**：最后管理员全局门禁独立数据库测试（本轮未配置该专库，明确 deselect，不能用历史通过替代）；远端 CI、生产 TLS、真实用户/真实公开来源评估、D1 负载/性能基线。
- **NOT RUN**：真实搜索 Provider、限额/费用/站点授权、SSRF 获取链；D1 没有网络抓取入口，不能据本轮规则测试宣称这些能力已验收。
- **DEFERRED**：客户/联系人停用，真实 LLM、知识库 PDF/RAG、正式商机转换、自动清理/过期、任务取消/历史操作台、线索认领/合并及跨文档项目去重。D2/D3 必须按设计门禁另行推进。
- **BLOCKED（后续接入门禁）**：DQ04 搜索供应商及外发/配额授权、DQ05 正式商机门槛、发现 PDF/知识资料的类型/下载策略和未批准的 Q08/Q09 等，不因本轮交付自行批准。
- D1 文本入口要求一份资料一个带标签项目；任意网页/多标包长文不属于已交付能力。已成功来源复用冻结结果；画像修改不会重跑既有来源，后续若增加重分析需另行设计版本策略。
- D1 没有取消任务、资料删除或下载接口，也没有敏感信息自动检测。上传者必须使用无患者资料的合成样本；真实资料治理仍需后续评审。

本轮没有未解决的 D1 实测 FAIL；不将这项结论扩大为整个商机发现模块、D2/D3 或完整知识库已完成。

## 7. 文件变更与保护

新增：

- `backend/alembic/versions/0008_discovery.py`：新增表及冻结 DDL。
- `backend/app/discovery/{__init__,models,schemas,service,extraction,processor,router}.py`：模型、契约、权限/事务、标签规则、租约 Worker、API 与有界上传。
- `backend/tests/test_discovery_unit.py`、`test_discovery_mysql.py`：Schema/提取与真实 MySQL 安全、幂等、回滚回归。
- `frontend/src/discovery.tsx`、`discovery.test.tsx`：发现工作区与组件回归。
- `frontend/e2e/discovery.spec.ts`：真实 D1 操作链及响应丢失重试。
- 本报告与 `docs/discovery-d1-api.md`：交付/限制及接口速查。

修改既有文件：`backend/alembic/env.py` 注册模型；`app/main.py` 注册路由及请求体边界；`runtime_grants.py` 增量最小权限；`schema.py` 就绪版本；`worker.py` 独立发现任务调度；`tools/check_runtime_permissions.py` 扩展权限探针；`frontend/src/App.tsx` 新入口与懒加载；README、决策和实施计划追加报告入口。没有新增应用依赖，没有修改 Compose、NGINX、根 `.env`、AGENTS.MD 或 `.gitignore`。

最终保护核验见 `.local/discovery-d1-397f840ec0/protection-final.json`：与开始的 169 文件快照逐文件比较，只有本轮列明的 10 个既有文件改变，新增 15 个文件；其余既有 M3 修改和历史报告保持不变，66 张旧截图哈希均未改变。Git HEAD 不变、索引为空，`.env`、`.local/`、`image.png` 未跟踪；已知秘密及私钥模式扫描无发现，扫描范围和局限见该摘要。完整本轮文件清单另存 `d1-files.json`。历史报告和旧保护摘要未改写。

最终 HTTP 复核：D1 1883 与旧 M3-B 7034、M3-A 14757、M2.1 5909 的 `/login` 和 `/api/v1/health/ready` 均实际返回 200，见 `manual-readiness.json`；这只证明入口/就绪，旧环境业务验收不据此重新标为通过。

## 8. 人工验收建议与结论

1. 打开专用入口，用本轮合成经理账户登录；创建 PRIVATE 医疗器械画像。
2. 上传无患者资料的 UTF-8 TXT/MD，包含 `采购人：示例医院`、`项目：示例超声采购`、`品类：超声`、`预算：120万元 人民币` 等标签；明确勾选无患者数据。
3. 选择需求资料并触发任务，等待 SUCCEEDED，读取服务端线索；核对引用，确认预算没有进入 CRM 金额且资质仍未核验。
4. 填写评审说明，经人工评审后认可；预览客户名称/负责人，明确共享后关联，打开 CRM 客户确认；Pipeline 不应因此新增商机。
5. 用另一销售账户、只读账户验证私有资料不能读取；需要团队摘要时另建 TEAM 画像并明确发布认可摘要。

**结论：D1 限定范围已实现并完成上述实际验收，可供用户评审与手动测试；真实互联网发现及知识库语义匹配仍未交付。本轮不提交、不推送，等待用户评审。**
