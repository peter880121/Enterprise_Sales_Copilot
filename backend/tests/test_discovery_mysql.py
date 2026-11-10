from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Barrier
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event, func, select
from test_crm_mysql import another_owner, signed_in

from app.auth.models import Role, User
from app.auth.security import hash_password
from app.auth.service import now
from app.crm.models import Account, AuditEvent
from app.discovery.models import AccountLink, DiscoveryLead, DiscoveryRun, Material, SalesProfile
from app.discovery.processor import DiscoveryProcessor
from app.sales.models import Opportunity

pytestmark = pytest.mark.integration


def setup(api, visibility="PRIVATE", reviewer_ids=None):
    headers = signed_in(api, Role.SALES_MANAGER)
    name = "Synthetic discovery " + uuid4().hex[:8]
    response = api[0].post(
        "/api/v1/discovery/profiles",
        headers=headers,
        json={
            "name": name,
            "product": "超声设备",
            "keywords": ["超声"],
            "regions": [],
            "visibility": visibility,
            "reviewer_ids": reviewer_ids or [],
        },
    )
    assert response.status_code == 201
    return headers, response.json()["data"]


def material(api, headers, profile, content=None, purpose="BUYER_DEMAND"):
    response = api[0].post(
        f"/api/v1/discovery/profiles/{profile['id']}/materials",
        headers=headers,
        json={
            "title": "Synthetic private source",
            "purpose": purpose,
            "content": content
            or (
                "采购人：示例医院\n项目：超声设备采购\n采购代理：示例代理\n"
                "公告类型：采购意向\n预算：120万元 人民币"
            ),
            "confirm_team_visibility": profile["visibility"] == "TEAM",
            "confirm_no_patient_data": True,
        },
    )
    assert response.status_code == 201
    return response.json()["data"]


def start(api, headers, profile, source, token=None):
    return api[0].post(
        f"/api/v1/discovery/profiles/{profile['id']}/runs",
        headers=headers,
        json={
            "expected_profile_version": profile["version"],
            "material_ids": [source["id"]],
            "request_token": token or str(uuid4()),
        },
    )


def finish(api, accepted):
    worker = DiscoveryProcessor(api[1], api[0].app.state.settings)
    for _ in range(100):
        data = api[0].get("/api/v1/discovery/runs/" + accepted["id"]).json()["data"]
        if data["status"] in {"SUCCEEDED", "FAILED"}:
            return data
        worker.process_one()
    raise AssertionError("Discovery run did not finish")


def lead_setup(api, visibility="PRIVATE"):
    headers, profile = setup(api, visibility)
    source = material(api, headers, profile)
    response = start(api, headers, profile, source)
    assert response.status_code == 202
    assert finish(api, response.json()["data"])["status"] == "SUCCEEDED"
    with api[1].transaction() as s:
        uid = s.scalar(select(DiscoveryLead.id).where(DiscoveryLead.material_id == source["id"]))
    lead = api[0].get("/api/v1/discovery/leads/" + uid).json()["data"]
    return headers, profile, source, lead


def review(api, headers, lead, status, publish=False):
    return api[0].patch(
        "/api/v1/discovery/leads/" + lead["id"],
        headers=headers,
        json={
            "expected_version": lead["version"],
            "status": status,
            "reason": "Synthetic private review",
            "publish_summary": publish,
        },
    )


def qualify(api, headers, lead, publish=False):
    first = review(api, headers, lead, "IN_REVIEW")
    assert first.status_code == 200
    second = review(api, headers, first.json()["data"], "QUALIFIED", publish)
    assert second.status_code == 200
    return second.json()["data"]


def other_client(api, role=Role.ADMIN):
    uid = another_owner(api[1], role=role)
    with api[1].seed.transaction() as s:
        user = s.get(User, uid)
        user.password_hash = hash_password(api[3])
        email = user.email
    client = TestClient(api[0].app)
    logged = client.post(
        "/api/v1/auth/login",
        headers={"Origin": "http://testserver"},
        json={"email": email, "password": api[3]},
    )
    assert logged.status_code == 200
    return (
        client,
        {"Origin": "http://testserver", "X-CSRF-Token": logged.json()["data"]["csrf_token"]},
        uid,
    )


