from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from uuid import uuid4

import pytest
from pydantic import SecretStr
from sqlalchemy import event, func, select
from test_crm_mysql import another_owner, signed_in
from test_discovery_mysql import setup

from app.auth.models import Role
from app.auth.service import now
from app.core.errors import AppError
from app.crm.models import AuditEvent
from app.discovery.models import SalesProfile, SearchGuard, SearchRun
from app.discovery.search_processor import SearchProcessor

pytestmark = pytest.mark.integration


@pytest.fixture(autouse=True)
def finish_synthetic_tasks(api):
    began = now()
    yield
    # Fixture identity, only this test's new synthetic tasks; retain rows, never dispatch leftovers.
    with api[1].seed.transaction() as s:
        for row in s.scalars(
            select(SearchRun).where(
                SearchRun.created_at >= began, SearchRun.status.in_(["QUEUED", "RUNNING"])
            )
        ):
            row.status = "FAILED"
            row.error_code = "TEST_FIXTURE_FINISHED"
            row.lease_token = row.lease_until = None
            row.completed_at = now()


def enabled(api, *, visibility="PRIVATE"):
    settings = api[0].app.state.settings
    settings.discovery_search_enabled = True
    settings.discovery_search_user_daily_limit = 10
    settings.discovery_search_global_daily_limit = 1000
    settings.tavily_api_key = SecretStr("synthetic-not-a-real-provider-key")
    return setup(api, visibility)


def preview(api, headers, profile, query="Synthetic public procurement"):
    response = api[0].post(
        f"/api/v1/discovery/profiles/{profile['id']}/search-preview",
        headers=headers,
        json={"expected_profile_version": profile["version"], "public_query": query},
    )
    assert response.status_code == 200, response.text
    return response.json()["data"]


def intent(api, headers, profile, query="Synthetic public procurement"):
    data = preview(api, headers, profile, query)
    assert data["web_execution_available"]
    return {
        "expected_profile_version": profile["version"],
        "public_query": query,
        "request_token": str(uuid4()),
        "preview_token": data["preview_token"],
        "confirmed_public": True,
    }


def accept(api, headers, profile, body):
    return api[0].post(
        f"/api/v1/discovery/profiles/{profile['id']}/search-runs", headers=headers, json=body
    )


def test_concurrent_same_request_reserves_one_quota_and_one_audit(api):
    headers, profile = enabled(api)
    body = intent(api, headers, profile)
    with ThreadPoolExecutor(max_workers=4) as pool:
        responses = list(pool.map(lambda _: accept(api, headers, profile, body), range(4)))
    assert all(r.status_code == 202 for r in responses)
    assert len({r.json()["data"]["id"] for r in responses}) == 1
    uid = responses[0].json()["data"]["id"]
    with api[1].transaction() as s:
        assert (
            s.scalar(
                select(func.count())
                .select_from(SearchRun)
                .where(SearchRun.request_token == body["request_token"])
            )
            == 1
        )
        assert (
            s.scalar(
                select(func.count())
                .select_from(AuditEvent)
                .where(AuditEvent.entity_id == uid, AuditEvent.action == "SEARCH_ACCEPTED")
            )
            == 1
        )
    assert (
        accept(
            api, headers, profile, body | {"public_query": "Changed public procurement"}
        ).status_code
        == 409
    )
    # Expired preview does not prevent safe readback of an already accepted receipt.
    assert (
        accept(api, headers, profile, body | {"preview_token": "1:" + "0" * 64}).status_code == 202
    )


def test_concurrent_quota_exhaustion_is_serialized_and_retry_does_not_reserve_again(api):
    headers, profile = enabled(api)
    api[0].app.state.settings.discovery_search_user_daily_limit = 1
    first, second = intent(api, headers, profile), intent(api, headers, profile)
    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(lambda b: accept(api, headers, profile, b), [first, second]))
    assert sorted(r.status_code for r in responses) == [202, 429]
    body = [first, second][next(i for i, r in enumerate(responses) if r.status_code == 202)]
    assert accept(api, headers, profile, body).status_code == 202


