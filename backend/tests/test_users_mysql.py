import json
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, insert, select
from test_crm_mysql import signed_in

from app.auth.models import AuthSession, Role, User
from app.core.errors import AppError
from app.crm.models import Account, AuditEvent
from app.users.schemas import UserCreate
from app.users.service import UserService

pytestmark = pytest.mark.integration
PASSWORD = "Synthetic-user-test-password-2026"


def create(api, headers, **extra):
    body = {
        "name": "Synthetic managed user",
        "email": f"managed-{uuid4().hex}@example.test",
        "password": PASSWORD,
        "role": "SALES_REP",
        **extra,
    }
    response = api[0].post("/api/v1/users", headers=headers, json=body)
    assert response.status_code == 201, response.json()
    assert (
        "password" not in response.json()["data"] and "password_hash" not in response.json()["data"]
    )
    return response.json()["data"]


def login_as(client, email, password=PASSWORD):
    response = client.post(
        "/api/v1/auth/login",
        headers={"Origin": "http://testserver"},
        json={"email": email, "password": password},
    )
    assert response.status_code == 200
    return {"Origin": "http://testserver", "X-CSRF-Token": response.json()["data"]["csrf_token"]}


def test_registration_is_pending_without_access_and_duplicate_response_is_uniform(api):
    client, db, *_ = api
    email = f"registered-{uuid4().hex}@example.test"
    body = {"name": "Synthetic registration", "email": email, "password": PASSWORD}
    response = client.post(
        "/api/v1/auth/register", headers={"Origin": "http://testserver"}, json=body
    )
    assert response.status_code == 202 and "set-cookie" not in response.headers
    duplicate = client.post(
        "/api/v1/auth/register",
        headers={"Origin": "http://testserver"},
        json={**body, "email": email.upper()},
    )
    assert duplicate.status_code == 202 and response.json()["data"] == duplicate.json()["data"]
    assert client.get("/api/v1/accounts").status_code == 401
    assert (
        client.post(
            "/api/v1/auth/login",
            headers={"Origin": "http://testserver"},
            json={"email": email, "password": PASSWORD},
        ).status_code
        == 401
    )
    with db.transaction() as session:
        user = session.scalar(select(User).where(User.email_normalized == email))
        assert (
            user.registration_status == "PENDING"
            and not user.is_active
            and user.role == "READ_ONLY"
        )
        events = session.scalars(select(AuditEvent).where(AuditEvent.entity_id == user.id)).all()
        assert len(events) == 1 and events[0].actor_id is None
    for invalid in [
        {**body, "role": "ADMIN"},
        {**body, "is_active": True},
        {**body, "password": "short"},
        {**body, "email": "person@a..example.test"},
    ]:
        assert (
            client.post(
                "/api/v1/auth/register", headers={"Origin": "http://testserver"}, json=invalid
            ).status_code
            == 422
        )
    assert (
        client.post(
            "/api/v1/auth/register", headers={"Origin": "https://untrusted.example.test"}, json=body
        ).status_code
        == 403
    )


def test_approve_registration_and_no_direct_activation_bypass(api):
    client, db, *_ = api
    headers = signed_in(api, Role.ADMIN)
    email = f"pending-{uuid4().hex}@example.test"
    assert (
        client.post(
            "/api/v1/auth/register",
            headers={"Origin": "http://testserver"},
            json={"name": "Pending synthetic", "email": email, "password": PASSWORD},
        ).status_code
        == 202
    )
    pending = client.get("/api/v1/users", params={"q": email, "status": "PENDING"}).json()["data"][
        0
    ]
    assert (
        client.patch(
            f"/api/v1/users/{pending['id']}",
            headers=headers,
            json={"expected_version": 1, "reason": "Synthetic", "is_active": True},
        ).json()["error"]["code"]
        == "REGISTRATION_PENDING"
    )
    response = client.post(
        f"/api/v1/users/{pending['id']}/approve",
        headers=headers,
        json={
            "expected_version": 1,
            "reason": "Synthetic reviewed registration",
            "role": "SALES_REP",
        },
    )
    assert response.status_code == 200 and response.json()["data"]["is_active"]
    assert response.json()["data"]["version"] == 2
    new = TestClient(client.app)
    try:
        own_headers = login_as(new, email)
        assert new.get("/api/v1/accounts").status_code == 200
        assert new.get("/api/v1/users").status_code == 403
        assert (
            new.post(
                "/api/v1/accounts",
                headers=own_headers,
                json={"name": "Registration synthetic account"},
            ).status_code
            == 201
        )
    finally:
        new.close()


