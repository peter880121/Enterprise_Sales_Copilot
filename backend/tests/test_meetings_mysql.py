from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from uuid import uuid4

import pytest
from sqlalchemy import func, select
from test_crm_mysql import another_owner, signed_in
from test_sales_mysql import setup_opportunity

from app.ai import MockProvider
from app.auth.models import Role, User
from app.auth.service import now
from app.crm.models import AuditEvent
from app.meetings.models import AIRun, Job, MeetingAnalysis, Suggestion
from app.meetings.processor import MeetingProcessor
from app.sales.models import Opportunity

pytestmark = pytest.mark.integration


def submit(api):
    headers, opportunity = setup_opportunity(api)
    opportunity = api[0].get(f"/api/v1/opportunities/{opportunity['id']}").json()["data"]
    body = {
        "expected_opportunity_version": 1,
        "meeting_text": "需求：合成报表\n预算：未明确金额",
        "request_token": str(uuid4()),
    }
    response = api[0].post(
        f"/api/v1/opportunities/{opportunity['id']}/meeting-analyses", headers=headers, json=body
    )
    assert response.status_code == 202
    return headers, opportunity, body, response.json()["data"]


def processor(api, provider=None):
    return MeetingProcessor(api[1], api[0].app.state.settings, provider)


def finish(api, accepted, worker=None):
    worker = worker or processor(api)
    for _ in range(100):
        state = api[0].get(f"/api/v1/jobs/{accepted['job_id']}").json()["data"]["status"]
        if state in {"FAILED", "SUCCEEDED"}:
            break
        assert worker.process_one()
    assert state in {"FAILED", "SUCCEEDED"}
    return api[0].get(f"/api/v1/meeting-analyses/{accepted['resource_id']}").json()["data"]


def test_durable_generation_idempotency_and_zero_crm_mutations(api):
    headers, opportunity, body, accepted = submit(api)
    path = f"/api/v1/opportunities/{opportunity['id']}/meeting-analyses"
    assert (
        api[0].post(path, headers=headers, json=body).json()["data"]["job_id"] == accepted["job_id"]
    )
    changed = api[0].post(
        path, headers=headers, json={**body, "meeting_text": "different synthetic"}
    )
    assert (
        changed.status_code == 409 and changed.json()["error"]["code"] == "IDEMPOTENCY_KEY_REUSED"
    )
    data = finish(api, accepted)
    assert data["mode"] == "MOCK" and data["suggestion"]["status"] == "DRAFT"
    assert data["result"]["proposed_changes"] == [] and data["suggestion"]["expires_at"] is None
    assert api[0].get(f"/api/v1/opportunities/{opportunity['id']}").json()["data"] == opportunity
    with api[1].transaction() as session:
        assert (
            session.scalar(
                select(func.count()).select_from(Job).where(Job.id == accepted["job_id"])
            )
            == 1
        )
        run = session.scalar(select(AIRun).where(AIRun.job_id == accepted["job_id"]))
        assert run.status == "SUCCEEDED" and run.mode == "MOCK"
    assert (
        api[0]
        .post(f"/api/v1/suggestions/{data['suggestion']['id']}/apply", headers=headers, json={})
        .status_code
        == 422
    )


@pytest.mark.parametrize("role", [Role.SALES_REP, Role.READ_ONLY])
def test_crm_visibility_does_not_open_private_notes_or_drafts(api, role):
    manager_headers, opportunity, body, accepted = submit(api)
    data = finish(api, accepted)
    other = another_owner(api[1])
    assert (
        api[0]
        .post(
            f"/api/v1/opportunities/{opportunity['id']}/assign-owner",
            headers={**manager_headers, "Idempotency-Key": str(uuid4())},
            json={"expected_version": 1, "owner_id": other, "reason": "Synthetic reassignment"},
        )
        .status_code
        == 200
    )
    headers = signed_in(api, role)
    assert api[0].get(f"/api/v1/opportunities/{opportunity['id']}").status_code == 200
    for path in [
        f"/meeting-analyses/{accepted['resource_id']}",
        f"/jobs/{accepted['job_id']}",
        f"/suggestions/{data['suggestion']['id']}",
        f"/opportunities/{opportunity['id']}/meeting-analyses",
    ]:
        assert api[0].get("/api/v1" + path).status_code == 403
    assert (
        api[0]
        .post(
            f"/api/v1/opportunities/{opportunity['id']}/meeting-analyses",
            headers=headers,
            json={**body, "request_token": str(uuid4())},
        )
        .status_code
        == 403
    )


