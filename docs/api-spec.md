# REST API 契约

第二轮设计提案 v0.2 · 2026-10-26。前缀 `/api/v1`。本文件描述待实现契约；详细字段范围以 [data-model.md](data-model.md) 和 [technical-design.md](technical-design.md) 为准。

实施状态：M1正式验收通过；Q03—Q06已批准；用户于2026-10-27明确授权开始M2。Q11仅成交证据PDF≤20 MiB/≤100页获批，Q12仅成交证据API代理下载、每次重新鉴权获批；Q05-A、Q07—Q10及Q11/Q12其余范围继续待确认。实施与未完成项见[M2报告](m2-report.md)，不自动进入M3。
## 1. 全局约定

JSON命名snake_case；ID为UUID字符串，时间RFC3339 UTC，金额为字符串，日期YYYY-MM-DD。未知字段拒绝422 VALIDATION_ERROR；已知只读/受保护字段（stage、probability、weighted_amount、actual_amount/actual_currency、close_evidence_id、submitted_by/reviewed_by等）出现在不允许写入的创建/PATCH/建议或执行载荷中，统一422 FIELD_NOT_EDITABLE；专用命令只允许自身显式Schema字段。Cookie会话认证，写入要求Origin+CSRF；登录仅要求可信Origin，成功建立会话并返回内存用CSRF token。所有受保护端点均可能401 SESSION_EXPIRED、403 FORBIDDEN、429 RATE_LIMITED、500 INTERNAL_ERROR、503 DEPENDENCY_UNAVAILABLE；每个端点还需统一验证错误422 VALIDATION_ERROR。查询对象不存在或不可读时404 NOT_FOUND；列表和汇总使用同样授权范围。

成功单对象：`{"data":{...},"request_id":"req_..."}`；列表：`{"data":[...],"page":{"number":1,"size":20,"total":42},"request_id":"req_..."}`。异步成功是202 `JobAccepted={job_id,status:"QUEUED",resource_id?,poll_url,mode?}`。无body的204不返回JSON，request_id通过响应头。每个列表默认page=1/page_size=20，上限100；排序白名单，稳定附加id，未知sort拒绝422。查询q≤100字符，日期区间必须from≤to。

ErrorEnvelope：

```json
{
  "error": {
    "code": "VERSION_CONFLICT",
    "message": "商机已更新，请重新读取后确认。",
    "details": {"expected_version": 3, "current_version": 4},
    "retryable": false
  },
  "request_id": "req_01"
}
```

422字段错误details.fields为`[{path:"amount",code:"DECIMAL_SCALE",message:"最多两位小数"}]`；message面向用户，不包含SQL/供应商错误原文；code稳定供前端分支。前端409不自动用新版本重试。

### 1.1 并发/幂等通用契约

下表“V”为请求体expected_version必填、成功对象返回新version，过期返回409 VERSION_CONFLICT；无V的读取/创建不涉及已有资源版本冲突，仍可能有关联资源停用竞态。建议命令额外使用expected_opportunity_version。请求缺版本422，不靠最后写入覆盖。

“K”为Idempotency-Key必填；同键同body重放原成功结果，不同body返回409 IDEMPOTENCY_KEY_REUSED；建议已执行的选择改变返回409 SUGGESTION_ALREADY_EXECUTED。命令死锁409 RETRYABLE_TRANSACTION_CONFLICT/锁超时503且retryable=true。“T”为生成/上传用body.request_token或multipart request_token绑定Job dedupe；不承担普通CRUD全局去重。

除列表中特有错误，V/K/T接口均测试：缺字段422、相同版本并发至多一次成功、重复键相同/不同body、失败无部分写入。读取接口不产生版本冲突；端点内状态冲突另列409。

### 1.2 权限缩写

U=任意有效用户；A=ADMIN；M=ADMIN/SALES_MANAGER；W=开放商机有写权限的REP本人或M；C=客户owner本人或M；AI=W，终态仅可读历史不生成可执行建议；S=建议对应商机的AI权限；R=角色授权的业务审计读取。READ_ONLY不能写入或发起收费AI任务。关闭商机和证据核验是M；详情capabilities由后端计算，但每次命令重新授权。

## 2. 共享请求与响应Schema