@pytest.mark.parametrize("role", [Role.SALES_REP, Role.SALES_MANAGER, Role.ADMIN, Role.READ_ONLY])
def test_private_search_cannot_be_read_or_started_by_an_ungranted_actor(api, role):
    headers, profile = enabled(api)
    body = intent(api, headers, profile)
    response = accept(api, headers, profile, body)
    uid = response.json()["data"]["id"]
    owner = another_owner(api[1], role=Role.SALES_MANAGER)
    with api[1].seed.transaction() as s:
        s.get(SalesProfile, profile["id"]).owner_id = owner
    other = signed_in(api, role)
    assert api[0].get("/api/v1/discovery/search-runs/" + uid).status_code == 403
    assert api[0].get(f"/api/v1/discovery/profiles/{profile['id']}/search-runs").status_code == 403
    assert accept(api, other, profile, body | {"request_token": str(uuid4())}).status_code == 403


def test_disabled_search_and_changed_preview_cannot_create_a_task(api):
    headers, profile = enabled(api)
    body = intent(api, headers, profile)
    assert (
        accept(api, headers, profile, body | {"public_query": "Other public query"}).status_code
        == 409
    )
    api[0].app.state.settings.discovery_search_enabled = False
    assert accept(api, headers, profile, body).status_code == 503
    with api[1].transaction() as s:
        assert (
            s.scalar(
                select(func.count())
                .select_from(SearchRun)
                .where(SearchRun.request_token == body["request_token"])
            )
            == 0
        )


def test_unknown_provider_outcome_is_not_replayed_and_has_no_results(api):
    headers, profile = enabled(api)
    query = "Synthetic public outcome " + uuid4().hex
    response = accept(api, headers, profile, intent(api, headers, profile, query))
    uid = response.json()["data"]["id"]
    calls = []

    class Provider:
        def __init__(self, *args):
            pass

        def search(self, query):
            calls.append(query)
            raise AppError(504, "SEARCH_OUTCOME_UNKNOWN", "Synthetic response lost")

    worker = SearchProcessor(api[1], api[0].app.state.settings, provider_factory=Provider)
    for _ in range(100):
        current = api[0].get("/api/v1/discovery/search-runs/" + uid).json()["data"]
        if current["status"] == "OUTCOME_UNKNOWN":
            break
        worker.process_one()
    assert current["status"] == "OUTCOME_UNKNOWN" and current["result"] is None
    assert current["may_have_been_charged"]
    for _ in range(5):
        worker.process_one()
    assert calls.count(query) == 1
    with api[1].transaction() as s:
        assert s.get(SearchRun, uid).status == "OUTCOME_UNKNOWN"


def test_expired_dispatched_claim_is_terminal_and_late_result_is_discarded(api):
    headers, profile = enabled(api)
    uid = accept(api, headers, profile, intent(api, headers, profile)).json()["data"]["id"]
    worker = SearchProcessor(api[1], api[0].app.state.settings)
    claim = None
    for _ in range(100):
        item = worker.claim()
        if item and item.get("id") == uid:
            claim = item
            break
    assert claim
    assert worker.dispatch(claim)
    with api[1].transaction() as s:
        s.get(SearchRun, uid, with_for_update=True).lease_until = now() - timedelta(seconds=1)
    assert not worker.publish(claim, {"results": []})
    for _ in range(100):
        worker.claim()
        with api[1].transaction() as s:
            if s.get(SearchRun, uid).status == "OUTCOME_UNKNOWN":
                break
    assert not worker.publish(claim, {"results": []})


def test_accept_audit_failure_rolls_back_task_and_quota_guard(api):
    headers, profile = enabled(api)
    body = intent(api, headers, profile)
    with api[1].transaction() as s:
        before = s.get(SearchGuard, 1).version

    def reject_audit(mapper, connection, target):
        if target.action == "SEARCH_ACCEPTED":
            target.actor_id = str(uuid4())  # Real FK rejection, not a fake transaction.

    event.listen(AuditEvent, "before_insert", reject_audit)
    try:
        assert accept(api, headers, profile, body).status_code >= 400
    finally:
        event.remove(AuditEvent, "before_insert", reject_audit)
    with api[1].transaction() as s:
        assert s.get(SearchGuard, 1).version == before
        assert (
            s.scalar(
                select(func.count())
                .select_from(SearchRun)
                .where(SearchRun.request_token == body["request_token"])
            )
            == 0
        )
