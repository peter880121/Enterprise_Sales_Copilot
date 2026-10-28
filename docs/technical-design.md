# Enterprise Sales Copilot 技术设计

版本：0.3 · 日期：2026-10-27 · 状态：M1正式验收通过；Q03—Q06已批准；用户于2026-10-27明确授权开始M2。Q11仅成交证据PDF≤20 MiB/≤100页获批，Q12仅成交证据API代理下载、每次重新鉴权获批；Q05-A、Q07—Q10及Q11/Q12其余范围继续待确认。实施与未完成项见[M2报告](m2-report.md)，不自动进入M3。

依据：[AGENTS.MD](../AGENTS.MD)、首轮对参考图的记录及2026-10-26第二轮修订指令。M0第二轮仅修订八份设计文档；当前按用户2026-10-27授权实施M2，AGENTS.MD及M1历史执行报告保持原样。本文中的参数是建议默认值，验收目标不是已完成或已实测结果。

## 1. 设计评审摘要

| 项目 | 推荐方案 |
| --- | --- |
| 架构 | React/TypeScript SPA + FastAPI 模块化单体；同一代码库的独立 worker 处理持久化异步任务 |
| 关系数据 | MySQL 8.4 LTS / InnoDB，SQLAlchemy 2 + Alembic；不采用双 ORM 或双迁移系统 |
| AI 与资料 | 独立 Provider 适配层；Milvus 向量检索；MinIO 私有对象；MinerU PDF 解析 |
| 核心流程 | CRM 建档 → 会议解析草稿 → 展示证据和差异 → 用户逐项确认 → 权限、版本和规则复检 → 同事务更新及审计 |
| 关键模型 | Account、Contact、Opportunity、Activity、MeetingAnalysis、AISuggestion、CloseEvidence、KnowledgeDocument/Revision/Chunk、Job、AuditEvent、IdempotencyRecord |
| 核心风险 | 业务决策待批准；成交证据依赖人工核验；跨 MySQL/Milvus/MinIO 最终一致性；MinerU 环境与资源；真实模型输出可靠性 |
| MVP | 单企业四角色、完整 CRM、五阶段状态机、会议解析、RAG、跟进建议、人工受控执行、并发/幂等/审计与自动化交付 |
| 明确不做 | 多租户、复杂 Agent、自动签约/自动发信、WON 重开、汇率换算、合同真实性外部认证、微服务平台 |

技术栈ADR-01/02及Q03已由最新M1任务书批准。本轮Q04/Q05/Q06已批准，剩余评审重点为OTHER_APPROVED审批细节Q05-A、Q07—Q10及Q11/Q12其余范围（含真实供应商政策）；见[decisions.md](decisions.md)。M1正式验收通过；本轮已获用户明确M2开发授权；M1历史执行证据见[M1报告](m1-report.md)。

## 2. 目标、范围与交付边界

产品面向 B2B 销售、经理、管理员与只读用户，以可测试的业务闭环展示企业 AI 工程能力。AI 负责提取、检索、解释与提议，业务服务负责所有事实变更。成功标准是能解释并复现一次安全更新，而不仅是展示聊天结果。

MVP 包含任务书 A—F 全部模块。客户、联系人支持创建/查询/更新/停用；商机支持创建/查询/允许字段编辑、状态转换、归档和 LOST 重开；销售活动包含电话、会议、邮件记录与任务，但不发送真实邮件、不接会议录音系统。截图里的录音播放、通知红点、百分比增长、工作空间切换不代表已有数据或功能：无真实依据时不显示；单企业不提供租户切换。

设计文件分工：本文负责总方案；[architecture.md](architecture.md) 负责模块与故障边界；[data-model.md](data-model.md) 负责字段和约束；[api-spec.md](api-spec.md) 负责接口契约；[state-machine.md](state-machine.md) 负责状态、事务和建议执行算法；[test-plan.md](test-plan.md) 负责验收；[implementation-plan.md](implementation-plan.md) 负责里程碑；[decisions.md](decisions.md) 负责决策与未决风险。规则冲突须先更新设计并评审，不由实现者自行选择。

## 3. 技术选型与模块

