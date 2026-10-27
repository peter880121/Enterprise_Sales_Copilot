"""Generate isolated local Compose secrets; never edit or copy the user's remote .env."""

import secrets
from pathlib import Path

root = Path(__file__).resolve().parents[2]
target = root / ".local" / "compose.env"
target.parent.mkdir(exist_ok=True)
if target.exists():
    raise SystemExit("Existing .local/compose.env preserved; no changes made.")
values = {
    "MYSQL_DATABASE": "enterprise_sales_copilot",
    "MYSQL_USER": "esc_app",
    "MINIO_ROOT_USER": "esc_root",
    "MINIO_ACCESS_KEY": "esc_business",
    **{
        name: secrets.token_urlsafe(40)
        for name in (
            "MYSQL_ROOT_PASSWORD",
            "MYSQL_PASSWORD",
            "MINIO_ROOT_PASSWORD",
            "MINIO_SECRET_KEY",
            "SESSION_SECRET",
        )
    },
}
target.write_text("".join(f"{key}={value}\n" for key, value in values.items()), encoding="utf-8")
target.chmod(0o600)
print("Created ignored .local/compose.env for isolated Core; no secret values printed.")
