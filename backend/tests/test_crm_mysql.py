from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from uuid import uuid4

import pytest
from sqlalchemy import func, select

from app.auth.models import Role, User
from app.auth.service import now
from app.crm.models import Account, AuditEvent
from app.crm.schemas import AccountPatch
from app.crm.service import CRMService

pytestmark = pytest.mark.integration


def signed_in(api, role=Role.SALES_REP):
    client, db, email, password, user_id = api
    with db.seed.transaction() as session:
        session.get(User, user_id).role = role
    response = client.post(
        "/api/v1/auth/login",
        headers={"Origin": "http://testserver"},
        json={"email": email, "password": password},
    )
    assert response.status_code == 200
    return {"Origin": "http://testserver", "X-CSRF-Token": response.json()["data"]["csrf_token"]}


def another_owner(db, *, active=True, role=Role.SALES_REP):
    entity_id = str(uuid4())
    with db.seed.transaction() as session:
        current = now()
        session.add(
            User(
                id=entity_id,
                name="Synthetic other seller",
                email=f"{entity_id}@example.test",
                email_normalized=f"{entity_id}@example.test",
                password_hash="not-a-login-hash",
                role=role,
                is_active=active,
                version=1,
                password_changed_at=current,
                created_at=current,
                updated_at=current,
            )
        )
    return entity_id


def test_account_contact_crud_search_and_audit(api):
    client, db, _, _, actor = api
    headers = signed_in(api)
    response = client.post("/api/v1/accounts", headers=headers, json={"name": "Synthetic CRUD"})
    assert response.status_code == 201
    account = response.json()["data"]
    assert account["owner_id"] == actor and account["created_at"].endswith("Z")
    assert set(response.json()) == {"data", "request_id"}
    contact = client.post(
        "/api/v1/contacts",
        headers=headers,
        json={
            "name": "Synthetic Contact",
            "account_id": account["id"],
            "email": "contact@example.test",
        },
    )
    assert contact.status_code == 201
    contact = contact.json()["data"]
    assert contact["account_id"] == account["id"]
    for path in (f"/accounts/{account['id']}/contacts", "/contacts?q=Synthetic%20Contact"):
        result = client.get("/api/v1" + path).json()
        assert any(row["id"] == contact["id"] for row in result["data"])
        assert result["page"]["total"] >= 1
    updated = client.patch(
        f"/api/v1/accounts/{account['id']}",
        headers=headers,
        json={"expected_version": 1, "description": "Updated synthetic"},
    )
    assert updated.status_code == 200 and updated.json()["data"]["version"] == 2
    assert (
        client.patch(
            f"/api/v1/accounts/{account['id']}",
            headers=headers,
            json={"expected_version": 1, "name": "stale"},
        ).status_code
        == 409
    )
    patch = client.patch(
        f"/api/v1/contacts/{contact['id']}",
        headers=headers,
        json={"expected_version": 1, "title": "Synthetic buyer", "email": None},
    )
    assert patch.status_code == 200 and patch.json()["data"]["email"] is None
    assert client.get(f"/api/v1/contacts/{contact['id']}").json()["data"]["version"] == 2
    assert (
        client.patch(
            f"/api/v1/contacts/{contact['id']}",
            headers=headers,
            json={"expected_version": 2, "account_id": str(uuid4())},
        ).status_code
        == 422
    )
    with db.transaction() as session:
        events = session.scalars(
            select(AuditEvent)
            .where(AuditEvent.entity_id == account["id"])
            .order_by(AuditEvent.resulting_version)
        ).all()
        assert len(events) == 2
        assert events[1].before_state == events[0].after_state
        assert events[1].expected_version == 1 and events[1].resulting_version == 2


@pytest.mark.parametrize("role", list(Role))
def test_q03_all_roles_read_all_and_write_own_only(api, role):
    client, db, _, _, actor = api
    other = another_owner(db)
    headers = signed_in(api, Role.SALES_MANAGER)
    owned = client.post(
        "/api/v1/accounts", headers=headers, json={"name": "Synthetic foreign", "owner_id": other}
    ).json()["data"]
    contact = client.post(
        "/api/v1/contacts",
        headers=headers,
        json={"name": "Other contact", "account_id": owned["id"]},
    ).json()["data"]
    headers = signed_in(api, role)
    assert client.get(f"/api/v1/accounts/{owned['id']}").status_code == 200
    assert client.get(f"/api/v1/contacts/{contact['id']}").status_code == 200
    assert client.get("/api/v1/accounts?owner_id=" + other).json()["page"]["total"] >= 1
    expected = 200 if role in {Role.ADMIN, Role.SALES_MANAGER} else 403
    assert (
        client.patch(
            f"/api/v1/accounts/{owned['id']}",
            headers=headers,
            json={"expected_version": 1, "name": "Other changed"},
        ).status_code
        == expected
    )
    assert client.post(
        "/api/v1/contacts",
        headers=headers,
        json={"name": "Foreign account contact", "account_id": owned["id"]},
    ).status_code == (201 if role in {Role.ADMIN, Role.SALES_MANAGER} else 403)
    assert (
        client.patch(
            f"/api/v1/contacts/{contact['id']}",
            headers=headers,
            json={"expected_version": 1, "title": "Changed"},
        ).status_code
        == expected
    )
    result = client.post("/api/v1/accounts", headers=headers, json={"name": "Own"})
    assert result.status_code == (403 if role == Role.READ_ONLY else 201)
    if result.status_code == 201:
        account = result.json()["data"]
        assert account["owner_id"] == actor
        assert (
            client.patch(
                f"/api/v1/accounts/{account['id']}",
                headers=headers,
                json={"expected_version": 1, "industry": "Synthetic"},
            ).status_code
            == 200
        )
    assert client.post(
        "/api/v1/accounts", headers=headers, json={"name": "Assigned", "owner_id": other}
    ).status_code == (201 if role in {Role.ADMIN, Role.SALES_MANAGER} else 403)


