import hashlib
import io
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from threading import Barrier
from types import SimpleNamespace
from uuid import uuid4

import pytest
from pypdf import PdfWriter
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError, OperationalError
from test_crm_mysql import another_owner, signed_in

from app.auth.models import Role, User
from app.crm.models import AuditEvent
from app.sales.models import CloseEvidence, IdempotencyRecord, Opportunity
from app.sales.schemas import OpportunityPatch, Transition
from app.sales.service import SalesService

pytestmark = pytest.mark.integration


def setup_opportunity(api, *, amount=None, currency="CNY"):
    client, _, *_ = api
    headers = signed_in(api, Role.SALES_MANAGER)
    account = client.post(
        "/api/v1/accounts", headers=headers, json={"name": "Synthetic sales"}
    ).json()["data"]
    response = client.post(
        "/api/v1/opportunities",
        headers=headers,
        json={
            "name": "Synthetic opportunity",
            "account_id": account["id"],
            "amount": amount,
            "currency": currency,
        },
    )
    assert response.status_code == 201, response.json()
    return headers, response.json()["data"]


def stage(client, headers, entity, target, **extra):
    return client.post(
        f"/api/v1/opportunities/{entity['id']}/transitions",
        headers={**headers, "Idempotency-Key": str(uuid4())},
        json={
            "expected_version": entity["version"],
            "target_stage": target,
            "reason": "Synthetic reviewed action",
            **extra,
        },
    )


class SyntheticStorage:
    """Only the S3 adapter is synthetic here; all DB transactions are real MySQL."""

    bucket = "synthetic-test-only"

    def __init__(self):
        self.client = self
        self.objects = {}

    def ready(self):
        return True

    def put_object(self, bucket, key, data, size, **kwargs):
        self.objects[key] = data.read()
        return SimpleNamespace(version_id=None)

    def stat_object(self, bucket, key, **kwargs):
        return SimpleNamespace(size=len(self.objects[key]))

    def get_object(self, bucket, key, **kwargs):
        data = self.objects[key]
        return SimpleNamespace(
            read=lambda limit: data[:limit], close=lambda: None, release_conn=lambda: None
        )


def evidence(api, headers, opportunity, *, amount="230000.00", kind="SIGNED_CONTRACT"):
    client, _, *_ = api
    if not isinstance(client.app.state.storage, SyntheticStorage):
        client.app.state.storage = SyntheticStorage()
    pdf = PdfWriter()
    pdf.add_blank_page(width=100, height=100)
    buffer = io.BytesIO()
    pdf.write(buffer)
    payload = buffer.getvalue()
    response = client.post(
        f"/api/v1/opportunities/{opportunity['id']}/evidence-files",
        headers=headers,
        data={"request_token": str(uuid4())},
        files={"file": ("synthetic.pdf", payload, "application/pdf")},
    )
    assert response.status_code == 201, response.json()
    uploaded = response.json()["data"]
    assert uploaded["sha256"] == hashlib.sha256(payload).hexdigest()
    response = client.post(
        f"/api/v1/opportunities/{opportunity['id']}/evidence",
        headers=headers,
        json={
            "stored_object_id": uploaded["stored_object_id"],
            "type": kind,
            "reference_number": "SYNTHETIC-PO",
            "customer_legal_name": "Synthetic legal party",
            "document_date": "2026-10-27",
            "amount": amount,
            "currency": opportunity["currency"],
            **(
                {"approval_basis": "Synthetic pending approval reference"}
                if kind == "OTHER_APPROVED"
                else {}
            ),
        },
    )
    assert response.status_code == 201, response.json()
    return response.json()["data"], payload


def review_as_other(api, headers, proof):
    from fastapi.testclient import TestClient

    client, db, _, password, actor_id = api
    reviewer_id = another_owner(db, role=Role.SALES_MANAGER)
    with db.seed.transaction() as session:
        source = session.get(User, actor_id)
        session.get(User, reviewer_id).password_hash = source.password_hash
    reviewer = TestClient(client.app)
    login = reviewer.post(
        "/api/v1/auth/login",
        headers={"Origin": "http://testserver"},
        json={"email": f"{reviewer_id}@example.test", "password": password},
    )
    assert login.status_code == 200
    response = reviewer.post(
        f"/api/v1/evidence/{proof['id']}/review",
        headers={
            "Origin": "http://testserver",
            "X-CSRF-Token": login.json()["data"]["csrf_token"],
            "Idempotency-Key": str(uuid4()),
        },
        json={"expected_version": 1, "decision": "VERIFY", "note": "Synthetic original reviewed"},
    )
    reviewer.close()
    assert response.status_code == 200, response.json()
    assert response.json()["data"]["reviewed_by"] == reviewer_id
    assert response.json()["data"]["submitted_by"] == actor_id
    return response.json()["data"]


