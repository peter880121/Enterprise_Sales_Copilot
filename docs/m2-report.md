# M2 销售业务闭环实施与验证记录

后续独立 Compose、动态 DNS、Pipeline SQL 汇总及剩余验收补全见 [M2 验收补全报告](m2-acceptance-report.md)。本文件保留当时的执行结果、失败和未运行记录，不用后续结果改写历史。

日期：2026-10-27。状态：M2已单独授权并交付本轮可运行功能；**不是整个M2正式验收通过声明**，不进入M3。

## 1. 起点、授权和保留边界

本轮从工作区实际状态继续：master已有Git基线及未提交M2-A客户/联系人实现，首次读取时并非空仓库。已有CRM模型、服务、表单和测试保留，没有重写。M2-A报告描述此前的代码及未运行项，本轮通过新报告补充运行证据，不覆写该报告；M1历史报告、AGENTS.MD、根.env和原业务库保持不变。未暂存或提交。

用户在单独M2授权询问后回复“开始”。随后明确批准：Q11仅限成交证据PDF、单文件≤20 MiB且≤100页；Q12仅限成交证据API代理下载、每次重新鉴权。Q05-A、Q07—Q10及Q11/Q12其余范围不随之批准，真实客户数据不发送给真实Provider。

## 2. 本轮交付

- 客户/联系人：复用M2-A代码并完成真实MySQL回归；Q03全企业CRM可读、REP本人对象可写。
- 商机：创建/查询/分页/搜索、编辑、负责人调整、五阶段看板/列表/详情、阶段命令、LOST重开、WON拒绝重开、终态归档/取消归档。PATCH和命令均用expected_version，最终UPDATE原子检查ID/version。
- 金额与Pipeline：Decimal及数据库精确生成列；预计金额null与已知零不同；默认CNY，四币种分组；五阶段固定20/60/40/100/0；实际金额只从选定VERIFIED证据投影，既不覆盖预计值也不累加其他证据。列表批量读取关联信息和最近活动，避免逐卡查询。
- 证据：multipart上传及请求标识去重，20 MiB文件/100页限制、PDF文件头和真实解析校验；解析在独立子进程中设置8秒时限。原件私有存储，提交保持PENDING；经理/ADMIN必须不同于提交人，后端重新检查身份、角色和操作权限，保存核验人、时间、结果、说明及审计。
- 下载：每次通过会话鉴权后由API读取原件并检查SHA-256，返回PDF附件，不向浏览器提供S3地址、密钥或签名URL。未承诺已经开始的响应可以中途撤销。
- 活动/任务：事实活动和任务创建、查询、内容编辑API、任务完成命令及幂等重放；详情页可追加不同类型活动、创建任务并完成任务。修改活动不更改商机版本，审计独立追加。
- 审计/可靠性：业务写入、状态、审计和幂等成功结果在同一事务；CAS冲突409，审计失败回滚。全局业务审计列表/详情仅经理与ADMIN，支持对象/操作者/动作/时间筛选；商机公开脱敏历史按原API契约读取。幂等结果没有实施未批准的七天自动过期。
- 前端/API：沿用同源Cookie/CSRF；冲突保留输入，不自动改用最新版本重试。销售接口有明确请求和响应Schema；NGINX包体上限21 MiB用于容纳multipart，文件自身仍严格≤20 MiB。

## 3. 文件职责与迁移

