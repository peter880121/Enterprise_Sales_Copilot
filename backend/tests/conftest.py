import os
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.engine import make_url

from app.auth.models import Role, User
from app.auth.security import hash_password
from app.auth.service import now
from app.core.config import Settings
from app.db import Database
from app.main import create_app


@pytest.fixture
def config_values():
    return {
        "_env_file": None,
        "app_env": "test",
        "database_url": "mysql+pymysql://synthetic:synthetic@127.0.0.1:1/esc_m1_test_unit",
        "csrf_signing_key": "synthetic-csrf-signing-key-only-for-tests-12345678",
        "minio_endpoint": "127.0.0.1",
        "minio_access_key": "synthetic-user",
        "minio_secret_key": "synthetic-secret",
        "allowed_origin": "http://testserver",
    }


@pytest.fixture
def settings(config_values):
    return Settings(**config_values)


class UnavailableStorage:
    def ready(self):
        return False


@pytest.fixture
def integration_db(config_values):
    url = os.getenv("TEST_DATABASE_URL")
    if not url:
        pytest.skip("TEST_DATABASE_URL is required; no SQLite or fake MySQL substitute")
    if not (make_url(url).database or "").startswith("esc_m1_test_"):
        pytest.fail("Refusing tests outside dedicated esc_m1_test_* database")
    config_values["database_url"] = url
    settings = Settings(**config_values)
    db = Database(settings)
    assert db.ready(), "Run Alembic against the dedicated test database first"
    yield settings, db
    db.close()


@pytest.fixture
def api(integration_db):
    settings, db = integration_db
    email = f"m1-{uuid4().hex}@example.test"
    password = "Synthetic-test-only-password-2026"
    user_id = str(uuid4())
    with db.transaction() as session:
        current = now()
        session.add(
            User(
                id=user_id,
                name="Synthetic M1 user",
                email=email,
                email_normalized=email,
                password_hash=hash_password(password),
                role=Role.SALES_REP,
                is_active=True,
                password_changed_at=current,
                version=1,
                created_at=current,
                updated_at=current,
            )
        )
    with TestClient(create_app(settings, db, UnavailableStorage())) as client:
        yield client, db, email, password, user_id
