# 商机发现 D1 API 速查

以 `docs/discovery-d1-report.md` 为实际范围。前缀 `/api/v1/discovery`；使用现有会话、Origin/CSRF 与统一错误格式。写操作拒绝 READ_ONLY。ID 为 UUID，时间采用现有 UTC 序列化，列表固定每页 20 条。D1 不调用搜索或 LLM。

| 方法/路径 | 请求 | 返回与权限 |
| --- | --- | --- |
| GET `/reviewers?q=&page=1` | 搜索/分页 | 有效经理/管理员 ID、名称、角色，不返回邮箱；供显式授权选择 |
| GET `/profiles?page=1` | 分页 | 仅可见画像；READ_ONLY 空列表 |
| GET `/profiles/{id}` | 无 | 画像、版本、授权集合；服务端 ACL |
| POST `/profiles` | name, product, keywords[], regions[], visibility, reviewer_ids[] | 201，当前用户为所有者，默认 PRIVATE |
| PATCH `/profiles/{id}` | 上述完整快照加 expected_version | 200/CAS 409；可见性不可变；仅所有者可改变授权集合 |
| GET `/profiles/{id}/materials?page=1` | 分页 | 有权限读取该空间资料者可见 |
| POST `/profiles/{id}/materials` | title, purpose, content, confirm_team_visibility, confirm_no_patient_data | 201；有空间写权限；原始哈希去重 |
| POST `/profiles/{id}/material-files` | multipart file、purpose、confirm_team_visibility、confirm_no_patient_data | UTF-8 TXT/MD；仅本地小文本原件，限制见下文 |
| GET `/materials/{id}` | 无 | ACL 保护的文本、原始 sha256、text_sha256；无公共下载地址 |
| POST `/profiles/{id}/runs` | expected_profile_version, material_ids[], request_token(UUID) | 202；同用户同 token 同意图返回原任务，意图冲突 409 |
| GET `/runs/{id}` | 无 | 实际任务状态、版本、错误码、结果数；重新检查空间权限 |
| GET `/leads?page=1&q=&status=` | 分页/搜索/状态 | 列表与计数同 SQL 权限范围；READ_ONLY 仅发布摘要 |
| GET `/leads/{id}` | 无 | ACL 允许的证据/评审详情，或只读摘要 |
| PATCH `/leads/{id}` | expected_version, status, reason, publish_summary | CAS；只能按合法评审路径，发布仅 TEAM/QUALIFIED |
| POST `/leads/{id}/account-preview` | expected_version，加 existing_account_id 或 new_account_name 二选一 | 返回绑定版本/身份/目标的 preview_hash 及客户名称/负责人；不写 CRM |
| POST `/leads/{id}/link-account` | 预览请求加 preview_hash、confirmed_shared_crm=true；`Idempotency-Key` 头 | 同事务客户关联与永久回执；同意图重试返回原结果；不创建商机 |

上传字段 `purpose` 为 `SELLER_CAPABILITY` 或 `BUYER_DEMAND`；资料内容非空、无 NUL，最多 64 KiB/50,000 字符。文件后缀 `.txt/.md`，允许普通文本/Markdown/octet-stream MIME，严格 UTF-8 解码；整个请求体上限 128 KiB，超限 413。患者数据确认必须 true；TEAM 上传的共享确认也必须 true。原始字节与去 BOM 后文本分别保留哈希，引文位置按后者 Unicode 字符定位。

资料标签示例（合成数据）：

```text
采购人：示例医院
项目：示例超声采购
采购代理：示例代理机构
品类：超声
公告类型：采购意向
预算：120万元 人民币
截止时间：2026-12-01T17:00:00+08:00
地区：示例地区
```

采购人/项目必填。重复别名、空值和多项目资料报错，不猜测缺失事实。公告类型支持采购意向、采购/招标公告、更正、终止、中标、企业动态，其他保留 UNKNOWN。预算仅是来源预算，不进入预计/实际成交金额；关键词命中不代表资质认证。相同来源重复运行复用冻结结果，不自动重算。

线索状态：NEW→IN_REVIEW/DISQUALIFIED；IN_REVIEW→QUALIFIED/DISQUALIFIED；QUALIFIED→DISQUALIFIED；DISQUALIFIED→IN_REVIEW。每次写入重新鉴权、版本检查和审计；不得以 UI 隐藏代替 API 权限。

主要错误：401 会话失效；403 权限/共享确认不足；404 不存在或不可访问对象；409 版本、幂等意图或已关联冲突；413 请求/资料过大；422 Schema、资料标签或关联不合法。精确业务码以 `schemas.py`、`service.py` 和 `extraction.py` 的实现为准。客户确认重试必须保留原意图、版本、preview_hash 和键；收到成功后不得因刷新失败自动重复 POST。