| 层 | MVP 必需 | 理由与边界 |
| --- | --- | --- |
| 前端 | React、TypeScript、Vite、React Router | 页面路由与类型化组件；静态构建由反向代理提供 |
| 数据/表单 | TanStack Query、React Hook Form、Zod | 服务端缓存与表单反馈；后端校验仍是权威 |
| UI | Tailwind、shadcn/ui、Lucide | 一致的可访问组件；建立原创图标与品牌，不复刻参考图头像/商标 |
| API | Python 3.12、FastAPI、Pydantic v2 | 严格 schema、统一异常及 OpenAPI |
| 数据 | SQLAlchemy 2、Alembic、MySQL 8.4、PyMySQL | 同步 Session 与短事务；同步 API 使用线程池，不在异步事件循环直接执行阻塞 ORM |
| 异步作业 | MySQL Job 表 + 同仓库 worker | 可恢复租约任务；无需先引入 Redis/Celery/Kafka |
| AI | 可替换 HTTP 适配器 | 分离 chat、structured、embedding；能力探测，供应商不兼容时明确报错 |
| 文件/检索 | MinIO、Milvus Standalone 及其配套 etcd、MinerU adapter | 业务单体不等于基础设施单进程；文档处理不占用 API 长事务 |
| 质量 | pytest、Ruff、TypeScript 检查、Vitest/Testing Library、Playwright | 规则、组件、真实 MySQL 集成及完整用户链路 |
| 交付 | Git、Docker Compose、锁文件、CI、README、配置模板 | M1 后逐步实现；本次不创建这些配置 |

后续增强：集中日志/监控平台、恶意文件扫描、SSO/MFA、专用队列、混合检索/reranker、审计防篡改存储。当前不引入 Kubernetes、微服务、Agent 编排、Redis 或 Elasticsearch。

唯一技术基线为 Python 3.12 / FastAPI / SQLAlchemy 2 / Alembic / MySQL 8.4 InnoDB。本轮用户指令优先于AGENTS.MD §3.3的Prisma条目及文末PostgreSQL建议；不引入Prisma、第二ORM或第二迁移系统。AGENTS.MD不修改，冲突及解决依据见ADR-01/02。

后端模块为 auth/users、accounts/contacts、opportunities、activities、ai、knowledge、audit、jobs。各模块依次划分 router → schema → service → repository，领域规则集中在 domain，外部调用放 adapters。repository 不提交事务，service/UoW 统一提交；AI adapter 不持有 CRM 写入凭证或业务 Session。

## 4. 数据与业务规则总览

MySQL 是业务事实唯一权威；Milvus 是可重建索引，MinIO 保存原件、解析结果与证据附件。ID 使用应用生成 UUID，API 用字符串；日期时间 UTC 存储并输出 RFC3339，业务日期使用 DATE，用户界面按 Asia/Hong_Kong 显示。详细类型见数据模型。

预计金额Opportunity.amount使用可空DECIMAL(18,2)，null表示未知，"0.00"表示已知零，JSON为十进制字符串或null。MVP 币种白名单 CNY、USD、EUR、HKD，默认CNY，Decimal计算并以ROUND_HALF_UP舍入到两位小数；不跨币种相加。probability使用0—100整数，按Q06已批准固定业务阶段映射（非历史销售数据校准预测）：PROPOSAL_SUBMITTED=20、NEGOTIATION=60、FOLLOW_UP=40、WON=100、LOST=0。加权金额为 CASE WHEN amount IS NULL THEN NULL ELSE ROUND(amount × probability / 100, 2) END，数据库生成列；用户与 AI 均不能直接编辑概率或加权金额。

新商机仅从 PROPOSAL_SUBMITTED 创建。WON/LOST 禁止普通编辑；LOST 经理重开后可编辑，WON 仅允许经理归档和追加活动/审计。不提供商机物理删除。客户/联系人停用保留关联，不级联删除。预计成交日期允许为空或已逾期；关闭时记录真实 closed_at，不伪造为预计日期。

Pipeline Value为开放阶段已知预计金额之和，Weighted Forecast为已知加权金额之和，各币种返回known_amount_count/unknown_amount_count。全部未知则金额合计null，空集合则"0.00"，部分未知展示已知小计及“另N笔金额待确认”，不能伪装完整预测。Open Deals包含未知金额商机；Win Rate 为指定关闭时间区间内 WON/(WON+LOST)，分母为零返回 null。阶段列total_amount/weighted_amount保留预计口径并标注；WON另展示closed_won_actual_amount，按选定且已核验的证据实际金额汇总，不取预计金额、不累加同商机的全部证据。终态不纳入开放Pipeline。所有汇总与列表共用权限、搜索、归档与日期筛选，按币种返回分组；截图数字仅为视觉参考，不能作为种子数据的真实统计。

