# M2-A 客户与联系人实施记录

日期：2026-10-27。起点：`bc425b6e5d3eb923711502c61bb571996e3ec9a7`，master。

## 1. 授权与实际范围

用户明确授权 M2-A；本轮进一步选择“先实现查询、创建和编辑，停用接口及相关验收留待确认”。原因：data-model 的幂等记录七天清理表述与 decisions Q10 待确认状态需要先明确。本轮不实现 activation、幂等记录或清理，不批准 Q10，也不自动授权其余 M2。

已实现客户及联系人模型、Schema、Repository、Service、API、前端目录/详情/表单、搜索分页、权限和验证错误。联系人所属客户不可编辑。数据库写入与白名单审计在同一事务；PATCH 使用 ID+expected_version 原子更新并递增版本。前端保留编辑开始时的版本，不因后台刷新自动提升版本并覆盖；成功后重新获取服务端数据。

尚未完成真实数据库运行验收，不能标记 M2-A 正式验收通过。没有应用迁移、没有连接默认 .env 数据库、没有运行会创建数据库或存储桶的 M1 live_validation 工具。

## 2. 文件职责

| 文件 | 职责 |
| --- | --- |
| backend/app/crm/__init__.py | M2-A 模块及停用延期边界 |
| backend/app/crm/models.py | Account、Contact 和本轮用户操作 AuditEvent；CHAR ASCII UUID、RESTRICT FK、版本/枚举约束和索引 |
| backend/app/crm/schemas.py | 字段、URL/邮箱、UUID、分页、PATCH、只读响应及 UTC 序列化 |
| backend/app/crm/repository.py | 查询、行锁、搜索分页和原子 CAS；不提交事务 |
| backend/app/crm/service.py | Q03、负责人校验、事务与追加审计；事务内复查有效角色及最新归属 |
| backend/app/crm/router.py | 九个 CRUD/关联端点、会话、Origin/CSRF、明确响应模型 |
| backend/alembic/versions/0002_accounts_contacts.py | 增量新增三表及约束，不改旧表或删除数据 |
| backend/alembic/env.py | 注册 CRM 元数据，仍使用唯一 Alembic 迁移 |
| backend/app/db.py | readiness 要求新迁移版本，防止旧库伪就绪 |
| backend/app/core/errors.py | 统一错误允许安全的字段/冲突 details |
| backend/app/main.py | 注册 CRM；校验错误仅返回字段路径/类型，不返回输入值；能力状态标记 accounts_contacts_only |
| backend/tests/test_crm_unit.py | Q03 写权限矩阵、输入和响应契约；无数据库替代结论 |
| backend/tests/test_crm_mysql.py | 专用 MySQL CRUD、角色、关系、冲突、审计回滚与双 Session 并发用例；本轮全部跳过 |
| frontend/src/crm.tsx | 列表/详情/搜索分页、账户和联系人表单、版本冲突反馈、真实请求及查询失效刷新 |
| frontend/src/crm.css | CRM 局部表单/表格样式 |
| frontend/src/crm.test.tsx | 表单、错误、权限、刷新、冻结版本及应用路由回归 |
| frontend/src/api.ts | 复用同源 Cookie/CSRF 客户端，允许读取完整分页响应 |
| frontend/src/App.tsx | 接入已认证 CRM 路由与导航，其余业务入口仍禁用 |
| README.md | 当前实现状态及本报告入口 |
| docs/m2-a-report.md | 范围、证据、未运行项和人工验收步骤 |

## 3. API 与权限

前缀 `/api/v1`。所有读取要求有效会话，所有写入同时要求可信 Origin 与 CSRF。

| 方法与路径 | 行为/权限 |
| --- | --- |
| GET /accounts | 全企业可读；page/page_size/q/owner_id/is_active/sort |
| POST /accounts | ADMIN/经理可指定有效销售负责人；REP 省略负责人归自己、指定他人 403；READ_ONLY 403 |
| GET /accounts/{id} | 全企业可读，含负责人简要信息 |
| PATCH /accounts/{id} | 经理/ADMIN 全部可写；REP 仅本人客户；负责人修改仅经理/ADMIN；expected_version 必填 |
| GET /accounts/{id}/contacts | 全企业可读，限定该客户；不存在客户 404 |
| GET /contacts | 跨客户搜索、account_id/is_active 筛选及分页，无隐式去重 |
| POST /contacts | 客户 owner REP 或经理/ADMIN；关联客户必须存在且有效 |
| GET /contacts/{id} | 全企业可读 |
| PATCH /contacts/{id} | 由最新客户归属决定写权限；expected_version 必填，account_id 不可变 |

默认分页 20，上限 100；稳定附加 ID 排序；q 最长 100。普通字段可空则显式 null 清空，省略保持。创建成功 201，查询/更新 200；统一错误含 request_id。错误包括 401 SESSION_EXPIRED、403 FORBIDDEN/CSRF_INVALID、404 NOT_FOUND、409 VERSION_CONFLICT、422 VALIDATION_ERROR/FIELD_NOT_EDITABLE/OWNER_INVALID/ACCOUNT_INACTIVE。没有 DELETE 或 activation 入口。

## 4. 迁移与风险

