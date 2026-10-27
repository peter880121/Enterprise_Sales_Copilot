"""Real HTTP roundtrip via Vite's same-origin proxy, using only a dedicated test DB."""

import argparse
import json
import os
import secrets
import subprocess
import sys
import time
from pathlib import Path
from uuid import uuid4

import httpx

from app.auth.models import Role, User
from app.auth.security import hash_password
from app.auth.service import now
from app.core.config import Settings, get_settings
from app.db import Database


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--database", required=True)
    parser.add_argument("--browser", action="store_true")
    args = parser.parse_args()
    if not args.database.startswith("esc_m1_test_") or not args.database.replace("_", "").isalnum():
        parser.error("Requires an existing, owned esc_m1_test_* schema")
    settings = get_settings()
    url = settings.sqlalchemy_url.set(database=args.database).render_as_string(hide_password=False)
    test_settings = Settings(database_url=url)
    db = Database(test_settings)
    if not db.ready():
        raise SystemExit("Dedicated database is not migrated; no changes made")
    email = f"proxy-{uuid4().hex}@example.test"
    password = secrets.token_urlsafe(24)
    with db.transaction() as session:
        current = now()
        session.add(
            User(
                id=str(uuid4()),
                name="Synthetic proxy user",
                email=email,
                email_normalized=email,
                password_hash=hash_password(password),
                role=Role.ADMIN,
                is_active=True,
                version=1,
                password_changed_at=current,
                created_at=current,
                updated_at=current,
            )
        )
    root = Path(__file__).resolve().parents[2]
    env = dict(
        os.environ,
        DATABASE_URL=url,
        ALLOWED_ORIGIN="http://localhost:5173",
        COOKIE_SECURE="false",
        AI_MODE="mock",
        API_PROXY_TARGET="http://127.0.0.1:8000",
    )
    flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    processes = []
    try:
        # No visible windows and no credential-bearing command arguments/log streams.
        for command, cwd in (
            (
                [
                    sys.executable,
                    "-m",
                    "uvicorn",
                    "app.main:create_app",
                    "--factory",
                    "--host",
                    "127.0.0.1",
                    "--port",
                    "8000",
                    "--no-access-log",
                ],
                root / "backend",
            ),
            (["node", "node_modules/vite/bin/vite.js", "--host", "127.0.0.1"], root / "frontend"),
        ):
            processes.append(
                subprocess.Popen(
                    command,
                    cwd=cwd,
                    env=env,
                    creationflags=flags,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
            )
        with httpx.Client(base_url="http://localhost:5173", timeout=8, trust_env=False) as client:
            for _ in range(40):
                if any(proc.poll() is not None for proc in processes):
                    raise RuntimeError("A test server exited before readiness")
                try:
                    if client.get("/api/v1/health/ready").status_code == 200:
                        break
                except httpx.HTTPError:
                    pass
                time.sleep(0.25)
            else:
                raise RuntimeError("Proxy readiness timeout")
            assert client.get("/").status_code == 200
            assert client.get("/api/v1/auth/me").status_code == 401
            result = client.post(
                "/api/v1/auth/login",
                headers={"Origin": "http://localhost:5173"},
                json={"email": email, "password": password},
            )
            assert result.status_code == 200
            assert client.get("/api/v1/auth/me").status_code == 200
            assert client.get("/api/v1/admin/access-check").status_code == 200
            capabilities = client.get("/api/v1/capabilities").json()["data"]
            assert capabilities["ai"]["mode"] == "MOCK"
            assert (
                client.post(
                    "/api/v1/auth/logout",
                    headers={
                        "Origin": "https://foreign.example.test",
                        "X-CSRF-Token": result.json()["data"]["csrf_token"],
                    },
                ).status_code
                == 403
            )
            assert (
                client.post(
                    "/api/v1/auth/logout",
                    headers={
                        "Origin": "http://localhost:5173",
                        "X-CSRF-Token": result.json()["data"]["csrf_token"],
                    },
                ).status_code
                == 204
            )
            assert client.get("/api/v1/auth/me").status_code == 401
            print(
                json.dumps(
                    {
                        "same_origin_proxy": "passed",
                        "login_me_logout": "passed",
                        "foreign_origin": "rejected",
                        "ai_mode": "MOCK",
                    }
                )
            )
            if args.browser:
                browser_env = dict(env, E2E_EMAIL=email, E2E_PASSWORD=password)
                browser = subprocess.run(
                    ["node", "node_modules/@playwright/test/cli.js", "test"],
                    cwd=root / "frontend",
                    env=browser_env,
                    check=False,
                    creationflags=flags,
                )
                if browser.returncode:
                    raise RuntimeError("Browser acceptance failed; inspect sanitized test output")
    finally:
        for proc in reversed(processes):
            proc.terminate()
        for proc in processes:
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=5)
        db.close()


if __name__ == "__main__":
    main()