| 名称 | 字段与约束 |
| --- | --- |
| UserPublic | id,name,email,role,is_active,version,created_at,updated_at；不含password_hash |
| UserCreate / UserPatch | create: name,email,password,role；patch: expected_version + name?/email?/role?/is_active?；不能批量赋值隐藏字段 |
| AccountCreate / AccountPatch | create: name必填，industry?/website?/company_size?/description?/owner_id?；REP owner由后端确定；patch: expected_version + 同字段；is_active走专用命令 |
| AccountView | Account公开字段+owner简要信息；关联列表分页，不嵌入无限商机 |
| ContactCreate / ContactPatch | create: account_id,name必填，title?/email?/phone?/decision_role?；patch: expected_version+允许字段，account_id不可改 |
| ContactView | Contact字段+version；不返回无关商机信息 |
| OpportunityCreate | name,account_id必填；currency省略默认CNY（非空、仅CNY/USD/EUR/HKD）；amount可省略或null（默认未知），非null为非负十进制字符串；primary_contact_id?/owner_id?/source?/priority?/expected_close_date?；不接受stage/probability |
| OpportunityPatch | expected_version必填；name?/primary_contact_id?/amount?/currency?/source?/priority?/expected_close_date?；至少一个变更，nullable用显式null清空 |
| OpportunityView | 数据模型公开字段、owner/account/contact简要信息、last_activity_at、capabilities；amount/weighted_amount为字符串或null；actual_amount/actual_currency只读投影WON选定VERIFIED证据，非WON为null |
| PipelineView | currency_groups:[{currency,open_count,known_amount_count,unknown_amount_count,pipeline_value,weighted_forecast,closed_won_actual_amount,stages:[{stage,count,known_amount_count,unknown_amount_count,total_amount,weighted_amount}],win_rate,closed_won_count,closed_lost_count}]；win_rate为0..1十进制字符串或null，注明统计窗口和filters |
| ActivityCreate / ActivityPatch | create: account_id,type,subject,content必填，opportunity_id?/contact_id?/occurred_at?/due_at?/assignee_id?；条件约束见数据模型；patch: expected_version,reason及允许修改内容/任务字段 |
| ActivityView | Activity公开字段、version、source_suggestion_id、source_change_id |
| EvidenceCreate | stored_object_id,type,reference_number,customer_legal_name,document_date,amount必填；amount为>0的实际金额字符串，currency省略默认CNY，仅CNY/USD/EUR/HKD且必须等于商机币种；OTHER_APPROVED附approval_basis |
| EvidenceView | CloseEvidence字段（submitted_by、reviewed_by、reviewed_at、status、verification_note、approval_basis）+原件元数据，下载另授权；提交人与核验人由服务确定，不含桶凭据 |
| SuggestionView | id,opportunity_id,type,status,version,mode,base_opportunity_version,context_as_of,proposed_changes,advisory,evidence,expires_at,reviewed_at,executed_at,result_version,error_code；服务端派生effective_status可标STALE/EXPIRED |
| ExecutionView | suggestion_id,execution_id,status=EXECUTED,selected_change_ids,resulting_opportunity_version,created_activity_ids,executed_at,mode |
| JobView | id,type,status,progress,attempts,error?,resource_id?,result?,mode?,created_at,updated_at；result带类型，不含内部payload和租约token |
| AnalysisView | id,opportunity_id,status,mode,base_opportunity_version,input_text（仅AI权限）,result（技术设计Schema v1）,suggestion_id?,error? |
| DocumentView | id,title,source_label,source_url,status,version,active_revision_id,pending_revision?,uploaded_at,uploaded_by,processing:{stage,progress,error_code?,message?} |
| ChunkView / Citation | document_id,revision_id,chunk_id,generation,title,page_start?,page_end?,start_offset,end_offset,quote,availability；只允许访问已发布有效版本或有权历史引用 |
| KnowledgeAnswer | answer:string\|null,answer_status:ANSWERED/INSUFFICIENT_EVIDENCE/RETRIEVAL_ONLY,citations:[],mode,limitations:[],error?；无证据时明确无法确认 |
| AuditView | id,entity_type,entity_id,actor_display,action,before_state,after_state,reason,expected_version,resulting_version,request_id,created_at；按权限脱敏 |

所有标准实体详情均返回version。PATCH不接受created_by/reviewed_by/actor_id。AI引用只允许本次输入与有效召回来源，API不允许模型提供任意可访问URL。

## 3. 认证与用户

每行“响应”写出成功状态与data类型；错误与关键测试是该接口特有，通用错误/并发规则仍适用。

| 方法 路径 | 请求 | 权限/并发 | 成功响应 | 特有错误与关键测试 |
| --- | --- | --- | --- | --- |
| POST /auth/login | {email,password} | 公开、可信Origin、限流 | 200 {user:UserPublic,csrf_token,absolute_expires_at} + Set-Cookie | 401 INVALID_CREDENTIALS统一隐藏账号存在性；429；错密码/失活账号/轮换会话 |
| POST /auth/logout | 无body，CSRF | U | 204，撤销cookie/session | 重复登出可204；原session再访问401 |
| GET /auth/me | 无 | U | 200 {user:UserPublic,capabilities,csrf_token,expires_at} | 过期401；不同角色能力一致 |
| POST /auth/change-password | {current_password,new_password} | U | 204，撤销全部会话，要求重新登录 | 401 WRONG_PASSWORD；422 PASSWORD_POLICY；新旧密码和撤销测试 |
| GET /users | page,page_size,q,role,is_active | A | 200 List<UserPublic> | 非管理员403；过滤与分页 |
| POST /users | UserCreate | A | 201 UserPublic | 409 EMAIL_EXISTS；弱密码422；不泄露hash |
| GET /users/{id} | UUID | A | 200 UserPublic | 不存在404；非管理员403 |
| PATCH /users/{id} | UserPatch | A,V | 200 UserPublic | 409 LAST_ADMIN_REQUIRED/EMAIL_EXISTS；停用立即撤销会话、并发最后管理员保护 |
| POST /users/{id}/reset-password | {expected_version,new_password,reason} | A,V,K | 200 UserPublic | 禁默认弱密码；撤销目标用户会话；审计无密码 |
| GET /assignable-users | q,page,page_size | U | 200 List<{id,name}> | 仅有效销售角色，不暴露全邮箱；owner下拉测试 |

