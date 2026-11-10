"""Frozen Q07 changes and immutable execution receipts; Q10 preview performs no cleanup."""

import sqlalchemy as sa
from sqlalchemy.dialects import mysql

from alembic import op

revision = "0006_execution"
down_revision = "0005_meetings"
branch_labels = None
depends_on = None


def upgrade():
    for name, kind in [
        ("proposed_changes", mysql.JSON()),
        ("base_snapshot", mysql.JSON()),
        ("context_digest", sa.BINARY(32)),
        ("execution_id", mysql.CHAR(36, charset="ascii", collation="ascii_bin")),
        ("executed_at", mysql.DATETIME(fsp=6)),
        ("result_version", mysql.BIGINT(unsigned=True)),
        ("selected_change_ids", mysql.JSON()),
    ]:
        op.add_column("ai_suggestions", sa.Column(name, kind, nullable=True))
    op.create_unique_constraint(
        "uq_ai_suggestions_execution_id", "ai_suggestions", ["execution_id"]
    )
    op.drop_constraint("ck_suggestion_status", "ai_suggestions", type_="check")
    op.create_check_constraint(
        "ck_suggestion_status",
        "ai_suggestions",
        "status IN ('GENERATING','DRAFT','REJECTED','ABANDONED','FAILED','EXECUTED')",
    )
    op.create_check_constraint(
        "ck_suggestion_execution",
        "ai_suggestions",
        "status<>'EXECUTED' OR (execution_id IS NOT NULL AND executed_at IS NOT NULL "
        "AND result_version IS NOT NULL AND reviewed_by IS NOT NULL "
        "AND selected_change_ids IS NOT NULL)",
    )
    op.add_column("activities", sa.Column("ai_execution_key", sa.String(100), nullable=True))
    op.create_unique_constraint("uq_activity_ai_execution", "activities", ["ai_execution_key"])
    op.create_table(
        "suggestion_executions",
        sa.Column("id", mysql.CHAR(36, charset="ascii", collation="ascii_bin"), primary_key=True),
        sa.Column(
            "suggestion_id",
            mysql.CHAR(36, charset="ascii", collation="ascii_bin"),
            sa.ForeignKey("ai_suggestions.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "opportunity_id",
            mysql.CHAR(36, charset="ascii", collation="ascii_bin"),
            sa.ForeignKey("opportunities.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "actor_id",
            sa.String(36),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("selected_change_ids", mysql.JSON(), nullable=False),
        sa.Column("result_version", mysql.BIGINT(unsigned=True), nullable=False),
        sa.Column("result", mysql.JSON(), nullable=False),
        sa.Column("created_at", mysql.DATETIME(fsp=6), nullable=False),
        sa.UniqueConstraint("suggestion_id"),
        mysql_engine="InnoDB",
        mysql_charset="utf8mb4",
    )


def downgrade():
    raise RuntimeError("Execution history rollback requires a reviewed forward repair")
