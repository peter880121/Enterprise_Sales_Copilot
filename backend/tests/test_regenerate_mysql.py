from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from uuid import uuid4

import pytest
from sqlalchemy import event, func, select
from test_crm_mysql import another_owner, signed_in
from test_execution_mysql import apply, draft
from test_meetings_mysql import finish, processor

from app.ai import MockProvider
from app.auth.models import Role
from app.crm.models import AuditEvent
from app.meetings.models import Job, MeetingAnalysis, Suggestion
from app.sales.models import Opportunity

pytestmark = pytest.mark.integration


def regenerate(api, headers, analysis, *, token=None, **changes):
    body = {
        "expected_version": analysis["suggestion"]["version"],
        "expected_opportunity_version": analysis["base_opportunity_version"],
        "request_token": token or str(uuid4()),
        **changes,
    }
    return api[0].post(
        f"/api/v1/suggestions/{analysis['suggestion']['id']}/regenerate", headers=headers, json=body
    )


def counts(api, oid):
    with api[1].transaction() as s:
        return [
            s.scalar(select(func.count()).select_from(model).where(model.opportunity_id == oid))
            for model in [Job, MeetingAnalysis, Suggestion]
        ]


def test_regeneration_copies_source_and_rebases_without_crm_writes(api):
    headers, opp, old = draft(api, "备注：Synthetic regeneration source")
    sid = old["suggestion"]["id"]
    token = str(uuid4())
    changed = api[0].patch(
        f"/api/v1/opportunities/{opp['id']}",
        headers=headers,
        json={"expected_version": 1, "priority": "HIGH"},
    )
    assert changed.status_code == 200
    with api[1].transaction() as s:
        frozen = s.get(Suggestion, sid).proposed_changes
    first = regenerate(api, headers, old, token=token, expected_opportunity_version=2)
    assert first.status_code == 202
    child = finish(api, first.json()["data"])
    assert (
        child["id"] != old["id"]
        and child["input_text"] == old["input_text"]
        and child["base_opportunity_version"] == 2
    )
    source = api[0].get(f"/api/v1/suggestions/{sid}").json()["data"]
    assert (
        source["status"] == "SUPERSEDED"
        and source["version"] == 3
        and not source["execution_enabled"]
    )
    assert source["replacement_analysis_id"] == child["id"]
    replay = regenerate(api, headers, old, token=token, expected_opportunity_version=2)
    assert replay.status_code == 202 and replay.json()["data"]["resource_id"] == child["id"]
    assert counts(api, opp["id"]) == [2, 2, 2]
    reused = regenerate(api, headers, old, token=token)
    assert reused.status_code == 409 and reused.json()["error"]["code"] == "IDEMPOTENCY_KEY_REUSED"
    with api[1].transaction() as s:
        assert s.get(Suggestion, sid).proposed_changes == frozen
        assert s.get(Opportunity, opp["id"]).version == 2
        audit = s.scalar(
            select(AuditEvent).where(
                AuditEvent.entity_id == sid, AuditEvent.action == "SUGGESTION_SUPERSEDED"
            )
        )
        assert (
            audit.actor_id == api[4] and audit.after_state["replacement_analysis_id"] == child["id"]
        )
        queued = s.scalar(
            select(AuditEvent).where(
                AuditEvent.entity_id == child["id"], AuditEvent.action == "MEETING_QUEUED"
            )
        )
        assert (
            queued.after_state["related_suggestion_id"] == sid
            and "input_text" not in queued.after_state
        )
    assert apply(api, headers, old).status_code == 409


@pytest.mark.parametrize("same_token", [True, False])
def test_concurrent_regeneration_creates_one_replacement(api, same_token):
    headers, opp, old = draft(api, "备注：Synthetic concurrent regeneration")
    barrier = Barrier(2)
    token = str(uuid4())

    def run(index):
        barrier.wait(timeout=10)
        return regenerate(api, headers, old, token=token if same_token else str(uuid4()))

    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(run, range(2)))
    assert sorted(r.status_code for r in responses) == ([202, 202] if same_token else [202, 409])
    assert counts(api, opp["id"]) == [2, 2, 2]
    if same_token:
        assert (
            responses[0].json()["data"]["resource_id"] == responses[1].json()["data"]["resource_id"]
        )


@pytest.mark.parametrize("position", [1, 2])
def test_regeneration_audit_failure_rolls_back_new_job_and_supersession(api, position):
    headers, opp, old = draft(api, "备注：Synthetic atomic regeneration")
    with api[1].transaction() as s:
        before_audits = s.scalar(select(func.count()).select_from(AuditEvent))
    calls = 0

    def fail(_mapper, _connection, target):
        nonlocal calls
        calls += 1
        if calls == position:
            target.actor_id = str(uuid4())  # Real FK rejection; no fixture privileges expanded.

    event.listen(AuditEvent, "before_insert", fail)
    try:
        response = regenerate(api, headers, old)
    finally:
        event.remove(AuditEvent, "before_insert", fail)
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "DEPENDENCY_UNAVAILABLE"
    assert counts(api, opp["id"]) == [1, 1, 1]
    with api[1].transaction() as s:
        assert s.get(Suggestion, old["suggestion"]["id"]).status == "DRAFT"
        assert s.get(Opportunity, opp["id"]).version == 1
        assert s.scalar(select(func.count()).select_from(AuditEvent)) == before_audits


