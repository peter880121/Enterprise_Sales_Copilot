from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from threading import Barrier
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event, func, select
from test_crm_mysql import another_owner, signed_in
from test_meetings_mysql import finish
from test_sales_mysql import setup_opportunity

from app.auth.models import Role, User
from app.auth.security import hash_password
from app.auth.service import now
from app.crm.models import AuditEvent
from app.meetings.models import MeetingAnalysis, Suggestion, SuggestionExecution
from app.meetings.proposals import propose
from app.sales.models import Activity, IdempotencyRecord, Opportunity
from app.sales.service import SalesService

pytestmark = pytest.mark.integration


def draft(api, text=None):
    headers, opp = setup_opportunity(api)
    text = text or (
        "预计金额：1500.00\n币种：USD\n优先级：HIGH\n备注：Synthetic confirmed note\n"
        f"任务：Synthetic follow-up\n任务负责人ID：{api[4]}\n任务截止：2026-12-01T16:00:00+08:00"
    )
    response = api[0].post(
        f"/api/v1/opportunities/{opp['id']}/meeting-analyses",
        headers=headers,
        json={
            "expected_opportunity_version": 1,
            "meeting_text": text,
            "request_token": str(uuid4()),
        },
    )
    assert response.status_code == 202
    analysis = finish(api, response.json()["data"])
    return headers, opp, analysis


def apply(api, headers, analysis, ids=None, key=None):
    row = analysis["suggestion"]
    return api[0].post(
        f"/api/v1/suggestions/{row['id']}/apply",
        headers={**headers, "Idempotency-Key": key or str(uuid4())},
        json={
            "expected_version": row["version"],
            "expected_opportunity_version": analysis["base_opportunity_version"],
            "selected_change_ids": ids
            if ids is not None
            else [c["id"] for c in row["proposed_changes"]],
            "confirmed": True,
        },
    )


@pytest.mark.parametrize("invalid", ["", "x" * 2001], ids=["empty", "too-long"])
def test_worker_blocks_invalid_duplicate_money_but_keeps_other_valid_proposals(api, invalid):
    _, _, analysis = draft(
        api, f"预计金额：100\n币种：USD\n预计金额：{invalid}\n备注：Synthetic valid note"
    )
    assert analysis["status"] == "SUCCEEDED"
    assert [change["kind"] for change in analysis["suggestion"]["proposed_changes"]] == ["NOTE"]
    assert analysis["result"]["limitations"]


@pytest.mark.parametrize("label", ["预计成交日期", "任务截止"])
def test_worker_reports_calendar_overflow_without_leaving_job_running(api, label):
    headers, opp = setup_opportunity(api)
    text = "备注：Synthetic valid note\n"
    text += (
        "预计成交日期：明天"
        if label == "预计成交日期"
        else f"任务：Synthetic task\n任务负责人ID：{api[4]}\n任务截止：明天 12:00"
    )
    accepted = api[0].post(
        f"/api/v1/opportunities/{opp['id']}/meeting-analyses",
        headers=headers,
        json={
            "expected_opportunity_version": 1,
            "meeting_text": text,
            "meeting_date": "9999-12-31",
            "timezone": "Asia/Hong_Kong",
            "request_token": str(uuid4()),
        },
    )
    assert accepted.status_code == 202
    analysis = finish(api, accepted.json()["data"])
    assert analysis["status"] == "SUCCEEDED" and analysis["result"]["limitations"]
    assert [change["kind"] for change in analysis["suggestion"]["proposed_changes"]] == ["NOTE"]


