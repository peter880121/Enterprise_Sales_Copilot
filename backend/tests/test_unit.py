import logging

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.ai import MockProvider
from app.auth.security import csrf_token, hash_password, token_hash, verify_password
from app.core.config import Settings
from app.core.logging import SafeFormatter
from app.db import Database
from app.main import create_app


@pytest.mark.parametrize(
    "overrides",
    [
        {"database_url": "sqlite:///:memory:"},
        {"csrf_signing_key": "short"},
        {"allowed_origin": "https://example.test/path"},
        {"app_env": "production", "cookie_secure": False},
        {
            "app_env": "production",
            "cookie_secure": True,
            "allowed_origin": "https://example.test",
            "enable_dev_seed": True,
        },
        {"minio_endpoint": "https://user:password@example.test"},
    ],
)
def test_invalid_configuration(config_values, overrides):
    with pytest.raises(ValidationError):
        Settings(**(config_values | overrides))


def test_required_configuration():
    with pytest.raises(ValidationError):
        Settings(_env_file=None, _env_ignore_empty=True, csrf_signing_key="")


def test_split_database_config_handles_special_password(config_values):
    settings = Settings(
        **(
            config_values
            | {
                "database_url": None,
                "db_host": "mysql",
                "db_user": "esc_app",
                "db_password": "synthetic@:/password",
                "db_name": "esc_m1_test_special",
            }
        )
    )
    assert settings.sqlalchemy_url.password == "synthetic@:/password"


def test_password_hash_and_csrf():
    password = "Synthetic-only-password-2026"
    encoded = hash_password(password)
    assert encoded.startswith("$argon2id$") and password not in encoded
    assert verify_password(encoded, password)
    assert not verify_password(encoded, "wrong")
    assert not verify_password("corrupt-hash", password)
    assert csrf_token("key", "session1", b"nonce") != csrf_token("key", "session2", b"nonce")
    assert len(token_hash("token")) == 32


def test_liveness_readiness_and_safe_errors(settings):
    # Deliberately unreachable TCP port verifies a genuine failed connection, not fake readiness.
    with TestClient(create_app(settings)) as client:
        assert client.get("/api/v1/health/live").status_code == 200
        result = client.get("/api/v1/health/ready")
        assert result.status_code == 503
        assert result.json()["error"]["code"] == "DEPENDENCY_UNAVAILABLE"
        assert "request_id" in result.json()
        assert client.get("/api/v1/auth/me").status_code == 401
        result = client.post(
            "/api/v1/auth/login",
            json={
                "email": "test@example.test",
                "password": "secret-do-not-reflect",
                "role": "ADMIN",
            },
        )
        assert result.status_code == 422
        assert "secret-do-not-reflect" not in result.text
        assert "password" not in result.text
        assert client.get("/unknown").json()["error"]["code"] == "NOT_FOUND"


def test_foreign_origin_rejected_before_database(settings):
    with TestClient(create_app(settings)) as client:
        result = client.post(
            "/api/v1/auth/login",
            headers={"Origin": "https://foreign.test"},
            json={"email": "test@example.test", "password": "synthetic"},
        )
        assert result.status_code == 403
        assert result.json()["error"]["code"] == "CSRF_INVALID"


def test_database_transaction_lifecycle(settings):
    db = Database(settings)
    created = []

    class FakeSession:
        def __init__(self):
            self.entered = self.exited = self.began = False
            created.append(self)

        def __enter__(self):
            self.entered = True
            return self

        def __exit__(self, *args):
            self.exited = True

        def begin(self):
            self.began = True
            return self

    db.sessions = FakeSession
    with db.transaction():
        pass
    with pytest.raises(RuntimeError), db.transaction():
        raise RuntimeError("synthetic failure")
    assert len(created) == 2
    assert all(s.entered and s.began and s.exited for s in created)
    db.close()


def test_mock_explicit_labelled_extraction_and_no_embedding():
    provider = MockProvider()
    assert provider.status()["mode"] == "MOCK"
    assert provider.chat("synthetic")["mode"] == "MOCK"
    result = provider.structured_generate("synthetic")
    assert result["mode"] == "MOCK"
    assert all(item["kind"] == "UNKNOWN" for item in result["facts"])
    assert result["proposed_changes"] == []
    with pytest.raises(NotImplementedError):
        provider.embed(["synthetic"])


def test_logs_only_operational_whitelist():
    record = logging.LogRecord("esc", logging.INFO, "", 1, "http_request", (), None)
    record.authorization = "do-not-log"
    record.password = "do-not-log"
    record.request_id = "synthetic-id"
    rendered = SafeFormatter().format(record)
    assert "synthetic-id" in rendered and "do-not-log" not in rendered
