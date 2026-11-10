"""Narrow Tavily transport: search only, fixed official destinations, no retries."""

import http.client
import json
import math
import re
import ssl
import time
from urllib.parse import urlsplit

from app.core.errors import AppError

MAX_BYTES = 262144
PARAMETERS = {
    "search_depth": "basic",
    "topic": "general",
    "max_results": 5,
    "auto_parameters": False,
    "include_answer": False,
    "include_raw_content": False,
    "include_images": False,
}


def destination(base):
    # Configuration cannot turn this credential-bearing client into an arbitrary HTTP fetcher.
    allowed = {
        "https://api.tavily.com": ("api.tavily.com", "/search", "REST"),
        "https://mcp.tavily.com/mcp": ("mcp.tavily.com", "/mcp/", "MCP"),
    }
    if not isinstance(base, str) or base.rstrip("/") not in allowed:
        raise AppError(503, "SEARCH_CONFIGURATION_INVALID", "搜索地址必须是官方Tavily接口。")
    return allowed[base.rstrip("/")]


def safe_url(value):
    if not isinstance(value, str) or len(value) > 2048 or any(ord(c) < 33 for c in value):
        return None
    try:
        u = urlsplit(value)
        if (
            u.scheme not in {"http", "https"}
            or not u.hostname
            or u.username is not None
            or u.password is not None
            or u.port not in {None, 80, 443}
            or "\\" in value
        ):
            return None
        import ipaddress

        try:
            if not ipaddress.ip_address(u.hostname).is_global:
                return None
        except ValueError:
            host = u.hostname.encode("idna").decode("ascii")
            if (
                "." not in host
                or host.endswith((".local", ".localhost", ".internal"))
                or host.rsplit(".", 1)[-1].isdigit()
                or any(
                    not re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?", label)
                    for label in host.split(".")
                )
            ):
                return None
        return value
    except (ValueError, UnicodeError):
        return None


def sanitize_results(data):
    if not isinstance(data, dict) or not isinstance(data.get("results"), list):
        raise AppError(502, "SEARCH_INVALID_RESPONSE", "搜索服务返回了无效结构。")
    rows, seen = [], set()
    for item in data["results"][:20]:
        if not isinstance(item, dict):
            continue
        url = safe_url(item.get("url"))
        if not url or url in seen:
            continue
        seen.add(url)
        score = item.get("score")
        rows.append(
            {
                "url": url,
                "title": item["title"][:300] if isinstance(item.get("title"), str) else "",
                "snippet": item["content"][:3000] if isinstance(item.get("content"), str) else "",
                "score": score
                if type(score) in {int, float} and math.isfinite(score) and 0 <= score <= 1
                else None,
                "verification": "SEARCH_SNIPPET_ONLY",
            }
        )
        if len(rows) == 5:
            break
    return {"provider": "TAVILY", "mode": "REAL", "results": rows, "crm_written": False}


