# M3-B 补充验收：管理员并发保护与持久化

日期：2026-10-28。用户要求继续推进后，本轮补齐 [M3-B 交付报告](m3-b-report.md) 中不依赖新业务决策的两项验收。原报告保留；一份旧保护检查摘要被误覆盖，详见第3节，不能宣称所有历史证据均未变化。本轮没有修改应用源码、迁移、依赖、测试源码或部署配置；没有暂存、提交、推送。

## 1. 环境与隔离

- 复用已明确归属 M3-B 的 Compose `esc-m2-core-848aae478f`，数据库 `esc_m1_test_m2core_848aae478f`；实际 MySQL **8.4.8**。
- 只对该项目的 `mysql`、`business-minio`、`api`、`worker`、`frontend` 执行 restart、stop、start。没有删除容器、数据库、对象或卷，没有操作旧 M2/M3-A 项目。
- 最后管理员测试另建全新库 `esc_m1_test_m2core_848aae478f_lastadmin_bbf98f6a`，迁移到 `0006_execution`，使用独立运行身份和测试准备身份，不清空其他测试库。
- 新证据目录：`.local/m3-followup-c67574566f/`。控制器显式注入隔离测试连接，不使用根 .env 的默认业务连接；根配置仅用于既有授权 SSH 控制入口，不打印秘密。
- 专用管理探针的凭据在忽略目录中保存，远端本轮新增探针配置移入其 `.local/` 并保持0600权限，避免进入后续 Docker 构建上下文。未移动用户已有文件或历史证据。

## 2. 实际命令与结果

控制器命令前缀：

```powershell
uv run --no-project --with paramiko --with python-dotenv python .local/m3-followup-c67574566f/control.py
```

| 状态 | 实际执行 | 结果与证据 |
| --- | --- | --- |
| **PASS** | 同一 uv 前缀运行 `prepare_lastadmin.py` | 新专库创建、迁移、独立运行授权成功；`lastadmin-prepare.log` |
| **PASS** | `control.py tunnel --command lastadmin_test.py --log lastadmin-test.log`；内部 `python -B -m pytest -q -p no:cacheprovider tests/test_users_last_admin_mysql.py` | **1 passed**，1.28秒；覆盖最后管理员并发停用及自降权保护；`lastadmin-test.log` |
| **PASS** | 真实 NGINX/API 创建合成客户、商机、纪要，Worker发布草稿，执行金额/币种及 NOTE/TASK，上传PDF并由另一位ADMIN核验 | 实际预计金额3200.50 USD、商机版本2、活动2条、执行回执1条；`persistence-resources.json`。所有材料为合成数据 |
| **PASS** | `control.py tunnel --command verify_persistence.py --log persistence-before.log` | 重启前 **11项**基准检查通过；`persistence-before.json` |
| **PASS** | `control.py command --command 'restart --timeout 30 mysql business-minio api worker frontend' --log owned-restart.log --timeout 180` | 五个专用服务实际重启，命令退出0；`owned-restart.log` |
| **PASS** | 设置本地阶段标记为 `restart` 后运行同一验证工具 | restart 后 **11项**检查通过；`persistence-restart.log`、`persistence-restart.json` |
| **PASS** | `control.py command --command 'stop --timeout 30 api worker frontend mysql business-minio' --log owned-stop.log --timeout 180`；再执行 `ps -a --format json` | 五个服务均实际 exited；`owned-stop.log`、`stopped-status.json`、`stopped-check.json` |
| **PASS** | `control.py command --command 'start --wait --wait-timeout 150 mysql business-minio api worker frontend' --log owned-start.log --timeout 200` | 数据/存储健康、迁移和授权初始化完成后启动API/Worker，随后前端健康；`owned-start.log` |
| **PASS** | 设置本地阶段标记为 `stop-start` 后运行同一验证工具 | stop/start 后 **12项**检查通过，含新登录；`persistence-stop-start.log`、`persistence-stop-start.json` |
| **PASS** | `control.py tunnel --command permissions.py --log permissions-after-start.log` | 启动后 **82项**真实数据库允许/拒绝探针通过；执行回执、审计及永久去重仍不可 UPDATE/DELETE |
| **PASS** | 最终 `ps -a --format json` 及实际HTTP请求 | 五个常驻服务 running/healthy；7034、旧14757、旧5909就绪接口均200；`final-status.json`、`acceptance-summary.json` |

