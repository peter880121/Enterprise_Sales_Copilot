# D2-A：Tavily 接入与公开查询预览

日期：2026-11-05。用户要求继续项目，明确选择 Tavily，并说明根 `.env` 已配置。供应商选择已确认；本轮完成 D2 的接入基础，不代表 D2 的网页异步执行、配额与来源获取全部交付。

## 实际完成

- 只读核对 `TAVILY_BASE_URL`、`TAVILY_API_KEY` 均已配置。现有地址是官方 MCP，不将它当 REST `/search` 地址拼接，不修改根 `.env`。
- 后端新增窄范围 Tavily 客户端，同时识别官方 MCP 与 REST 两种固定地址。MCP 执行 initialize→initialized→tools/list→仅 tavily_search；不向模型开放任意工具调用，不调用 extract/crawl/map/research。
- 固定 basic、最多 5 条、关闭 auto_parameters、生成答案、原文与图片。密钥仅进 HTTPS Authorization 头，不进 URL、查询或前端；禁止自动重定向、自动重试及静默 Mock 回退。响应最多 256 KiB，仅返回 title/url/snippet/score 白名单。
- 搜索摘要标记 `SEARCH_SNIPPET_ONLY`；不把相似度当资质认证，不抓取搜索结果链接、不写资料表/CRM，也不把搜索摘要喂给真实 LLM。
- 新增 `POST /api/v1/discovery/profiles/{id}/search-preview`：现有 Origin/CSRF、身份及空间 ACL，携带 `expected_profile_version`，过期返回 409。仅回显用户明确输入的 `public_query`，不自动复制私有画像、原文、内部价格或客户信息。不会调用 Provider。
- 发现工作区新增独立空白公开查询表单，显示完整外发内容、供应商、数量和画像版本。修改输入使旧预览失效；请求失败保留输入；晚到响应不覆盖新输入。网页搜索执行按钮明确未开放，避免在持久化去重/费用门禁未接入前产生不受控重复调用。
- 新增一次性命令行工具，要求 `--confirm-public`，只读本机 Tavily 配置，不创建数据库连接；输出写到 `.local/` 内独占 UUID 子目录，失败不覆盖旧证据、不自动再次搜索。