def test_old_ambiguous_frozen_proposal_is_rejected_without_rewriting_history(api):
    text = "预计金额：100\n币种：USD\n预计金额：\n备注：Synthetic valid note"
    headers, opp, analysis = draft(api, text)
    sid = analysis["suggestion"]["id"]
    with api[1].seed.transaction() as session:
        row = session.get(Suggestion, sid)
        legacy, _ = propose("预计金额：100\n币种：USD", row.base_snapshot)
        row.proposed_changes = legacy
    with api[1].transaction() as session:
        count = session.scalar(select(func.count()).select_from(AuditEvent))
    response = apply(api, headers, analysis, ids=[legacy[0]["id"]])
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "SUGGESTION_REGENERATE_REQUIRED"
    with api[1].transaction() as session:
        row = session.get(Suggestion, sid)
        assert row.proposed_changes == legacy and row.status == "DRAFT" and row.version == 2
        assert session.get(Opportunity, opp["id"]).version == 1
        assert session.scalar(select(func.count()).select_from(AuditEvent)) == count
        assert (
            session.scalar(
                select(func.count())
                .select_from(SuggestionExecution)
                .where(SuggestionExecution.suggestion_id == sid)
            )
            == 0
        )


def test_partial_execution_is_atomic_and_permanently_deduplicated(api):
    headers, opp, analysis = draft(api)
    changes = analysis["suggestion"]["proposed_changes"]
    ids = [c["id"] for c in changes if c["kind"] == "NOTE" or "amount" in c["values"]]
    key = str(uuid4())
    first = apply(api, headers, analysis, ids, key)
    assert first.status_code == 200, first.json()
    receipt = first.json()["data"]
    assert apply(api, headers, analysis, ids, key).json()["data"] == receipt
    assert apply(api, headers, analysis, ids).json()["data"] == receipt
    reused = apply(api, headers, analysis, key=key)
    assert reused.status_code == 409 and reused.json()["error"]["code"] == "IDEMPOTENCY_KEY_REUSED"
    assert apply(api, headers, analysis).status_code == 409
    current = api[0].get(f"/api/v1/opportunities/{opp['id']}").json()["data"]
    assert (
        current["version"] == 2 and current["amount"] == "1500.00" and current["currency"] == "USD"
    )
    assert (
        current["priority"] == "MEDIUM"
        and current["stage"] == "PROPOSAL_SUBMITTED"
        and current["probability"] == 20
    )
    with api[1].transaction() as session:
        assert (
            session.scalar(
                select(func.count())
                .select_from(SuggestionExecution)
                .where(SuggestionExecution.suggestion_id == analysis["suggestion"]["id"])
            )
            == 1
        )
        activities = session.scalars(
            select(Activity).where(Activity.opportunity_id == opp["id"])
        ).all()
        assert (
            len(activities) == 1 and activities[0].type == "NOTE" and activities[0].ai_execution_key
        )
    assert (
        api[0].get(f"/api/v1/suggestions/{analysis['suggestion']['id']}/execution").json()["data"]
        == receipt
    )


def test_task_execution_uses_existing_actor_and_explicit_due_time(api):
    headers, opp, analysis = draft(api)
    ids = [c["id"] for c in analysis["suggestion"]["proposed_changes"] if c["kind"] == "TASK"]
    response = apply(api, headers, analysis, ids)
    assert response.status_code == 200, response.json()
    with api[1].transaction() as session:
        task = session.get(Activity, response.json()["data"]["activity_ids"][0])
        assert task.assignee_id == api[4] and task.status == "OPEN"
        assert task.due_at == datetime(2026, 12, 1, 8, 0)
        assert session.get(Opportunity, opp["id"]).amount is None


def test_activity_context_change_rejects_even_without_opportunity_version_change(api):
    headers, opp, analysis = draft(api)
    added = api[0].post(
        "/api/v1/activities",
        headers=headers,
        json={
            "account_id": opp["account_id"],
            "opportunity_id": opp["id"],
            "type": "NOTE",
            "subject": "Synthetic newer context",
            "content": "Synthetic newer context",
            "occurred_at": "2026-10-28T00:00:00Z",
        },
    )
    assert added.status_code == 201
    assert (
        api[0]
        .get(f"/api/v1/meeting-analyses/{analysis['id']}")
        .json()["data"]["suggestion"]["effective_status"]
        == "STALE"
    )
    response = apply(api, headers, analysis)
    assert response.status_code == 409 and response.json()["error"]["code"] == "SUGGESTION_STALE"
    assert api[0].get(f"/api/v1/opportunities/{opp['id']}").json()["data"]["version"] == 1