def test_owner_rep_can_access_but_nonowner_rep_cannot(api):
    headers, opportunity = setup_opportunity(api)
    # Role changes do not transfer ownership of the fixture user's opportunity.
    headers = signed_in(api, Role.SALES_REP)
    response = api[0].post(
        f"/api/v1/opportunities/{opportunity['id']}/meeting-analyses",
        headers=headers,
        json={
            "expected_opportunity_version": 1,
            "meeting_text": "合成",
            "request_token": str(uuid4()),
        },
    )
    assert response.status_code == 202
    assert (
        api[0].get("/api/v1/meeting-analyses/" + response.json()["data"]["resource_id"]).status_code
        == 200
    )
    finish(api, response.json()["data"])


@pytest.mark.parametrize("action", ["reject", "abandon"])
def test_draft_review_idempotency_cas_and_no_business_writes(api, action):
    headers, opportunity, _, accepted = submit(api)
    data = finish(api, accepted)
    draft = data["suggestion"]
    path = f"/api/v1/suggestions/{draft['id']}/{action}"
    body = {"expected_version": draft["version"], "reason": "Synthetic reviewed only"}
    write = {**headers, "Idempotency-Key": str(uuid4())}
    response = api[0].post(path, headers=write, json=body)
    assert response.status_code == 200
    assert api[0].post(path, headers=write, json=body).json()["data"] == response.json()["data"]
    assert (
        api[0]
        .post(path, headers={**headers, "Idempotency-Key": str(uuid4())}, json=body)
        .status_code
        == 409
    )
    assert api[0].get(f"/api/v1/opportunities/{opportunity['id']}").json()["data"] == opportunity


def test_invalid_output_fails_and_never_produces_draft(api):
    _, _, _, accepted = submit(api)

    class Invalid(MockProvider):
        def structured_generate(self, text):
            return {"probability": 100}

    data = finish(api, accepted, processor(api, Invalid()))
    assert data["status"] == "FAILED" and data["result"] is None
    assert data["suggestion"]["status"] == "FAILED"
    assert (
        api[0].get("/api/v1/jobs/" + accepted["job_id"]).json()["data"]["error_code"]
        == "AI_OUTPUT_INVALID"
    )


def test_expired_worker_lease_cannot_publish_late_result(api):
    _, _, _, accepted = submit(api)
    worker = processor(api)
    claim = None
    for _ in range(100):
        candidate = worker.claim()
        assert candidate
        if candidate["job_id"] == accepted["job_id"]:
            claim = candidate
            break
        worker.publish(candidate, None, "SYNTHETIC_SKIP", False, 0)
    with api[1].seed.transaction() as session:
        session.get(Job, accepted["job_id"]).lease_until = now() - timedelta(seconds=1)
    newer = worker.claim()
    assert newer["job_id"] == accepted["job_id"] and newer["token"] != claim["token"]
    raw = MockProvider().structured_generate("需求：合成报表\n预算：未明确金额")
    assert worker.publish(newer, raw, None, False, 1)
    assert not worker.publish(claim, raw, None, False, 2)
    with api[1].transaction() as session:
        assert session.get(AIRun, claim["run_id"]).status == "DISCARDED"
        assert session.get(Job, accepted["job_id"]).status == "SUCCEEDED"


def test_two_workers_claim_each_job_at_most_once(api):
    _, _, _, accepted = submit(api)
    with ThreadPoolExecutor(max_workers=2) as executor:
        claims = list(executor.map(lambda _: processor(api).claim(), range(2)))
    own = [c for c in claims if c and c["job_id"] == accepted["job_id"]]
    assert len(own) == 1
    for claim in claims:
        if claim:
            processor(api).publish(claim, None, "SYNTHETIC_FINISH", False, 0)


def test_real_mode_never_falls_back_to_mock(api):
    headers, opportunity = setup_opportunity(api)
    api[0].app.state.settings.ai_mode = "real"
    response = api[0].post(
        f"/api/v1/opportunities/{opportunity['id']}/meeting-analyses",
        headers=headers,
        json={
            "expected_opportunity_version": 1,
            "meeting_text": "合成",
            "request_token": str(uuid4()),
        },
    )
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "AI_PROVIDER_UNAVAILABLE"