def test_management_crud_versions_session_revocation_and_retained_links(api):
    client, db, *_ = api
    headers = signed_in(api, Role.ADMIN)
    user = create(api, headers)
    target = TestClient(client.app)
    try:
        login_as(target, user["email"])
        account = client.post(
            "/api/v1/accounts",
            headers=headers,
            json={"name": "Retained owner synthetic", "owner_id": user["id"]},
        ).json()["data"]
        response = client.patch(
            f"/api/v1/users/{user['id']}",
            headers=headers,
            json={
                "expected_version": 1,
                "name": "Updated synthetic",
                "role": "READ_ONLY",
                "reason": "Synthetic role update",
            },
        )
        assert response.status_code == 200 and response.json()["data"]["version"] == 2
        assert target.get("/api/v1/auth/me").status_code == 401
        assert (
            client.patch(
                f"/api/v1/users/{user['id']}",
                headers=headers,
                json={"expected_version": 1, "name": "Stale", "reason": "Synthetic stale"},
            ).json()["error"]["code"]
            == "VERSION_CONFLICT"
        )
        login_as(target, user["email"])
        assert (
            target.post(
                "/api/v1/accounts",
                headers={
                    "Origin": "http://testserver",
                    "X-CSRF-Token": target.get("/api/v1/auth/me").json()["data"]["csrf_token"],
                },
                json={"name": "Denied"},
            ).status_code
            == 403
        )
        response = client.request(
            "DELETE",
            f"/api/v1/users/{user['id']}",
            headers=headers,
            json={"expected_version": 2, "reason": "Synthetic removal"},
        )
        assert response.status_code == 200 and response.json()["data"]["deleted_at"]
        assert target.get("/api/v1/auth/me").status_code == 401
        assert (
            client.get(f"/api/v1/accounts/{account['id']}").json()["data"]["owner_id"] == user["id"]
        )
        assert (
            client.get("/api/v1/users", params={"q": user["email"], "status": "DELETED"}).json()[
                "page"
            ]["total"]
            == 1
        )
        restored = client.post(
            f"/api/v1/users/{user['id']}/restore",
            headers=headers,
            json={"expected_version": 3, "reason": "Synthetic restore"},
        )
        assert restored.status_code == 200 and restored.json()["data"]["version"] == 4
        login_as(target, user["email"])
        with db.transaction() as session:
            assert session.get(Account, account["id"]).owner_id == user["id"]
            assert (
                session.scalar(
                    select(func.count())
                    .select_from(AuditEvent)
                    .where(AuditEvent.entity_id == user["id"])
                )
                == 4
            )
    finally:
        target.close()


@pytest.mark.parametrize("role", [Role.SALES_MANAGER, Role.SALES_REP, Role.READ_ONLY])
def test_all_management_apis_deny_non_admin_direct_calls(api, role):
    client, db, *_ = api
    admin_headers = signed_in(api, Role.ADMIN)
    user = create(api, admin_headers)
    headers = signed_in(api, role)
    before = user["version"]
    for path in ["/users", "/users/roles", f"/users/{user['id']}", f"/users/{user['id']}/history"]:
        assert client.get("/api/v1" + path).status_code == 403
    calls = [
        (
            "POST",
            "/users",
            {
                "name": "Denied",
                "email": "denied@example.test",
                "password": PASSWORD,
                "role": "ADMIN",
            },
        ),
        (
            "PATCH",
            f"/users/{user['id']}",
            {"expected_version": 1, "reason": "Denied", "role": "ADMIN"},
        ),
        ("DELETE", f"/users/{user['id']}", {"expected_version": 1, "reason": "Denied"}),
        (
            "POST",
            f"/users/{user['id']}/approve",
            {"expected_version": 1, "reason": "Denied", "role": "ADMIN"},
        ),
        ("POST", f"/users/{user['id']}/restore", {"expected_version": 1, "reason": "Denied"}),
        (
            "POST",
            f"/users/{user['id']}/reset-password",
            {"expected_version": 1, "reason": "Denied", "new_password": PASSWORD},
        ),
    ]
    for method, path, body in calls:
        assert (
            client.request(
                method,
                "/api/v1" + path,
                headers={**headers, "Idempotency-Key": str(uuid4())},
                json=body,
            ).status_code
            == 403
        )
    with db.transaction() as session:
        assert session.get(User, user["id"]).version == before
        assert (
            session.scalar(
                select(func.count())
                .select_from(AuditEvent)
                .where(AuditEvent.entity_id == user["id"])
            )
            == 1
        )


