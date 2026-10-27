"""M1 identity, opaque sessions and shared authentication throttle only."""

import sqlalchemy as sa
from sqlalchemy.dialects import mysql

from alembic import op

revision = "0001_auth"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    options = {"mysql_engine": "InnoDB", "mysql_charset": "utf8mb4"}
    dt = mysql.DATETIME(fsp=6)
    op.create_table(
        "users",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("email", sa.String(254), nullable=False),
        sa.Column("email_normalized", sa.String(254), nullable=False, unique=True),
        sa.Column("password_hash", sa.String(512), nullable=False),
        sa.Column("role", sa.String(24), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("password_changed_at", dt, nullable=False),
        sa.Column("version", sa.BigInteger(), nullable=False),
        sa.Column("created_at", dt, nullable=False),
        sa.Column("updated_at", dt, nullable=False),
        sa.CheckConstraint(
            "role IN ('ADMIN','SALES_MANAGER','SALES_REP','READ_ONLY')", name="ck_users_role"
        ),
        **options,
    )
    op.create_index("ix_users_role_active", "users", ["role", "is_active", "id"])
    op.create_table(
        "sessions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
        ),
        sa.Column("token_hash", mysql.BINARY(32), nullable=False, unique=True),
        sa.Column("csrf_nonce", mysql.BINARY(32), nullable=False),
        *[
            sa.Column(name, dt, nullable=False)
            for name in ("created_at", "last_seen_at", "idle_expires_at", "absolute_expires_at")
        ],
        sa.Column("revoked_at", dt, nullable=True),
        **options,
    )
    op.create_index("ix_sessions_user_revoked", "sessions", ["user_id", "revoked_at"])
    op.create_index("ix_sessions_expiry", "sessions", ["absolute_expires_at"])
    op.create_table(
        "auth_throttles",
        sa.Column("key_hash", mysql.BINARY(32), primary_key=True),
        sa.Column("window_start", dt, nullable=False),
        sa.Column("failed_count", sa.Integer(), nullable=False),
        sa.Column("blocked_until", dt, nullable=True),
        sa.Column("expires_at", dt, nullable=False),
        **options,
    )
    op.create_index("ix_throttle_expiry", "auth_throttles", ["expires_at"])


def downgrade():
    op.drop_table("auth_throttles")
    op.drop_table("sessions")
    op.drop_table("users")
