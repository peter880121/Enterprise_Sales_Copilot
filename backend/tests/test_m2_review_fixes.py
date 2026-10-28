from datetime import date, datetime
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from app import runtime_grants
from app.sales.audit import AUDIT_FIELDS
from app.sales.models import Activity, CloseEvidence, Opportunity
from app.sales.service import audit_snapshot, snapshot


@pytest.mark.parametrize(
    "identities",
    [
        ("root", "migrate", "migrate"),
        ("root", "migrate", "root"),
        ("root", "root", "runtime"),
        *[
            (
                None if index == 0 else "root",
                None if index == 1 else "migrate",
                None if index == 2 else "runtime",
            )
            for index in range(3)
        ],
        *[(value, "migrate", "runtime") for value in ["", "bad'user", "a" * 33, "管理员"]],
        *[("root", value, "runtime") for value in ["", "bad-name", "a" * 33]],
        *[("root", "migrate", value) for value in ["", "bad-name", "a" * 33]],
    ],
)
def test_bad_identity_configuration_executes_no_sql(monkeypatch, identities):
    manager, migration, runtime = identities
    monkeypatch.setattr(
        runtime_grants,
        "get_settings",
        lambda: SimpleNamespace(
            sqlalchemy_url=SimpleNamespace(username=manager, database="esc_m1_test_config")
        ),
    )
    for key, value in [("MYSQL_MIGRATION_USER", migration), ("MYSQL_RUNTIME_USER", runtime)]:
        if value is None:
            monkeypatch.delenv(key, raising=False)
        else:
            monkeypatch.setenv(key, value)
    monkeypatch.setenv("MYSQL_RUNTIME_PASSWORD", "synthetic-long-configuration-test-password")
    connect = Mock(side_effect=AssertionError("No engine/SQL may run for bad identities"))
    monkeypatch.setattr(runtime_grants, "create_engine", connect)
    with pytest.raises(RuntimeError):
        runtime_grants.main()
    connect.assert_not_called()


def test_runtime_policy_has_no_delete_or_version_insert():
    assert runtime_grants.TABLE_PRIVILEGES["alembic_version"] == ("SELECT",)
    assert runtime_grants.TABLE_PRIVILEGES["audit_events"] == ("SELECT", "INSERT")
    assert runtime_grants.TABLE_PRIVILEGES["idempotency_records"] == ("SELECT", "INSERT")
    assert all(
        "DELETE" not in privilege
        for values in runtime_grants.TABLE_PRIVILEGES.values()
        for privilege in values
    )


@pytest.mark.parametrize("model", [Opportunity, Activity, CloseEvidence])
def test_audit_allowlist_does_not_follow_new_internal_orm_columns(monkeypatch, model):
    entity = model(
        id="synthetic-id",
        version=7,
        created_at=datetime(2026, 10, 27),
        updated_at=datetime(2026, 10, 27),
    )
    entity.synthetic_internal = "synthetic-only-internal-value"
    monkeypatch.setattr(
        entity,
        "__table__",
        SimpleNamespace(
            columns=[*model.__table__.columns, SimpleNamespace(key="synthetic_internal")]
        ),
    )
    if model is not Activity:
        entity.amount = Decimal("123.40")
    if model is CloseEvidence:
        entity.document_date = date(2026, 10, 27)
    response = snapshot(entity)
    audit = audit_snapshot(entity)
    assert response["synthetic_internal"] == "synthetic-only-internal-value"
    assert "synthetic_internal" not in audit
    assert set(audit) == set(AUDIT_FIELDS[model])
    assert audit["version"] == 7 and audit["created_at"] == "2026-10-27T00:00:00Z"
    if model is not Activity:
        assert audit["amount"] == "123.40"
    if model is CloseEvidence:
        assert audit["document_date"] == "2026-10-27"
