"""User registration, soft deletion and serialized last-admin protection."""

import sqlalchemy as sa
from sqlalchemy.dialects import mysql

from alembic import op

revision = "0004_users"
down_revision = "0003_sales"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "users",
        sa.Column("registration_status", sa.String(16), nullable=False, server_default="APPROVED"),
    )
    op.add_column("users", sa.Column("deleted_at", mysql.DATETIME(fsp=6), nullable=True))
    op.create_check_constraint(
        "ck_users_registration", "users", "registration_status IN ('PENDING','APPROVED')"
    )
    op.create_check_constraint(
        "ck_users_pending", "users", "registration_status='APPROVED' OR NOT is_active"
    )
    op.create_check_constraint("ck_users_deleted", "users", "deleted_at IS NULL OR NOT is_active")
    op.create_index(
        "ix_users_registration", "users", ["registration_status", "is_active", "deleted_at", "id"]
    )
    op.create_table(
        "system_guards",
        sa.Column("key", sa.String(40), primary_key=True),
        sa.Column("version", sa.BigInteger(), nullable=False),
        mysql_engine="InnoDB",
        mysql_charset="utf8mb4",
    )
    op.bulk_insert(
        sa.table("system_guards", sa.column("key", sa.String), sa.column("version", sa.BigInteger)),
        [{"key": "active_admin", "version": 1}],
    )


def downgrade():
    raise RuntimeError("Destructive user history rollback is disabled; review a forward repair")
