import argparse
import getpass
from uuid import uuid4

from sqlalchemy import select

from app.auth.models import Role, User
from app.auth.security import hash_password
from app.auth.service import now
from app.core.config import get_settings
from app.db import Database


def main():
    parser = argparse.ArgumentParser(description="Create one user; never overwrite existing users")
    parser.add_argument("--email", required=True)
    parser.add_argument("--name", required=True)
    parser.add_argument("--role", choices=list(Role), default=Role.ADMIN)
    args = parser.parse_args()
    settings = get_settings()
    if settings.app_env != "development" or not settings.enable_dev_seed:
        parser.error("Requires APP_ENV=development and ENABLE_DEV_SEED=true")
    email = args.email.strip().lower()
    if "@" not in email:
        parser.error("valid email required")
    password = getpass.getpass("New password (12-128 characters, never printed): ")
    encoded = hash_password(password)
    db = Database(settings)
    try:
        with db.transaction() as session:
            if session.scalar(select(User).where(User.email_normalized == email)):
                parser.error("User already exists; no change made")
            current = now()
            session.add(
                User(
                    id=str(uuid4()),
                    name=args.name,
                    email=email,
                    email_normalized=email,
                    password_hash=encoded,
                    role=args.role,
                    is_active=True,
                    version=1,
                    password_changed_at=current,
                    created_at=current,
                    updated_at=current,
                )
            )
        print("Development user created. No password was logged.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
