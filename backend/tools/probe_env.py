"""Read-only connectivity probe. Report categories, never URLs, credentials or exceptions."""

import json

from sqlalchemy import text

from app.core.config import get_settings
from app.db import Database
from app.storage import ObjectStorage


def main():
    try:
        settings = get_settings()
    except Exception as exc:
        # Pydantic input/context may contain secrets; only publish field locations/types.
        errors = getattr(exc, "errors", lambda: [])()
        print(
            json.dumps(
                {
                    "config": "invalid",
                    "fields": [
                        {"location": item.get("loc"), "type": item.get("type")} for item in errors
                    ],
                }
            )
        )
        return 1
    result = {"config": "valid", "ai_mode": settings.ai_mode, "ai_calls": 0}
    db = Database(settings)
    try:
        with db.engine.connect() as connection:
            version = connection.scalar(text("SELECT VERSION()"))
            result["mysql"] = "connected"
            result["mysql_version"] = version
            result["mysql_8_4"] = str(version).startswith("8.4.")
            result["schema_table_count"] = connection.scalar(
                text("SELECT COUNT(*) FROM information_schema.tables WHERE table_schema=DATABASE()")
            )
    except Exception as exc:
        result["mysql"] = "unavailable"
        result["mysql_error_type"] = type(exc).__name__
    finally:
        db.close()
    result["configured_storage_bucket_accessible"] = ObjectStorage(settings).ready()
    print(json.dumps(result))
    return 0 if result.get("mysql") == "connected" else 1


if __name__ == "__main__":
    raise SystemExit(main())
