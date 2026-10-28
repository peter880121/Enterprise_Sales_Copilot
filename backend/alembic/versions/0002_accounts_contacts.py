"""M2-A accounts, contacts and their append-only mutation audit. No data deletion."""

import sqlalchemy as sa
from sqlalchemy.dialects import mysql

from alembic import op

revision = "0002_accounts_contacts"
down_revision = "0001_auth"
branch_labels = None
depends_on = None


def upgrade():
    options = {"mysql_engine": "InnoDB", "mysql_charset": "utf8mb4"}
    uuid = mysql.CHAR(36, charset="ascii", collation="ascii_bin")
    dt = mysql.DATETIME(fsp=6)
    version = mysql.BIGINT(unsigned=True)

    def common():
        return [
            sa.Column("version", version, nullable=False),
            sa.Column("created_at", dt, nullable=False),
            sa.Column("updated_at", dt, nullable=False),
        ]

    op.create_table(
        "accounts",
        sa.Column("id", uuid, primary_key=True),
        sa.Column(
            "owner_id",
            sa.String(36),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("industry", sa.String(100)),
        sa.Column("website", sa.String(2048)),
        sa.Column("company_size", sa.String(24)),
        sa.Column("description", sa.Text()),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        *common(),
        sa.CheckConstraint("CHAR_LENGTH(TRIM(name)) > 0", name="ck_accounts_name"),
        sa.CheckConstraint("version >= 1", name="ck_accounts_version"),
        sa.CheckConstraint(
            "company_size IS NULL OR company_size IN "
            "('SOLO','SMALL','MEDIUM','LARGE','ENTERPRISE')",
            name="ck_accounts_size",
        ),
        **options,
    )
    op.create_index("ix_accounts_owner_active_id", "accounts", ["owner_id", "is_active", "id"])
    op.create_index("ix_accounts_name_id", "accounts", ["name", "id"])
    op.create_table(
        "contacts",
        sa.Column("id", uuid, primary_key=True),
        sa.Column(
            "account_id", uuid, sa.ForeignKey("accounts.id", ondelete="RESTRICT"), nullable=False
        ),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("title", sa.String(100)),
        sa.Column("email", sa.String(254)),
        sa.Column("phone", sa.String(40)),
        sa.Column("decision_role", sa.String(24), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        *common(),
        sa.CheckConstraint("CHAR_LENGTH(TRIM(name)) > 0", name="ck_contacts_name"),
        sa.CheckConstraint("version >= 1", name="ck_contacts_version"),
        sa.CheckConstraint(
            "decision_role IN ('DECISION_MAKER','CHAMPION','INFLUENCER',"
            "'USER','PROCUREMENT','UNKNOWN')",
            name="ck_contacts_role",
        ),
        sa.UniqueConstraint("account_id", "id", name="uq_contacts_account_id"),
        **options,
    )
    op.create_index(
        "ix_contacts_account_active_name", "contacts", ["account_id", "is_active", "name"]
    )
    op.create_index("ix_contacts_email", "contacts", ["email"])
    op.create_table(
        "audit_events",
        sa.Column("id", uuid, primary_key=True),
        sa.Column("entity_type", sa.String(64), nullable=False),
        sa.Column("entity_id", uuid, nullable=False),
        sa.Column("actor_kind", sa.String(16), nullable=False),
        sa.Column("actor_id", sa.String(36), sa.ForeignKey("users.id", ondelete="RESTRICT")),
        sa.Column("action", sa.String(64), nullable=False),
        sa.Column("before_state", mysql.JSON()),
        sa.Column("after_state", mysql.JSON()),
        sa.Column("reason", sa.String(2000)),
        sa.Column("expected_version", version),
        sa.Column("resulting_version", version),
        sa.Column("request_id", sa.String(64), nullable=False),
        sa.Column("mutation_event_key", sa.String(200), unique=True),
        sa.Column("created_at", dt, nullable=False),
        **options,
    )
    op.create_index(
        "ix_audit_entity_time", "audit_events", ["entity_type", "entity_id", "created_at", "id"]
    )
    op.create_index("ix_audit_actor_time", "audit_events", ["actor_id", "created_at", "id"])
    op.create_index("ix_audit_time", "audit_events", ["created_at", "id"])
    op.create_index("ix_audit_request", "audit_events", ["request_id"])


def downgrade():
    # Intentionally refuse destructive rollback, including loss of historical audit data.
    raise RuntimeError("M2-A downgrade is destructive; use an explicitly reviewed recovery plan")
