"""Provision a fresh native dev schema/config using .env connection info, preserving the source."""

from pathlib import Path
from uuid import uuid4

from sqlalchemy import create_engine, text

from app.core.config import get_settings


def main():
    root = Path(__file__).resolve().parents[2]
    target = root / ".local" / "native.env"
    if target.exists():
        raise SystemExit("Existing .local/native.env preserved. No changes made.")
    settings = get_settings()
    name = "esc_dev_" + uuid4().hex[:12]
    engine = create_engine(
        settings.sqlalchemy_url.set(database=None),
        hide_parameters=True,
        connect_args={"connect_timeout": 3},
    )
    try:
        with engine.begin() as connection:
            connection.execute(text(f"CREATE DATABASE `{name}` CHARACTER SET utf8mb4"))
    except Exception as exc:
        raise SystemExit(
            f"Dev schema creation blocked ({type(exc).__name__}); no source DB migration"
        ) from None
    finally:
        engine.dispose()
    values = {
        "APP_ENV": "development",
        "DATABASE_URL": settings.sqlalchemy_url.set(database=name).render_as_string(
            hide_password=False
        ),
        "SESSION_SECRET": settings.csrf_signing_key.get_secret_value(),
        "ALLOWED_ORIGIN": "http://localhost:5173",
        "COOKIE_SECURE": "false",
        "MINIO_ENDPOINT": settings.minio_endpoint,
        "MINIO_PORT": str(settings.minio_port),
        "MINIO_USE_SSL": str(settings.minio_use_ssl).lower(),
        "MINIO_ACCESS_KEY": settings.minio_access_key.get_secret_value(),
        "MINIO_SECRET_KEY": settings.minio_secret_key.get_secret_value(),
        "MINIO_BUCKET": settings.minio_bucket,
        "AI_MODE": "mock",
        "ENABLE_DEV_SEED": "true",
        "KNOWLEDGE_ENABLED": "false",
    }
    # JSON string quoting is valid dotenv double quoting, including passwords with special chars.
    import json

    target.parent.mkdir(exist_ok=True)
    target.write_text(
        "".join(f"{key}={json.dumps(value)}\n" for key, value in values.items()), encoding="utf-8"
    )
    target.chmod(0o600)
    print(
        f"Created fresh dev schema {name} and ignored .local/native.env; credentials not printed."
    )


if __name__ == "__main__":
    main()
