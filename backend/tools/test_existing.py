"""Rerun tests in an explicitly named task-owned schema without printing connection secrets."""

import argparse
import os
import subprocess
import sys

from app.core.config import get_settings


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--database", required=True)
    args = parser.parse_args()
    if not args.database.startswith("esc_m1_test_") or not args.database.replace("_", "").isalnum():
        parser.error("Requires a dedicated esc_m1_test_* schema")
    url = (
        get_settings()
        .sqlalchemy_url.set(database=args.database)
        .render_as_string(hide_password=False)
    )
    env = dict(os.environ, DATABASE_URL=url, TEST_DATABASE_URL=url, APP_ENV="test", AI_MODE="mock")
    for command in (["alembic", "upgrade", "head"], ["pytest", "-q"], ["alembic", "check"]):
        result = subprocess.run([sys.executable, "-m", *command], env=env, check=False)
        if result.returncode:
            return result.returncode
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
