from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Computed,
    Date,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.mysql import BIGINT, DATETIME, JSON
from sqlalchemy.orm import Mapped, mapped_column

from app.crm.models import TABLE_OPTIONS, UUID_TYPE, Versioned
from app.db import Base


class Opportunity(Versioned, Base):
    __tablename__ = "opportunities"
    __table_args__ = (
        CheckConstraint("CHAR_LENGTH(TRIM(name)) > 0", name="ck_opp_name"),
        CheckConstraint("version >= 1", name="ck_opp_version"),
        CheckConstraint("amount IS NULL OR amount >= 0", name="ck_opp_amount"),
        CheckConstraint("currency IN ('CNY','USD','EUR','HKD')", name="ck_opp_currency"),
        CheckConstraint(
            "(stage='PROPOSAL_SUBMITTED' AND probability=20) OR "
            "(stage='NEGOTIATION' AND probability=60) OR (stage='FOLLOW_UP' AND probability=40) "
            "OR (stage='WON' AND probability=100) OR (stage='LOST' AND probability=0)",
            name="ck_opp_probability",
        ),
        CheckConstraint("priority IN ('LOW','MEDIUM','HIGH')", name="ck_opp_priority"),
        CheckConstraint(
            "(stage IN ('PROPOSAL_SUBMITTED','NEGOTIATION','FOLLOW_UP') AND closed_at IS NULL "
            "AND closed_by IS NULL AND close_reason IS NULL AND close_reason_code IS NULL "
            "AND close_evidence_id IS NULL) OR (stage='WON' AND closed_at IS NOT NULL "
            "AND closed_by IS NOT NULL AND close_evidence_id IS NOT NULL "
            "AND close_reason IS NULL AND close_reason_code IS NULL) OR "
            "(stage='LOST' AND closed_at IS NOT NULL AND closed_by IS NOT NULL "
            "AND close_evidence_id IS NULL AND close_reason IS NOT NULL "
            "AND CHAR_LENGTH(TRIM(close_reason))>0 AND close_reason_code IS NOT NULL)",
            name="ck_opp_close",
        ),
        CheckConstraint("NOT is_archived OR stage IN ('WON','LOST')", name="ck_opp_archive"),
        ForeignKeyConstraint(
            ["account_id", "primary_contact_id"],
            ["contacts.account_id", "contacts.id"],
            name="fk_opp_contact_account",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["close_evidence_id", "id"],
            ["close_evidence.id", "close_evidence.opportunity_id"],
            name="fk_opp_selected_evidence",
            ondelete="RESTRICT",
            use_alter=True,
        ),
        Index("ix_opp_board", "is_archived", "stage", "currency", "id"),
        Index("ix_opp_owner", "owner_id", "is_archived", "stage", "id"),
        Index("ix_opp_account", "account_id", "created_at", "id"),
        Index("ix_opp_closed", "closed_at", "stage", "currency"),
        TABLE_OPTIONS,
    )
    id: Mapped[str] = mapped_column(UUID_TYPE, primary_key=True)
    account_id: Mapped[str] = mapped_column(ForeignKey("accounts.id", ondelete="RESTRICT"))
    primary_contact_id: Mapped[str | None] = mapped_column(UUID_TYPE)
    owner_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    name: Mapped[str] = mapped_column(String(200))
    stage: Mapped[str] = mapped_column(String(32), default="PROPOSAL_SUBMITTED")
    amount: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    currency: Mapped[str] = mapped_column(String(3), server_default="CNY")
    probability: Mapped[int] = mapped_column(default=20)
    weighted_amount: Mapped[Decimal | None] = mapped_column(
        Numeric(18, 2),
        Computed(
            "CASE WHEN amount IS NULL THEN NULL ELSE ROUND(amount*probability/100,2) END",
            persisted=True,
        ),
    )
    source: Mapped[str] = mapped_column(String(32), default="UNKNOWN")
    priority: Mapped[str] = mapped_column(String(8), default="MEDIUM")
    expected_close_date: Mapped[date | None] = mapped_column(Date)
    close_reason_code: Mapped[str | None] = mapped_column(String(32))
    close_reason: Mapped[str | None] = mapped_column(String(2000))
    close_evidence_id: Mapped[str | None] = mapped_column(UUID_TYPE)
    closed_at: Mapped[datetime | None] = mapped_column(DATETIME(fsp=6))
    closed_by: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    is_archived: Mapped[bool] = mapped_column(Boolean, default=False)
    archived_at: Mapped[datetime | None] = mapped_column(DATETIME(fsp=6))
    archived_by: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))


class StoredObject(Base):
    __tablename__ = "stored_objects"
    __table_args__ = (
        UniqueConstraint("bucket", "object_key", name="uq_object_key"),
        UniqueConstraint("uploaded_by", "request_token", name="uq_object_request"),
        CheckConstraint("size_bytes > 0 AND size_bytes <= 20971520", name="ck_object_size"),
        CheckConstraint("pages >= 1 AND pages <= 100", name="ck_object_pages"),
        TABLE_OPTIONS,
    )
    id: Mapped[str] = mapped_column(UUID_TYPE, primary_key=True)
    opportunity_id: Mapped[str] = mapped_column(ForeignKey("opportunities.id", ondelete="RESTRICT"))
    bucket: Mapped[str] = mapped_column(String(100))
    object_key: Mapped[str] = mapped_column(String(200))
    storage_version_id: Mapped[str | None] = mapped_column(String(200))
    original_name: Mapped[str] = mapped_column(String(255))
    mime_type: Mapped[str] = mapped_column(String(100), default="application/pdf")
    size_bytes: Mapped[int] = mapped_column(BIGINT(unsigned=True))
    sha256: Mapped[str] = mapped_column(String(64))
    pages: Mapped[int] = mapped_column()
    purpose: Mapped[str] = mapped_column(String(32), default="CLOSE_EVIDENCE")
    status: Mapped[str] = mapped_column(String(24), default="UPLOADING")
    uploaded_by: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    request_token: Mapped[str] = mapped_column(UUID_TYPE)
    created_at: Mapped[datetime] = mapped_column(DATETIME(fsp=6))