def test_discovery_creates_evidenced_private_lead_without_crm_side_effects(api):
    with api[1].transaction() as s:
        before = s.scalar(select(func.count()).select_from(Opportunity))
    headers, profile, source, lead = lead_setup(api)
    assert lead["status"] == "NEW" and not lead["account_id"]
    assert (
        lead["analysis"]["mode"] == "RULES" and lead["analysis"]["qualification"] == "NOT_VERIFIED"
    )
    assert (
        lead["analysis"]["facts"]["buyer"]["value"] != lead["analysis"]["facts"]["agency"]["value"]
    )
    text = api[0].get("/api/v1/discovery/materials/" + source["id"]).json()["data"]
    for fact in lead["analysis"]["facts"].values():
        span = fact["evidence"]
        assert (
            text["content"][span["start"] : span["end"]] == span["quote"]
            and span["sha256"] == text["text_sha256"]
        )
    with api[1].transaction() as s:
        assert s.scalar(select(func.count()).select_from(Opportunity)) == before
        audits = s.scalars(
            select(AuditEvent).where(
                AuditEvent.entity_id.in_([profile["id"], source["id"], lead["id"]])
            )
        )
        assert all(
            "Synthetic private" not in str(row.after_state) and "buyer_name" not in row.after_state
            for row in audits
        )


@pytest.mark.parametrize("role", [Role.SALES_REP, Role.SALES_MANAGER, Role.ADMIN, Role.READ_ONLY])
def test_private_sources_do_not_become_readable_through_roles_or_known_ids(api, role):
    _, profile, source, lead = lead_setup(api)
    client, headers, _ = other_client(api, role)
    try:
        for path in [
            "/profiles/" + profile["id"],
            "/materials/" + source["id"],
            "/leads/" + lead["id"],
        ]:
            assert client.get("/api/v1/discovery" + path).status_code == 403
        response = client.get("/api/v1/discovery/leads")
        assert response.status_code == 200
        assert not any(row["id"] == lead["id"] for row in response.json()["data"])
        denied = client.patch(
            "/api/v1/discovery/leads/" + lead["id"],
            headers=headers,
            json={"expected_version": 1, "status": "IN_REVIEW", "reason": "Synthetic"},
        )
        assert denied.status_code == 403
    finally:
        client.close()


def test_explicit_reviewer_grant_and_revocation_apply_to_sources_and_runs(api):
    client, _, uid = other_client(api)
    try:
        headers, profile = setup(api, reviewer_ids=[uid])
        source = material(api, headers, profile)
        assert client.get("/api/v1/discovery/materials/" + source["id"]).status_code == 200
        response = api[0].patch(
            "/api/v1/discovery/profiles/" + profile["id"],
            headers=headers,
            json={
                key: profile[key]
                for key in ["name", "product", "keywords", "regions", "visibility"]
            }
            | {"expected_version": 1, "reviewer_ids": []},
        )
        assert response.status_code == 200
        assert client.get("/api/v1/discovery/materials/" + source["id"]).status_code == 403
        stale = start(api, headers, profile, source)
        assert stale.status_code == 409
    finally:
        client.close()


def test_readonly_sees_only_explicitly_published_team_summary(api):
    headers, _, _, lead = lead_setup(api, "TEAM")
    client, _, _ = other_client(api, Role.READ_ONLY)
    try:
        assert client.get("/api/v1/discovery/leads/" + lead["id"]).status_code == 403
        updated = qualify(api, headers, lead, True)
        summary = client.get("/api/v1/discovery/leads/" + updated["id"]).json()["data"]
        assert (
            summary["summary_only"]
            and "analysis" not in summary
            and "material_id" not in summary
            and "review_note" not in summary
        )
    finally:
        client.close()


def test_run_retry_and_source_reuse_do_not_duplicate_leads(api):
    headers, profile = setup(api)
    source = material(api, headers, profile)
    token = str(uuid4())
    first = start(api, headers, profile, source, token)
    second = start(api, headers, profile, source, token)
    assert (
        first.status_code == second.status_code == 202
        and first.json()["data"]["id"] == second.json()["data"]["id"]
    )
    assert finish(api, first.json()["data"])["status"] == "SUCCEEDED"
    third = start(api, headers, profile, source)
    assert finish(api, third.json()["data"])["status"] == "SUCCEEDED"
    with api[1].transaction() as s:
        assert (
            s.scalar(
                select(func.count())
                .select_from(DiscoveryLead)
                .where(DiscoveryLead.material_id == source["id"])
            )
            == 1
        )


def test_seller_material_and_cross_profile_source_are_rejected(api):
    headers, profile = setup(api)
    seller = material(api, headers, profile, purpose="SELLER_CAPABILITY")
    assert start(api, headers, profile, seller).status_code == 422
    headers, other = setup(api)
    other_source = material(api, headers, other)
    assert start(api, headers, profile, other_source).status_code == 422