成交规则（Q04/Q05已批准）：CloseEvidence.amount为合同/PO实际金额，必须>0；WON引用同商机、原件AVAILABLE且VERIFIED的不可变证据。预计金额可未知、为零或与实际不同，不自动覆盖预计值；actual_amount/actual_currency仅从所选证据投影，不另存可编辑副本。证据币种须在白名单且等于商机currency，不符返回EVIDENCE_CURRENCY_MISMATCH；用户可在开放阶段经CAS明确纠正币种后重新审核，不做换汇。类型为SIGNED_CONTRACT/PURCHASE_ORDER/OTHER_APPROVED；允许多候选，仅WON命令原子选一份，上传/核验不替换、不累加。后端强制核验人是另一位有角色、对象和操作权限的SALES_MANAGER/ADMIN，submitted_by != reviewed_by，记录核验人/时间/结果/依据及审计；REP不能核验，ADMIN也不能自核验。OTHER_APPROVED审批责任/步骤仅Q05-A待确认，最小审计提案见decisions §13与data-model §4，不默认任意文件有效。

## 5. 前端设计与参考图映射

### 5.1 布局与视觉

参考图采用左导航、顶部工具条、中部指标与看板、右侧 AI Copilot 面板。建议桌面导航宽 224px，AI 面板 400px，内容区边距 24px；五列最小宽 260px，剩余空间不足时横向滚动。≥1440px 并排显示审核面板；1024—1439px 使用覆盖式侧栏；小屏默认列表并允许切换看板。避免缩窄卡片直至无法阅读。

背景浅灰、内容白色、主操作蓝色；阶段顶部用紫、蓝、琥珀、绿、红区分，同时明确文字标签；优先级和状态分别显示，WON 不是优先级。字体优先系统无衬线，正文 14—16px，标题 24px；可交互元素具备焦点、键盘支持、文字标签及足够对比度。Logo 使用原创字标/几何标识。图中 “Online” 改为实际任务状态及 REAL/MOCK 徽标，不能以静态绿色表示模型健康。

### 5.2 页面与路由

| 路由 | 内容、主要行为与异常状态 |
| --- | --- |
| /login | 登录、密码错误、限流、过期会话；无自助注册 |
| /dashboard | 币种化指标、阶段图、逾期任务、近期活动；空值说明统计口径 |
| /opportunities?view=board/list | 搜索、负责人/阶段/币种/日期筛选、五列看板或分页列表；URL 保存筛选 |
| /opportunities/new、/:id/edit | Account、联系人、金额、币种、来源、优先级、日期；提交携带 version；阶段单独操作 |
| /opportunities/:id | 概览、活动、状态历史、证据、AI 建议；按后端 capabilities 显示操作 |
| /accounts、/accounts/:id | 企业列表、详情、联系人、关联商机、停用；/contacts 支持跨企业搜索 |
| /activities | 活动与任务列表、到期筛选、完成任务；不连接邮箱 |
| /opportunities/:id/meeting-analysis | 输入纪要及会议日期，异步进度、解析草稿、逐字段依据、未知信息 |
| /suggestions、/suggestions/:id | 建议筛选、before/after、引用、逐项勾选、接受/拒绝/放弃/重新生成 |
| /knowledge | 上传 TXT/MD/PDF、状态/失败原因、重试、版本更新、引用预览与删除进度；问答 tab |
| /audit | 对象/操作者/时间筛选，仅授权角色；脱敏详情，无编辑按钮 |
| /settings/users | ADMIN 创建/停用/角色调整，不能停用最后一个有效 ADMIN |

### 5.3 看板和审核行为

每列显示真实总数、按币种总金额；分页卡片与总体汇总区分，不以已加载卡片计算总额。每卡显示名称、企业、金额/币种、负责人、日期、优先级、来源、最近活动时间；最近活动无记录显示“暂无活动”。创建按钮统一从初始阶段创建，不在 Won/Lost 列直接新增终态。

MVP 用“变更阶段”菜单；后续若启用拖拽，也只打开同一确认表单并调用同一状态接口。关闭必须填证据或原因，不能拖拽直接成功。状态写入与 AI 应用不做乐观成功提示；等待服务端提交后刷新详情、看板、历史和统计缓存。

AI 默认无选中项。用户逐项选择建议，明确点击“确认并执行 N 项”后提交建议 ID、建议版本、商机版本与选中 change IDs；后端不接受客户端重写建议值。显示原值、新值、FACT/INFERENCE/UNKNOWN、对应片段、引用、过期时间和权限提示；存在依赖关系的变更作为一个组确认。推断项只可作为参考，不能直接执行关键字段变更。冲突后保留用户选择供参考，禁用旧建议，重新读取并重新生成，不能悄悄覆盖。重新生成创建新建议并将旧草稿标为 SUPERSEDED。