def test_reset_password_idempotency_revoke_all_sessions_and_audit_without_secrets(api):
    client, db, *_ = api
    headers = signed_in(api, Role.ADMIN)
    user = create(api, headers)
    target, second = TestClient(client.app), TestClient(client.app)
    try:
        login_as(target, user["email"])
        login_as(second, user["email"])
        new_password = "Synthetic-replacement-password-2026"
        body = {
            "expected_version": 1,
            "reason": "Synthetic password reset",
            "new_password": new_password,
        }
        key = str(uuid4())
        response = client.post(
            f"/api/v1/users/{user['id']}/reset-password",
            headers={**headers, "Idempotency-Key": key},
            json=body,
        )
        assert response.status_code == 200 and response.json()["data"]["version"] == 2
        replay = client.post(
            f"/api/v1/users/{user['id']}/reset-password",
            headers={**headers, "Idempotency-Key": key},
            json=body,
        )
        assert replay.status_code == 200 and replay.json()["data"] == response.json()["data"]
        reused = client.post(
            f"/api/v1/users/{user['id']}/reset-password",
            headers={**headers, "Idempotency-Key": key},
            json={**body, "new_password": "Another-synthetic-password-2026"},
        )
        assert reused.json()["error"]["code"] == "IDEMPOTENCY_KEY_REUSED"
        assert (
            target.get("/api/v1/auth/me").status_code
            == second.get("/api/v1/auth/me").status_code
            == 401
        )
        assert (
            target.post(
                "/api/v1/auth/login",
                headers={"Origin": "http://testserver"},
                json={"email": user["email"], "password": PASSWORD},
            ).status_code
            == 401
        )
        login_as(target, user["email"], new_password)
        history = client.get(f"/api/v1/users/{user['id']}/history").json()
        assert history["page"]["total"] == 2
        encoded = json.dumps(history)
        assert (
            PASSWORD not in encoded
            and new_password not in encoded
            and "password_hash" not in encoded
            and "$argon2" not in encoded
        )
    finally:
        target.close()
        second.close()


def test_user_audit_failure_rolls_back_user_and_session_revocation(api, monkeypatch):
    client, db, *_ = api
    headers = signed_in(api, Role.ADMIN)
    user = create(api, headers)
    target = TestClient(client.app)
    try:
        login_as(target, user["email"])

        def fail(*args, **kwargs):
            raise RuntimeError("synthetic user audit failure")

        monkeypatch.setattr(UserService, "audit", fail)
        response = client.patch(
            f"/api/v1/users/{user['id']}",
            headers=headers,
            json={"expected_version": 1, "reason": "Synthetic rollback", "is_active": False},
        )
        assert response.status_code == 500
        assert target.get("/api/v1/auth/me").status_code == 200
        with db.transaction() as session:
            current = session.get(User, user["id"])
            assert current.is_active and current.version == 1
            assert all(
                row.revoked_at is None
                for row in session.scalars(
                    select(AuthSession).where(AuthSession.user_id == user["id"])
                )
            )
    finally:
        target.close()


