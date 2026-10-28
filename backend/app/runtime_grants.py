"""One-shot bootstrap for the isolated Compose runtime account; never run in API/worker."""

import os
import re

from sqlalchemy import create_engine, inspect, text

from app.core.config import get_settings
from app.schema import CURRENT_REVISION

# No schema-wide grants: new tables receive no implicit runtime privileges.
TABLE_PRIVILEGES = {
    "alembic_version": ("SELECT",),
    "users": (
        "SELECT",
        "INSERT",
        "UPDATE (name, email, email_normalized, password_hash, role, is_active, "
        "registration_status, deleted_at, password_changed_at, version, updated_at)",
    ),
    "system_guards": ("SELECT", "UPDATE (version)"),
    "sessions": ("SELECT", "INSERT", "UPDATE"),
    "auth_throttles": ("SELECT", "INSERT", "UPDATE"),
    "accounts": ("SELECT", "INSERT", "UPDATE"),
    "contacts": ("SELECT", "INSERT", "UPDATE"),
    "opportunities": ("SELECT", "INSERT", "UPDATE"),
    "activities": ("SELECT", "INSERT", "UPDATE"),
    "audit_events": ("SELECT", "INSERT"),
    "idempotency_records": ("SELECT", "INSERT"),
    "stored_objects": ("SELECT", "INSERT", "UPDATE (status, storage_version_id)"),
    "close_evidence": (
        "SELECT",
        "INSERT",
        "UPDATE (status, reviewed_by, reviewed_at, verification_note, "
        "approval_basis, version, updated_at)",
    ),
}


def validate_identities(manager, migration, runtime):
    identities = (manager, migration, runtime)
    if not all(
        isinstance(name, str) and re.fullmatch(r"[A-Za-z0-9_]{1,32}", name) for name in identities
    ):
        raise RuntimeError("Three explicit valid database identities required")
    if len(set(identities)) != 3:
        raise RuntimeError("Management, migration and runtime identities must differ")


def main():
    settings = get_settings()
    database = settings.sqlalchemy_url.database
    username = os.environ.get("MYSQL_RUNTIME_USER")
    password = os.environ.get("MYSQL_RUNTIME_PASSWORD", "")
    validate_identities(
        settings.sqlalchemy_url.username, os.environ.get("MYSQL_MIGRATION_USER"), username
    )
    if not re.fullmatch(r"[A-Za-z0-9_]{1,64}", database or ""):
        raise RuntimeError("Invalid isolated database/account identifier")
    if username == "root" or len(password) < 24:
        raise RuntimeError("Separate runtime account and strong secret required")
    engine = create_engine(settings.sqlalchemy_url, hide_parameters=True)
    try:
        with engine.begin() as connection:
            revision = connection.scalar(text("SELECT version_num FROM alembic_version"))
            if revision != CURRENT_REVISION:
                raise RuntimeError("M2 migration must complete before runtime grants")
            if not set(TABLE_PRIVILEGES).issubset(inspect(connection).get_table_names()):
                raise RuntimeError("Expected runtime tables are missing")
            connection.execute(
                text(f"CREATE USER IF NOT EXISTS '{username}'@'%' IDENTIFIED BY :password"),
                {"password": password},
            )
            # This identity belongs exclusively to this Compose instance. Reassert least privilege.
            connection.execute(text(f"REVOKE ALL PRIVILEGES, GRANT OPTION FROM '{username}'@'%'"))
            for table, privileges in TABLE_PRIVILEGES.items():
                connection.execute(
                    text(
                        f"GRANT {', '.join(privileges)} ON `{database}`.`{table}` "
                        f"TO '{username}'@'%'"
                    )
                )
        print("M2 runtime privileges initialized; audit history is SELECT/INSERT only.")
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