全页面定义 skeleton、空态、422 字段错误、401 重登录、403 禁止、404 不可见、409 冲突、502/504 AI 失败、503 服务不可用；用 aria-live 宣告异步结果。引用点击可授权获取原件/片段；本期只上传文本纪要，无真实录音就不呈现播放和时间戳按钮。

## 6. AI 架构与输出契约

### 6.1 Provider 与超时

环境变量建议包含 AI_MODE=mock|real、AI_BASE_URL、AI_API_KEY、AI_CHAT_MODEL、AI_STRUCTURED_MODEL、AI_EMBEDDING_MODEL、AI_EMBEDDING_DIMENSIONS、AI_REQUEST_TIMEOUT、AI_MAX_ATTEMPTS、MINERU_ENDPOINT。服务端启动校验模式；REAL 缺配置阻止 AI 就绪，CRM 可运行。只接受部署管理员配置的 HTTPS/内部地址，不允许用户提交 provider URL。

chat、structured_generate、embed 分离接口。结构化输出能力不足的兼容供应商可返回 JSON 后做同一严格校验，不降为自由文本成功。每次外部 HTTP 连接超时建议 5 秒、单次总超时 45 秒，瞬态超时/429/502/503 最多 2 次尝试（含首调用），指数退避+jitter 并尊重 Retry-After 和任务总预算。401/403、维度不匹配不重试。无效结构可在总计 3 次调用上限内修正一次；失败标记 AI_OUTPUT_INVALID，绝不转换为 Mock 成功。调用可能重复计费必须记录，不声明供应商侧 exactly-once。

任务总预算建议会议解析 180 秒、跟进/问答 120 秒，文档解析独立 15 分钟（试验后调整）。记录 provider/model、prompt/schema 版本、mode、耗时、tokens、attempts；价格表带版本与币种，仅可估算费用，供应商无 usage 返回 null。默认不把原始 prompt/纪要写日志。

### 6.2 会议解析 Schema v1

所有顶层键必填，未知标量用 null，未知列表用 []，禁止额外字段。原文保存为不可变 MeetingAnalysis 输入，生成前记录商机 version 和活动上下文；生成结束若商机已变更，可展示解析，但建议标记 STALE。

| 字段 | 类型/校验 |
| --- | --- |
| schema_version / language | 固定 "1"；语言代码或 null |
| needs | EvidenceValue<string>[]；每项≤1000 字符 |
| budget | {amount: EvidenceValue<decimal-string>, currency: EvidenceValue<enum>, confirmation: CONFIRMED/UNCONFIRMED/UNKNOWN}；预算不同于成交金额 |
| contacts | {name, title, decision_role} 的 EvidenceValue 对象数组；不自动创建或匹配同名联系人 |
| decision_makers | EvidenceValue<string>[]；明确来源或标 UNKNOWN |
| expected_close_date | EvidenceValue<YYYY-MM-DD>；模糊日期保留 raw_text 且 value=null，不能默认年份 |
| action_items | {description: EvidenceValue<string>, owner_name: EvidenceValue<string>, due_date: EvidenceValue<date>, priority: LOW/MEDIUM/HIGH/null}[] |
| risks / open_questions | EvidenceValue<string>[] |
| proposed_changes | {id, field, value, evidence_refs[], kind: FACT/INFERENCE}[]；字段白名单 |

EvidenceValue<T> = {value:T|null, kind:FACT|INFERENCE|UNKNOWN, evidence:[{source_id,start,end,quote}], raw_text:string|null}。start/end 是规范化 Unicode 文本的半开区间字符偏移；quote 必须等于该区间，source_id 来自本任务实际输入。FACT 非空必须有证据；UNKNOWN 必须 value=null；INFERENCE 必须标明推断来源且禁止伪称原文。服务端检验定位和类型只能证明引用存在，不能保证语义正确，仍须人工审核和真实模型评测。相对时间仅在会议日期和时区明确且无歧义时转换，展示转换依据。

### 6.3 可执行建议边界

以下具体白名单为Q07待确认提案，不随Q04—Q06批准；其中probability禁止人工/AI覆盖已由Q06明确批准。

MeetingAnalysis 保存需求、预算、联系人、决策人和风险结构，不等同于自动扩展 CRM 字段。AISuggestion MVP 绑定单一 Opportunity。允许 AI 提议 amount、currency、expected_close_date、priority、source、primary_contact_id（必须是该企业已有有效联系人），以及通过显式原文意图提议开放阶段的合法转换；阶段属于关键字段，必须 FACT + 用户确认 + 状态机复检。金额与币种相互依赖时成组选择；未确认预算不直接等同 amount。