## 4. 客户与联系人

| 方法 路径 | 请求 | 权限/并发 | 成功响应 | 特有错误与关键测试 |
| --- | --- | --- | --- | --- |
| GET /accounts | page,page_size,q,owner_id,is_active,sort=name/created_at | U | 200 List<AccountView> | q超长422；过滤/同名企业 |
| POST /accounts | AccountCreate | C的创建策略 | 201 AccountView | 422 OWNER_INVALID；REP指定他人403；缺name422 |
| GET /accounts/{id} | UUID | U | 200 AccountView | 404；关联不无限嵌套 |
| PATCH /accounts/{id} | AccountPatch | C,V | 200 AccountView | 409 VERSION_CONFLICT；owner修改仅M；越权403 |
| POST /accounts/{id}/activation | {expected_version,is_active,reason} | M,V,K | 200 AccountView | 409 ACCOUNT_HAS_OPEN_OPPORTUNITIES；停用与创建竞态 |
| GET /accounts/{id}/contacts | page,page_size,q,is_active | U | 200 List<ContactView> | 404；仅本客户联系人 |
| GET /contacts | account_id?,q,is_active,page,page_size | U | 200 List<ContactView> | 搜索跨客户分页；无隐式去重 |
| POST /contacts | ContactCreate | C | 201 ContactView | 422 ACCOUNT_INACTIVE；同名合法；邮箱格式422 |
| GET /contacts/{id} | UUID | U | 200 ContactView | 404；字段正确 |
| PATCH /contacts/{id} | ContactPatch | C,V | 200 ContactView | account_id改动422；越权403；版本409 |
| POST /contacts/{id}/activation | {expected_version,is_active,reason} | C,V,K | 200 ContactView | 已被引用时停用保留关联；新选择被拒绝 |

客户/联系人无DELETE接口；停用不级联删除。owner赋值错误不得默默覆盖为当前用户：创建时REP省略owner由后端赋自己，显式提供他人则403。

## 5. 商机、活动与成交证据