@pytest.mark.parametrize("terminal", ["REJECTED", "ABANDONED", "EXECUTED"])
def test_terminal_drafts_cannot_be_regenerated(api, terminal):
    headers, opp, old = draft(api, "备注：Synthetic terminal draft")
    if terminal == "EXECUTED":
        assert apply(api, headers, old).status_code == 200
    else:
        response = api[0].post(
            f"/api/v1/suggestions/{old['suggestion']['id']}/"
            + ("reject" if terminal == "REJECTED" else "abandon"),
            headers={**headers, "Idempotency-Key": str(uuid4())},
            json={"expected_version": 2, "reason": "Synthetic review"},
        )
        assert response.status_code == 200
    response = regenerate(
        api,
        headers,
        old,
        expected_version=3,
        expected_opportunity_version=2 if terminal == "EXECUTED" else 1,
    )
    assert (
        response.status_code == 409
        and response.json()["error"]["code"] == "INVALID_SUGGESTION_STATUS"
    )
    assert counts(api, opp["id"]) == [1, 1, 1]


@pytest.mark.parametrize("role", [Role.SALES_REP, Role.READ_ONLY])
def test_regeneration_rejects_nonowner_rep_and_read_only(api, role):
    headers, opp, old = draft(api)
    other = another_owner(api[1])
    with api[1].seed.transaction() as s:
        s.get(Opportunity, opp["id"]).owner_id = other
    denied = signed_in(api, role)
    assert regenerate(api, denied, old).status_code == 403
    assert counts(api, opp["id"]) == [1, 1, 1]


@pytest.mark.parametrize("role", [Role.SALES_REP, Role.ADMIN])
def test_owner_rep_and_admin_can_regenerate(api, role):
    _, _, old = draft(api)
    assert regenerate(api, signed_in(api, role), old).status_code == 202


def test_new_generation_failure_never_revives_superseded_draft(api):
    headers, _, old = draft(api)
    accepted = regenerate(api, headers, old)
    assert accepted.status_code == 202

    class Invalid(MockProvider):
        def structured_generate(self, text):
            return {"probability": 100}

    child = finish(api, accepted.json()["data"], processor(api, Invalid()))
    assert child["status"] == "FAILED"
    assert (
        api[0].get(f"/api/v1/suggestions/{old['suggestion']['id']}").json()["data"]["status"]
        == "SUPERSEDED"
    )


def test_apply_racing_regeneration_has_one_atomic_outcome(api):
    headers, opp, old = draft(api, "备注：Synthetic race")
    barrier = Barrier(2)

    def run(index):
        barrier.wait(timeout=10)
        return apply(api, headers, old) if index == 0 else regenerate(api, headers, old)

    with ThreadPoolExecutor(max_workers=2) as pool:
        applied, generated = list(pool.map(run, range(2)))
    assert (applied.status_code, generated.status_code) in {(200, 409), (409, 202)}
    with api[1].transaction() as s:
        assert s.get(Suggestion, old["suggestion"]["id"]).status == (
            "EXECUTED" if applied.status_code == 200 else "SUPERSEDED"
        )
        assert s.get(Opportunity, opp["id"]).version == (2 if applied.status_code == 200 else 1)
    assert counts(api, opp["id"]) == ([1, 1, 1] if applied.status_code == 200 else [2, 2, 2])


def test_regeneration_rejects_stale_versions_without_creating_job(api):
    headers, opp, old = draft(api)
    for changes in [{"expected_version": 1}, {"expected_opportunity_version": 2}]:
        response = regenerate(api, headers, old, **changes)
        assert (
            response.status_code == 409 and response.json()["error"]["code"] == "VERSION_CONFLICT"
        )
    assert counts(api, opp["id"]) == [1, 1, 1]


def test_regeneration_requires_origin_and_csrf(api):
    _, opp, old = draft(api)
    assert regenerate(api, {}, old).status_code == 403
    assert counts(api, opp["id"]) == [1, 1, 1]


def test_regeneration_in_real_mode_does_not_fall_back(api):
    headers, opp, old = draft(api)
    api[0].app.state.settings.ai_mode = "real"
    response = regenerate(api, headers, old)
    assert (
        response.status_code == 503
        and response.json()["error"]["code"] == "AI_PROVIDER_UNAVAILABLE"
    )
    assert counts(api, opp["id"]) == [1, 1, 1]
