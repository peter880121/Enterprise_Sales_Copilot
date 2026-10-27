"""Use .env's services with a newly owned test schema/bucket. Never migrate the configured DB."""

import io
import json
import os
import subprocess
import sys
from uuid import uuid4

from sqlalchemy import create_engine, text

from app.core.config import get_settings
from app.storage import ObjectStorage


def main():
    settings = get_settings()
    test_name = "esc_m1_test_" + uuid4().hex[:12]
    # Credentials from .env, same host/port, but deliberately no configured database.
    server = create_engine(
        settings.sqlalchemy_url.set(database=None),
        hide_parameters=True,
        connect_args={"connect_timeout": 3},
        pool_pre_ping=True,
    )
    try:
        with server.begin() as conn:
            version = conn.scalar(text("SELECT VERSION()"))
            conn.execute(text(f"CREATE DATABASE `{test_name}` CHARACTER SET utf8mb4"))
    except Exception as exc:
        print(json.dumps({"database_tests": "blocked", "error_type": type(exc).__name__}))
        server.dispose()
        return 1
    # Keep the isolated schema for evidence; never DROP any database automatically.
    test_url = settings.sqlalchemy_url.set(database=test_name).render_as_string(hide_password=False)
    env = dict(
        os.environ,
        DATABASE_URL=test_url,
        TEST_DATABASE_URL=test_url,
        APP_ENV="test",
        AI_MODE="mock",
    )
    print(
        json.dumps(
            {
                "isolated_test_database": test_name,
                "mysql_version": version,
                "mysql_8_4_acceptance": str(version).startswith("8.4."),
            }
        )
    )
    results = []
    for args in (["alembic", "upgrade", "head"], ["pytest", "-q"], ["alembic", "check"]):
        # Only sanitized test output should be emitted by the subprocesses.
        result = subprocess.run([sys.executable, "-m", *args], env=env, check=False)
        results.append({"command": " ".join(args), "returncode": result.returncode})
        if result.returncode:
            break
    server.dispose()

    storage = ObjectStorage(settings)
    bucket = "esc-m1-test-" + uuid4().hex[:12]
    store_result = {"bucket": bucket, "status": "unverified"}
    try:
        # Creates only a fresh namespace; does not modify existing buckets, users or policies.
        for _ in range(2):
            if not storage.client.bucket_exists(bucket):
                storage.client.make_bucket(bucket)
        payload = b"Synthetic M1 connectivity test. No customer data."
        storage.client.put_object(bucket, "probe.txt", io.BytesIO(payload), len(payload))
        response = storage.client.get_object(bucket, "probe.txt")
        try:
            assert response.read() == payload
        finally:
            response.close()
            response.release_conn()
        storage.client.stat_object(bucket, "probe.txt")
        store_result["status"] = "put_get_stat_passed"
        store_result["policy_isolation"] = "not_verified_against_existing_credentials"
    except Exception as exc:
        store_result["status"] = "blocked"
        store_result["error_type"] = type(exc).__name__
        store_result["s3_code"] = getattr(exc, "code", None)
    print(json.dumps({"commands": results, "storage": store_result, "ai_calls": 0}))
    return 0 if all(r["returncode"] == 0 for r in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