def test_invalid_rules_fail_visibly_without_partial_leads(api):
    headers, profile = setup(api)
    source = material(api, headers, profile, "This is an unlabelled synthetic article")
    accepted = start(api, headers, profile, source).json()["data"]
    result = finish(api, accepted)
    assert (
        result["status"] == "FAILED"
        and result["error_code"] == "MATERIAL_NEEDS_LABELS"
        and result["result_count"] == 0
    )


def test_upload_preserves_bom_bytes_and_limits_and_rejects_pdf(api):
    headers, profile = setup(api)
    path = f"/api/v1/discovery/profiles/{profile['id']}/material-files"
    raw = b"\xef\xbb\xbf" + "采购人：示例医院\n项目：超声".encode()
    response = api[0].post(
        path,
        headers=headers,
        data={
            "purpose": "BUYER_DEMAND",
            "confirm_team_visibility": "false",
            "confirm_no_patient_data": "true",
        },
        files={"file": ("synthetic.md", raw, "text/markdown")},
    )
    assert response.status_code == 201
    with api[1].transaction() as s:
        assert s.get(Material, response.json()["data"]["id"]).original_bytes == raw
    for name, data, mime, expected in [
        ("wrong.pdf", b"%PDF-synthetic", "application/pdf", 422),
        ("large.txt", b"x" * 65537, "text/plain", 413),
    ]:
        rejected = api[0].post(
            path,
            headers=headers,
            data={
                "purpose": "BUYER_DEMAND",
                "confirm_team_visibility": "false",
                "confirm_no_patient_data": "true",
            },
            files={"file": (name, data, mime)},
        )
        assert rejected.status_code == expected
    assert (
        api[0]
        .post("/api/v1/discovery/profiles", headers=headers, content=b"x" * 131073)
        .status_code
        == 413
    )


def test_team_upload_requires_explicit_sharing_confirmation(api):
    headers, profile = setup(api, "TEAM")
    response = api[0].post(
        f"/api/v1/discovery/profiles/{profile['id']}/materials",
        headers=headers,
        json={
            "title": "Synthetic",
            "purpose": "BUYER_DEMAND",
            "content": "Synthetic",
            "confirm_no_patient_data": True,
        },
    )
    assert response.status_code == 422


def test_review_cas_and_audit_failure_roll_back(api):
    headers, _, _, lead = lead_setup(api)
    first = review(api, headers, lead, "IN_REVIEW")
    assert first.status_code == 200
    assert review(api, headers, lead, "IN_REVIEW").status_code == 409

    def fail(_mapper, _connection, target):
        if target.action == "DISCOVERY_LEAD_REVIEWED":
            target.actor_id = str(uuid4())

    event.listen(AuditEvent, "before_insert", fail)
    try:
        response = review(api, headers, first.json()["data"], "QUALIFIED")
    finally:
        event.remove(AuditEvent, "before_insert", fail)
    assert response.status_code == 503
    with api[1].transaction() as s:
        assert s.get(DiscoveryLead, lead["id"]).status == "IN_REVIEW"


def link_body(api, headers, lead):
    body = {
        "expected_version": lead["version"],
        "new_account_name": "Synthetic reviewed hospital",
        "existing_account_id": None,
    }
    preview = api[0].post(
        f"/api/v1/discovery/leads/{lead['id']}/account-preview", headers=headers, json=body
    )
    assert preview.status_code == 200
    return body | {
        "preview_hash": preview.json()["data"]["preview_hash"],
        "confirmed_shared_crm": True,
    }


def test_account_link_retries_do_not_create_accounts_twice_or_create_opportunity(api):
    headers, _, _, lead = lead_setup(api)
    lead = qualify(api, headers, lead)
    body = link_body(api, headers, lead)
    key = str(uuid4())
    with api[1].transaction() as s:
        opportunities = s.scalar(select(func.count()).select_from(Opportunity))
    path = f"/api/v1/discovery/leads/{lead['id']}/link-account"
    first = api[0].post(path, headers={**headers, "Idempotency-Key": key}, json=body)
    assert first.status_code == 200
    for retry_key in [key, str(uuid4())]:
        response = api[0].post(path, headers={**headers, "Idempotency-Key": retry_key}, json=body)
        assert response.status_code == 200 and response.json()["data"] == first.json()["data"]
    assert (
        api[0]
        .post(
            path,
            headers={**headers, "Idempotency-Key": key},
            json={**body, "new_account_name": "Different synthetic"},
        )
        .status_code
        == 409
    )
    with api[1].transaction() as s:
        assert (
            s.scalar(
                select(func.count())
                .select_from(AccountLink)
                .where(AccountLink.lead_id == lead["id"])
            )
            == 1
        )
        account = s.get(Account, first.json()["data"]["account_id"])
        assert account.description is None and account.owner_id == api[4]
        assert s.scalar(select(func.count()).select_from(Opportunity)) == opportunities