可提议追加 NOTE/TASK Activity，引用需求与风险保留为关联活动/解析记录；任务负责人由用户在合法范围明确确认。禁止 AI 提议或执行 owner_id、probability、weighted_amount、WON/LOST、close_evidence、用户角色与权限。客户资料修订作为文字建议，本期由用户手动编辑客户，不伪装成可执行工具。跟进建议可完全是 advisory：行动、理由、引用、缺失信息、风险、日期/优先级；无可执行 change 时禁止“接受并执行”，提供“已阅/放弃”。confidence 不存储，避免未校准分数被误解为业务概率。

### 6.4 RAG

上传 → MySQL 元数据和 Job → MinIO 原件 → TXT/MD 本地解析或 MinerU PDF → 规范化文本/页码 → 按标题段落分块 → embedding → Milvus 写入 → 校验 → MySQL 发布 READY generation。默认 600 tokens/块、重叠 80、尽量不跨页，单块≤1000 tokens；保留标题路径、页码、文本偏移、hash、模型与索引版本。

检索初始 Top-K=8，以向量 cosine 召回，再经 MySQL 过滤有效文档、当前发布 revision/generation 及读取权限，去重后最多 5 块/6000 tokens 进入生成。过滤后不足可扩大候选一次至 24；不用无界检索。阈值不是通用固定真理，M4 用标注集校准并版本化，未达标不上线。返回 answer、answer_status=ANSWERED|INSUFFICIENT_EVIDENCE、citations、mode。每条事实需引用实际召回块；校验引用 ID 和片段属于输入，语义正确性由评测与人工审核补足。

无相关块直接返回“无法从现有资料中确认”，不调用模型编造。Milvus/embedding 不可用返回明确 503；生成失败可返回 RETRIEVAL_ONLY 及带标签原文片段、错误原因，不声称已生成答案。文档删除先在 MySQL 隐藏，检索必须再次核验，后台清理向量与对象；历史引用保留元数据但原文删除后显示“来源已删除”。详见架构与数据模型。

## 7. 权限、身份与安全

### 7.1 MVP 权限矩阵

Q03已由M1任务书批准：全员可读全企业CRM，REP仅写本人对象；原始纪要及AI草稿另按对象权限控制。本策略不能满足销售隔离场景。Q04核验职责和Q05成交规则本轮已批准；Q05-A及Q07—Q10、Q11/Q12其余范围仍待确认（成交证据限制和代理下载已批准）；M1只实现基础角色授权，READ_ONLY不能写入。业务授权 = 有效身份 ∩ 角色能力 ∩ 对象范围 ∩ 状态约束 ∩ 版本约束。

| 操作 | ADMIN | SALES_MANAGER | SALES_REP | READ_ONLY |
| --- | --- | --- | --- | --- |
| 查看客户/联系人/商机/已发布知识 | 全部 | 全部 | 全部 | 全部 |
| 新建客户/商机 | 任意有效销售负责人 | 任意有效销售负责人 | 自动归自己 | 否 |
| 编辑客户/联系人 | 全部 | 全部 | 客户 owner=自己 | 否 |
| 编辑开放商机/开放阶段推进 | 全部 | 全部 | 商机 owner=自己 | 否 |
| 更改负责人/归档 | 是 | 是 | 否 | 否 |
| 关闭 WON/LOST、重开 LOST | 是 | 是 | 否 | 否 |
| 上传成交证据 | 全部 | 全部 | 自己商机 | 否 |
| 核验成交证据 | 是，须非提交人且有对象/操作权限 | 是，须非提交人且有对象/操作权限 | 否 | 否 |
| 生成/接受/拒绝/放弃 AI 建议 | 全部 | 全部 | 自己商机 | 否 |
| 记录活动/完成任务 | 全部 | 全部 | 自己商机；无商机则客户归自己 | 否 |
| 上传/更新/删除知识文档 | 是 | 是 | 否 | 否 |
| 查看审计 | 全部 | 业务审计，不含安全/用户管理 | 自己商机业务时间线的脱敏视图 | 否 |
| 管理用户/角色 | 是 | 否 | 否 | 否 |

负责人必须有效且角色为 ADMIN、SALES_MANAGER 或 SALES_REP。更换客户负责人不隐式转移商机；修改联系人由客户负责人控制；不允许通过提供其他 owner_id 创建越权对象。查询、详情、聚合、引用下载均由后端执行相同范围约束。用户角色停用后权限即时生效。

### 7.2 认证

建议服务端不透明会话 token：256-bit 随机值，仅 hash 存数据库 Session，浏览器 HttpOnly、Secure、SameSite=Lax cookie。空闲 30 分钟、绝对 8 小时，登录后轮换，登出/停用立即撤销；不使用 localStorage 存长期 token。写请求校验 Origin 和与会话绑定的 CSRF token，前端通过受限响应获取并仅保存在内存。生产同源部署，开发代理转发 /api，CORS 禁止任意带凭证源。