def test_null_money_pipeline_readonly_and_currency(api):
    client, _, *_ = api
    headers, opportunity = setup_opportunity(api)
    assert opportunity["amount"] is None and opportunity["weighted_amount"] is None
    summary = client.get("/api/v1/pipeline/summary?account_id=" + opportunity["account_id"]).json()[
        "data"
    ]["currency_groups"][0]
    assert summary["pipeline_value"] is None and summary["unknown_amount_count"] == 1
    assert (
        client.patch(
            f"/api/v1/opportunities/{opportunity['id']}",
            headers=headers,
            json={"expected_version": 1, "probability": 20},
        ).json()["error"]["code"]
        == "FIELD_NOT_EDITABLE"
    )
    response = client.patch(
        f"/api/v1/opportunities/{opportunity['id']}",
        headers=headers,
        json={"expected_version": 1, "amount": "0.00"},
    )
    assert response.status_code == 200 and response.json()["data"]["weighted_amount"] == "0.00"
    for bad in ["GBP", "cny", None]:
        assert (
            client.post(
                "/api/v1/opportunities",
                headers=headers,
                json={
                    "name": "bad currency",
                    "account_id": opportunity["account_id"],
                    "currency": bad,
                },
            ).status_code
            == 422
        )


def test_pipeline_aggregation_keeps_per_row_rounding_empty_and_unknown_groups(api):
    client, _, *_ = api
    headers, first = setup_opportunity(api, amount="0.03")
    for amount, currency in [("0.03", "CNY"), ("0.03", "CNY"), (None, "USD"), ("0.00", "EUR")]:
        response = client.post(
            "/api/v1/opportunities",
            headers=headers,
            json={
                "name": "Synthetic aggregate boundary",
                "account_id": first["account_id"],
                "amount": amount,
                "currency": currency,
            },
        )
        assert response.status_code == 201
    params = {"account_id": first["account_id"]}
    groups = {
        row["currency"]: row
        for row in client.get("/api/v1/pipeline/summary", params=params).json()["data"][
            "currency_groups"
        ]
    }
    assert set(groups) == {"CNY", "USD", "EUR", "HKD"}
    assert groups["CNY"]["pipeline_value"] == "0.09"
    assert groups["CNY"]["weighted_forecast"] == "0.03"  # SUM(ROUND(each)), not ROUND(SUM).
    assert groups["CNY"]["open_count"] == 3
    assert groups["USD"]["pipeline_value"] is None
    assert groups["USD"]["unknown_amount_count"] == 1
    assert groups["EUR"]["pipeline_value"] == "0.00"
    assert groups["EUR"]["known_amount_count"] == 1
    assert groups["HKD"]["pipeline_value"] == "0.00"
    assert groups["HKD"]["open_count"] == 0
    assert groups["HKD"]["win_rate"] is None
    filtered = client.get("/api/v1/pipeline/summary", params={**params, "currency": "USD"}).json()[
        "data"
    ]["currency_groups"]
    assert len(filtered) == 1 and filtered[0] == groups["USD"]


@pytest.mark.parametrize("estimate", [None, "0.00", "250000.00"])
def test_actual_close_can_differ_unknown_or_zero_and_download(api, estimate):
    client, _, *_ = api
    headers, opportunity = setup_opportunity(api, amount=estimate)
    opportunity = stage(client, headers, opportunity, "NEGOTIATION").json()["data"]
    proof, payload = evidence(api, headers, opportunity)
    assert (
        stage(client, headers, opportunity, "WON", evidence_id=proof["id"]).json()["error"]["code"]
        == "EVIDENCE_INVALID"
    )
    review_as_other(api, headers, proof)
    response = stage(client, headers, opportunity, "WON", evidence_id=proof["id"])
    assert response.status_code == 200, response.json()
    won = response.json()["data"]
    assert won["amount"] == estimate and won["actual_amount"] == "230000.00"
    assert won["probability"] == 100
    if estimate is None:
        assert won["weighted_amount"] is None
    summary = client.get("/api/v1/pipeline/summary?account_id=" + opportunity["account_id"]).json()[
        "data"
    ]["currency_groups"][0]
    assert (
        summary["closed_won_actual_amount"] == "230000.00" and summary["pipeline_value"] == "0.00"
    )
    download = client.get(f"/api/v1/evidence/{proof['id']}/download")
    assert download.status_code == 200 and download.content == payload
    assert "attachment" in download.headers["content-disposition"]
    assert (
        client.post(
            f"/api/v1/opportunities/{won['id']}/reopen",
            headers={**headers, "Idempotency-Key": str(uuid4())},
            json={"expected_version": won["version"], "reason": "Synthetic"},
        ).json()["error"]["code"]
        == "WON_REOPEN_NOT_ALLOWED"
    )