def test_validation_absent_inactive_and_protected_fields(api):
    client, db, *_ = api
    headers = signed_in(api)
    assert client.post("/api/v1/accounts", json={"name": "No CSRF"}).status_code == 403
    for body in (
        {},
        {"name": " "},
        {"name": "x", "owner_id": "invalid"},
        {"name": "x", "is_active": False},
    ):
        assert client.post("/api/v1/accounts", headers=headers, json=body).status_code == 422
    for path in (f"/accounts/{uuid4()}", f"/contacts/{uuid4()}", f"/accounts/{uuid4()}/contacts"):
        assert client.get("/api/v1" + path).status_code == 404
    assert (
        client.post(
            "/api/v1/contacts", headers=headers, json={"name": "x", "account_id": str(uuid4())}
        ).status_code
        == 404
    )
    assert client.get("/api/v1/accounts?page_size=101").status_code == 422
    assert client.get("/api/v1/accounts?sort=owner_id").status_code == 422
    account = client.post("/api/v1/accounts", headers=headers, json={"name": "Retained"}).json()[
        "data"
    ]
    # Synthetic pre-existing inactive data fixture; no activation API is being implemented/tested.
    with db.transaction() as session:
        session.get(Account, account["id"]).is_active = False
    response = client.post(
        "/api/v1/contacts", headers=headers, json={"name": "Blocked", "account_id": account["id"]}
    )
    assert response.status_code == 422 and response.json()["error"]["code"] == "ACCOUNT_INACTIVE"
    assert client.get(f"/api/v1/accounts/{account['id']}").json()["data"]["is_active"] is False
    for path in (f"/accounts/{account['id']}/activation", f"/contacts/{uuid4()}/activation"):
        assert client.post("/api/v1" + path, headers=headers, json={}).status_code == 404


def test_owner_validation_and_transfer(api):
    client, db, *_ = api
    headers = signed_in(api, Role.ADMIN)
    for other in (
        str(uuid4()),
        another_owner(db, active=False),
        another_owner(db, role=Role.READ_ONLY),
    ):
        result = client.post(
            "/api/v1/accounts", headers=headers, json={"name": "Invalid owner", "owner_id": other}
        )
        assert result.status_code == 422 and result.json()["error"]["code"] == "OWNER_INVALID"
    account = client.post("/api/v1/accounts", headers=headers, json={"name": "Transfer"}).json()[
        "data"
    ]
    target = another_owner(db)
    result = client.patch(
        f"/api/v1/accounts/{account['id']}",
        headers=headers,
        json={"expected_version": 1, "owner_id": target},
    )
    assert result.status_code == 200 and result.json()["data"]["owner_id"] == target


def test_audit_failure_rolls_back_update(api, monkeypatch):
    client, db, *_ = api
    headers = signed_in(api)
    account = client.post("/api/v1/accounts", headers=headers, json={"name": "Rollback"}).json()[
        "data"
    ]

    def fail(*args, **kwargs):
        raise RuntimeError("synthetic audit failure")

    monkeypatch.setattr(CRMService, "audit", fail)
    response = client.patch(
        f"/api/v1/accounts/{account['id']}",
        headers=headers,
        json={"expected_version": 1, "name": "Must roll back"},
    )
    assert response.status_code == 500
    with db.transaction() as session:
        entity = session.get(Account, account["id"])
        assert entity.version == 1 and entity.name == "Rollback"
        assert (
            session.scalar(
                select(func.count())
                .select_from(AuditEvent)
                .where(AuditEvent.entity_id == entity.id)
            )
            == 1
        )


def test_real_mysql_two_sessions_same_version(api):
    client, db, *_ = api
    headers = signed_in(api)
    account = client.post("/api/v1/accounts", headers=headers, json={"name": "Concurrent"}).json()[
        "data"
    ]
    auth = client.app.state.auth
    identity = auth.authenticate(client.cookies.get("esc_session"))
    barrier = Barrier(2)

    def write(name):
        barrier.wait(timeout=10)
        try:
            CRMService(db).patch(
                Account,
                account["id"],
                AccountPatch(expected_version=1, name=name),
                identity,
                str(uuid4()),
            )
            return 200
        except Exception as exc:
            return getattr(exc, "status", 500)

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(write, ["Concurrent A", "Concurrent B"]))
    assert sorted(results) == [200, 409]
    with db.transaction() as session:
        assert session.get(Account, account["id"]).version == 2
        assert (
            session.scalar(
                select(func.count())
                .select_from(AuditEvent)
                .where(AuditEvent.entity_id == account["id"])
            )
            == 2
        )
