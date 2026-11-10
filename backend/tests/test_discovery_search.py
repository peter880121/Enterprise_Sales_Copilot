import json
from contextlib import contextmanager
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from app.core.errors import AppError
from app.discovery.schemas import PublicSearchPreview
from app.discovery.service import DiscoveryService
from app.discovery.tavily import PARAMETERS, TavilySearch, destination, safe_url, sanitize_results


class FakeResponse:
    def __init__(self, status=200, content=b"", content_type="application/json"):
        self.status, self.content, self.content_type = status, content, content_type

    def getheader(self, name, default=None):
        return self.content_type if name == "Content-Type" else default

    def read1(self, maximum):
        part, self.content = self.content[:maximum], self.content[maximum:]
        return part


def fake_connection(monkeypatch, response):
    calls = []

    class Connection:
        def __init__(self, *args, **kwargs):
            self.closed = False

        def request(self, method, path, body, headers):
            calls.append({"method": method, "path": path, "body": body, "headers": headers})

        def getresponse(self):
            return response

        def close(self):
            self.closed = True

    monkeypatch.setattr("app.discovery.tavily.http.client.HTTPSConnection", Connection)
    return calls


@pytest.mark.parametrize(
    "status,code",
    [
        (401, "SEARCH_PROVIDER_AUTH"),
        (429, "SEARCH_PROVIDER_LIMIT"),
        (503, "SEARCH_PROVIDER_FAILED"),
        (302, "SEARCH_PROVIDER_FAILED"),
    ],
)
def test_http_failure_is_sanitized_and_never_retried_or_redirected(monkeypatch, status, code):
    calls = fake_connection(monkeypatch, FakeResponse(status, b"synthetic-secret-key"))
    with pytest.raises(AppError) as failure:
        TavilySearch("https://api.tavily.com", "synthetic-secret-key").search(
            "Synthetic public query"
        )
    assert failure.value.code == code and len(calls) == 1
    assert "synthetic-secret-key" not in failure.value.message
    assert calls[0]["headers"]["Authorization"] == "Bearer synthetic-secret-key"
    assert b"synthetic-secret-key" not in calls[0]["body"]


def test_transport_accepts_mcp_sse_without_waiting_for_stream_close(monkeypatch):
    payload = {"jsonrpc": "2.0", "id": 1, "result": {"protocolVersion": "2025-03-26"}}
    fake_connection(
        monkeypatch,
        FakeResponse(
            content=b"data: " + json.dumps(payload).encode() + b"\n\n",
            content_type="text/event-stream",
        ),
    )
    result = TavilySearch("https://mcp.tavily.com/mcp", "synthetic-key").rpc("initialize", {}, 1)
    assert result["protocolVersion"] == "2025-03-26"


def test_transport_bounds_provider_response_before_json_parsing(monkeypatch):
    fake_connection(monkeypatch, FakeResponse(content=b"x" * 262145))
    with pytest.raises(AppError) as failure:
        TavilySearch("https://api.tavily.com", "synthetic-key").search("Synthetic public query")
    assert failure.value.code == "SEARCH_RESPONSE_TOO_LARGE"


def test_mcp_search_uses_only_approved_search_tool_and_public_query():
    calls = []

    def request(body):
        calls.append(body)
        method = body["method"]
        result = {
            "initialize": {"protocolVersion": "2025-03-26"},
            "notifications/initialized": {},
            "tools/list": {
                "tools": [
                    {
                        "name": "tavily_search",
                        "inputSchema": {
                            "properties": {"query": {}, **{key: {} for key in PARAMETERS}}
                        },
                    }
                ]
            },
            "tools/call": {
                "content": [
                    {
                        "type": "text",
                        "text": json.dumps(
                            {
                                "results": [
                                    {
                                        "title": "Synthetic public result",
                                        "url": "https://example.test/notice",
                                        "content": "Synthetic public procurement",
                                        "score": 0.5,
                                    }
                                ]
                            }
                        ),
                    }
                ]
            },
        }[method]
        return {"id": body.get("id"), "result": result}

    result = TavilySearch(
        "https://mcp.tavily.com/mcp/", "synthetic-only-api-key", request=request
    ).search("Synthetic public procurement")
    assert result["mode"] == "REAL" and not result["crm_written"]
    assert [row["method"] for row in calls] == [
        "initialize",
        "notifications/initialized",
        "tools/list",
        "tools/call",
    ]
    assert calls[-1]["params"] == {
        "name": "tavily_search",
        "arguments": {"query": "Synthetic public procurement", **PARAMETERS},
    }
    assert "synthetic-only-api-key" not in json.dumps(calls)
    assert result["results"][0]["verification"] == "SEARCH_SNIPPET_ONLY"