def test_q04_self_review_roles_and_other_policy(api):
    client, _, *_ = api
    headers, opportunity = setup_opportunity(api)
    proof, _ = evidence(api, headers, opportunity)
    body = {"expected_version": 1, "decision": "VERIFY", "note": "Synthetic"}
    response = client.post(
        f"/api/v1/evidence/{proof['id']}/review",
        headers={**headers, "Idempotency-Key": str(uuid4())},
        json=body,
    )
    assert (
        response.status_code == 403
        and response.json()["error"]["code"] == "EVIDENCE_REVIEWER_CONFLICT"
    )
    headers = signed_in(api, Role.SALES_REP)
    response = client.post(
        f"/api/v1/evidence/{proof['id']}/review",
        headers={**headers, "Idempotency-Key": str(uuid4())},
        json=body,
    )
    assert response.status_code == 403 and response.json()["error"]["code"] == "FORBIDDEN"


def test_idempotency_lost_reopen_and_stale_reselection(api):
    client, db, *_ = api
    headers, opportunity = setup_opportunity(api, amount="12.34")
    opportunity = stage(client, headers, opportunity, "NEGOTIATION").json()["data"]
    key = str(uuid4())
    body = {
        "expected_version": 2,
        "target_stage": "LOST",
        "reason": "Synthetic",
        "close_reason_code": "BUDGET",
        "close_reason": "Synthetic budget",
    }
    url = f"/api/v1/opportunities/{opportunity['id']}/transitions"
    first = client.post(url, headers={**headers, "Idempotency-Key": key}, json=body)
    second = client.post(url, headers={**headers, "Idempotency-Key": key}, json=body)
    assert first.status_code == second.status_code == 200
    assert first.json()["data"] == second.json()["data"]
    assert (
        client.post(
            url, headers={**headers, "Idempotency-Key": key}, json={**body, "reason": "different"}
        ).status_code
        == 409
    )
    response = client.post(
        f"/api/v1/opportunities/{opportunity['id']}/reopen",
        headers={**headers, "Idempotency-Key": str(uuid4())},
        json={"expected_version": 3, "reason": "Synthetic reopen"},
    )
    assert response.status_code == 200, response.json()
    assert response.json()["data"]["probability"] == 60
    assert response.json()["data"]["closed_at"] is None
    with db.transaction() as session:
        assert (
            session.scalar(
                select(func.count())
                .select_from(IdempotencyRecord)
                .where(IdempotencyRecord.request_key == key)
            )
            == 1
        )


def test_currency_rechecked_and_audit_failure_rolls_back(api, monkeypatch):
    client, db, *_ = api
    headers, opportunity = setup_opportunity(api)
    proof, _ = evidence(api, headers, opportunity)
    review_as_other(api, headers, proof)
    opportunity = client.patch(
        f"/api/v1/opportunities/{opportunity['id']}",
        headers=headers,
        json={"expected_version": 1, "currency": "USD"},
    ).json()["data"]
    opportunity = stage(client, headers, opportunity, "NEGOTIATION").json()["data"]
    assert (
        stage(client, headers, opportunity, "WON", evidence_id=proof["id"]).json()["error"]["code"]
        == "EVIDENCE_CURRENCY_MISMATCH"
    )

    def fail(*args, **kwargs):
        raise RuntimeError("synthetic audit failure")

    monkeypatch.setattr(SalesService, "audit_sales", fail)
    response = stage(client, headers, opportunity, "FOLLOW_UP")
    assert response.status_code == 500
    with db.transaction() as session:
        entity = session.get(Opportunity, opportunity["id"])
        assert entity.stage == "NEGOTIATION" and entity.version == opportunity["version"]


@pytest.mark.parametrize("attempt", range(20))
def test_real_concurrent_opportunity_updates_and_database_probability_check(api, attempt):
    client, db, *_ = api
    headers, opportunity = setup_opportunity(api)
    identity = client.app.state.auth.authenticate(client.cookies.get("esc_session"))
    barrier = Barrier(2)

    def write(name):
        barrier.wait(timeout=10)
        try:
            SalesService(db).patch_opportunity(
                opportunity["id"],
                OpportunityPatch(expected_version=1, name=name),
                identity,
                str(uuid4()),
            )
            return 200
        except Exception as exc:
            return getattr(exc, "status", 500)

    with ThreadPoolExecutor(max_workers=2) as executor:
        assert sorted(executor.map(write, ["Synthetic A", "Synthetic B"])) == [200, 409]
    with pytest.raises((IntegrityError, OperationalError)), db.transaction() as session:
        session.execute(
            text("UPDATE opportunities SET probability=99 WHERE id=:id"), {"id": opportunity["id"]}
        )