@pytest.mark.parametrize("operation", ["registration", "creation", "update"])
def test_duplicate_audit_is_not_misclassified_as_duplicate_email(api, monkeypatch, operation):
    client, db, *_ = api
    headers = signed_in(api, Role.ADMIN)
    user = create(api, headers)
    target = TestClient(client.app)
    try:
        login_as(target, user["email"])
        with db.transaction() as session:
            event = session.scalar(select(AuditEvent).where(AuditEvent.entity_id == user["id"]))
            duplicate = {
                column.name: getattr(event, column.name) for column in AuditEvent.__table__.columns
            }
            count_before = session.scalar(select(func.count()).select_from(AuditEvent))

        def duplicate_audit(self, session, *args, **kwargs):
            # The real MySQL server raises 1062 on the existing audit primary key.
            session.execute(insert(AuditEvent).values(**duplicate))

        monkeypatch.setattr(UserService, "audit", duplicate_audit)
        email = f"audit-failure-{uuid4().hex}@example.test"
        body = {"name": "Synthetic failed audit", "email": email, "password": PASSWORD}
        if operation == "registration":
            response = client.post(
                "/api/v1/auth/register", headers={"Origin": "http://testserver"}, json=body
            )
        elif operation == "creation":
            response = client.post(
                "/api/v1/users", headers=headers, json={**body, "role": "SALES_REP"}
            )
        else:
            response = client.patch(
                f"/api/v1/users/{user['id']}",
                headers=headers,
                json={
                    "expected_version": 1,
                    "reason": "Synthetic audit rollback",
                    "email": email,
                    "is_active": False,
                },
            )
        assert response.status_code == 503
        assert response.json()["error"]["code"] == "DEPENDENCY_UNAVAILABLE"
        assert target.get("/api/v1/auth/me").status_code == 200
        with db.transaction() as session:
            assert session.scalar(select(User.id).where(User.email_normalized == email)) is None
            unchanged = session.get(User, user["id"])
            assert (
                unchanged.version == 1 and unchanged.is_active and unchanged.email == user["email"]
            )
            assert session.scalar(select(func.count()).select_from(AuditEvent)) == count_before
    finally:
        target.close()


def test_profile_and_password_change_do_not_allow_role_escalation(api):
    client, db, email, password, uid = api
    headers = signed_in(api)
    profile = {
        "expected_version": 1,
        "name": "Synthetic profile",
        "email": f"profile-{uuid4().hex}@example.test",
        "current_password": password,
    }
    assert (
        client.patch(
            "/api/v1/auth/profile", headers=headers, json={**profile, "role": "ADMIN"}
        ).status_code
        == 422
    )
    assert (
        client.patch(
            "/api/v1/auth/profile", headers=headers, json={**profile, "current_password": "wrong"}
        ).json()["error"]["code"]
        == "WRONG_PASSWORD"
    )
    assert client.get("/api/v1/auth/me").status_code == 200
    response = client.patch("/api/v1/auth/profile", headers=headers, json=profile)
    assert response.status_code == 200 and response.json()["data"]["version"] == 2
    assert client.get("/api/v1/auth/me").status_code == 401
    headers = login_as(client, profile["email"], password)
    assert (
        client.post(
            "/api/v1/auth/change-password",
            headers=headers,
            json={"current_password": password, "new_password": password},
        ).json()["error"]["code"]
        == "PASSWORD_UNCHANGED"
    )
    new_password = "Synthetic-self-changed-password-2026"
    assert (
        client.post(
            "/api/v1/auth/change-password",
            headers=headers,
            json={"current_password": password, "new_password": new_password},
        ).status_code
        == 204
    )
    assert client.get("/api/v1/auth/me").status_code == 401
    login_as(client, profile["email"], new_password)
    assert client.get("/api/v1/auth/me").json()["data"]["user"]["role"] == "SALES_REP"


def test_registration_rate_limit_is_real_and_persists(api):
    client = TestClient(api[0].app, client=("rate-" + uuid4().hex, 50000))
    body = {
        "name": "Synthetic rate",
        "email": f"rate-{uuid4().hex}@example.test",
        "password": PASSWORD,
    }
    try:
        for _ in range(20):
            assert (
                client.post(
                    "/api/v1/auth/register", headers={"Origin": "http://testserver"}, json=body
                ).status_code
                == 202
            )
        assert (
            client.post(
                "/api/v1/auth/register", headers={"Origin": "http://testserver"}, json=body
            ).status_code
            == 429
        )
    finally:
        client.close()


def test_revoked_session_cannot_write_after_earlier_authentication(api):
    client, db, *_ = api
    headers = signed_in(api, Role.ADMIN)
    identity = client.app.state.auth.authenticate(client.cookies.get("esc_session"))
    assert client.post("/api/v1/auth/logout", headers=headers).status_code == 204
    with db.transaction() as session:
        before = session.scalar(select(func.count()).select_from(User))
    with pytest.raises(AppError) as exc:
        UserService(db, client.app.state.settings).create(
            identity,
            UserCreate(
                name="Denied stale identity",
                email=f"stale-{uuid4().hex}@example.test",
                password=PASSWORD,
                role="ADMIN",
            ),
            str(uuid4()),
        )
    assert exc.value.code == "SESSION_EXPIRED"
    with db.transaction() as session:
        assert session.scalar(select(func.count()).select_from(User)) == before