def test_account_and_link_roll_back_on_real_late_audit_failure(api):
    headers, _, _, lead = lead_setup(api)
    lead = qualify(api, headers, lead)
    body = link_body(api, headers, lead)
    with api[1].transaction() as s:
        before = s.scalar(select(func.count()).select_from(Account))

    def fail(_mapper, _connection, target):
        if target.action == "DISCOVERY_ACCOUNT_LINKED":
            target.actor_id = str(uuid4())

    event.listen(AuditEvent, "before_insert", fail)
    try:
        response = api[0].post(
            f"/api/v1/discovery/leads/{lead['id']}/link-account",
            headers={**headers, "Idempotency-Key": str(uuid4())},
            json=body,
        )
    finally:
        event.remove(AuditEvent, "before_insert", fail)
    assert response.status_code == 503
    with api[1].transaction() as s:
        assert s.scalar(select(func.count()).select_from(Account)) == before
        assert s.get(DiscoveryLead, lead["id"]).account_id is None
        assert (
            s.scalar(
                select(func.count())
                .select_from(AccountLink)
                .where(AccountLink.lead_id == lead["id"])
            )
            == 0
        )


def test_two_concurrent_links_have_one_permanent_receipt(api):
    headers, _, _, lead = lead_setup(api)
    lead = qualify(api, headers, lead)
    body = link_body(api, headers, lead)
    barrier = Barrier(2)

    def run(index):
        barrier.wait(timeout=10)
        return api[0].post(
            f"/api/v1/discovery/leads/{lead['id']}/link-account",
            headers={**headers, "Idempotency-Key": str(uuid4())},
            json=body,
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(run, range(2)))
    assert [r.status_code for r in responses] == [200, 200]
    assert responses[0].json()["data"]["account_id"] == responses[1].json()["data"]["account_id"]


def test_expired_lease_late_publication_and_permission_change_are_rejected(api):
    headers, profile = setup(api)
    source = material(api, headers, profile)
    accepted = start(api, headers, profile, source).json()["data"]
    worker = DiscoveryProcessor(api[1], api[0].app.state.settings)
    claim = worker.claim()
    assert claim["id"] == accepted["id"]
    with api[1].seed.transaction() as s:
        s.get(DiscoveryRun, claim["id"]).lease_until = now() - timedelta(seconds=1)
    assert not worker.publish(claim, [])
    with api[1].seed.transaction() as s:
        s.get(User, api[4]).role = Role.READ_ONLY
    worker.process_one()
    with api[1].transaction() as s:
        assert s.get(DiscoveryRun, accepted["id"]).status == "FAILED"
        assert (
            s.scalar(
                select(func.count())
                .select_from(DiscoveryLead)
                .where(DiscoveryLead.material_id == source["id"])
            )
            == 0
        )


def test_profile_and_material_pagination_reaches_records_after_one_hundred(api):
    import hashlib

    headers, profile = setup(api)
    profile_ids, material_ids = set(), set()
    with api[1].seed.transaction() as session:
        for index in range(105):
            pid, mid = str(uuid4()), str(uuid4())
            profile_ids.add(pid)
            material_ids.add(mid)
            session.add(
                SalesProfile(
                    id=pid,
                    owner_id=api[4],
                    name="Synthetic page " + str(index),
                    product="Synthetic product",
                    keywords=["synthetic"],
                    regions=[],
                    visibility="PRIVATE",
                    version=1,
                    created_at=now(),
                    updated_at=now(),
                )
            )
            raw = ("Synthetic source " + str(index)).encode()
            session.add(
                Material(
                    id=mid,
                    profile_id=profile["id"],
                    uploaded_by=api[4],
                    title="Synthetic " + str(index),
                    purpose="BUYER_DEMAND",
                    content=raw.decode(),
                    original_bytes=raw,
                    sha256=hashlib.sha256(raw).digest(),
                    created_at=now(),
                )
            )
    seen_profiles, seen_materials = set(), set()
    for page in range(1, 8):
        profiles = api[0].get("/api/v1/discovery/profiles", params={"page": page}).json()
        materials = (
            api[0]
            .get(f"/api/v1/discovery/profiles/{profile['id']}/materials", params={"page": page})
            .json()
        )
        seen_profiles.update(row["id"] for row in profiles["data"])
        seen_materials.update(row["id"] for row in materials["data"])
    assert profile_ids <= seen_profiles and material_ids <= seen_materials
