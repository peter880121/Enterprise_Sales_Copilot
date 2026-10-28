import os
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.engine import make_url
from test_users_mysql import PASSWORD, login_as

from app.auth.models import Role, User
from app.auth.security import hash_password
from app.auth.service import now
from app.core.config import Settings
from app.core.errors import AppError
from app.db import Database
from app.main import create_app
from app.users.schemas import UserCommand, UserPatch
from app.users.service import UserService

pytestmark = pytest.mark.integration


def test_last_admin_global_guard_serializes_disable_other_and_self_demotion(config_values):
    runtime, seed = (
        os.getenv("TEST_LAST_ADMIN_DATABASE_URL"),
        os.getenv("TEST_LAST_ADMIN_SEED_DATABASE_URL"),
    )
    if not runtime or not seed:
        pytest.skip("Dedicated fresh last-admin scenario database is required")
    runtime_url, seed_url = make_url(runtime), make_url(seed)
    assert (runtime_url.database or "").startswith(
        "esc_m1_test_"
    ) and "lastadmin" in runtime_url.database
    assert (runtime_url.host, runtime_url.port, runtime_url.database) == (
        seed_url.host,
        seed_url.port,
        seed_url.database,
    )
    assert runtime_url.username != seed_url.username
    settings = Settings(**{**config_values, "database_url": runtime})
    db, preparation = (
        Database(settings),
        Database(Settings(**{**config_values, "database_url": seed})),
    )
    clients = []
    try:
        assert db.ready()
        with preparation.transaction() as session:
            assert session.scalar(select(func.count()).select_from(User)) == 0, (
                "Use a fresh isolated scenario database; no cleanup is performed"
            )
            encoded = hash_password(PASSWORD)
            ids = [str(uuid4()), str(uuid4())]
            emails = [f"last-admin-{uid}@example.test" for uid in ids]
            for uid, email in zip(ids, emails, strict=True):
                session.add(
                    User(
                        id=uid,
                        name="Synthetic last administrator",
                        email=email,
                        email_normalized=email,
                        password_hash=encoded,
                        role=Role.ADMIN,
                        is_active=True,
                        registration_status="APPROVED",
                        version=1,
                        password_changed_at=now(),
                        created_at=now(),
                        updated_at=now(),
                    )
                )
        app = create_app(settings, db)
        clients = [TestClient(app), TestClient(app)]
        for client, email in zip(clients, emails, strict=True):
            login_as(client, email)
        identities = [
            app.state.auth.authenticate(client.cookies.get("esc_session")) for client in clients
        ]
        barrier = Barrier(2)

        def disable_other(index):
            barrier.wait(timeout=10)
            try:
                UserService(db, settings).mutate(
                    identities[index],
                    ids[1 - index],
                    "update",
                    UserPatch(
                        expected_version=1, is_active=False, reason="Synthetic concurrent disable"
                    ),
                    str(uuid4()),
                )
                return 200
            except AppError as exc:
                return exc.status

        with ThreadPoolExecutor(max_workers=2) as executor:
            assert sorted(executor.map(disable_other, range(2))) == [200, 401]
        with db.transaction() as session:
            active = session.scalar(
                select(User).where(User.role == Role.ADMIN, User.is_active.is_(True))
            )
            survivor, version = active.id, active.version
            assert (
                session.scalar(
                    select(func.count())
                    .select_from(User)
                    .where(User.role == Role.ADMIN, User.is_active.is_(True))
                )
                == 1
            )
        survivor_index = ids.index(survivor)
        manager = UserService(db, settings)
        for action, body in [
            (
                "delete",
                UserCommand(expected_version=version, reason="Synthetic last admin deletion"),
            ),
            (
                "update",
                UserPatch(
                    expected_version=version, is_active=False, reason="Synthetic last admin disable"
                ),
            ),
            (
                "update",
                UserPatch(
                    expected_version=version,
                    role=Role.READ_ONLY,
                    reason="Synthetic last admin demotion",
                ),
            ),
        ]:
            with pytest.raises(AppError) as exc:
                manager.mutate(identities[survivor_index], survivor, action, body, str(uuid4()))
            assert exc.value.code == "LAST_ADMIN_REQUIRED"
        other = ids[1 - survivor_index]
        with db.transaction() as session:
            other_version = session.get(User, other).version
        manager.mutate(
            identities[survivor_index],
            other,
            "update",
            UserPatch(
                expected_version=other_version,
                is_active=True,
                reason="Synthetic restore second admin",
            ),
            str(uuid4()),
        )
        for client, email in zip(clients, emails, strict=True):
            login_as(client, email)
        identities = [
            app.state.auth.authenticate(client.cookies.get("esc_session")) for client in clients
        ]
        with db.transaction() as session:
            versions = {uid: session.get(User, uid).version for uid in ids}
        barrier = Barrier(2)

        def demote_self(index):
            barrier.wait(timeout=10)
            try:
                manager.mutate(
                    identities[index],
                    ids[index],
                    "update",
                    UserPatch(
                        expected_version=versions[ids[index]],
                        role=Role.READ_ONLY,
                        reason="Synthetic concurrent demotion",
                    ),
                    str(uuid4()),
                )
                return 200
            except AppError as exc:
                assert exc.code == "LAST_ADMIN_REQUIRED"
                return exc.status

        with ThreadPoolExecutor(max_workers=2) as executor:
            assert sorted(executor.map(demote_self, range(2))) == [200, 409]
        with db.transaction() as session:
            assert (
                session.scalar(
                    select(func.count())
                    .select_from(User)
                    .where(User.role == Role.ADMIN, User.is_active.is_(True))
                )
                == 1
            )
    finally:
        for client in clients:
            client.close()
        db.close()
        preparation.close()