class CloseEvidence(Versioned, Base):
    __tablename__ = "close_evidence"
    __table_args__ = (
        UniqueConstraint("id", "opportunity_id", name="uq_evidence_opportunity"),
        CheckConstraint("amount > 0", name="ck_evidence_amount"),
        CheckConstraint("currency IN ('CNY','USD','EUR','HKD')", name="ck_evidence_currency"),
        CheckConstraint(
            "type IN ('SIGNED_CONTRACT','PURCHASE_ORDER','OTHER_APPROVED')", name="ck_evidence_type"
        ),
        CheckConstraint(
            "reviewed_by IS NULL OR reviewed_by <> submitted_by", name="ck_evidence_separation"
        ),
        CheckConstraint(
            "(status='PENDING' AND reviewed_by IS NULL AND reviewed_at IS NULL "
            "AND verification_note IS NULL) OR (status IN ('VERIFIED','REJECTED') "
            "AND reviewed_by IS NOT NULL AND reviewed_at IS NOT NULL "
            "AND verification_note IS NOT NULL AND CHAR_LENGTH(TRIM(verification_note))>0)",
            name="ck_evidence_review",
        ),
        Index("ix_evidence_opportunity", "opportunity_id", "created_at", "id"),
        TABLE_OPTIONS,
    )
    id: Mapped[str] = mapped_column(UUID_TYPE, primary_key=True)
    opportunity_id: Mapped[str] = mapped_column(ForeignKey("opportunities.id", ondelete="RESTRICT"))
    stored_object_id: Mapped[str] = mapped_column(
        ForeignKey("stored_objects.id", ondelete="RESTRICT"),
        unique=True,
    )
    type: Mapped[str] = mapped_column(String(32))
    reference_number: Mapped[str] = mapped_column(String(100))
    customer_legal_name: Mapped[str] = mapped_column(String(200))
    document_date: Mapped[date] = mapped_column(Date)
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    currency: Mapped[str] = mapped_column(String(3), server_default="CNY")
    status: Mapped[str] = mapped_column(String(16), default="PENDING")
    submitted_by: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    reviewed_by: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    reviewed_at: Mapped[datetime | None] = mapped_column(DATETIME(fsp=6))
    verification_note: Mapped[str | None] = mapped_column(String(2000))
    approval_basis: Mapped[str | None] = mapped_column(String(2000))


class IdempotencyRecord(Base):
    __tablename__ = "idempotency_records"
    __table_args__ = (
        UniqueConstraint("actor_id", "scope", "request_key", name="uq_idempotency_actor_scope_key"),
        TABLE_OPTIONS,
    )
    id: Mapped[str] = mapped_column(UUID_TYPE, primary_key=True)
    actor_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    scope: Mapped[str] = mapped_column(String(160))
    request_key: Mapped[str] = mapped_column(String(100))
    request_hash: Mapped[str] = mapped_column(String(64))
    response: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DATETIME(fsp=6))


class Activity(Versioned, Base):
    __tablename__ = "activities"
    __table_args__ = (
        UniqueConstraint("ai_execution_key", name="uq_activity_ai_execution"),
        CheckConstraint(
            "type IN ('CALL','MEETING','EMAIL','NOTE','TASK')", name="ck_activity_type"
        ),
        CheckConstraint(
            "(type='TASK' AND due_at IS NOT NULL AND assignee_id IS NOT NULL "
            "AND status IN ('OPEN','DONE','CANCELLED')) OR "
            "(type<>'TASK' AND occurred_at IS NOT NULL AND status='RECORDED')",
            name="ck_activity_shape",
        ),
        CheckConstraint("(status='DONE') = (completed_at IS NOT NULL)", name="ck_activity_done"),
        Index("ix_activity_opp_time", "opportunity_id", "occurred_at", "id"),
        Index("ix_activity_account", "account_id", "created_at"),
        TABLE_OPTIONS,
    )
    id: Mapped[str] = mapped_column(UUID_TYPE, primary_key=True)
    account_id: Mapped[str] = mapped_column(ForeignKey("accounts.id", ondelete="RESTRICT"))
    opportunity_id: Mapped[str | None] = mapped_column(
        ForeignKey("opportunities.id", ondelete="RESTRICT")
    )
    contact_id: Mapped[str | None] = mapped_column(ForeignKey("contacts.id", ondelete="RESTRICT"))
    type: Mapped[str] = mapped_column(String(16))
    subject: Mapped[str] = mapped_column(String(200))
    content: Mapped[str] = mapped_column(Text)
    occurred_at: Mapped[datetime | None] = mapped_column(DATETIME(fsp=6))
    due_at: Mapped[datetime | None] = mapped_column(DATETIME(fsp=6))
    assignee_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    status: Mapped[str] = mapped_column(String(16))
    completed_at: Mapped[datetime | None] = mapped_column(DATETIME(fsp=6))
    created_by: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    ai_execution_key: Mapped[str | None] = mapped_column(String(100))
