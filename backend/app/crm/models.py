from datetime import datetime

from sqlalchemy import Boolean, CheckConstraint, ForeignKey, Index, String, Text, UniqueConstraint
from sqlalchemy.dialects.mysql import BIGINT, CHAR, DATETIME, JSON
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base

UUID_TYPE = CHAR(36, charset="ascii", collation="ascii_bin")
TABLE_OPTIONS = {"mysql_engine": "InnoDB", "mysql_charset": "utf8mb4"}


class Versioned:
    version: Mapped[int] = mapped_column(BIGINT(unsigned=True), default=1)
    created_at: Mapped[datetime] = mapped_column(DATETIME(fsp=6))
    updated_at: Mapped[datetime] = mapped_column(DATETIME(fsp=6))


class Account(Versioned, Base):
    __tablename__ = "accounts"
    __table_args__ = (
        CheckConstraint("CHAR_LENGTH(TRIM(name)) > 0", name="ck_accounts_name"),
        CheckConstraint("version >= 1", name="ck_accounts_version"),
        CheckConstraint(
            "company_size IS NULL OR company_size IN "
            "('SOLO','SMALL','MEDIUM','LARGE','ENTERPRISE')",
            name="ck_accounts_size",
        ),
        Index("ix_accounts_owner_active_id", "owner_id", "is_active", "id"),
        Index("ix_accounts_name_id", "name", "id"),
        TABLE_OPTIONS,
    )
    id: Mapped[str] = mapped_column(UUID_TYPE, primary_key=True)
    # Match M1 users.id's existing VARCHAR/charset for FK compatibility.
    owner_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    name: Mapped[str] = mapped_column(String(200))
    industry: Mapped[str | None] = mapped_column(String(100))
    website: Mapped[str | None] = mapped_column(String(2048))
    company_size: Mapped[str | None] = mapped_column(String(24))
    description: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class Contact(Versioned, Base):
    __tablename__ = "contacts"
    __table_args__ = (
        CheckConstraint("CHAR_LENGTH(TRIM(name)) > 0", name="ck_contacts_name"),
        CheckConstraint("version >= 1", name="ck_contacts_version"),
        CheckConstraint(
            "decision_role IN ('DECISION_MAKER','CHAMPION','INFLUENCER',"
            "'USER','PROCUREMENT','UNKNOWN')",
            name="ck_contacts_role",
        ),
        UniqueConstraint("account_id", "id", name="uq_contacts_account_id"),
        Index("ix_contacts_account_active_name", "account_id", "is_active", "name"),
        Index("ix_contacts_email", "email"),
        TABLE_OPTIONS,
    )
    id: Mapped[str] = mapped_column(UUID_TYPE, primary_key=True)
    account_id: Mapped[str] = mapped_column(ForeignKey("accounts.id", ondelete="RESTRICT"))
    name: Mapped[str] = mapped_column(String(100))
    title: Mapped[str | None] = mapped_column(String(100))
    email: Mapped[str | None] = mapped_column(String(254))
    phone: Mapped[str | None] = mapped_column(String(40))
    decision_role: Mapped[str] = mapped_column(String(24), default="UNKNOWN")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class AuditEvent(Base):
    __tablename__ = "audit_events"
    __table_args__ = (
        Index("ix_audit_entity_time", "entity_type", "entity_id", "created_at", "id"),
        Index("ix_audit_actor_time", "actor_id", "created_at", "id"),
        Index("ix_audit_time", "created_at", "id"),
        Index("ix_audit_request", "request_id"),
        TABLE_OPTIONS,
    )
    id: Mapped[str] = mapped_column(UUID_TYPE, primary_key=True)
    entity_type: Mapped[str] = mapped_column(String(64))
    entity_id: Mapped[str] = mapped_column(UUID_TYPE)
    actor_kind: Mapped[str] = mapped_column(String(16))
    actor_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    action: Mapped[str] = mapped_column(String(64))
    before_state: Mapped[dict | None] = mapped_column(JSON)
    after_state: Mapped[dict | None] = mapped_column(JSON)
    reason: Mapped[str | None] = mapped_column(String(2000))
    expected_version: Mapped[int | None] = mapped_column(BIGINT(unsigned=True))
    resulting_version: Mapped[int | None] = mapped_column(BIGINT(unsigned=True))
    request_id: Mapped[str] = mapped_column(String(64))
    mutation_event_key: Mapped[str | None] = mapped_column(String(200), unique=True)
    created_at: Mapped[datetime] = mapped_column(DATETIME(fsp=6))