迁移链：0001_auth → 0002_accounts_contacts；新增 accounts、contacts、audit_events 和对应索引/CHECK/FK。客户与联系人用 CHAR(36) ASCII UUID，owner_id/actor_id 沿用 M1 users.id 的 VARCHAR 类型以匹配 FK。所有 FK 为 RESTRICT，无级联物理删除。日期 DATETIME(6) UTC，版本为无符号 BIGINT。

已执行 Alembic 增量离线 SQL 生成（内存注入合成配置，不加载 .env、不建立网络连接）：仅 CREATE 三表，未包含 DROP/TRUNCATE/DELETE。此结果不代表 MySQL 已执行或约束已通过。MySQL DDL 可能隐式提交，部分失败须检查现场，不自动回滚或删除新表。downgrade 明确拒绝破坏性回滚，不提供自动删审计路径。

部署新代码前必须在经确认的 MySQL 8.4 专用测试环境验证 upgrade/check；旧库停在 0001 时新版本 readiness 返回不可用，不能将新代码直接切到未升级库。应用账户对 audit_events 应仅有 SELECT/INSERT，迁移账户分离；本轮未修改任何数据库授权，权限隔离运行验证仍未完成。审计仅实现本轮用户变更所需子集，不引入未来 Job/SYSTEM 任务字段、审计浏览模块或清理任务。

## 5. 实际检查

在 backend 目录使用已有 `.venv/Scripts/python.exe`，未安装或升级依赖：

| 检查/命令 | 实际结果 |
| --- | --- |
| python -m ruff check . | PASS |
| python -m ruff format --check . | PASS，39 文件符合格式 |
| python -m pytest -q -m "not integration" | PASS，34 passed、22 deselected |
| python -m pytest -q -m integration | NOT RUN，22 skipped；无 TEST_DATABASE_URL |
| python -m pytest -q | PASS：34 passed；NOT RUN：22 skipped；无数据库连接 |
| Alembic command.upgrade(config, "0001_auth:head", sql=True) | PASS，离线三表 SQL，3173 字节，无网络连接；并非数据库迁移通过 |
| npm.cmd run typecheck（frontend） | PASS |
| npm.cmd test（frontend） | PASS，3 文件、14 测试 |
| npm.cmd run build（frontend） | PASS |
| 真实 MySQL upgrade/alembic check/CRUD/FK/事务/并发 | NOT RUN，缺少确认的专用测试连接；不回退到 .env 或 SQLite |
| 浏览器连接真实 API 的端到端验收 | NOT RUN；前端组件/路由测试不替代真实端到端 |
| 远端 CI、Compose 部署 | NOT RUN |
| 停用、重新启用及其验收 | DEFERRED，用户明确留待确认 |

首次静态检查发现格式问题，已修正后重新检查通过。保留的既有警告：Starlette/httpx 弃用提示，Vite 对依赖中 PURE 注释位置的提示；未升级依赖或掩盖警告。

## 6. 安全和剩余事项

Q03 状态已批准且文档一致：有效用户读全企业 CRM，REP 仅写本人客户及其联系人，READ_ONLY 不写，经理/ADMIN 可写全企业。旧 AGENTS 的 Prisma/PostgreSQL/仅设计表述已有 ADR 和后续明确授权处理依据；原文件不修改。Q04—Q06 未改动，Q05-A、Q07—Q12 未获本轮批准。

本轮无 AI 调用，无真实客户数据，无文件上传下载，无停用/幂等/清理，无商机、阶段、概率、Pipeline、成交证据或其他 M2-B/C/D 功能。仅为本轮 CRUD 提供必要的版本和事务内审计支撑。

未完成事项：真实 MySQL 8.4 验收、应用账户审计表权限验证、真实浏览器链路。停用将来还须结合未归档开放商机检查和跨模块锁序，不在没有商机模型时伪造“无开放商机”的验收。当前账户负责人界面使用 UUID 输入，尚未提供搜索式人员选择器；全局联系人目录通过所属客户进入编辑。

## 7. 人工验收建议

1. 提供明确授权、可写且与业务库隔离的 MySQL 8.4 测试环境。TEST_DATABASE_URL 必须为 `esc_m1_test_*` 专用库；迁移配置与测试连接必须指向同一专用库。不要直接使用 README 历史根 .env 命令迁移现有实例。
2. 由该环境管理员确认备份和迁移账户/应用账户权限后，在该专用库执行 Alembic upgrade head、alembic check，再运行 pytest。测试会保留新增的合成用户、客户、联系人和审计，不自动删除数据。
3. API 与前端连接该测试环境，以 REP 创建客户和联系人、刷新页面检查持久化，验证编辑与空字段清除。
4. 以另一 REP 和 READ_ONLY 验证全企业读取、拒绝越权写入；以经理验证合法负责人调整及原 REP 立即失去写权限。
5. 两个页面同时编辑同一版本，第二次保存应显示冲突并保留输入，不自动覆盖。检查每次成功变更只有对应版本审计，模拟审计失败应回滚。
6. 检查必填、无效邮箱/URL/UUID、无效负责人、不存在客户、不可变 account_id；确认界面及 API 都没有停用或删除入口。

本报告中的实施记录不是正式验收通过声明，也不构成后续阶段授权。本轮不暂存、不提交。