@pytest.mark.parametrize("role", [Role.SALES_REP, Role.READ_ONLY])
def test_other_rep_and_read_only_cannot_execute(api, role):
    headers, opp, analysis = draft(api)
    other = another_owner(api[1])
    moved = api[0].post(
        f"/api/v1/opportunities/{opp['id']}/assign-owner",
        headers={**headers, "Idempotency-Key": str(uuid4())},
        json={"expected_version": 1, "owner_id": other, "reason": "Synthetic ownership transfer"},
    )
    assert moved.status_code == 200
    headers = signed_in(api, role)
    assert apply(api, headers, analysis).status_code == 403


def test_owner_rep_can_execute(api):
    _, _, analysis = draft(api, "优先级：HIGH")
    headers = signed_in(api, Role.SALES_REP)
    assert apply(api, headers, analysis).status_code == 200


@pytest.mark.parametrize("position", ["opportunity", "suggestion"])
def test_audit_failure_rolls_back_every_execution_write(api, monkeypatch, position):
    headers, opp, analysis = draft(api)

    def fail(*args, **kwargs):
        raise RuntimeError("synthetic audit failure")

    if position == "opportunity":
        monkeypatch.setattr(SalesService, "audit_sales", fail)
    else:
        monkeypatch.setattr("app.meetings.execution.audit", fail)
    assert apply(api, headers, analysis).status_code == 500
    with api[1].transaction() as session:
        assert session.get(Opportunity, opp["id"]).version == 1
        assert session.get(Suggestion, analysis["suggestion"]["id"]).status == "DRAFT"
        assert (
            session.scalar(
                select(func.count())
                .select_from(Activity)
                .where(Activity.opportunity_id == opp["id"])
            )
            == 0
        )
        assert (
            session.scalar(
                select(func.count())
                .select_from(SuggestionExecution)
                .where(SuggestionExecution.suggestion_id == analysis["suggestion"]["id"])
            )
            == 0
        )


def test_cross_account_contact_is_rejected_without_partial_changes(api):
    headers, opp = setup_opportunity(api)
    account = (
        api[0]
        .post("/api/v1/accounts", headers=headers, json={"name": "Synthetic other account"})
        .json()["data"]
    )
    contact = (
        api[0]
        .post(
            "/api/v1/contacts",
            headers=headers,
            json={"account_id": account["id"], "name": "Synthetic other contact"},
        )
        .json()["data"]
    )
    response = api[0].post(
        f"/api/v1/opportunities/{opp['id']}/meeting-analyses",
        headers=headers,
        json={
            "expected_opportunity_version": 1,
            "meeting_text": f"主要联系人ID：{contact['id']}\n优先级：HIGH",
            "request_token": str(uuid4()),
        },
    )
    analysis = finish(api, response.json()["data"])
    assert apply(api, headers, analysis).status_code == 422
    assert api[0].get(f"/api/v1/opportunities/{opp['id']}").json()["data"]["version"] == 1


def test_two_managers_concurrently_apply_one_execution(api):
    headers, opp, analysis = draft(api, "备注：Synthetic concurrent note")
    second_id = another_owner(api[1], role=Role.SALES_MANAGER)
    with api[1].seed.transaction() as session:
        session.get(User, second_id).password_hash = hash_password(api[3])
    second = TestClient(api[0].app)
    try:
        logged = second.post(
            "/api/v1/auth/login",
            headers={"Origin": "http://testserver"},
            json={"email": f"{second_id}@example.test", "password": api[3]},
        )
        assert logged.status_code == 200
        h2 = {"Origin": "http://testserver", "X-CSRF-Token": logged.json()["data"]["csrf_token"]}
        barrier = Barrier(2)

        def submit(index):
            barrier.wait()
            if index == 0:
                return apply(api, headers, analysis)
            return apply((second, *api[1:]), h2, analysis)

        with ThreadPoolExecutor(max_workers=2) as pool:
            responses = list(pool.map(submit, range(2)))
        assert [response.status_code for response in responses] == [200, 200]
        assert responses[0].json()["data"] == responses[1].json()["data"]
        assert api[0].get(f"/api/v1/opportunities/{opp['id']}").json()["data"]["version"] == 2
    finally:
        second.close()