| 方法 路径 | 请求 | 权限/并发 | 成功响应 | 特有错误与关键测试 |
| --- | --- | --- | --- | --- |
| GET /opportunities | page,page_size,q,stage[],owner_id,account_id,currency,priority,is_archived=false,close_from?,close_to?,sort | U | 200 List<OpportunityView> | 列表/看板同筛选；组合查询不重复/漏项 |
| POST /opportunities | OpportunityCreate | REP自己或M | 201 OpportunityView | 422 CONTACT_ACCOUNT_MISMATCH/ACCOUNT_INACTIVE/OWNER_INVALID；初始阶段固定；省略/null金额创建，零金额明确保留 |
| GET /opportunities/{id} | UUID | U | 200 OpportunityView | 404；capabilities含当前状态与角色 |
| PATCH /opportunities/{id} | OpportunityPatch | W,V | 200 OpportunityView | 422 FIELD_NOT_EDITABLE/TERMINAL_OPPORTUNITY；409；金额边界/无部分更新 |
| POST /opportunities/{id}/assign-owner | {expected_version,owner_id,reason} | M,V,K | 200 OpportunityView | 422 OWNER_INVALID/TERMINAL_OPPORTUNITY；不能改终态owner |
| POST /opportunities/{id}/transitions | {expected_version,target_stage,reason,evidence_id?,close_reason_code?,close_reason?} | 开放转换W，WON/LOST为M；V,K | 200 OpportunityView | 422 INVALID_STAGE_TRANSITION/EVIDENCE_INVALID/EVIDENCE_CURRENCY_MISMATCH/CLOSE_REASON_REQUIRED；完整25格矩阵 |
| POST /opportunities/{id}/reopen | {expected_version,reason} | M,V,K | 200 OpportunityView | 422 WON_REOPEN_NOT_ALLOWED/NOT_LOST/REOPEN_REASON_REQUIRED；清关闭字段、独立审计 |
| POST /opportunities/{id}/archive | {expected_version,is_archived,reason} | M,V,K | 200 OpportunityView | 422 OPEN_OPPORTUNITY_CANNOT_ARCHIVE；重复提交不新增审计 |
| GET /opportunities/{id}/history | page,page_size,from?,to? | U；脱敏业务历史 | 200 List<AuditView> | 不包含用户/会话安全审计；顺序稳定 |
| GET /opportunities/{id}/activities | page,page_size,type?,status? | U | 200 List<ActivityView> | 无活动空数组；按occurred_at/created_at稳定排序 |
| GET /pipeline/summary | 与商机列表相同业务筛选，win_from/win_to（默认近90日） | U | 200 PipelineView | 422 DATE_RANGE_INVALID；多币种不求和；全未知/部分未知/全零区分；WON实际金额取所选核验证据；零分母null；和列表口径一致 |
| GET /activities | account_id?,opportunity_id?,assignee_id?,status?,due_from?,due_to?,page,page_size | U | 200 List<ActivityView> | 到期筛选/空态；状态组合校验 |
| POST /activities | ActivityCreate | 商机owner或无商机的客户owner/M | 201 ActivityView | 422 RELATIONSHIP_MISMATCH/TASK_ASSIGNEE_REQUIRED；终态允许追加记录 |
| PATCH /activities/{id} | ActivityPatch | 对应对象写权限,V | 200 ActivityView | 409版本；TASK和事实活动字段约束；改变digest |
| POST /activities/{id}/complete | {expected_version,reason?} | 对应对象写权限,V,K | 200 ActivityView | 422 NOT_A_TASK；已完成不同键409 ACTIVITY_ALREADY_COMPLETED |
| POST /opportunities/{id}/evidence-files | multipart file,request_token | W,T | 201 {stored_object_id,status:"AVAILABLE",sha256,size_bytes} | 413 FILE_TOO_LARGE/422 FILE_TYPE_INVALID；MinIO失败503；文件落库失败清理孤儿 |
| POST /opportunities/{id}/evidence | EvidenceCreate | W | 201 EvidenceView(status=PENDING) | 422 OBJECT_NOT_AVAILABLE/EVIDENCE_RELATIONSHIP_INVALID/EVIDENCE_CURRENCY_MISMATCH/APPROVAL_BASIS_REQUIRED；非法类型/金额/币种按VALIDATION_ERROR；他人文件不可引用；上传不选定 |
| GET /opportunities/{id}/evidence | page,page_size | U | 200 List<EvidenceView> | 只返回本商机、原件另鉴权 |
| POST /evidence/{id}/review | {expected_version,decision:VERIFY/REJECT,note,approval_basis?} | M且非submitted_by，须有对象/核验操作权限；V,K | 200 EvidenceView | 403 FORBIDDEN（角色/对象/操作无权）、EVIDENCE_REVIEWER_CONFLICT（自核验）；422 EVIDENCE_IMMUTABLE/NOTE_REQUIRED/EVIDENCE_CURRENCY_MISMATCH/APPROVAL_BASIS_REQUIRED；409 OTHER_APPROVAL_POLICY_PENDING（Q05-A提案）；AI不能核验 |
| GET /evidence/{id}/download | 无 | U，对象可见且非删除 | 200 application/pdf附件，API代理且每次重新鉴权（Q12成交证据范围已批准） | 401无有效会话；404原件不可用；503 STORAGE_UNAVAILABLE或完整性校验失败；无对象签名URL |

关闭与重开接口返回最新详情；状态写入/审计/幂等结果必须同事务。关闭前证据不得靠本次请求body直接创建VERIFIED状态。

## 6. AI解析、跟进与审核

具体可建议/执行字段范围仍为Q07待确认提案；本次仅冻结probability不可被AI覆盖等Q06规则，不批准其他字段白名单。

| 方法 路径 | 请求 | 权限/并发 | 成功响应 | 特有错误与关键测试 |
| --- | --- | --- | --- | --- |
| POST /opportunities/{id}/meeting-analyses | {expected_opportunity_version,meeting_text,meeting_date?,timezone,request_token} | AI,T；基础版本检查 | 202 JobAccepted(resource_id=analysis_id) | 409 VERSION_CONFLICT；422 TEXT_EMPTY/TEXT_TOO_LONG；Mock标记/非法JSON任务失败 |
| GET /meeting-analyses/{id} | UUID | 对应AI权限 | 200 AnalysisView | 403原文限制；pending/result/failed各态 |
| POST /opportunities/{id}/follow-up-suggestions | {expected_opportunity_version,request_token} | AI,T | 202 JobAccepted(resource_id=suggestion_id) | 409版本；上下文快照冻结；知识失败不伪装有引用 |
| GET /suggestions | opportunity_id?,status?,page,page_size | 仅可操作商机的AI权限 | 200 List<SuggestionView> | REP不列出他人建议；effective stale/expired正确 |
| GET /suggestions/{id} | UUID | S | 200 SuggestionView | 404/403；before/after和证据可追溯 |
| POST /suggestions/{id}/apply | {expected_version,expected_opportunity_version,selected_change_ids} | S,V,K | 200 ExecutionView | 409 SUGGESTION_STALE/ALREADY_EXECUTED/INVALID_SUGGESTION_STATUS；410 SUGGESTION_EXPIRED；422 CHANGE_DEPENDENCY_INVALID/NO_EXECUTABLE_CHANGES；重复任务无副作用 |
| POST /suggestions/{id}/reject | {expected_version,reason} | S,V,K | 200 SuggestionView(REJECTED) | 409 INVALID_SUGGESTION_STATUS；拒绝原因/无CRM变更 |
| POST /suggestions/{id}/abandon | {expected_version,reason} | S,V,K | 200 SuggestionView(ABANDONED) | advisory已阅与放弃；已EXECUTED不可改状态 |
| POST /suggestions/{id}/regenerate | {expected_version,expected_opportunity_version,request_token} | S,V,T | 202 JobAccepted（旧草稿SUPERSEDED，新ID） | 409草稿状态/商机版本；旧建议不可执行；任务失败不复活旧稿 |
| GET /suggestions/{id}/execution | UUID | S | 200 ExecutionView | 409 SUGGESTION_NOT_EXECUTED；返回原执行结果 |
| GET /jobs/{id} | UUID | 创建者或M，且仍有目标权限 | 200 JobView | 404/403；不泄露内部payload/密钥/租约；任务进度真实 |