@pytest.mark.parametrize(
    "base",
    [
        "http://api.tavily.com",
        "https://api.tavily.com.evil.test",
        "https://api.tavily.com/search",
        "https://mcp.tavily.com/mcp?token=synthetic",
        "https://127.0.0.1/mcp",
        "https://user:synthetic@mcp.tavily.com/mcp",
    ],
)
def test_destination_rejects_unapproved_host_protocol_path_or_credentials(base):
    with pytest.raises(AppError) as failure:
        destination(base)
    assert failure.value.code == "SEARCH_CONFIGURATION_INVALID"


@pytest.mark.parametrize(
    "url",
    [
        "javascript:alert(1)",
        "http://127.1/",
        "http://127.0.0.1/",
        "https://[::1]/",
        "https://user:password@example.test/",
        "https://example.test:bogus/",
        "https://example.test:9000/",
        "https://localhost.local/",
        "https://example..test/",
        "https://example.test/\nheader",
    ],
)
def test_result_urls_reject_unsafe_link_forms_without_fetching(url):
    assert safe_url(url) is None


def test_results_are_deduplicated_bounded_whitelisted_and_not_qualification():
    data = {
        "results": [
            {
                "url": f"https://example.test/{i}",
                "title": "x" * 500,
                "content": "y" * 4000,
                "score": float("nan"),
                "raw_content": "do not return",
                "secret": "synthetic",
            }
            for i in range(10)
        ]
    }
    data["results"].insert(1, data["results"][0])
    result = sanitize_results(data)
    assert len(result["results"]) == 5
    assert all(
        len(row["title"]) == 300 and len(row["snippet"]) == 3000 and row["score"] is None
        for row in result["results"]
    )
    assert "raw_content" not in json.dumps(result) and "secret" not in json.dumps(result)


def test_rest_failure_is_not_automatically_retried_or_replaced_with_mock():
    calls = []

    def request(body):
        calls.append(body)
        raise AppError(504, "SEARCH_OUTCOME_UNKNOWN", "Synthetic timeout")

    with pytest.raises(AppError) as failure:
        TavilySearch("https://api.tavily.com", "synthetic-key", request=request).search(
            "Public synthetic"
        )
    assert failure.value.code == "SEARCH_OUTCOME_UNKNOWN" and len(calls) == 1


def test_provider_cannot_echo_api_key_into_result():
    def request(body):
        return {"results": [{"url": "https://example.test/", "content": "synthetic-secret-key"}]}

    with pytest.raises(AppError) as failure:
        TavilySearch("https://api.tavily.com", "synthetic-secret-key", request=request).search(
            "Public synthetic"
        )
    assert failure.value.code == "SEARCH_UNSAFE_RESPONSE"


@pytest.mark.parametrize("text", ["ab", " ", "abc\nprivate", "abc\x00def", "x" * 201])
def test_public_preview_rejects_invalid_query(text):
    with pytest.raises(ValidationError):
        PublicSearchPreview(expected_profile_version=1, public_query=text)


class ReadOnlyUnitOfWork:
    @contextmanager
    def transaction(self):
        yield object()


def test_preview_only_uses_explicit_public_input_not_private_profile_fields(monkeypatch, settings):
    service = DiscoveryService(ReadOnlyUnitOfWork(), settings)
    profile = SimpleNamespace(
        id="profile",
        version=7,
        product="private product",
        keywords=["private keyword"],
        regions=["private region"],
    )
    monkeypatch.setattr(service, "actor", lambda session, identity: SimpleNamespace(id="actor"))
    monkeypatch.setattr(service, "access", lambda session, actor, entity_id: profile)
    body = PublicSearchPreview(expected_profile_version=7, public_query="Synthetic public query")
    data = service.search_preview(None, profile.id, body)
    assert data["public_query"] == "Synthetic public query"
    assert not data["external_request_sent"] and not data["web_execution_available"]
    assert "private" not in json.dumps(data)
    profile.version = 8
    with pytest.raises(AppError) as failure:
        service.search_preview(None, profile.id, body)
    assert failure.value.code == "VERSION_CONFLICT"


def test_preview_preserves_space_acl_denial(monkeypatch, settings):
    service = DiscoveryService(ReadOnlyUnitOfWork(), settings)
    monkeypatch.setattr(service, "actor", lambda session, identity: SimpleNamespace(id="actor"))

    def forbidden(*args):
        raise AppError(403, "FORBIDDEN", "Synthetic private space")

    monkeypatch.setattr(service, "access", forbidden)
    with pytest.raises(AppError) as failure:
        service.search_preview(
            None,
            "private-profile",
            PublicSearchPreview(expected_profile_version=1, public_query="Synthetic public query"),
        )
    assert failure.value.status == 403