| 文件 | 本轮职责 |
| --- | --- |
| backend/app/sales/domain.py | 唯一阶段概率映射、合法边、Decimal及WON证据校验 |
| backend/app/sales/models.py、schemas.py、views.py | 关系模型、严格输入、只读响应契约 |
| backend/app/sales/service.py | 权限、锁序、CAS、事务审计、幂等、Pipeline及任务 |
| backend/app/sales/files.py、router.py | 受限PDF处理、存储、代理下载及API |
| backend/alembic/versions/0003_sales_sales_core.py | 增量新增五表及选择证据组合外键；拒绝破坏性downgrade |
| backend/app/main.py、db.py、alembic/env.py | 注册模块、只读字段错误、死锁映射及迁移就绪检查 |
| backend/tests/test_sales_unit.py、test_sales_mysql.py | 25格状态矩阵、金额/权限/证据、真实事务、20轮并发及审计权限 |
| backend/tools/m2_validation.py | 只创建/复用专用测试库、账户，分离迁移及运行权限，保存脱敏命令结果 |
| frontend/src/sales.tsx、sales.css、sales.test.tsx | 看板、表单、详情、证据审核、活动和测试 |
| frontend/src/App.tsx、api.ts | 在原CRM导航上接入销售页；FormData保留浏览器boundary |
| frontend/e2e/sales.spec.ts、playwright.config.ts | 可指定隔离入口的真实浏览器验证 |
| infra/nginx.conf、.github/workflows/ci.yml | 上传包体边界；CI专用运行账户无审计UPDATE/DELETE权限 |
| backend/pyproject.toml、uv.lock | 添加并锁定pypdf 6.21.2及python-multipart 0.0.32，无第二ORM/迁移系统 |
| README及八份设计文档 | 同步当前授权、部分批准范围、下载契约及本轮报告入口 |

迁移链：0001_auth → 0002_accounts_contacts（已有M2-A）→ 0003_sales。新增opportunities、activities、stored_objects、close_evidence、idempotency_records。环形选择关系在两表创建后显式添加组合外键，防止选择其他商机证据；没有DROP/TRUNCATE/DELETE或破坏性旧表变更。

M2物理实现注记：概率目前用INTEGER配CHECK表达只读固定映射；SHA-256用64字符十六进制字符串；StoredObject记录所属商机、页数及request_token用于本轮证据上传，不据此冻结未来知识文档模型。M1 User主键VARCHAR和本轮业务CHAR UUID的FK兼容沿用M2-A。AI专有活动去重、完整Job/SYSTEM审计仍归后续阶段。

新代码readiness要求0003_sales；本轮**没有升级原.env指定的数据库**，不能把新代码直接切到旧schema并称其就绪。

## 4. 实际环境与隔离资源

| 资源 | 实际使用 |
| --- | --- |
| MySQL | Windows本机8.4.13；本轮库esc_m1_test_m2_4a9479139fe9，专用用户esc_m2_4a9479139fe9；实际查询12张表均为InnoDB，迁移号0003_sales并通过模型检查 |
| 迁移/运行权限 | 迁移用原配置中的管理连接仅指向新库；运行用专用用户，audit_events仅SELECT/INSERT，真实UPDATE拒绝测试通过 |
| MinIO | 192.168.10.150新建容器esc-m2-accept-8c7e59d326、卷esc-m2-data-8c7e59d326；不公开宿主机端口，经已确认主机指纹的SSH隧道访问 |
| MinIO镜像 | 既有缓存的固定官方摘要14cea493d9a34af32f524e538b8346cf79f3321eff8e708c1e2960462bd8936e，未升级系统服务 |
| 存储权限 | 专用业务用户esc_m2_business，仅esc-evidence桶的必要对象/列举操作；root只用于新测试实例初始化，不作为应用凭据 |
| 测试输入 | 合成用户、空白PDF、合成客户/合同信息，无真实客户资料 |
| API/浏览器 | 临时本地API/Vite动态端口，真实同源代理；每次验证结束关闭自己启动的进程，测试库/对象/卷保留 |

本轮MySQL8.4.13结论不等于在8.4.8上执行了M2测试；8.4.8是M1既有历史证据。

## 5. 实际执行与结果

