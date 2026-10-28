"""Create/reuse only an isolated M2 test schema; never migrate the configured database.

Secrets remain in an ignored local config and child environments. No cleanup/deletion.
"""

import argparse
import json
import os
import secrets
import subprocess
import sys
from pathlib import Path
from uuid import uuid4

from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

from app.core.config import get_settings


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--prepare-only", action="store_true")
    parser.add_argument("--generate-migration", action="store_true")
    parser.add_argument("--evidence-dir", default=".local/m2-validation")
    args = parser.parse_args()
    settings = get_settings()
    root = Path(__file__).resolve().parents[2]
    directory = (root / args.evidence_dir).resolve()
    if not directory.is_relative_to((root / ".local").resolve()):
        raise RuntimeError("Evidence directory must remain inside .local")
    directory.mkdir(exist_ok=True)
    private = directory / "connection.json"
    server = create_engine(
        settings.sqlalchemy_url.set(database=None),
        hide_parameters=True,
        connect_args={"connect_timeout": 3, "read_timeout": 5, "write_timeout": 5},
    )
    with server.connect() as connection:
        version = str(connection.scalar(text("SELECT VERSION()")))
    if not version.startswith("8.4."):
        print(json.dumps({"status": "BLOCKED", "reason": "requires_mysql_8_4", "version": version}))
        return 1
    if not private.exists():
        suffix = uuid4().hex[:12]
        name, username, password = (
            "esc_m1_test_m2_" + suffix,
            "esc_m2_" + suffix,
            secrets.token_urlsafe(32),
        )
        migration_user = "esc_m2_migrate_" + suffix
        migration_password = secrets.token_urlsafe(32)
        with server.begin() as connection:
            connection.execute(text(f"CREATE DATABASE `{name}` CHARACTER SET utf8mb4"))
            connection.execute(
                text(f"CREATE USER '{username}'@'%' IDENTIFIED BY :password"),
                {"password": password},
            )
        with server.begin() as connection:
            connection.execute(
                text(f"CREATE USER '{migration_user}'@'%' IDENTIFIED BY :password"),
                {"password": migration_password},
            )
            connection.execute(text(f"GRANT ALL ON `{name}`.* TO '{migration_user}'@'%'"))
        url = settings.sqlalchemy_url.set(database=name, username=username, password=password)
        migration_connection = settings.sqlalchemy_url.set(
            database=name, username=migration_user, password=migration_password
        )
        private.write_text(
            json.dumps(
                {
                    "migration_url": migration_connection.render_as_string(hide_password=False),
                    "database": name,
                    "username": username,
                    "url": url.render_as_string(hide_password=False),
                }
            )
        )
    config = json.loads(private.read_text())
    name, username = config["database"], config["username"]
    if (
        not name.startswith("esc_m1_test_m2_")
        or not name.replace("_", "").isalnum()
        or not username.startswith("esc_m2_")
        or not username.replace("_", "").isalnum()
    ):
        raise RuntimeError("refusing unsafe test resource name")
    if name == settings.sqlalchemy_url.database:
        raise RuntimeError("refusing configured database")
    if "migration_url" not in config:
        raise RuntimeError("Old test configuration preserved; choose a fresh --evidence-dir")
    migration_url = config["migration_url"]
    if make_url(migration_url).database != name or make_url(config["url"]).database != name:
        raise RuntimeError("Test URLs must match the validated isolated database")
    env = dict(
        os.environ,
        DATABASE_URL=migration_url,
        TEST_DATABASE_URL=config["url"],
        APP_ENV="test",
        AI_MODE="mock",
    )

    def run(command, log):
        output = subprocess.run(
            [sys.executable, "-m", *command], env=env, capture_output=True, check=False
        )
        (directory / log).write_bytes(output.stdout + b"\n" + output.stderr)
        print(
            json.dumps(
                {
                    "command": " ".join(command),
                    "returncode": output.returncode,
                    "evidence": str(directory / log),
                }
            )
        )
        return output.returncode

    if args.generate_migration:
        return run(
            ["alembic", "revision", "--autogenerate", "-m", "sales core", "--rev-id", "0003_sales"],
            "generate.log",
        )
    if run(["alembic", "upgrade", "head"], "migration.log"):
        return 1
    env.update(
        DATABASE_URL=settings.sqlalchemy_url.set(database=name).render_as_string(
            hide_password=False
        ),
        MYSQL_MIGRATION_USER=make_url(migration_url).username,
        MYSQL_RUNTIME_USER=username,
        MYSQL_RUNTIME_PASSWORD=make_url(config["url"]).password,
        TEST_SEED_DATABASE_URL=migration_url,
    )
    if run(["app.runtime_grants"], "runtime-grants.log"):
        return 1
    server.dispose()
    print(
        json.dumps(
            {"version": version, "database": name, "dedicated_user": username, "mode": "MOCK"}
        )
    )
    if args.prepare_only:
        return 0
    env["DATABASE_URL"] = config["url"]
    if run(["pytest", "-q"], "pytest.log"):
        return 1
    env["DATABASE_URL"] = migration_url
    return run(["alembic", "check"], "model-check.log")


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(json.dumps({"status": "BLOCKED", "error_type": type(exc).__name__}))
        raise SystemExit(1) from None