CSRF token由服务端签名密钥、session ID和会话随机nonce确定性派生，login/me可返回同一会话的token，页面刷新后可重新获取；服务端比较签名并核对会话和Origin，不把随机token hash当作可逆数据。CSRF_SIGNING_KEY仅在服务端配置，轮换后旧token失效。

密码 Argon2id，参数在 M1 按实际硬件标定并支持 rehash；最少 12、最多 128 字符，不记录明文。登录失败统一响应，按账号 hash+来源限速并短时锁定；密码更新、管理员重置撤销所有会话。开发 demo seed 明确标记并仅在 development 显式启用，密码从环境提供或随机生成；生产禁止 demo seed，初始化管理员无固定弱密码，不通过公开 HTTP bootstrap。保留至少一个有效 ADMIN 的并发保护。

### 7.3 数据安全与注入边界

会议、知识和用户输入均视为不可信数据，LLM 无数据库/MinIO 管理密钥、无执行工具、无任意网络访问；工具输出只是严格白名单草稿。认证身份从 session 产生，不从模型或请求 body 的 actor_id 产生；schema 禁 extra、防越权字段赋值。系统提示词中不放密钥，提示词隔离只是辅助，不作为安全边界。

MinIO 按业务附件/知识原件/解析结果/审计导出和 Milvus 内部对象使用独立 bucket 与最小权限凭据，共享实例但禁止共享 root 凭据。成交证据下载按已批准Q12经API代理，每次重新鉴权并校验原件hash，不向浏览器暴露对象地址/凭据或签名链接；已开始的响应不承诺中途即时撤销。知识文档的签名窗口/下载方式仍待Q12对应范围确认。网页 Markdown 禁 raw HTML，链接协议白名单，PDF 在隔离预览中打开；拒绝可执行文件、路径穿越、超大文件、压缩包、受密码保护 PDF。解析容器无业务数据库写权限、限制 CPU/内存/磁盘与外网；任意 URL 导入不做，来源 URL 仅展示且不主动抓取。

审计/日志用字段白名单排除 password_hash、cookie、authorization、API key、原始文件和整段纪要；业务 PII 最小化，错误不回传供应商原文或 SQL。审计存储是追加式和访问隔离，并不宣称可抵抗数据库超级管理员篡改。外部模型的数据传输范围与供应商留存条款需部署方确认，未确认仅使用合成数据演示。

## 8. 并发、事务、审计和幂等

每次更新携带 expected_version；SQL 使用 id + version + 必要 stage/owner 条件的原子 CAS，并 version=version+1。rows affected=0 时区分不存在、无权限或冲突；不得查询后无条件保存。状态变更与 AuditEvent 同一个 MySQL 事务，审计失败全部回滚。远程模型、解析、Milvus、MinIO 操作全部置于业务短事务之外。

AI 应用同一事务锁定 suggestion、校验到期/状态/审批人/冻结变更，CAS 更新商机、创建被选择活动、追加审计、标记 EXECUTED 并保存幂等结果。任一步失败都不能残留 CRM 写入。失败终态或 STALE 使用后续独立短事务记录，不能误提交此前业务更新。完整锁序、重试与生命周期见 [state-machine.md](state-machine.md)。

关闭、重开、AI apply 使用 Idempotency-Key；键绑定 actor、route、对象、请求 hash；重复同内容返回原结果，不同内容 409。AI execute 还依赖 suggestion 状态与唯一 execution ID，即使换 key 也不能重复产生 Activity。普通 GET 和低风险 PATCH 不引入复杂去重；PATCH 因 CAS 避免覆盖，但客户端超时需重读确认而不是声称 exactly-once。

必审计：CRM 创建/修改/停用/归档/负责人调整、状态转换/重开、证据提交/核验、AI 生成请求及结果/审核/执行/失效、文档上传/发布/删除、用户权限和启停；登录失败记安全日志，登录/登出记不含 token 的安全事件。业务成功审计只随事务提交产生，失败记脱敏 operation attempt/security log；不可伪装成成功审计。审计完整性通过每个 mutation 的 request_id、entity/resulting_version 唯一约束及集成对账验证。

## 9. API 与测试总览

统一 /api/v1，使用 schema 版号、明确命令端点、分页上限 100、严格输入、统一 ErrorEnvelope。列表/汇总/下载不绕过对象权限；409 要求重新读取，不自动覆写。接口详情、响应例子及逐接口测试见 [api-spec.md](api-spec.md)。

