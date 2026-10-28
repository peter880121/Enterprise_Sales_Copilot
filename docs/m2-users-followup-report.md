# M2.1 用户模块补充验收

日期：2026-10-28。继续用户管理的完善与验收，不进入 M3，不暂存、提交或推送。前轮报告 [m2-users-report.md](m2-users-report.md) 保持原样，本轮结果单独记录。

## 本轮完成

### 邮箱冲突与审计失败正确区分

此前注册/create/mutate 的外层异常处理把 MySQL 1062 都当成重复邮箱。实际审计主键或唯一键异常也可能返回 1062：注册会误报受理成功，管理员操作会误报 EMAIL_EXISTS，掩盖事务失败。

现在必须先完成失败事务回滚，再独立查询规范化邮箱的实际占用。编辑时排除目标用户本人；只有确有其他邮箱占用才走重复邮箱逻辑。其他唯一约束错误继续交给既有统一数据库错误处理，不改变该处理的 503 DEPENDENCY_UNAVAILABLE 契约，不回显 SQL 或参数。正常重复注册仍返回通用 202。

新增三项真实 MySQL 回归，在注册、管理员创建、编辑三条路径中注入实际重复审计主键 INSERT，由真实数据库抛出 1062，断言：

- 不返回 202/EMAIL_EXISTS，而返回既有统一数据库失败响应。
- 不遗留新用户或修改后的邮箱，不增加目标版本/审计。
- 编辑失败不撤销目标已有会话，目标仍可获取当前用户信息。

不新增数据模型、迁移或权限，不更改历史审计，不增加自动重试。

### 用户审计完整范围与可读性

此前后端已有分页，但用户详情只请求第一页，界面不能查看 20 条之后的记录。本轮接入服务端 page/page_size，独立缓存各页，提供上一页/下一页、总数、加载/失败重试与空状态。用户切换时分页状态重置。写入成功仍按 user-history 前缀失效相应缓存，不修改编辑输入或版本。

每条展示服务端操作人 ID、UTC 时间、操作及原因，可展开查看实际变化字段的 before/after。数据来自既有后端审计白名单，不展示密码/哈希，也不自行从 ORM 或其他接口补充内部字段。非 ADMIN 仍不能读取用户审计。

新增前端分页/字段变化测试和请求失败重试测试；新增真实浏览器场景，通过 API 创建合成用户并执行 21 次合法版本更新，验证 22 条真实审计的第二页、最初创建记录、操作人及字段差异。数据准备是 API，翻页和展示断言是浏览器交互，未伪称全部数据准备都由 UI 完成。

## 实际环境与资源

复用已明确归属的专用 Compose 项目 `esc-m2-core-33bee69cd6` 和库 `esc_m1_test_m2core_33bee69cd6`，**真实 MySQL 8.4.8**。独立 MinIO 保留。只使用新增合成用户及业务数据，不连接根 `.env` 的业务数据库，不删除库、对象或卷。

所有本轮新证据单独写 `.local/m2-users-followup-20261028/`，旧报告与旧测试日志不覆盖。控制器副本及私有配置留在该忽略目录，不纳入 Git。源码上传/构建只用于上述专用项目。

## 实际验证记录

以下 `control.py` 指本轮证据目录内的副本，负责明确注入该隔离库连接；不应直接使用默认 `.env` 运行数据库测试。

| 状态 | 实际命令/检查 | 本轮结果 |
|---|---|---|
| PASS | `control.py tunnel --command regression.py --log backend-final.log`，内部 `python -B -m pytest -q -p no:cacheprovider -k 'not last_admin_global_guard'` | **317 passed，1 deselected**，62.56 秒；真实 MySQL。保留原并发/审计回滚等回归，新增三项数据库失败回滚测试通过 |
| PASS | `npm.cmd --prefix frontend test -- --reporter=dot` | **105 passed / 6 files** |
| PASS | `npm.cmd --prefix frontend run typecheck` | TypeScript 通过 |
| PASS | `npm.cmd --prefix frontend run build` | TypeScript/Vite 构建成功；依赖 PURE 注释警告不影响退出码 |
| PASS | `backend/.venv/Scripts/ruff.exe check backend` | All checks passed |
| PASS | `backend/.venv/Scripts/ruff.exe format --check backend` | 66 files already formatted |
| PASS | `control.py deploy` | 专用环境 config --quiet、实际构建、up --wait 成功；长期服务健康，正常初始化任务退出 0。无新增数据库迁移 |
| PASS | `deployed_checks.py` | 容器内 40 个后端 app 文件 SHA-256 与工作区一致；`alembic check` 无模型差异 |
| PASS | `control.py tunnel --command api --log api-final.log` | **118 项 API 检查通过**，MySQL 8.4.8、真实隔离 MinIO |
| PASS | `control.py tunnel --command browser --log browser-final.log` | **8 项浏览器测试通过**，25.9 秒，含新增审计分页及原 7 项核心流程 |
| PASS | `Invoke-WebRequest http://localhost:5909/login` 及 `/api/v1/health/ready` | 均返回 200 |
| PASS | `final_checks.py`、`git diff --check`、最终索引检查 | 保护文件及前轮正式报告不变；原文件均保留；6 张已有基准截图哈希不变；无已知秘密命中；暂存区空 |
| NOT RUN | 独立空库最后管理员并发场景 | 本轮显式 deselect 1 项，未复用已有非空场景库；保护实现未修改，前轮通过仅保留为历史证据 |
| NOT RUN | 55 项权限专项、授权失败门禁重新测试 | 权限及部署依赖配置未修改；本轮实际业务 API/数据库已使用运行账户测试，不将前轮专项数字作为本轮结果 |
| NOT RUN | MySQL 8.4.13、托管 CI、生产部署及本轮性能/持久化全套 | 无新结论，不使用历史数字替代 |
| DEFERRED | 客户/联系人停用、Q05-A、Q07—Q10 等未批准范围 | 保持原约定；未批准其他业务决策，不实现邮件验证/找回、保留期限或自动清理 |