def test_review_audit_failure_rolls_back_draft_and_leaves_crm_unchanged(api, monkeypatch):
    headers, opportunity, _, accepted = submit(api)
    data = finish(api, accepted)

    def fail(*args, **kwargs):
        raise RuntimeError("synthetic audit failure")

    monkeypatch.setattr("app.meetings.service.audit", fail)
    response = api[0].post(
        f"/api/v1/suggestions/{data['suggestion']['id']}/reject",
        headers={**headers, "Idempotency-Key": str(uuid4())},
        json={"expected_version": data["suggestion"]["version"], "reason": "Synthetic rollback"},
    )
    assert response.status_code == 500
    with api[1].transaction() as session:
        row = session.get(Suggestion, data["suggestion"]["id"])
        assert row.status == "DRAFT" and row.version == data["suggestion"]["version"]
        assert session.get(Opportunity, opportunity["id"]).version == 1


def test_worker_rechecks_permission_before_publishing(api):
    _, _, _, accepted = submit(api)
    worker = processor(api)
    claim = worker.claim()
    assert claim["job_id"] == accepted["job_id"]
    with api[1].seed.transaction() as session:
        session.get(User, claim["actor_id"]).role = Role.READ_ONLY
    raw = MockProvider().structured_generate("需求：合成报表\n预算：未明确金额")
    worker.publish(claim, raw, None, False, 1)
    with api[1].transaction() as session:
        assert session.get(Job, claim["job_id"]).error_code == "AI_PERMISSION_CHANGED"
        assert session.get(MeetingAnalysis, accepted["resource_id"]).result is None


def test_timeout_retries_are_bounded_without_fake_success(api):
    _, _, _, accepted = submit(api)

    class Timeout(MockProvider):
        def structured_generate(self, text):
            raise TimeoutError("synthetic secret must never be stored")

    worker = processor(api, Timeout())
    for attempt in range(3):
        assert worker.process_one()
        with api[1].seed.transaction() as session:
            row = session.get(Job, accepted["job_id"])
            assert row.attempts == attempt + 1
            if attempt < 2:
                assert row.status == "QUEUED"
                row.available_at = now() - timedelta(seconds=1)
    with api[1].transaction() as session:
        row = session.get(Job, accepted["job_id"])
        assert row.status == "FAILED" and row.error_code == "AI_TIMEOUT"
        assert (
            session.scalar(select(func.count()).select_from(AIRun).where(AIRun.job_id == row.id))
            == 3
        )


@pytest.mark.parametrize("error", [None, "AI_OUTPUT_INVALID"])
def test_repeated_publish_preserves_terminal_run_and_business_records(api, error):
    _, opportunity, body, accepted = submit(api)
    worker = processor(api)
    claim = worker.claim()
    assert claim["job_id"] == accepted["job_id"]
    raw = None if error else MockProvider().structured_generate(body["meeting_text"])
    assert worker.publish(claim, raw, error, False, 10)
    with api[1].transaction() as session:
        run = session.get(AIRun, claim["run_id"])
        baseline = {column.name: getattr(run, column.name) for column in AIRun.__table__.columns}
        draft = session.scalar(
            select(Suggestion).where(Suggestion.analysis_id == accepted["resource_id"])
        )
        version = draft.version
        audit_count = session.scalar(select(func.count()).select_from(AuditEvent))
    assert not worker.publish(claim, raw, error, False, 999)
    with api[1].transaction() as session:
        current = session.get(AIRun, claim["run_id"])
        assert {
            column.name: getattr(current, column.name) for column in AIRun.__table__.columns
        } == baseline
        assert session.get(Suggestion, draft.id).version == version
        assert session.scalar(select(func.count()).select_from(AuditEvent)) == audit_count
        assert session.get(Opportunity, opportunity["id"]).version == 1


def test_lease_recovery_finalizes_orphan_run_before_late_publish(api):
    _, _, body, accepted = submit(api)
    worker = processor(api)
    old = worker.claim()
    assert old["job_id"] == accepted["job_id"]
    with api[1].seed.transaction() as session:
        session.get(Job, accepted["job_id"]).lease_until = now() - timedelta(seconds=1)
    replacement = worker.claim()
    assert replacement["job_id"] == old["job_id"]
    with api[1].transaction() as session:
        run = session.get(AIRun, old["run_id"])
        assert run.status == "DISCARDED" and run.error_code == "LEASE_EXPIRED"
        assert run.ended_at is not None and run.latency_ms is None
        ended = run.ended_at
    raw = MockProvider().structured_generate(body["meeting_text"])
    assert worker.publish(replacement, raw, None, False, 10)
    assert not worker.publish(old, raw, None, False, 900)
    with api[1].transaction() as session:
        run = session.get(AIRun, old["run_id"])
        assert run.error_code == "LEASE_EXPIRED" and run.ended_at == ended