def test_audit_runtime_account_cannot_modify_history(api):
    _, db, *_ = api
    _, opportunity = setup_opportunity(api)
    with pytest.raises(OperationalError), db.transaction() as session:
        session.execute(
            text("UPDATE audit_events SET reason='forbidden' WHERE entity_id=:id"),
            {"id": opportunity["id"]},
        )


def test_concurrent_same_key_command_replays_with_insert_only_idempotency(api):
    client, db, *_ = api
    headers, opportunity = setup_opportunity(api)
    identity = client.app.state.auth.authenticate(client.cookies.get("esc_session"))
    key, barrier = str(uuid4()), Barrier(2)
    body = Transition(expected_version=1, target_stage="NEGOTIATION", reason="Synthetic same key")

    def write(_):
        barrier.wait(timeout=10)
        return SalesService(db).command(
            opportunity["id"], "transitions", body, key, identity, str(uuid4())
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        first, second = list(executor.map(write, range(2)))
    assert first == second and first["version"] == 2
    with db.transaction() as session:
        assert (
            session.scalar(
                select(func.count())
                .select_from(IdempotencyRecord)
                .where(
                    IdempotencyRecord.actor_id == identity.user.id,
                    IdempotencyRecord.request_key == key,
                )
            )
            == 1
        )
        assert (
            session.scalar(
                select(func.count())
                .select_from(AuditEvent)
                .where(AuditEvent.entity_id == opportunity["id"])
            )
            == 2
        )


def test_multiple_candidates_only_selected_actual_and_terminal_reselection(api):
    client, _, *_ = api
    headers, opportunity = setup_opportunity(api, amount="250000.00")
    first, _ = evidence(api, headers, opportunity, amount="230000.00")
    second, _ = evidence(api, headers, opportunity, amount="999.00")
    review_as_other(api, headers, first)
    review_as_other(api, headers, second)
    opportunity = stage(client, headers, opportunity, "NEGOTIATION").json()["data"]
    won = stage(client, headers, opportunity, "WON", evidence_id=first["id"]).json()["data"]
    assert won["close_evidence_id"] == first["id"]
    assert (
        stage(client, headers, won, "WON", evidence_id=second["id"]).json()["error"]["code"]
        == "TERMINAL_OPPORTUNITY"
    )
    summary = client.get(
        "/api/v1/pipeline/summary", params={"account_id": opportunity["account_id"]}
    ).json()["data"]["currency_groups"][0]
    assert summary["closed_won_actual_amount"] == "230000.00"


def test_pipeline_equal_actual_amounts_count_each_deal_once_with_filters_and_window(api):
    client, _, *_ = api
    headers, first = setup_opportunity(api, amount=None)
    deals = [first]
    for currency in ["CNY", "USD"]:
        response = client.post(
            "/api/v1/opportunities",
            headers=headers,
            json={
                "name": "Synthetic equal actual",
                "account_id": first["account_id"],
                "currency": currency,
            },
        )
        assert response.status_code == 201
        deals.append(response.json()["data"])
    closed = []
    for deal in deals:
        selected, _ = evidence(api, headers, deal, amount="230000.00")
        alternative, _ = evidence(api, headers, deal, amount="999.00")
        review_as_other(api, headers, selected)
        review_as_other(api, headers, alternative)
        deal = stage(client, headers, deal, "NEGOTIATION").json()["data"]
        response = stage(client, headers, deal, "WON", evidence_id=selected["id"])
        assert response.status_code == 200
        closed.append(response.json()["data"])
    params = {"account_id": first["account_id"], "owner_id": first["owner_id"], "stage": "WON"}

    def groups(**extra):
        response = client.get("/api/v1/pipeline/summary", params={**params, **extra})
        assert response.status_code == 200
        return {row["currency"]: row for row in response.json()["data"]["currency_groups"]}

    summary = groups()
    # Equal amounts on separate deals must both count; SUM(DISTINCT amount) would return 230000.
    assert summary["CNY"]["closed_won_actual_amount"] == "460000.00"
    assert summary["CNY"]["closed_won_count"] == 2
    assert summary["USD"]["closed_won_actual_amount"] == "230000.00"
    assert summary["USD"]["closed_won_count"] == 1
    assert summary["CNY"]["stages"][3]["unknown_amount_count"] == 2
    assert groups(currency="CNY") == {"CNY": summary["CNY"]}
    assert groups(q="equal actual")["CNY"]["closed_won_actual_amount"] == "230000.00"
    assert groups(priority="HIGH")["CNY"]["closed_won_count"] == 0
    within = groups(win_from=closed[0]["closed_at"], win_to=closed[-1]["closed_at"])
    assert within["CNY"]["closed_won_actual_amount"] == "460000.00"
    later = (
        datetime.fromisoformat(closed[-1]["closed_at"].replace("Z", "+00:00"))
        + timedelta(seconds=1)
    ).isoformat()
    excluded = groups(
        win_from=later, win_to=(datetime.fromisoformat(later) + timedelta(days=1)).isoformat()
    )
    assert excluded["CNY"]["closed_won_actual_amount"] == "0.00"
    assert excluded["CNY"]["closed_won_count"] == 0
    assert (
        excluded["CNY"]["stages"][3]["count"] == 2
    )  # Stage totals do not acquire a close window filter.


def test_other_approved_candidate_not_automatically_verified(api):
    client, db, *_ = api
    headers, opportunity = setup_opportunity(api)
    proof, _ = evidence(api, headers, opportunity, kind="OTHER_APPROVED")
    reviewer_id = another_owner(db, role=Role.ADMIN)
    identity = SimpleNamespace(user=SimpleNamespace(id=reviewer_id))
    from app.core.errors import AppError
    from app.sales.schemas import Review

    with pytest.raises(AppError) as error:
        SalesService(db).review(
            proof["id"],
            Review(expected_version=1, decision="VERIFY", note="Synthetic"),
            str(uuid4()),
            identity,
            str(uuid4()),
        )
    assert error.value.code == "OTHER_APPROVAL_POLICY_PENDING"
    with db.transaction() as session:
        assert session.get(CloseEvidence, proof["id"]).status == "PENDING"


def test_q03_opportunity_foreign_read_pipeline_but_not_write(api):
    client, _, *_ = api
    headers, opportunity = setup_opportunity(api)
    other_id = another_owner(api[1])
    assigned = client.post(
        f"/api/v1/opportunities/{opportunity['id']}/assign-owner",
        headers={**headers, "Idempotency-Key": str(uuid4())},
        json={"expected_version": 1, "owner_id": other_id, "reason": "Synthetic transfer"},
    )
    assert assigned.status_code == 200
    headers = signed_in(api, Role.SALES_REP)
    assert client.get(f"/api/v1/opportunities/{opportunity['id']}").status_code == 200
    assert (
        client.get("/api/v1/opportunities", params={"owner_id": other_id}).json()["page"]["total"]
        >= 1
    )
    assert client.get("/api/v1/pipeline/summary", params={"owner_id": other_id}).status_code == 200
    assert (
        client.patch(
            f"/api/v1/opportunities/{opportunity['id']}",
            headers=headers,
            json={"expected_version": 2, "amount": "1.00"},
        ).status_code
        == 403
    )
    assert client.get("/api/v1/audit-events").status_code == 403


def test_activity_task_completion_and_audit(api):
    client, db, *_ = api
    headers, opportunity = setup_opportunity(api)
    response = client.post(
        "/api/v1/activities",
        headers=headers,
        json={
            "account_id": opportunity["account_id"],
            "opportunity_id": opportunity["id"],
            "type": "TASK",
            "subject": "Synthetic follow-up",
            "content": "Synthetic task",
            "due_at": "2026-11-01T00:00:00Z",
            "assignee_id": api[4],
        },
    )
    assert response.status_code == 201, response.json()
    task = response.json()["data"]
    key = str(uuid4())
    path = f"/api/v1/activities/{task['id']}/complete"
    response = client.post(
        path, headers={**headers, "Idempotency-Key": key}, json={"expected_version": 1}
    )
    assert response.status_code == 200 and response.json()["data"]["status"] == "DONE"
    assert (
        client.post(
            path, headers={**headers, "Idempotency-Key": key}, json={"expected_version": 1}
        ).json()["data"]
        == response.json()["data"]
    )
    assert (
        client.post(
            path, headers={**headers, "Idempotency-Key": str(uuid4())}, json={"expected_version": 2}
        ).status_code
        == 409
    )
    with db.transaction() as session:
        assert (
            session.scalar(
                select(func.count())
                .select_from(AuditEvent)
                .where(AuditEvent.entity_id == task["id"])
            )
            == 2
        )
