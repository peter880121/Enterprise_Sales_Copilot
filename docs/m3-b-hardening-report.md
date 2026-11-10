# M3-B 收尾审查与修复

日期：2026-10-28。用户要求继续推进，本轮只审查和完善已经批准的 M3-B，未进入真实 Provider、知识库或实际清理。此前 [交付报告](m3-b-report.md)、[补充验收报告](m3-b-followup-report.md) 及更正记录保留。

## 1. 发现及实际修复

| 确认问题 | 修复与影响 |
| --- | --- |
| 解析器先忽略空值/超过2000字符的标签值，导致它们不参与重复判断；例如一个合法预计金额后跟空值或超长重复金额，仍可能产生可执行金额组 | 先收集所有已识别标签，再进行歧义及Schema验证。金额或币种任一重复，整组不执行，不静默选择先出现的值。其他独立有效项可保留 |
| 合法会议日期9999-12-31加“明天”会抛出未处理OverflowError，发布事务回滚而任务仍等待租约恢复 | 将日历越界转换为明确的校验限制；Worker能正常发布其他合法项。不会自动改成其他日期或填充参数 |
| 执行后页面仍保留原商机版本，却缺少明确读取新基准的入口；后台查询刷新不能解决当前选择的旧基准 | 新增“读取当前商机版本”，显式GET当前商机并更新下一次提交的基准，保留纪要输入。读取失败保留旧基准；后台刷新不自动推进，旧草稿基准不变，也不自动POST |
| 仅修复生成器不足以保护此前已保存的歧义提议 | apply在业务写入前按当前确定性规则重新验证所选冻结提议的语义/依据。选项不再符合规则时409 SUGGESTION_REGENERATE_REQUIRED，不重写历史草稿或清理数据 |

兼容性：正常、依据一致的旧提议仍可执行，原执行回执按既有权限/永久去重重放。不符合当前规则的未执行旧提议可能需要重新生成；这是执行入口的安全校验变化，不是数据迁移。未选项不因该检查自动执行。仍只使用已批准六字段与NOTE/TASK；不允许AI改变阶段、负责人、概率或成交证据。

审查中复核了：当前身份及对象权限在加锁后重查，商机CAS与业务/活动/草稿审计及唯一回执处于同一事务；活动上下文变化使草稿失效；同键和不同键重试不会再次执行；运行身份无管理/迁移凭据。未发现需要另行改变业务规则的权限/CAS/事务缺陷，不能将本次审查等同于穷尽所有安全问题。

## 2. 修改文件

| 文件 | 职责 |
| --- | --- |
| `backend/app/meetings/proposals.py` | 先计重复标签、日历溢出校验 |
| `backend/app/meetings/execution.py` | 选定旧提议按当前规则复核，无历史数据改写 |
| `backend/tests/test_execution_unit.py` | 新增6项空值/超长重复金额币种、日期溢出回归 |
| `backend/tests/test_execution_mysql.py` | 新增5项真实Worker发布和旧提议拒绝/无副作用回归 |
| `frontend/src/meetings.tsx` | 主动读取新提交基准，读取/提交互斥，保留输入和原草稿版本 |
| `frontend/src/meetings.test.tsx` | 新增2项手动读取成功/失败、后台刷新及输入保留回归 |
| `frontend/e2e/execution.spec.ts` | 扩充真实执行流程，验证主动读取版本2并生成下一份默认未选草稿，不自动执行 |
| `docs/api-spec.md`、`docs/test-plan.md` | 当前兼容性及验收契约补充 |
| `README.md`、`docs/implementation-plan.md`、本报告 | 当前交付入口与实际结果 |

未新增迁移，schema仍为0006_execution；没有修改数据库模型、依赖、Compose/NGINX、运行权限白名单、AGENTS.MD、根.env、.gitignore或历史报告。既有未提交M3文件全部保留，不自动暂存/提交/推送。

## 3. 实测、环境与证据

独立证据目录 `.local/m3-hardening-7dd8b98d88/`，复用已确认归属的 `esc-m2-core-848aae478f` 与 `esc_m1_test_m2core_848aae478f`，实际MySQL **8.4.8**、真实隔离MinIO及NGINX。仅在数据库故障/并发测试时停止本轮Worker，最终Compose启动后已恢复。原M2/M3-A项目未迁移、停止或清理。无真实客户资料或真实模型调用。

控制器前缀为 `uv run --no-project --with paramiko --with python-dotenv python .local/m3-hardening-7dd8b98d88/`，连接均显式注入隔离运行/测试准备身份；浏览器和API使用原手动入口 `http://localhost:7034`。敏感材料和合成账号只留忽略目录，不进入提交。

