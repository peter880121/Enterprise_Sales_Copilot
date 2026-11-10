"""Allow explicit supersession of a draft; preserve every original record."""

from alembic import op

revision = "0007_regenerate"
down_revision = "0006_execution"
branch_labels = None
depends_on = None


def upgrade():
    op.drop_constraint("ck_suggestion_status", "ai_suggestions", type_="check")
    op.create_check_constraint(
        "ck_suggestion_status",
        "ai_suggestions",
        "status IN ('GENERATING','DRAFT','REJECTED','ABANDONED','FAILED','EXECUTED','SUPERSEDED')",
    )


def downgrade():
    raise RuntimeError("Supersession history rollback requires a reviewed forward repair")