测试金字塔以领域单元测试为底，真实 MySQL 事务/并发和 API 集成为主，少量关键浏览器端到端；Milvus/MinIO/MinerU 分层集成，Mock AI 测业务确定性，真实模型评测分开报告。不能以 SQLite/单线程假并发代替 MySQL 核验。所有验收目标见 [test-plan.md](test-plan.md)。

## 10. 非功能要求与验收口径

| 要求 | 级别 | 可测量验收 |
| --- | --- | --- |
| 正确性 | MVP 必需 | 状态/权限/事务/幂等/并发矩阵全部通过；不得忽略失败用例 |
| 分页/索引 | MVP 必需 | 页≤100，搜索≤100字符；1万条商机样本 EXPLAIN 检查关键索引与查询数；说明 LIKE 搜索扫描限制 |
| 性能基线 | MVP 必需 | 在记录 CPU/RAM/版本的机器上，以1万商机、10并发、5分钟测 p50/p95/错误率；普通 CRM p95≤500ms 为试验目标，未测不承诺 SLA，达不到需记录原因和整改 |
| 超时/重试 | MVP 必需 | API 数据库语句/锁等待有上限；模型/任务预算可配置，重试有上限，故障测试无无限循环 |
| 错误处理 | MVP 必需 | 所有 4xx/5xx 统一 code/message/request_id；无堆栈和敏感原文 |
| 可观测性 | MVP 必需 | JSON 日志含 request_id/job_id/action/status/duration；AI usage/成本未知可为 null；日志脱敏测试 |
| 配置与迁移 | MVP 必需 | 空库升级、上一版升级、缺配置启动失败检查；锁依赖与镜像 digest，无 latest |
| 恢复 | MVP 必需 | MySQL、业务 MinIO 及索引版本清单离机备份并演练；向量可从块重建；记录实测恢复时间 |
| 本地复现 | MVP 必需 | 新机器以core及AI_MODE=mock完成会议闭环；完整MVP再启knowledge；AI_MODE=real缺密钥禁用AI并明确报错，CRM可用 |
| 敏感数据 | MVP 必需 | HTTPS/私有 bucket/会话撤销/权限与日志扫描通过；演示仅合成数据 |
| 文件限制 | MVP 必需 | 知识 TXT/MD≤5MiB，PDF≤20MiB/100页，超限明确413/422；任务资源与并发上限 |
| 可访问性 | MVP 必需 | 键盘可完成登录、编辑、审核；状态不只靠颜色；自动检测加人工验证 |
| 监控/可用性 | 后续增强 | 告警、SLO、HA、负载均衡；MVP 不声明高可用或99.9% SLA |
| 审计强化 | 后续增强 | WORM/外部签名、SIEM、自动敏感信息发现、细粒度保留策略 |
| 容灾 | 后续增强 | PITR、异地副本，RPO/RTO 在业务明确后制定；MVP 仅建议每日离机备份，非保证 |
| 多租户/外部集成 | 当前不做 | 不承诺租户隔离、自动合同认证、跨币种换算、自动发信 |

建议数据库锁等待 5 秒、普通读写请求总预算 10 秒，服务层不在不明事务状态下盲目重试。任务与文件上限通过 M1/M4 基准修订，不能以超时重试掩盖过载。

## 11. 部署、备份与演示

生产演示采用 Linux 单机 Compose + HTTPS 反向代理，API/worker 分进程同版本；MySQL/Milvus/MinIO/etcd 仅内部网络。Windows 开发推荐 Docker Desktop WSL2 Linux 容器；MinerU 原生/远程配置必须按硬件验证。core profile启动前端/API/MySQL/worker/业务MinIO及受控桶策略初始化；knowledge profile增加Milvus/etcd/MinerU及锁定版本必需检索依赖，复用core MinIO的独立内部桶；关闭 profile 时 UI 明确显示模块未启用，完整 MVP 验收必须启用全部必需服务。