| 状态 | 实际命令/检查 | 最终结果与证据 |
| --- | --- | --- |
| **PASS** | `.venv/Scripts/python.exe -B -m pytest -q -p no:cacheprovider tests/test_execution_unit.py tests/test_meetings_unit.py` | 定向37项通过；`parser-after-fix.log` |
| **PASS** | `control.py tunnel --command regression.py --log backend-with-execution-guard.log`；内部 `python -B -m pytest -q -p no:cacheprovider -k 'not last_admin_global_guard'` | 最终代码 **391 passed, 1 deselected**，96.21秒，含真实MySQL事务/并发/故障注入；`backend-with-execution-guard.log` |
| **PASS** | `npm.cmd test -- src/meetings.test.tsx src/meeting-execution.test.tsx` | 定向16项通过；`frontend-targeted.log` |
| **PASS** | `npm.cmd test`、`npm.cmd run typecheck`、`npm.cmd run build` | **121项/8文件通过**、TypeScript及构建通过；`frontend-final.log`、`frontend-build.log`；显式typecheck结果见终端 |
| **PASS** | `.venv/Scripts/python.exe -m ruff check .`、`-m ruff format --check .` | 全部检查通过，82文件符合格式；结果见终端 |
| **PASS** | `control.py deploy` | 最终代码实际config检查、标准构建、up等待健康成功；五个常驻服务健康，正常初始化任务退出0；`compose-build-final.log`、`compose-up.log`、`compose-status.json` |
| **PASS** | `deployed_checks.py` | 容器内50个app源码文件SHA256与本地一致，Alembic check无差异；`deployed-source-check.json`、`alembic-check-final.log` |
| **PASS** | `control.py tunnel --command api --log api-with-execution-guard.log` | 最终部署版本 **118项API检查通过**、失败0；`api-with-execution-guard.log` |
| **PASS** | `control.py tunnel --command browser --log browser-final.log` | **12项真实浏览器测试通过**，40.2秒，包含扩充后的连续草稿流程；`browser-final.log` |
| **PASS** | `control.py tunnel --command permissions.py --log permissions-final.log` | 最终部署后 **82项**运行账户权限探针通过；权限白名单未扩大 |
| **PASS** | `final_runtime.py` | 对API/Worker及初始化容器原始日志进行内存中已知秘密精确匹配，命中0；`container-log-scan.json`。不声称能识别所有未知凭据 |

浏览器9张截图保存在本轮唯一目录 `.local/browser-runs/run-1793172705515-0a2f2fec-b390-4a2a-b362-51966a965800/`；未复用旧截图输出目录。扩充流程确实经真实Worker生成新草稿：第一次执行后商机仍版本2；主动读取后以版本2提交；新草稿的NOTE默认未选，原执行POST次数仍为2（一次响应丢失、一次同键重试），没有自动第三次执行。

修复前6项新增后端边界测试实际失败、2项新增前端基准测试因缺少按钮失败；修复后通过。日志分别为 `parser-before-fix.log`、`frontend-before-fix.log`。首次前端测试命令的正则参数经npm.cmd被错误当成管道，已改用不含管道的筛选参数执行；不能将该命令错误当作代码失败。中途390项后端及118项API成功发生在旧提议复核加入前，保留为中间证据；最终结果以391项与 `api-with-execution-guard.log` 为准。

## 4. 保护、未运行及结论

最终基于本轮开始快照比较全部Git可见文件（含未跟踪源码），并核查暂存区、保护文件和候选文本秘密，结果记录在本轮 `protection-final.json`。只写本轮证据目录，不复用旧检查器的输出路径；上一轮保护摘要和用户决定更正记录另做只读哈希比对。旧覆盖事件仍以原更正说明为准，不重建历史证据，不将旧结果改成本轮结果。HEAD仍为 `1cf537eefceb2cf2922eaa1476ac7d432bba18c3`，暂存区空，.env/.local/image.png未进入索引。

**NOT RUN**：最后管理员专库测试本轮未重复执行（上一轮独立PASS保留，不合并成本轮392项）；最终补丁后的restart/stop-start持久化专项未重复运行（此前专项记录保留）；性能重新测量、全新检出空缓存构建、其他MySQL版本、远端CI、生产TLS和生产部署未运行。没有使用SQLite代替MySQL结论。

**DEFERRED / 待批准**：客户/联系人停用、真实Provider与真实资料传输、实际清理/归档、草稿自动失效、知识库及其他未批准业务决策。Q07/Q10范围、Q04—Q06业务规则不变。

结论：本轮确认的问题已局部修复，最终版本的已执行回归及专用部署验证 **PASS**，可继续用户评审。手动入口仍为 `http://localhost:7034`，需本机SSH转发保持运行。未自动暂存、提交或推送；不宣称生产验收或全部后续阶段完成。