接受与执行合为apply命令，以一次事务完成，不增加只改变ACCEPTED但尚未写业务的接口。executable字段白名单与禁止项见技术设计。知识问答通过下节接口，结果异步取JobView.result；结果永久性需求由保存的建议引用负责，不通过Job成为事实数据库。

## 7. 知识库

| 方法 路径 | 请求 | 权限/并发 | 成功响应 | 特有错误与关键测试 |
| --- | --- | --- | --- | --- |
| POST /knowledge/documents | multipart {file,title,source_label,source_url?,request_token} | M,T | 202 {document:DocumentView,job_id} | 413 FILE_TOO_LARGE；422 FILE_TYPE_INVALID/EMPTY_DOCUMENT；伪PDF/路径穿越；处理异步 |
| GET /knowledge/documents | page,page_size,q,status? | U，失败细节仅M | 200 List<DocumentView> | 空库/处理中/已删隐藏；不能展示临时未发布正文 |
| GET /knowledge/documents/{id} | UUID | U | 200 DocumentView | 404已删；M可见错误详情；旧发布版在重建时可用 |
| POST /knowledge/documents/{id}/revisions | multipart {expected_version,file,request_token} | M,V,T | 202 {document:DocumentView,job_id} | 409 DOCUMENT_BUSY/VERSION_CONFLICT；新版本失败保留旧版 |
| POST /knowledge/documents/{id}/retry | {expected_version,request_token} | M,V,T | 202 JobAccepted | 409 DOCUMENT_NOT_RETRYABLE；允许解析/索引失败或DELETING清理任务失败，按原任务类型重试；租约过期/无重复发布 |
| DELETE /knowledge/documents/{id} | JSON {expected_version} | M,V,K | 202 {document_id,status:"DELETING",job_id} | 409版本；即时检索不可见、清理失败仍隐藏；删任务可重试 |
| GET /knowledge/documents/{id}/processing | 无 | M | 200 {document_id,jobs:[{id,stage,status,attempts,error_code?,message?}]} | 脱敏错误/解析失败与embedding失败分别展示 |
| GET /knowledge/documents/{id}/download | revision_id? | U；仅有效发布版或有权历史引用 | 200 {url,expires_at} | 404 SOURCE_UNAVAILABLE；503存储；不能任意枚举未发布版 |
| GET /knowledge/chunks/{id} | generation必填 | U；当前有效源或授权历史引用 | 200 ChunkView | 404 SOURCE_UNAVAILABLE；已删旧向量不能回正文 |
| POST /knowledge/query | {question≤4000字符,request_token} | A/M/REP,T | 202 JobAccepted | 503 KNOWLEDGE_UNAVAILABLE；无相关结果为200任务结果INSUFFICIENT_EVIDENCE，非伪造错误成功 |

知识库查询不执行CRM写入。生成失败但检索成功时，任务result可为RETRIEVAL_ONLY并带error/limitations，不标ANSWERED。完整失败时Job=FAILED，result=null。文件超页数在解析前可校验则立即422，否则Job失败FILE_PAGE_LIMIT，不能在202时声称已完成解析。

## 8. 审计与运行状态

| 方法 路径 | 请求 | 权限/并发 | 成功响应 | 特有错误与关键测试 |
| --- | --- | --- | --- | --- |
| GET /audit-events | entity_type?,entity_id?,actor_id?,from?,to?,action?,page,page_size | A全部/M业务 | 200 List<AuditView> | REP/READ_ONLY403；经理不能读安全/用户管理事件；分页/时间边界 |
| GET /audit-events/{id} | UUID | R | 200 AuditView | 404无权事件；脱敏无敏感字段 |
| GET /health/live | 无 | 公开，仅最小状态 | 200 {status:"alive"} | 不因模型失败误判进程死亡 |
| GET /health/ready | 无 | 内网，公开只最小状态 | 200 {status:"ready"} 或503 | DB/迁移失败503，禁止详细连接串泄露 |
| GET /capabilities | 无 | U | 200 {crm:{available,reason},storage:{available,reason},knowledge:{enabled,available,reason},ai:{mode,available,reason},limits} | profile关闭明确disabled，MOCK不标REAL |