def test_retention_preview_is_admin_only_and_never_deletes(api):
    headers, opp, analysis = draft(api, "备注：Synthetic retained note")
    signed_in(api, Role.ADMIN)
    with api[1].seed.transaction() as session:
        session.get(MeetingAnalysis, analysis["id"]).created_at = now() - timedelta(days=91)
    preview = api[0].get("/api/v1/admin/retention/preview")
    assert preview.status_code == 200 and preview.json()["data"]["writes_enabled"] is False
    raw = next(
        group
        for group in preview.json()["data"]["groups"]
        if group["scope"] == "meeting_source_and_quotes"
    )
    assert raw["blocked_by_reason"]["PENDING_REVIEW"] >= 1
    assert api[0].post("/api/v1/admin/retention/preview", json={}).status_code == 405
    with api[1].transaction() as session:
        row = session.get(MeetingAnalysis, analysis["id"])
        assert row.input_text == "备注：Synthetic retained note"
    signed_in(api, Role.SALES_MANAGER)
    assert api[0].get("/api/v1/admin/retention/preview").status_code == 403


def test_all_approved_field_types_execute_and_selected_contact_is_preserved(api):
    headers, opp = setup_opportunity(api)
    contact = (
        api[0]
        .post(
            "/api/v1/contacts",
            headers=headers,
            json={"account_id": opp["account_id"], "name": "Synthetic valid primary"},
        )
        .json()["data"]
    )
    response = api[0].post(
        f"/api/v1/opportunities/{opp['id']}/meeting-analyses",
        headers=headers,
        json={
            "expected_opportunity_version": 1,
            "meeting_date": "2026-10-28",
            "timezone": "Asia/Hong_Kong",
            "request_token": str(uuid4()),
            "meeting_text": (
                f"优先级：HIGH\n来源：EVENT\n预计成交日期：明天\n主要联系人ID：{contact['id']}"
            ),
        },
    )
    analysis = finish(api, response.json()["data"])
    assert len(analysis["suggestion"]["proposed_changes"]) == 4
    assert apply(api, headers, analysis).status_code == 200
    after = api[0].get(f"/api/v1/opportunities/{opp['id']}").json()["data"]
    assert after["priority"] == "HIGH" and after["source"] == "EVENT"
    assert (
        after["expected_close_date"] == "2026-10-29"
        and after["primary_contact_id"] == contact["id"]
    )
    assert after["amount"] is None and after["stage"] == "PROPOSAL_SUBMITTED"


def test_retention_cutoff_is_inclusive_and_execution_references_block_source(api):
    headers, opp, analysis = draft(api, "备注：Synthetic cutoff note")
    applied = apply(api, headers, analysis)
    assert applied.status_code == 200
    moment = datetime(2026, 10, 28, 12, 0)
    with api[1].seed.transaction() as session:
        session.get(MeetingAnalysis, analysis["id"]).created_at = moment - timedelta(days=90)
    signed_in(api, Role.ADMIN)
    url = "/api/v1/admin/retention/preview?as_of=2026-10-28T12:00:00Z"
    protected = api[0].get(url).json()["data"]
    group = next(
        item for item in protected["groups"] if item["scope"] == "meeting_source_and_quotes"
    )
    assert group["blocked_by_reason"]["EXECUTION_REFERENCE"] >= 1
    with api[1].transaction() as session:
        execution = session.scalar(
            select(SuggestionExecution).where(
                SuggestionExecution.suggestion_id == analysis["suggestion"]["id"]
            )
        )
        before = execution.result
    api[0].get(url)
    with api[1].transaction() as session:
        assert session.get(SuggestionExecution, execution.id).result == before
        assert (
            session.get(MeetingAnalysis, analysis["id"]).input_text == "备注：Synthetic cutoff note"
        )