持久化比对总计 **34项**（11+11+12），包括原登录会话、客户、商机金额/币种/版本、NOTE/TASK、原始合成纪要、EXECUTED草稿、执行回执及PDF原件SHA256。每阶段使用相同和不同幂等键重试，回执一致，业务状态、版本、活动数、执行数、审计数、幂等记录数均与基准一致，没有重复副作用。额外的新登录成功不替代原会话存续检查。

stop/start 重新触发了既有迁移/存储/授权初始化容器；当前schema未变化，服务按既有依赖恢复。此次验证的是相同容器/持久卷的重启和停止启动，不是删除容器、重建数据库或备份恢复演练。停止窗口内HTTP不可用的具体时长未测量，不承诺无中断或恢复SLA。

## 3. 验收工具问题及保留材料

最初私有验收工具在项目测试解释器中导入缺少的 paramiko，以及误读异步响应的资源ID，分别失败；这些是工具问题，没有改变应用依赖或API契约。随后分离控制器与HTTP/数据库验证，并按真实 `resource_id` 读取结果。首次合成准备数据留在本轮专库，没有清空或重新发送旧请求；失败日志和初次测试账号配置保留在本轮忽略目录。

首次重启命令误用了服务名 `web`，Compose返回 `no such service: web`，并未重启服务；按实际配置改为 `frontend` 后重启成功。保留 `owned-restart-service-name-failure.log`，不能将该失败计为应用问题或成功重启。停止状态JSON第一次本地读取使用了错误编码；改用UTF-8读取同一已保存证据后确认五个服务均已停止，没有重复停止服务来制造结果。

**证据保护异常，用户已批准保留现状并更正**：收尾时误复用了上一轮 `protection_check.py`，该工具将本轮结果写回旧目录 `.local/m3-execution-20261028/protection-final.json`。上一轮已报告的候选文本范围为159，本轮新增报告后为160；其他已观察字段仍为保护文件不变、索引空、无秘密命中、三个入口200。旧摘要原始字节备份不可用，不能将重建内容冒充原件。自动审批已拒绝修改旧摘要以恢复计数，理由是历史验收证据篡改风险；未执行恢复。用户随后明确选择“保留当前文件，追加更正说明”。据此保留当前文件，另存本轮 `old-protection-summary-observed.json` 和 `evidence-incident.json`，不再尝试恢复旧摘要。此异常不改变真实数据库/API测试结果，但不能宣称所有历史证据未变。原M1/M2/M3报告及后端/API/浏览器原始测试日志未因此改写。

## 4. 文件、保护检查及剩余范围

本轮可提交文档变更仅：

- `docs/m3-b-followup-report.md`：新增实际补验收结果。
- `README.md`：新增补充报告入口。
- `docs/implementation-plan.md`：新增阶段验收补充入口。

临时控制器、配置、账号、会话Cookie、SQL/API证据只在 `.local/`，不纳入提交。开始快照与结束比较用于确认：既有源码、测试、迁移、部署配置、AGENTS.MD、根 .env、.gitignore、image.png 和原历史报告保持不变。此前所有M3工作仍保留，HEAD仍为 `1cf537eefceb2cf2922eaa1476ac7d432bba18c3`，暂存区为空。最终保护与候选文本扫描记录见 `protection-final.json`；扫描不是对未知秘密不存在的绝对保证，私有忽略材料和二进制不作为公开候选扫描。

**NOT RUN**：本轮没有重跑上一轮380项后端、119项前端、118项API及12项浏览器整套测试；源码未变，历史通过只作为既有结果引用，不冒充本轮通过。远端CI、其他MySQL版本、生产TLS/部署、全新检出空缓存构建、性能重新测量及备份恢复演练仍未运行。

**DEFERRED / 待批准**：真实Provider及真实数据传输、实际清理/归档/缓存裁剪、草稿自动失效期限、客户/联系人停用、知识库，以及其他未批准业务决策。本轮没有扩大任何批准范围。

结论：本轮选择补齐的最后管理员专库测试和新增执行后的 restart / stop-start 持久化均 **PASS**，未发现需要修改应用代码的缺陷。旧保护摘要覆盖异常已按用户决定保留并更正，作为明确保护保留项，不宣称所有历史证据未变。M3-B 可继续用户评审；不能宣称生产验收或全部后续里程碑完成。手动入口仍为 `http://localhost:7034`，需要本机独立SSH转发保持运行。没有自动暂存、提交、推送。
