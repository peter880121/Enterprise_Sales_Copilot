from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from test_crm_mysql import another_owner
from test_search_runs_mysql import (
    accept,
    enabled,
    finish_synthetic_tasks,  # noqa: F401
    intent,
)

from app.auth.models import Role, User
from app.auth.security import hash_password
from app.auth.service import now
from app.crm.models import Account
from app.discovery.models import SalesProfile, SearchRun
from app.discovery.search_processor import SearchProcessor
from app.sales.models import Opportunity

pytestmark = pytest.mark.integration


def test_global_quota_serializes_distinct_users_and_profiles(api):
    headers, profile = enabled(api)
    other_id = another_owner(api[1], role=Role.SALES_MANAGER)
    with api[1].seed.transaction() as s:
        s.get(User, other_id).password_hash = hash_password(api[3])
    other = TestClient(api[0].app, raise_server_exceptions=False)
    try:
        login = other.post(
            "/api/v1/auth/login",
            headers={"Origin": "http://testserver"},
            json={"email": f"{other_id}@example.test", "password": api[3]},
        )
        assert login.status_code == 200
        other_headers = {
            "Origin": "http://testserver",
            "X-CSRF-Token": login.json()["data"]["csrf_token"],
        }
        response = other.post(
            "/api/v1/discovery/profiles",
            headers=other_headers,
            json={"name": "Synthetic other search", "product": "Synthetic", "keywords": ["public"]},
        )
        assert response.status_code == 201
        second_profile = response.json()["data"]
        with api[1].transaction() as s:
            used = s.scalar(
                select(func.count())
                .select_from(SearchRun)
                .where(
                    SearchRun.created_at >= now().replace(hour=0, minute=0, second=0, microsecond=0)
                )
            )
        api[0].app.state.settings.discovery_search_global_daily_limit = used + 1
        first = intent(api, headers, profile)
        p = other.post(
            f"/api/v1/discovery/profiles/{second_profile['id']}/search-preview",
            headers=other_headers,
            json={"expected_profile_version": 1, "public_query": "Synthetic global second"},
        )
        assert p.status_code == 200 and p.json()["data"]["web_execution_available"]
        second = {
            "expected_profile_version": 1,
            "public_query": "Synthetic global second",
            "request_token": str(uuid4()),
            "preview_token": p.json()["data"]["preview_token"],
            "confirmed_public": True,
        }
        with ThreadPoolExecutor(max_workers=2) as pool:
            a = pool.submit(accept, api, headers, profile, first)
            b = pool.submit(
                other.post,
                f"/api/v1/discovery/profiles/{second_profile['id']}/search-runs",
                headers=other_headers,
                json=second,
            )
            assert sorted([a.result().status_code, b.result().status_code]) == [202, 429]
    finally:
        other.close()


def test_changed_profile_before_dispatch_never_calls_provider(api):
    headers, profile = enabled(api)
    uid = accept(api, headers, profile, intent(api, headers, profile)).json()["data"]["id"]
    with api[1].seed.transaction() as s:
        s.get(SalesProfile, profile["id"]).version += 1
    calls = []

    class Provider:
        def __init__(self, *args):
            calls.append("constructed")

        def search(self, query):
            calls.append(query)
            return {"results": []}

    SearchProcessor(api[1], api[0].app.state.settings, provider_factory=Provider).process_one()
    data = api[0].get("/api/v1/discovery/search-runs/" + uid).json()["data"]
    assert data["status"] == "FAILED" and data["error_code"] == "SEARCH_PROFILE_CHANGED"
    assert not data["provider_attempted"] and not calls


def test_permission_revoked_during_external_call_discards_result(api):
    headers, profile = enabled(api)
    uid = accept(api, headers, profile, intent(api, headers, profile)).json()["data"]["id"]
    owner = another_owner(api[1], role=Role.SALES_MANAGER)

    class Provider:
        def __init__(self, *args):
            pass

        def search(self, query):
            with api[1].seed.transaction() as s:
                s.get(SalesProfile, profile["id"]).owner_id = owner
            return {"results": [{"title": "Synthetic private result"}]}

    SearchProcessor(api[1], api[0].app.state.settings, provider_factory=Provider).process_one()
    assert api[0].get("/api/v1/discovery/search-runs/" + uid).status_code == 403
    with api[1].transaction() as s:
        row = s.get(SearchRun, uid)
        assert (
            row.status == "FAILED"
            and row.error_code == "SOURCE_ACCESS_REVOKED"
            and row.result is None
        )


def test_success_history_pagination_and_no_crm_write(api):
    headers, profile = enabled(api)
    with api[1].transaction() as s:
        before = [
            s.scalar(select(func.count()).select_from(model)) for model in [Account, Opportunity]
        ]
    uid = accept(api, headers, profile, intent(api, headers, profile)).json()["data"]["id"]

    class Provider:
        def __init__(self, *args):
            pass

        def search(self, query):
            return {
                "provider": "TAVILY",
                "mode": "REAL",
                "results": [
                    {
                        "url": "https://example.test/notice",
                        "title": "Synthetic public notice",
                        "snippet": "Synthetic snippet",
                        "verification": "SEARCH_SNIPPET_ONLY",
                    }
                ],
                "crm_written": False,
            }

    SearchProcessor(api[1], api[0].app.state.settings, provider_factory=Provider).process_one()
    data = api[0].get("/api/v1/discovery/search-runs/" + uid).json()["data"]
    assert data["status"] == "SUCCEEDED" and len(data["result"]["results"]) == 1
    with api[1].transaction() as s:
        assert before == [
            s.scalar(select(func.count()).select_from(model)) for model in [Account, Opportunity]
        ]
    with api[1].seed.transaction() as s:
        original = s.get(SearchRun, uid)
        for _ in range(24):
            s.add(
                SearchRun(
                    id=str(uuid4()),
                    profile_id=profile["id"],
                    created_by=original.created_by,
                    request_token=str(uuid4()),
                    request_hash=b"x" * 32,
                    profile_version=1,
                    public_query="Synthetic history fixture",
                    endpoint="https://mcp.tavily.com/mcp",
                    status="SUCCEEDED",
                    provider_attempted=False,
                    result={"results": []},
                    version=1,
                    created_at=now(),
                    updated_at=now(),
                )
            )
    history = api[0].get(f"/api/v1/discovery/profiles/{profile['id']}/search-runs?page=2").json()
    assert history["page"]["total"] == 25 and len(history["data"]) == 5
    assert all("result" not in row for row in history["data"])