MinerU引擎/硬件兼容性不能由Python版本保证。按最新M1任务书，本期不部署解析/向量服务，兼容验证延至M4前置，再锁定镜像/权重/资源，不假定GPU存在。[官方部署说明](https://opendatalab.github.io/MinerU/quick_start/docker_deployment/)

先 healthcheck → 一次性 Alembic migration → 受控初始化用户 → API/worker 就绪。禁止每个 API 副本各自迁移。开发种子使用固定合成业务与版本化 Mock fixture；数据库、模型和依赖版本在 M1 验证后固定，不在设计中捏造兼容矩阵。迁移采用 expand/contract；回滚应用前确认 schema 兼容，否则前滚修复，从不假设自动 downgrade 无损。

备份在低流量维护窗口暂停上传/索引发布/删除与 CRM 写入，备份 MySQL 一致性快照与业务 MinIO 版本/manifest，恢复后核对 hash 和引用；Milvus 可重建，etcd/Milvus 内部备份按所锁版本官方流程联合处理，不能仅拷贝运行中数据目录。生产清理任务暂停后再恢复，验证审计与建议状态不出现二次执行。Secrets 由环境/密钥管理注入，配置示例只放占位符。

## 12. 评审自检与未解决风险

| 检查点 | 设计结论 / 实现验收 |
| --- | --- |
| 对象及关联 | 同企业联系人/证据约束、冻结 revision、owner 策略已定义；真实 FK 与服务验证待测试 |
| 后端不可绕过 | 普通 PATCH 拒绝 stage/概率/证据字段；所有入口共用 domain/service |
| 事务和覆盖 | CAS+同事务审计；需真实并发和注入失败证明 |
| AI 人工确认 | 模型只生成草稿，apply 校验冻结 change IDs、权限、版本和状态 |
| 过期与事实 | STALE/EXPIRED、字段级证据；语义正确仍非数据库约束可证明 |
| 环境 | M1 MySQL8.4及Core已实际验证，见M1报告§9；MinerU资源、Milvus组合归M4前置，仍未部署验证 |
| 测试与范围 | 核心规则可测且覆盖全部模块；无复杂 Agent/微服务；功能尚未实现 |

仍需解决：OTHER_APPROVED审批责任/步骤（Q05-A）、Q07白名单、供应商留存及输出能力、MinerU资源与质量、向量阈值、备份窗口、共享MinIO故障、数据库超级管理员信任边界。Q03已批准，不再列为未决，详见决策文件和M1报告。

M1正式验收通过；Q04/Q05/Q06已批准；Q05-A、Q07—Q10及Q11/Q12其余范围仍待确认（成交证据范围已批准）；M2已获单独开发授权，实际进度见M2报告。

## 13. 第二轮修订与静态一致性复核

| 修改主题 | 同步文档与章节 | 复核结论 |
| --- | --- | --- |
| 唯一ORM/数据库 | 本文§1/3；architecture §2/8；data-model §1；api-spec §1；state-machine §4；test-plan §1；implementation-plan M0/M1；decisions ADR-01/02、R01 | Python/FastAPI/SQLAlchemy/Alembic/MySQL 8.4统一；Prisma/PostgreSQL只保留冲突历史或排除说明；AGENTS.MD不改 |
| 预计/实际金额 | 本文§4；data-model Opportunity/CloseEvidence/§8及ER；api-spec §2/5/10/12；state-machine §2/3/7；test-plan A01—A05；implementation-plan M2；decisions ADR-06/07/13、Q05/Q06 | 预计可空、零为已知；加权随未知为空；成交无需等额；实际取所选核验证据；分币种不混加 |
| MinIO及服务边界 | 本文§7.3/10/11；architecture §1/7/9；data-model StoredObject；api-spec §8/10/12；test-plan D01—D04；implementation-plan M1/M2/M4；decisions ADR-04/14 | core包含MinIO；knowledge显式复用独立桶/凭据；标准Compose不会自动复用；关闭知识不阻断CRM及会议执行 |
| 提前AI闭环 | 本文§6/8及本节；architecture §4/9；data-model AISuggestion；api-spec §6/12；state-machine §5；test-plan §8；implementation-plan §1/M3/M5；decisions ADR-08/14 | M2可靠性→M3完整会议审核执行（无RAG依赖）→M4知识→M5增强建议→M6全量交付 |
| 业务决策状态 | 本文§7/12、decisions §13 | Q03及本轮Q04/Q05/Q06已批准；Q05-A与Q07—Q10、Q11/Q12其余范围仍待确认（成交证据范围已批准），保留推荐/备选/影响/期限 |

本节记录第二轮设计修订时的静态复核，不能代表M1运行结果；最新M1实际测试/未验证项见[M1报告](m1-report.md)。

历史M0准入结论已由M1任务书覆盖：当时设计、技术栈及Q03已明确批准，授权实施M1；后续任务书批准Q04/Q05/Q06。当前M1正式验收通过；Q04/Q05/Q06已批准；Q05-A、Q07—Q10及Q11/Q12其余范围仍待确认（成交证据范围已批准）；M2已获单独开发授权，实际进度见M2报告。M1历史运行结果及失败、补全过程仍以原执行报告为准，不以本轮文档清理替代运行证据。
