from datetime import timedelta

import pytest
from sqlalchemy import select, text

from app.auth.models import AuthSession, User
from app.auth.service import now

pytestmark = pytest.mark.integration


def login(api):
    client, _, email, password, _ = api
    return client.post(
        "/api/v1/auth/login",
        headers={"Origin": "http://testserver"},
        json={"email": email, "password": password},
    )


def test_login_me_logout_cookie_rotation(api):
    client, db, _, password, _ = api
    assert client.get("/api/v1/auth/me").status_code == 401
    result = login(api)
    assert result.status_code == 200
    cookie = result.headers["set-cookie"].lower()
    assert "httponly" in cookie and "samesite=lax" in cookie and "path=/api" in cookie
    assert password not in result.text and "password_hash" not in result.text
    old_token = client.cookies.get("esc_session")
    identity = client.get("/api/v1/auth/me")
    assert identity.status_code == 200
    assert identity.json()["data"]["user"]["role"] == "SALES_REP"
    with db.transaction() as session:
        auth = session.scalar(select(AuthSession).where(AuthSession.user_id == api[4]))
        assert auth.token_hash != old_token.encode() and len(auth.token_hash) == 32
    assert login(api).status_code == 200
    current_token = client.cookies.get("esc_session")
    assert current_token != old_token
    client.cookies.set("esc_session", old_token)
    assert client.get("/api/v1/auth/me").status_code == 401
    client.cookies.set("esc_session", current_token)
    me = client.get("/api/v1/auth/me").json()["data"]
    result = client.post(
        "/api/v1/auth/logout",
        headers={
            "Origin": "http://testserver",
            "X-CSRF-Token": me["csrf_token"],
        },
    )
    assert result.status_code == 204
    client.cookies.set("esc_session", current_token)
    assert client.get("/api/v1/auth/me").status_code == 401


def test_invalid_credentials_same_response(api):
    client, _, email, _, _ = api
    responses = [
        client.post(
            "/api/v1/auth/login",
            headers={"Origin": "http://testserver"},
            json={"email": value, "password": "synthetic-wrong"},
        )
        for value in (email, "not-present@example.test")
    ]
    assert all(r.status_code == 401 for r in responses)
    assert responses[0].json()["error"] == responses[1].json()["error"]


def test_role_and_csrf_enforced(api):
    client, _, email, password, _ = api
    assert login(api).status_code == 200
    assert client.get("/api/v1/admin/access-check").status_code == 403
    assert (
        client.post("/api/v1/auth/logout", headers={"Origin": "http://testserver"}).status_code
        == 403
    )
    csrf = client.get("/api/v1/auth/me").json()["data"]["csrf_token"]
    assert (
        client.post(
            "/api/v1/auth/logout",
            headers={
                "Origin": "https://evil.test",
                "X-CSRF-Token": csrf,
            },
        ).status_code
        == 403
    )
    assert (
        client.post(
            "/api/v1/auth/login",
            headers={"Origin": "http://testserver"},
            json={"email": email, "password": password, "role": "ADMIN"},
        ).status_code
        == 422
    )


@pytest.mark.parametrize("expiry", ["idle_expires_at", "absolute_expires_at"])
def test_expiry(api, expiry):
    client, db, _, _, user_id = api
    assert login(api).status_code == 200
    with db.transaction() as session:
        auth = session.scalar(select(AuthSession).where(AuthSession.user_id == user_id))
        setattr(auth, expiry, now() - timedelta(seconds=1))
    assert client.get("/api/v1/auth/me").status_code == 401


def test_inactive_and_role_change_immediately_effective(api):
    client, db, _, _, user_id = api
    assert login(api).status_code == 200
    with db.transaction() as session:
        session.get(User, user_id).role = "ADMIN"
    assert client.get("/api/v1/admin/access-check").status_code == 200
    with db.transaction() as session:
        session.get(User, user_id).is_active = False
    assert client.get("/api/v1/auth/me").status_code == 401


def test_real_transaction_rollback_and_pool_release(api):
    _, db, _, _, user_id = api
    with pytest.raises(RuntimeError), db.transaction() as session:
        session.get(User, user_id).name = "Should roll back"
        session.flush()
        raise RuntimeError("synthetic failure")
    with db.transaction() as session:
        assert session.get(User, user_id).name == "Synthetic M1 user"
        engine = session.scalar(
            text(
                "SELECT ENGINE FROM information_schema.tables "
                "WHERE table_schema=DATABASE() AND table_name='users'"
            )
        )
        assert engine == "InnoDB"
    assert db.engine.pool.checkedout() == 0


def test_throttle_persists_rejected_attempts(api):
    client, _, email, _, _ = api
    for _ in range(10):
        result = client.post(
            "/api/v1/auth/login",
            headers={"Origin": "http://testserver"},
            json={"email": email, "password": "synthetic-wrong"},
        )
        assert result.status_code == 401
    assert login(api).status_code == 429


def test_capabilities_real_dependency_state(api):
    client = api[0]
    login(api)
    response = client.get("/api/v1/capabilities")
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["storage"]["available"] is False  # explicit unavailable test adapter
    assert data["ai"]["mode"] == "MOCK"
    assert data["knowledge"]["available"] is False


@pytest.mark.parametrize(
    "role,expected",
    [
        ("ADMIN", 200),
        ("SALES_MANAGER", 403),
        ("SALES_REP", 403),
        ("READ_ONLY", 403),
    ],
)
def test_all_roles_come_from_database(api, role, expected):
    client, db, _, _, user_id = api
    with db.transaction() as session:
        session.get(User, user_id).role = role
    assert login(api).status_code == 200
    assert client.get("/api/v1/admin/access-check").status_code == expected