## 9. 完整交互示例

### 创建商机

POST /opportunities：

```json
{
  "name": "Acme 产品平台采购",
  "account_id": "10000000-0000-4000-8000-000000000001",
  "amount": "250000.00",
  "currency": "CNY",
  "priority": "HIGH",
  "source": "REFERRAL",
  "expected_close_date": "2026-12-15"
}
```

201 data（其他公开详情字段按OpportunityView补齐）：

```json
{
  "id": "20000000-0000-4000-8000-000000000001",
  "name": "Acme 产品平台采购",
  "stage": "PROPOSAL_SUBMITTED",
  "amount": "250000.00",
  "currency": "CNY",
  "probability": 20,
  "weighted_amount": "50000.00",
  "version": 1
}
```

### 开放阶段推进与丢单重开

POST /opportunities/{id}/transitions，Idempotency-Key=用户生成UUID：

```json
{"expected_version":1,"target_stage":"NEGOTIATION","reason":"客户已进入报价协商"}
```

200 OpportunityView版本2、概率60、加权150000.00。随后经理以版本2、target_stage=LOST、close_reason_code=BUDGET、close_reason="预算冻结"关闭，得到版本3。POST /opportunities/{id}/reopen：

```json
{"expected_version":3,"reason":"客户已批准新年度预算，重新洽谈"}
```

200版本4、NEGOTIATION、关闭字段清空；历史仍保留丢单原因。

### 会议解析与应用

POST /opportunities/{id}/meeting-analyses：

```json
{
  "expected_opportunity_version": 4,
  "meeting_text": "预算尚未确认。客户希望2026年12月20日前成交。",
  "meeting_date": "2026-10-25",
  "timezone": "Asia/Hong_Kong",
  "request_token": "30000000-0000-4000-8000-000000000001"
}
```

202返回job_id、analysis_id和mode。解析budget.amount.value=null、confirmation=UNCONFIRMED；日期FACT需原文片段。SuggestionView展示日期before="2026-12-15"、value="2026-12-20"、base版本4、建议version=1。POST /suggestions/{id}/apply，带Idempotency-Key：

```json
{"expected_version":1,"expected_opportunity_version":4,"selected_change_ids":["change_close_date"]}
```

200 ExecutionView包含唯一execution_id和resulting_opportunity_version=5。若商机已为版本5则409 SUGGESTION_STALE，不能把expected版本改成5继续执行旧建议。报价预算没有被明确确认，不生成amount更新。

## 10. 错误码目录与重试

| HTTP | 代码 | 客户端动作 |
| --- | --- | --- |
| 401 | SESSION_EXPIRED / INVALID_CREDENTIALS / WRONG_PASSWORD | 登录或提示凭据错误；不无界重试 |
| 403 | CSRF_INVALID | 提示请求安全校验失败；通过GET /auth/me获取当前CSRF token，核对可信Origin及请求头，修复后由用户重试；仅当/auth/me返回401时按会话失效处理，持续403应检查同源/代理配置，不循环重登或自动重放写入 |
| 403 | FORBIDDEN | 提示当前用户无该对象/操作权限；可通过GET /auth/me刷新身份与capabilities，按当前权限禁用操作，必要时联系管理员或有权限人员处理；不能仅凭此403判定会话失效，也不得绕过授权重试 |
| 403 | EVIDENCE_REVIEWER_CONFLICT | 提示提交人不能核验自己的证据，请更换另一位有相应对象/核验操作权限的SALES_MANAGER或ADMIN；保留待核验状态，不提示会话失效、不通过刷新Token或重复提交解决 |
| 404 | NOT_FOUND / SOURCE_UNAVAILABLE | 显示不存在/已删除来源 |
| 409 | VERSION_CONFLICT / SUGGESTION_STALE | 重新读取，重新确认/生成 |
| 409 | IDEMPOTENCY_KEY_REUSED / SUGGESTION_ALREADY_EXECUTED | 不重复写入；显示原执行结果或更换业务意图 |
| 409 | DOCUMENT_BUSY / INVALID_SUGGESTION_STATUS / LAST_ADMIN_REQUIRED / ACCOUNT_HAS_OPEN_OPPORTUNITIES | 用户先处理前置状态 |
| 409 | OTHER_APPROVAL_POLICY_PENDING（Q05-A待确认提案） | 先确认并配置其他依据审批责任/步骤，不当作瞬时故障重试 |
| 409 | RETRYABLE_TRANSACTION_CONFLICT | 已确认回滚后，原键有限重试 |
| 410 | SUGGESTION_EXPIRED | 重新生成 |
| 413 | FILE_TOO_LARGE | 减小文件 |
| 422 | VALIDATION_ERROR / FIELD_NOT_EDITABLE / INVALID_STAGE_TRANSITION / TERMINAL_OPPORTUNITY / WON_REOPEN_NOT_ALLOWED | 纠正请求或显示禁止操作 |
| 422 | EVIDENCE_INVALID / EVIDENCE_CURRENCY_MISMATCH / APPROVAL_BASIS_REQUIRED / CLOSE_REASON_REQUIRED / RELATIONSHIP_MISMATCH | 补充/修正业务资料 |
| 429 | RATE_LIMITED | 遵循Retry-After |
| 502 | AI_OUTPUT_INVALID / AI_PROVIDER_UNAVAILABLE | 任务失败详情；可显式重新生成，不能切Mock |
| 504 | AI_TIMEOUT / PARSE_TIMEOUT | 在Job中记录明确失败，用户有限重试 |
| 503 | DEPENDENCY_UNAVAILABLE / KNOWLEDGE_UNAVAILABLE / KNOWLEDGE_DISABLED / FEATURE_NOT_ENABLED / STORAGE_UNAVAILABLE | 保留草稿，恢复后重试 |
| 500 | INTERNAL_ERROR | request_id供诊断，不显示堆栈 |