接口契约依据官方 [Tavily Search](https://docs.tavily.com/documentation/api-reference/endpoint/search) 与 [Tavily MCP](https://docs.tavily.com/documentation/mcp)：MCP 支持 Authorization 头和 DEFAULT_PARAMETERS；固定参数防止自动提升搜索深度。本轮真实调用通过当前配置的 MCP 地址完成。第三方服务内部处理不属于本项目可独立核验范围，不能据关闭答案参数声称外部服务绝不使用模型。

## 实际测试与证据

本轮证据目录：`.local/discovery-d2-cf50fc9220/`。只记录脱敏结果；不将私有配置、搜索生成物或历史报告纳入提交。

| 状态 | 命令/场景 | 实际结果 |
| --- | --- | --- |
| PASS | `python -B -m tools.discovery_search --query "超声 医疗器械 采购意向" --confirm-public --output-parent <本轮.local目录>` | **一次真实 Tavily MCP 搜索，5 条结果**，未写 CRM；`search-4a77da74e7a34e308853a7d7d1e5575d/request.json`、`results.json` |
| PASS | `pytest -q -p no:cacheprovider tests/test_discovery_search.py tests/test_discovery_unit.py` 初次定向回归 | 40 passed；后续补充传输层用例已包含下面最终回归，不将初次数字当最终数量 |
| PASS | `pytest -q -p no:cacheprovider -m "not integration"` | **333 passed, 144 deselected**，4.67 秒；`backend-unit-final.log`。本轮新增搜索相关测试 33 项 |
| PASS | `npm test`（frontend） | **135 passed / 11 files**；`frontend-final.log`，新增查询预览 3 项 |
| PASS | `npm run typecheck`、`npm run build`（frontend） | TypeScript 和构建通过；主 JS 498.32 kB，发现模块 20.44 kB；`typescript-final.log`、`frontend-build-final.log` |
| PASS | `ruff check .`、`ruff format --check .`（backend） | 最终静态检查通过；`ruff-final.log`、`format-final.log` |
| NOT RUN | 本轮真实 MySQL 集成、浏览器、Compose 部署、迁移比对 | 没有连接/修改数据库，没有迁移；现有 144 项集成测试明确排除，不能冒充通过。本轮没有新增模型或迁移 |
| NOT RUN | 全网页发现闭环、并发持久化去重、总费用限制、来源许可/站点白名单、网页下载安全链 | 尚未实现完整执行层，不将单次 Provider 通信测试扩大为这些验收通过 |
| DEFERRED | PDF/RAG、真实 LLM、正式商机转换、客户/联系人停用、自动清理 | 保持既有边界，不随供应商选择扩大 |

最终非数据库回归包括 MCP 固定工具与最小参数、REST 兼容、域名/协议/路径/URL 凭据拒绝、HTTP 401/429/503/302 的脱敏错误与不重试、SSE 解析、256 KiB 限制、结果字段白名单/去重/链接卫生、凭据回显拒绝、公开文本校验、预览不读取私有字段、空间拒绝及版本冲突。链接卫生检查不是 DNS 固定或完整 SSRF 验证；本轮不会自动抓取这些 URL。

一次真实调用后，补充了结果链接校验和传输层反例测试；它们通过最终离线回归，不为重复统计结果而再次产生搜索费用。没有把未知发布时间、搜索摘要或评分写成已核验采购事实。保留既有 Starlette 弃用提示，未升级依赖。

## 文件清单

新增：

- `backend/app/discovery/tavily.py`：固定目的地、MCP/REST 适配、有界响应、脱敏错误及结果白名单。
- `backend/tools/discovery_search.py`：显式确认的单次公开搜索工具，独占证据目录。
- `backend/tests/test_discovery_search.py`：协议、权限边界、传输和预览单元回归。
- `frontend/src/discovery-search-preview.tsx`、`.test.tsx`：空白公开查询预览与交互回归。
- 本报告。

修改：`backend/app/core/config.py` 增加后端 SecretStr 配置；`discovery/schemas.py` 定义公开查询；`discovery/service.py` 只读权限/版本预览；`discovery/router.py` 接入新路由；`frontend/src/discovery.tsx` 挂载预览表单；README、决策、实施计划增加本轮入口。未增加应用依赖，未改 Compose/运行权限/模型/迁移。

## 保护与部署状态

Git HEAD 仍为 `1cf537eefceb2cf2922eaa1476ac7d432bba18c3`。本轮开始记录 Git 可见文件（含未跟踪 M3/D1 源码）及根 `.env` 哈希，与最终状态比较，保护摘要见 `protection-final.json`。AGENTS.MD、根 `.env`、`.gitignore`、既有证据与历史报告保留；不暂存、提交或推送。

本轮没有向远端发送源码或 Tavily 密钥，没有改动现有 M2/M3/D1 资源；`http://localhost:1883` 仍是上一轮部署的 D1，不包含本轮查询预览。用户此前授权的是独立 D1 验收部署，本轮未扩大为携带 Tavily 凭据的 D2 远端部署。

## 后续工作

1. 明确搜索调用额度/费用上限、目标来源范围；同意联网搜索不等于授权真实 LLM 或任意网页抓取。
2. 使用独立持久化搜索任务记录冻结公开查询、确认人、额度预留、调用状态与回执；外部调用在事务外，响应丢失/超时视为可能计费，不自动重放。
3. 接入网页确认执行、服务端历史与结果查看；恢复权限/版本复检和一次执行收据，不能仅靠禁用按钮防重复计费。
4. 再进行独立 MySQL/Compose/浏览器验收；若需向服务器发送本轮源码或 Tavily 凭据，先明确本轮部署目录与资源范围。搜索结果转为候选线索需保留原始来源和人工核验，不直接写 CRM。

**结论：Tavily 真实通信与 D2-A 公开预览基础已交付；D2 网页搜索完整闭环尚未完成。**
