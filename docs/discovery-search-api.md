# D2 公开搜索契约

本接口沿用 `/api/v1/discovery`、现有会话、Origin/CSRF、统一错误和 UTC 时间序列化。搜索与本地 RULES 任务分开，不创建 CRM 对象、成交证据或知识库文档。

| 方法/路径 | 输入 | 行为 |
| --- | --- | --- |
| POST `/profiles/{id}/search-preview` | expected_profile_version、public_query（3—200单行字符） | 当前空间鉴权；返回完整公开查询、画像版本、可执行状态、受理额度及10分钟签名。没有外部调用 |
| POST `/profiles/{id}/search-runs` | 上述字段、preview_token、request_token(UUID)、confirmed_public=true | 202，持久化 QUEUED 任务和审计，原子保留当日额度；当前用户必须有该空间写权限 |
| GET `/profiles/{id}/search-runs?page=1` | 每页20条 | 按空间鉴权的历史；仅摘要，不返回原始结果 |
| GET `/search-runs/{id}` | UUID | 当前权限复检；返回状态、错误、可能计费标记和成功后的摘要结果 |

READ_ONLY 不可读取搜索历史/资料，也不能发起搜索。TEAM 允许销售角色读取该空间搜索结果，但不因此取得写权限；PRIVATE 仅所有者和明确授权的有效经理/管理员可访问。管理员不隐式读 PRIVATE。

签名绑定用途、操作者、空间、画像版本、公开文本、Tavily官方端点、固定搜索参数和时间。新受理检查签名与当前版本；已受理的同用户同 request_token、同意图重试重新鉴权后返回原任务，即使预览已过期、画像版本后来改变或开关关闭。不同意图复用 token 返回409，不再次保留额度。显式确认不是患者/秘密自动检测，用户仍需只输入公开词语。

`discovery_search_runs` 保存独立请求、冻结公开文本/端点/画像版本、版本、状态、租约/派发标记、结果和错误。唯一键 `(created_by, request_token)`；索引覆盖领取、空间历史和UTC日额度。`discovery_search_guard` 是迁移创建的单行锁，序列化不同用户的全局受理额度；不使用内存计数或仅依赖前端禁用。

状态：QUEUED→RUNNING→SUCCEEDED / FAILED / OUTCOME_UNKNOWN。Worker领取与派发栅栏各自提交；网络请求不持有数据库事务。派发前和发布前检查用户有效性、空间写权限及画像版本；终态不可再次领取。租约180秒；已标记派发的过期任务进入 OUTCOME_UNKNOWN，没有派发标记则 FAILED，均不自动重发。租约/身份不匹配的晚到结果丢弃。

网络调用与本地事务不能形成分布式“恰好一次”保证。这里选择每个受理请求最多派发一次，进程在派发标记提交后崩溃可能导致未搜索但结果未知；以不自动重复计费为优先。用户要再次搜索必须重新预览、明确创建新请求，仍消耗额度。

默认 `DISCOVERY_SEARCH_ENABLED=false`；默认受理上限每人每日10次、全局50次，可配置。UTC日统计所有受理记录，包括排队、失败、未知及成功，不自动退款/删记录。这是受理次数上限，**不是货币账单或供应商费用硬上限**；跨日积压也可能在下一日才派发。实际账单仍须由Tavily账户限额约束。验收环境按用户批准设为每人5次/全局15次。

Tavily密钥只在API/Worker后端环境；前端、迁移和授权初始化任务不携带。只支持固定官方 MCP/REST 目的地，basic、最多5条、关闭生成答案/自动深度/原文/图片，不自动重定向或重试。结果仅保留title/url/snippet/score，明确是待核验摘要。不会自动抓取结果URL；链接卫生检查不等于完整SSRF抓取安全链。

新增运行权限：

| 表 | SELECT | INSERT | UPDATE | DELETE |
| --- | --- | --- | --- | --- |
| discovery_search_guard | 是 | 否 | version | 否 |
| discovery_search_runs | 是 | 是 | status、provider_attempted、lease_token/until、started_at、completed_at、error_code、result、version、updated_at | 否 |

公开查询、端点、身份、空间、画像基准和幂等摘要均不可由运行账户UPDATE。结果终态不变由租约与服务层状态检查执行；数据库列权限仍允许Worker写结果，不能声称数据库独立强制完整业务状态机。

全局审计仅ID、版本、状态等白名单，不记录查询或搜索正文。SEARCH_ACCEPTED和额度/回执同事务；派发标记与SEARCH_DISPATCHED同事务；结果发布与SEARCH_COMPLETED/FAILED同事务。失败无部分本地成功，但供应商可能已计费，不能伪装自动退款或成功。

典型错误：403空间/角色拒绝；409画像或预览过期、幂等意图冲突；429当日受理额度耗尽；503未启用/配置不全/门禁未初始化。Provider错误存入任务错误码；响应丢失可能为SEARCH_OUTCOME_UNKNOWN，不自动重试。