def test_rejected_old_source_becomes_preview_candidate_without_being_deleted(api):
    headers, opp, analysis = draft(api, "备注：Synthetic rejected source")
    row = analysis["suggestion"]
    response = api[0].post(
        f"/api/v1/suggestions/{row['id']}/reject",
        headers={**headers, "Idempotency-Key": str(uuid4())},
        json={"expected_version": row["version"], "reason": "Synthetic rejected"},
    )
    assert response.status_code == 200
    signed_in(api, Role.ADMIN)
    moment = datetime(2026, 10, 28, 12, 0)
    with api[1].seed.transaction() as session:
        session.get(MeetingAnalysis, analysis["id"]).created_at = moment - timedelta(days=90)
    data = api[0].get("/api/v1/admin/retention/preview?as_of=2026-10-28T12:00:00Z").json()["data"]
    group = next(item for item in data["groups"] if item["scope"] == "meeting_source_and_quotes")
    assert group["candidate_count"] >= 1 and group["keep_identity"] is True
    with api[1].transaction() as session:
        assert (
            session.get(MeetingAnalysis, analysis["id"]).input_text
            == "备注：Synthetic rejected source"
        )


def test_receipt_foreign_key_failure_rolls_back_business_audit_and_cache(api):
    headers, opp, analysis = draft(api)
    with api[1].transaction() as session:
        count = session.scalar(select(func.count()).select_from(AuditEvent))

    def invalid_actor(mapper, connection, target):
        target.actor_id = str(uuid4())

    event.listen(SuggestionExecution, "before_insert", invalid_actor)
    try:
        response = apply(api, headers, analysis)
        assert (
            response.status_code == 503
            and response.json()["error"]["code"] == "DEPENDENCY_UNAVAILABLE"
        )
    finally:
        event.remove(SuggestionExecution, "before_insert", invalid_actor)
    with api[1].transaction() as session:
        assert session.get(Opportunity, opp["id"]).version == 1
        assert session.get(Suggestion, analysis["suggestion"]["id"]).status == "DRAFT"
        assert (
            session.scalar(
                select(func.count())
                .select_from(Activity)
                .where(Activity.opportunity_id == opp["id"])
            )
            == 0
        )
        assert session.scalar(select(func.count()).select_from(AuditEvent)) == count
        assert (
            session.scalar(
                select(IdempotencyRecord.id).where(
                    IdempotencyRecord.scope == f"suggestion:{analysis['suggestion']['id']}:apply"
                )
            )
            is None
        )


def test_concurrent_account_disable_either_follows_execution_or_blocks_it(api):
    headers, opp, analysis = draft(api, "备注：Synthetic concurrent revocation")
    admin_id = another_owner(api[1], role=Role.ADMIN)
    with api[1].seed.transaction() as session:
        session.get(User, admin_id).password_hash = hash_password(api[3])
    admin = TestClient(api[0].app)
    try:
        login = admin.post(
            "/api/v1/auth/login",
            headers={"Origin": "http://testserver"},
            json={"email": f"{admin_id}@example.test", "password": api[3]},
        )
        assert login.status_code == 200
        admin_headers = {
            "Origin": "http://testserver",
            "X-CSRF-Token": login.json()["data"]["csrf_token"],
        }
        barrier = Barrier(2)

        def race(index):
            barrier.wait()
            if index == 0:
                return apply(api, headers, analysis)
            return admin.patch(
                f"/api/v1/users/{api[4]}",
                headers=admin_headers,
                json={
                    "expected_version": 1,
                    "is_active": False,
                    "reason": "Synthetic concurrent disable",
                },
            )

        with ThreadPoolExecutor(max_workers=2) as pool:
            applied, disabled = list(pool.map(race, range(2)))
        assert disabled.status_code == 200 and applied.status_code in {200, 401, 403}
        with api[1].transaction() as session:
            assert not session.get(User, api[4]).is_active
            assert session.get(Opportunity, opp["id"]).version == (
                2 if applied.status_code == 200 else 1
            )
            count = session.scalar(
                select(func.count())
                .select_from(SuggestionExecution)
                .where(SuggestionExecution.suggestion_id == analysis["suggestion"]["id"])
            )
            assert count == (1 if applied.status_code == 200 else 0)
    finally:
        admin.close()