class TavilySearch:
    def __init__(self, base, api_key, *, request=None):
        self.host, self.path, self.protocol = destination(base)
        self.key = api_key.get_secret_value() if hasattr(api_key, "get_secret_value") else api_key
        if not isinstance(self.key, str) or not self.key or any(c.isspace() for c in self.key):
            raise AppError(503, "SEARCH_NOT_CONFIGURED", "尚未配置有效的搜索凭据。")
        self.request = request or self._request
        self.session = None
        self.version = "2025-03-26"

    def _request(self, payload):
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
            "Authorization": "Bearer " + self.key,
        }
        if self.protocol == "MCP":
            headers["DEFAULT_PARAMETERS"] = json.dumps(PARAMETERS)
            if self.session:
                headers["Mcp-Session-Id"] = self.session
            headers["MCP-Protocol-Version"] = self.version
        connection = http.client.HTTPSConnection(
            self.host, timeout=12, context=ssl.create_default_context()
        )
        try:
            connection.request("POST", self.path, json.dumps(payload).encode(), headers)
            response = connection.getresponse()
            if response.status in {401, 403}:
                raise AppError(502, "SEARCH_PROVIDER_AUTH", "搜索服务认证失败，请管理员核对配置。")
            if response.status in {429, 432, 433}:
                raise AppError(503, "SEARCH_PROVIDER_LIMIT", "搜索服务限流或额度不足，未自动重试。")
            if not 200 <= response.status < 300:
                raise AppError(502, "SEARCH_PROVIDER_FAILED", "搜索服务请求失败，未自动重试。")
            session = response.getheader("Mcp-Session-Id")
            if session:
                self.session = session
            if "id" not in payload and self.protocol == "MCP":
                return {}
            body = b""
            deadline = time.monotonic() + 20
            sse = "text/event-stream" in response.getheader("Content-Type", "")
            while len(body) <= MAX_BYTES:
                if time.monotonic() >= deadline:
                    raise TimeoutError
                chunk = response.read1(min(8192, MAX_BYTES + 1 - len(body)))
                body += chunk
                if len(body) > MAX_BYTES:
                    raise AppError(502, "SEARCH_RESPONSE_TOO_LARGE", "搜索响应超过大小限制。")
                if sse:
                    for event in body.replace(b"\r\n", b"\n").split(b"\n\n")[:-1]:
                        parts = [
                            line[5:].lstrip()
                            for line in event.splitlines()
                            if line.startswith(b"data:")
                        ]
                        if parts:
                            obj = json.loads(b"\n".join(parts))
                            if isinstance(obj, dict) and obj.get("id") == payload.get("id"):
                                return obj
                if not chunk:
                    if not sse:
                        return json.loads(body)
                    break
            raise AppError(502, "SEARCH_INVALID_RESPONSE", "搜索服务返回了无效结构。")
        except AppError:
            raise
        except (TimeoutError, OSError, http.client.HTTPException):
            raise AppError(
                504, "SEARCH_OUTCOME_UNKNOWN", "搜索响应未确认，可能已计费；未自动重试。"
            ) from None
        except (ValueError, UnicodeError):
            raise AppError(502, "SEARCH_INVALID_RESPONSE", "搜索服务返回了无效结构。") from None
        finally:
            connection.close()

    def rpc(self, method, params, request_id=None):
        payload = {"jsonrpc": "2.0", "method": method, "params": params}
        if request_id is not None:
            payload["id"] = request_id
        reply = self.request(payload)
        if request_id is None:
            return {}
        if not isinstance(reply, dict) or reply.get("id") != request_id or "error" in reply:
            raise AppError(502, "SEARCH_PROTOCOL_FAILED", "搜索协议响应失败。")
        result = reply.get("result")
        if not isinstance(result, dict):
            raise AppError(502, "SEARCH_INVALID_RESPONSE", "搜索服务返回了无效结构。")
        return result

    def initialize(self):
        result = self.rpc(
            "initialize",
            {
                "protocolVersion": self.version,
                "capabilities": {},
                "clientInfo": {"name": "esc-discovery", "version": "1"},
            },
            1,
        )
        if result.get("protocolVersion") not in {"2024-11-05", "2025-03-26", "2025-06-18"}:
            raise AppError(502, "SEARCH_PROTOCOL_FAILED", "搜索协议版本尚不支持。")
        self.version = result["protocolVersion"]
        self.rpc("notifications/initialized", {})

    def search(self, public_query):
        if (
            not isinstance(public_query, str)
            or not 3 <= len(public_query.strip()) <= 200
            or any(ord(c) < 32 for c in public_query)
        ):
            raise AppError(422, "INVALID_PUBLIC_QUERY", "公开查询需为3—200字符的单行文本。")
        query = public_query.strip()
        if self.protocol == "REST":
            data = self.request({"query": query, **PARAMETERS})
        else:
            self.initialize()
            tools = self.rpc("tools/list", {}, 2).get("tools", [])
            if not isinstance(tools, list):
                raise AppError(502, "SEARCH_INVALID_RESPONSE", "搜索服务返回了无效结构。")
            tool = next(
                (t for t in tools if isinstance(t, dict) and t.get("name") == "tavily_search"), None
            )
            if tool is None:
                raise AppError(502, "SEARCH_TOOL_UNAVAILABLE", "搜索工具不可用。")
            schema = tool.get("inputSchema")
            properties = schema.get("properties") if isinstance(schema, dict) else None
            if not isinstance(properties, dict) or "query" not in properties:
                raise AppError(502, "SEARCH_INVALID_RESPONSE", "搜索工具缺少受支持的输入结构。")
            # Also applied as documented DEFAULT_PARAMETERS, never request answer/extract/crawl.
            arguments = {"query": query, **{k: v for k, v in PARAMETERS.items() if k in properties}}
            result = self.rpc("tools/call", {"name": "tavily_search", "arguments": arguments}, 3)
            if result.get("isError"):
                raise AppError(502, "SEARCH_TOOL_FAILED", "搜索工具执行失败，未自动重试。")
            data = result.get("structuredContent")
            if not isinstance(data, dict) or "results" not in data:
                content = result.get("content")
                if not isinstance(content, list):
                    raise AppError(502, "SEARCH_INVALID_RESPONSE", "搜索服务返回了无效结构。")
                texts = [
                    part["text"]
                    for part in content
                    if isinstance(part, dict)
                    and part.get("type") == "text"
                    and isinstance(part.get("text"), str)
                ]
                try:
                    data = json.loads("\n".join(texts))
                except ValueError:
                    raise AppError(
                        502, "SEARCH_INVALID_RESPONSE", "搜索结果不是可核验的结构化数据。"
                    ) from None
        cleaned = sanitize_results(data)
        if self.key in json.dumps(cleaned):
            raise AppError(502, "SEARCH_UNSAFE_RESPONSE", "搜索响应包含凭据，拒绝返回。")
        return cleaned