| 状态 | 命令或验证 | 结果/证据 |
| --- | --- | --- |
| PASS | backend下python -m tools.m2_validation | 新库upgrade head、专用权限初始化、完整pytest、alembic check；未连接原业务schema执行迁移 |
| PASS | python -m pytest -q（通过上述工具注入隔离连接） | 262 passed；含真实MySQL集成，无SQLite替代；.local/m2-validation/pytest.log |
| PASS | python -m alembic check | No new upgrade operations detected；.local/m2-validation/model-check.log |
| PASS | Python Ruff check、format --check、compileall | 代码检查及语法检查通过 |
| PASS | frontend npm.cmd run typecheck / test / build | 类型、92项前端测试、生产构建通过 |
| PASS | 20轮独立Session并发修改同一商机版本 | 每轮恰一成功、一409；数据库阶段概率CHECK拒绝错误值 |
| PASS | 审计故障注入、幂等和权限 | 失败写入回滚；同键重放不重复写入，改body冲突；专用运行账户不能改审计 |
| PASS | 两位真实认证用户经同源HTTP上传/核验/关闭 | MinIO真实上传及stat、请求标识重放、自核验403、另一用户核验、预计250000/实际230000成交、重复关闭只返回原结果、原件下载hash一致、无会话下载401 |
| PASS | 真实MinIO负例 | 专用账户跨桶访问、创建未授权桶均真实403/AccessDenied；网络失败不计作权限成功 |
| PASS | Playwright sales.spec.ts | 1项真实浏览器测试：登录→创建客户→创建未知金额商机→NEGOTIATION/60%→刷新仍持久化→登出；不是所有未来E2E矩阵已通过 |
| PASS | docker compose --env-file .local/compose.env --profile core config --quiet | 仅配置语法检查，不代表连接引擎或服务运行 |
| NOT RUN | 整套M2 Core Compose重新构建/部署及容器重启持久化 | 本轮使用原生API/Vite与独立测试MinIO，不借用M1结果宣称M2镜像/部署已通过 |
| NOT RUN | GitHub远端CI、完整性能基线 | CI已调整配置，本地运行不能替代远端CI或性能测量 |
| NOT RUN | M3 AI执行、知识库/真实Provider | 未进入后续阶段，模型调用0 |
| DEFERRED | 客户/联系人停用及其验收 | 保留此前用户明确延期范围；尚未实现，不伪造无开放商机检查 |

本地证据：.local/m2-validation/database-actual.json、final-integrity.json、attempt-history.json、migration.log、pytest.log、model-check.log、live-checks.json、live-flow.log、browser.log、opportunity-browser.png。专用连接/密码另存忽略的私有配置，不提交。真实存储及端到端编排为本机证据脚本，不是可直接在任意克隆环境运行的部署工具；可移植E2E测试与数据库验证工具已入源码。

## 6. 失败历史与尚存限制

初次受限环境不能写uv缓存，依赖安装改在获准环境执行；受限网络下数据库探测失败、部分单测停滞，允许访问本机服务后实际通过。不是把失败计成通过。

首次真实MinIO验收失败：原M1测试容器当时exited/unhealthy、容器IP为空，SSH转发连接失败。本轮没有重启原容器或触及原卷，另建上述M2测试实例后完成真实请求。SSH连接关闭时曾出现连接重置诊断，最终业务/浏览器结果独立验证，不以隧道断连作为权限拒绝。既有依赖仍有Starlette/httpx、Zod构建注释及临时SSH验证环境的弃用提示，未为消除警告升级系统或既有框架。

OTHER_APPROVED的审批职责仍待Q05-A，不能核验通过或用于WON；已允许保存有批准依据说明的PENDING候选。失败或授权在上传后变化会留下UPLOADING记录/对象，当前拒绝将其用于成交；需人工对账，自动恢复/清理及保留期限未批准、未实现。PDF处理有大小/页数和子进程时限，但尚无操作系统级内存配额或恶意文件扫描。API代理不会撤销已经发出的响应字节。

待完善的M2验收包括：延期停用功能的单独确认、完整浏览器负面矩阵、M2镜像/Compose部署及持久化、性能基线。人员/客户选择器目前最多读取100条，人员调整仍输入UUID；活动编辑已有API但页面主要提供新增与任务完成，需后续交互完善。Pipeline当前按已筛选数据做精确应用层聚合，不声称大规模数据性能已验证。

## 7. 下一步边界

本轮代码和实测证据提交评审，M2整体保持IN PROGRESS，不把上述NOT RUN/DEFERRED记作完成。后续只补M2剩余范围；Q05-A、Q07—Q10及Q11/Q12其他范围按决策表期限确认。没有启动M3、真实AI或知识库开发，没有自动创建下一阶段任务。
