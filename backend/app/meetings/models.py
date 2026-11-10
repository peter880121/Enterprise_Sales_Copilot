from datetime import date, datetime

from sqlalchemy import (
    CheckConstraint,
    Date,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.mysql import BIGINT, BINARY, DATETIME, JSON, MEDIUMTEXT
from sqlalchemy.orm import Mapped, mapped_column

from app.crm.models import TABLE_OPTIONS, UUID_TYPE, Versioned
from app.db import Base


class Job(Base):
    __tablename__ = "jobs"
    __table_args__ = (
        CheckConstraint(
            "status IN ('QUEUED','RUNNING','SUCCEEDED','FAILED')", name="ck_jobs_status"
        ),
        CheckConstraint("attempts >= 0 AND attempts <= 3", name="ck_jobs_attempts"),
        Index("ix_jobs_claim", "status", "available_at", "id"),
        Index("ix_jobs_lease", "status", "lease_until"),
        TABLE_OPTIONS,
    )
    id: Mapped[str] = mapped_column(UUID_TYPE, primary_key=True)
    created_by: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    opportunity_id: Mapped[str] = mapped_column(ForeignKey("opportunities.id", ondelete="RESTRICT"))
    dedupe_key: Mapped[str] = mapped_column(String(200), unique=True)
    request_hash: Mapped[bytes] = mapped_column(BINARY(32))
    status: Mapped[str] = mapped_column(String(16))
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    available_at: Mapped[datetime] = mapped_column(DATETIME(fsp=6))
    lease_until: Mapped[datetime | None] = mapped_column(DATETIME(fsp=6))
    lease_token: Mapped[str | None] = mapped_column(UUID_TYPE)
    error_code: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DATETIME(fsp=6))
    updated_at: Mapped[datetime] = mapped_column(DATETIME(fsp=6))


class MeetingAnalysis(Base):
    __tablename__ = "meeting_analyses"
    __table_args__ = (
        CheckConstraint(
            "status IN ('QUEUED','RUNNING','SUCCEEDED','FAILED')", name="ck_meeting_status"
        ),
        CheckConstraint("mode='MOCK'", name="ck_meeting_mock"),
        Index("ix_meeting_opportunity", "opportunity_id", "created_at", "id"),
        TABLE_OPTIONS,
    )
    id: Mapped[str] = mapped_column(UUID_TYPE, primary_key=True)
    opportunity_id: Mapped[str] = mapped_column(ForeignKey("opportunities.id", ondelete="RESTRICT"))
    submitted_by: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    source_job_id: Mapped[str] = mapped_column(
        ForeignKey("jobs.id", ondelete="RESTRICT"), unique=True
    )
    meeting_date: Mapped[date | None] = mapped_column(Date)
    timezone: Mapped[str] = mapped_column(String(64))
    input_text: Mapped[str] = mapped_column(MEDIUMTEXT)
    input_sha256: Mapped[bytes] = mapped_column(BINARY(32))
    base_opportunity_version: Mapped[int] = mapped_column(BIGINT(unsigned=True))
    status: Mapped[str] = mapped_column(String(16))
    result: Mapped[dict | None] = mapped_column(JSON)
    mode: Mapped[str] = mapped_column(String(8))
    schema_version: Mapped[str] = mapped_column(String(32))
    prompt_version: Mapped[str] = mapped_column(String(32))
    created_at: Mapped[datetime] = mapped_column(DATETIME(fsp=6))
    updated_at: Mapped[datetime] = mapped_column(DATETIME(fsp=6))


class Suggestion(Versioned, Base):
    __tablename__ = "ai_suggestions"
    __table_args__ = (
        CheckConstraint(
            "status IN ('GENERATING','DRAFT','REJECTED','ABANDONED','FAILED',"
            "'EXECUTED','SUPERSEDED')",
            name="ck_suggestion_status",
        ),
        CheckConstraint(
            "status<>'EXECUTED' OR (execution_id IS NOT NULL AND executed_at IS NOT NULL "
            "AND result_version IS NOT NULL AND reviewed_by IS NOT NULL "
            "AND selected_change_ids IS NOT NULL)",
            name="ck_suggestion_execution",
        ),
        Index("ix_suggestion_opportunity", "opportunity_id", "status", "created_at", "id"),
        TABLE_OPTIONS,
    )
    id: Mapped[str] = mapped_column(UUID_TYPE, primary_key=True)
    opportunity_id: Mapped[str] = mapped_column(ForeignKey("opportunities.id", ondelete="RESTRICT"))
    analysis_id: Mapped[str] = mapped_column(
        ForeignKey("meeting_analyses.id", ondelete="RESTRICT"), unique=True
    )
    source_job_id: Mapped[str] = mapped_column(
        ForeignKey("jobs.id", ondelete="RESTRICT"), unique=True
    )
    created_by: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    reviewed_by: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    reviewed_at: Mapped[datetime | None] = mapped_column(DATETIME(fsp=6))
    expires_at: Mapped[datetime | None] = mapped_column(DATETIME(fsp=6))
    status: Mapped[str] = mapped_column(String(16))
    reason: Mapped[str | None] = mapped_column(Text)
    base_opportunity_version: Mapped[int] = mapped_column(BIGINT(unsigned=True))

    proposed_changes: Mapped[list | None] = mapped_column(JSON)
    base_snapshot: Mapped[dict | None] = mapped_column(JSON)
    context_digest: Mapped[bytes | None] = mapped_column(BINARY(32))
    execution_id: Mapped[str | None] = mapped_column(UUID_TYPE, unique=True)
    executed_at: Mapped[datetime | None] = mapped_column(DATETIME(fsp=6))
    result_version: Mapped[int | None] = mapped_column(BIGINT(unsigned=True))
    selected_change_ids: Mapped[list | None] = mapped_column(JSON)


class SuggestionExecution(Base):
    __tablename__ = "suggestion_executions"
    __table_args__ = (TABLE_OPTIONS,)
    id: Mapped[str] = mapped_column(UUID_TYPE, primary_key=True)
    suggestion_id: Mapped[str] = mapped_column(
        ForeignKey("ai_suggestions.id", ondelete="RESTRICT"), unique=True
    )
    opportunity_id: Mapped[str] = mapped_column(ForeignKey("opportunities.id", ondelete="RESTRICT"))
    actor_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    selected_change_ids: Mapped[list] = mapped_column(JSON)
    result_version: Mapped[int] = mapped_column(BIGINT(unsigned=True))
    result: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DATETIME(fsp=6))


class AIRun(Base):
    __tablename__ = "ai_runs"
    __table_args__ = (
        UniqueConstraint("job_id", "attempt", name="uq_ai_run_attempt"),
        TABLE_OPTIONS,
    )
    id: Mapped[str] = mapped_column(UUID_TYPE, primary_key=True)
    job_id: Mapped[str] = mapped_column(ForeignKey("jobs.id", ondelete="RESTRICT"))
    attempt: Mapped[int] = mapped_column(Integer)
    mode: Mapped[str] = mapped_column(String(8))
    provider: Mapped[str] = mapped_column(String(80))
    schema_version: Mapped[str] = mapped_column(String(32))
    prompt_version: Mapped[str] = mapped_column(String(32))
    input_hash: Mapped[bytes] = mapped_column(BINARY(32))
    status: Mapped[str] = mapped_column(String(16))
    error_code: Mapped[str | None] = mapped_column(String(64))
    started_at: Mapped[datetime] = mapped_column(DATETIME(fsp=6))
    ended_at: Mapped[datetime | None] = mapped_column(DATETIME(fsp=6))
    latency_ms: Mapped[int | None] = mapped_column(Integer)