异步任务已经返回202后，模型/解析错误体现在Job.error，不能后来改变原HTTP响应；同步入口前置失败才直接返回对应5xx。Job.result和资源详情保存mode及版本，前端不得用HTTP202显示“处理成功”。

## 11. 契约验收

从以上schema生成并审核OpenAPI；每个端点至少覆盖表内关键场景、通用认证/422，以及V/K/T相应的冲突/重放。契约测试验证实际响应不多暴露字段。日期、Decimal、未知字段、过滤与排序、跨对象关联、删除引用、角色降级后的旧建议均加入矩阵。后端真实MySQL测试通过后，前端再验证错误code映射；禁止只有成功截图而没有业务拒绝路径。

## 12. 金额与能力的补充契约

### Q04—Q06冻结补充（设计契约，未实现）

- 核验后端先验证有效身份、M角色及对象/操作权限；无权403 FORBIDDEN，有权但submitted_by等于当前身份则403 EVIDENCE_REVIEWER_CONFLICT（VERIFY/REJECT均适用），版本冲突409 VERSION_CONFLICT。仅PENDING可review；成功记录reviewed_by/reviewed_at、status=VERIFIED或REJECTED、verification_note、审批依据及审计，证据version+1。失败不改变任何记录；不能通过客户端传reviewed_by、VERIFIED或布尔字段绕过。
- 商机预计amount省略/null允许，"0.00"为已知零；负值、数值类型、超精度、超范围金额及非法/空币种均422 VALIDATION_ERROR，details.fields定位字段；证据amount必须非空且>0。商机/证据币种省略默认CNY（不推断继承商机币种），显式null/非白名单拒绝；证据与商机不同422 EVIDENCE_CURRENCY_MISMATCH。提交、核验、WON均复检；预计和实际不同无需报错。所有计算Decimal、ROUND_HALF_UP到分，无自动换汇。
- WON仅transitions的evidence_id选定一份；可保留多候选，上传/核验均不替换选择。无证据、PENDING/REJECTED、非该商机、无效类型、实际<=0或未通过职责分离核验均422 EVIDENCE_INVALID；非法type输入为422 VALIDATION_ERROR。actual_amount/actual_currency、close_evidence_id均不接受普通写入，不累加多份证据。
- 重复选定遵循现有命令契约：仍有权限时，同键同body重放原200；同键改evidence_id返回409 IDEMPOTENCY_KEY_REUSED。不同键必须先检查expected_version，旧版本409 VERSION_CONFLICT；最新版本再次关闭/更换已选证据返回422 TERMINAL_OPPORTUNITY，包含相同证据的重复选择。并发不同证据仅一请求成功，另一409；不增设独立选择入口，也不静默替换。
- probability是只读整数百分比：PROPOSAL_SUBMITTED=20、NEGOTIATION=60、FOLLOW_UP=40、WON=100、LOST=0。创建/PATCH携带probability（即使等于正确值）或其他派生金额字段统一422 FIELD_NOT_EDITABLE；合法转换由后端集中映射及数据库CHECK保证。AI建议/执行请求试图改probability同样422 FIELD_NOT_EDITABLE；Provider输出包含该非法提议则Schema校验失败，Job.error=AI_OUTPUT_INVALID，不生成可执行草稿。Q07其他字段白名单仍待批准。映射是固定业务配置，不是历史数据校准预测；amount未知时weighted_amount仍null。
- OTHER_APPROVED类型已批准，但Q05-A审批责任/步骤未批准。最小提案为approval_basis必填并记录批准人/时间/决定引用，review时核对并审计；未明确配置审批规则时，该类型核验/关闭建议返回409 OTHER_APPROVAL_POLICY_PENDING（不重试，先确认政策），允许保存PENDING候选。该门禁及具体审批方案仍须Q05-A确认，不能据此宣称其他依据已获批准。合同/PO不受该分支限制。

创建amount省略/null均为未知，返回amount/weighted_amount=null；"0.00"为已知零，加权为"0.00"。PATCH省略保持原值，显式null清空。金额输入仍拒绝负数/浮点/超精度，实际证据金额必须>0。