首轮回归失败记录保存在 backend-regression.log：新增测试错误预期 500，实际现有数据库异常契约为 503，已改为严格断言 503/DEPENDENCY_UNAVAILABLE；另有一项原用户版本冲突检查在部署重新授权期间得到 503，部署结束后再次完整回归通过。本轮不据此确认独立代码缺陷，也不将首轮失败计为通过。前端新增错误重试测试初次使用了错误按钮名，按现有组件“重新加载”修正后全套通过，未删除场景或放宽业务断言。

测试日志中仍有已有 TestClient/httpx 弃用警告；本轮不升级无关依赖。

## 证据和手动入口

- 本轮日志、配置检查、源码哈希、完整候选清单、M1 至当前工作区差异：`.local/m2-users-followup-20261028/`，其中 `M1-to-working.patch` 包含已跟踪及未跟踪候选文本；只供本机审核，不提交私有材料。
- 浏览器截图：`.local/browser-runs/run-1793151415336-19190b1f-47f8-4266-b10d-7c7a4414dd1c/`。新增 `user-audit-page-two.png`，使用唯一运行目录及 testInfo.outputPath，不覆盖旧截图。
- 手动测试：`http://localhost:5909`，需保持本轮专用 SSH 转发运行。管理员合成凭据仅存本轮 `browser-private.json`，不在报告展示。

当天检查发现前轮本地 SSH 隧道已断开，但仍占用 5909。核对进程命令行确为本项目专用 manual_web.py 后，仅停止该失效转发进程，再建立本轮 Web 转发，没有停止远端业务服务。新辅助脚本仅在转发请求字节之前重新建立失效 SSH 通道，已发送的请求不会自动重放；应用/NGINX 的写入重试策略未修改。恢复后入口 200 已验证；长时间断网恢复专项未运行。

人工验收可用 ADMIN 打开用户详情，在“用户操作审计”翻到第二页并展开“查看字段变更”；新增合成用户名以 `Audit pages` 开头。继续按前轮流程验证注册/审批、角色、禁用、逻辑删除恢复及密码管理。

## 文件与保护检查

本轮应用修改仅五个文件：

| 文件 | 职责 |
|---|---|
| backend/app/users/service.py | 回滚后核验真实邮箱占用，区分审计约束失败 |
| backend/tests/test_users_mysql.py | 三项真实重复审计键失败/回滚回归 |
| frontend/src/users.tsx | 分页审计组件、操作人及字段差异 |
| frontend/src/users.test.tsx | 分页/变化字段/错误重试回归 |
| frontend/e2e/users.spec.ts | 22 条真实审计的浏览器翻页 |

另更新 README 报告入口、新增本报告。没有改 AGENTS.MD、根 `.env`、`.gitignore`、前轮正式报告、角色矩阵、数据库权限、模型/迁移、商机金额/阶段/概率/成交核验规则。原有未提交 M2/M2.1 工作保留。所有执行前文件存在，Git HEAD 仍为 M1 `bc425b6e5d3eb923711502c61bb571996e3ec9a7`；暂存区为空，`.env`、`.local/`、image.png 不在索引中。

秘密扫描覆盖全部拟提交文本中的已知根配置/本轮秘密值及常见私钥/Token 形态；不涵盖未知编码秘密、依赖二进制或数据库原件，不声称安全扫描绝无遗漏。完整候选包含本报告共 131 文件，排除 image.png 及忽略材料；没有自动暂存这些文件。

本轮两项补充已通过对应实际回归，具备继续人工验收/代码评审条件；不宣称生产上线或整个 M2 无延期项。等待用户评审，不自动提交，不进入 M3。