PipelineView顶层known/unknown_amount_count指该币种开放商机，stages内计数指该阶段。pipeline_value/weighted_forecast及stage total_amount/weighted_amount都为预计口径，字符串或null。无记录为"0.00"，有记录全未知为null，部分未知返回已知小计和未知数量，不能无条件COALESCE抹掉未知。closed_won_actual_amount按win_from/win_to关闭窗口（与win_rate相同）及所选核验证据实际币种统计；每商机只计选中证据一次。跨币种不提供总计；未知预计金额仍计入商机数及胜率分母。

例：预计250000.00 CNY、核验证据230000.00 CNY的NEGOTIATION商机，经理以当前版本请求WON应成功；响应保留amount=250000.00、weighted_amount=250000.00，actual_amount=230000.00、actual_currency=CNY，实际成交统计增加230000.00。预计null/零亦可成交。证据未核验或实际<=0返回422 EVIDENCE_INVALID，币种不符422 EVIDENCE_CURRENCY_MISMATCH（Q05已批准），版本过期409 VERSION_CONFLICT；均无成功副作用。

M3交付会议解析与suggestions完整审核/apply/reject/abandon/regenerate/execution和jobs接口，依赖M2可靠性与core，不调用RAG/embedding。M4开放知识API，M5开放增强follow-up-suggestions；未交付模块503 FEATURE_NOT_ENABLED。knowledge关闭时知识与增强跟进生成返回503 KNOWLEDGE_DISABLED，启用但故障返回503 KNOWLEDGE_UNAVAILABLE，UI明确禁用并显示原因，不伪装空库；CRM和会议apply继续可用。已有RAG建议在来源无法复核时拒绝apply并保留草稿，不回传伪成功。MinIO故障时上传/下载503 STORAGE_UNAVAILABLE，普通CRM可用。AI_MODE是配置模式而非Compose profile，real配置缺失只禁用AI。以上503沿用ErrorEnvelope，并覆盖关闭/故障/恢复测试。
# M2.1 用户接口增量（2026-10-27）

以下路径均以 `/api/v1` 为前缀，复用统一 `{data, request_id}` / 错误响应格式，分页另带 `page`，使用 HttpOnly 会话、Origin 与写入 CSRF 检查。公开注册只检查可信 Origin，不要求已有会话。请求拒绝额外字段；邮箱与 CRM 共享格式规则，姓名去首尾空白，密码不裁剪。

| 方法/路径 | 请求/结果 | 权限 |
|---|---|---|
| POST `/auth/register` | name,email,password；202 通用受理信息，重复邮箱同响应，无 cookie | 公开；每来源 15 分钟最多 20 次 |
| GET `/users/roles` | 固定四角色说明 | ADMIN |
| GET `/users` | page,page_size(1..100),q,role,status(PENDING/ACTIVE/DISABLED/DELETED),is_active；分页 UserPublic | ADMIN |
| POST `/users` | name,email,password,role,is_active；201 已批准 UserPublic | ADMIN |
| GET `/users/{id}` | UserPublic，包括 registration_status、deleted_at | ADMIN |
| PATCH `/users/{id}` | expected_version,reason；可选 name,email,role,is_active | ADMIN |
| DELETE `/users/{id}` | JSON expected_version,reason；返回逻辑删除后 UserPublic | ADMIN |
| POST `/users/{id}/approve` | expected_version,reason,role；批准并启用 | ADMIN |
| POST `/users/{id}/restore` | expected_version,reason；已批准恢复启用，未审批恢复仍不可登录 | ADMIN |
| POST `/users/{id}/reset-password` | expected_version,reason,new_password；必须 Idempotency-Key | ADMIN |
| GET `/users/{id}/history` | page,page_size；分页白名单 USER 审计 | ADMIN |
| PATCH `/auth/profile` | expected_version,name,email,current_password；200 UserPublic，清会话 cookie | 本人 |
| POST `/auth/change-password` | current_password,new_password；204，清会话 cookie | 本人 |

密码 12..128 字符且不得全为空白，确认密码仅为前端交互。普通角色直接调用管理接口返回 403；待审批/禁用/删除用户不能登录或使用已有会话。版本冲突 409 VERSION_CONFLICT，重复邮箱管理接口 409 EMAIL_EXISTS，最后管理员保护 409 LAST_ADMIN_REQUIRED；未审批不能通过普通 PATCH 绕过审批。错误当前密码 401 WRONG_PASSWORD 与会话失效区分。

管理变更及个人变更撤销目标用户全部会话，客户端随后重新登录。密码重置同 actor、scope、key、body 重放返回原结果，不追加版本/审计；相同 key 不同内容返回 409 IDEMPOTENCY_KEY_REUSED。用户响应、日志和审计不返回密码/哈希，审计仅 ADMIN 可查。不实现邮件发送或公开密码恢复。见 [M2.1 报告](m2-users-report.md)。
