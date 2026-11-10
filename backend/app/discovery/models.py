from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.mysql import BINARY, DATETIME, JSON, MEDIUMBLOB, MEDIUMTEXT
from sqlalchemy.orm import Mapped, mapped_column

from app.crm.models import TABLE_OPTIONS, UUID_TYPE, Versioned
from app.db import Base


class SalesProfile(Versioned, Base):
    __tablename__ = "discovery_profiles"
    __table_args__ = (
        CheckConstraint("visibility IN ('PRIVATE','TEAM')", name="ck_discovery_visibility"),
        CheckConstraint("version >= 1", name="ck_discovery_profile_version"),
        Index("ix_discovery_profile_owner", "owner_id", "created_at", "id"),
        TABLE_OPTIONS,
    )
    id: Mapped[str] = mapped_column(UUID_TYPE, primary_key=True)
    owner_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    name: Mapped[str] = mapped_column(String(200))
    product: Mapped[str] = mapped_column(String(200))
    keywords: Mapped[list] = mapped_column(JSON)
    regions: Mapped[list] = mapped_column(JSON)
    visibility: Mapped[str] = mapped_column(String(16))


class ProfileAccess(Base):
    __tablename__ = "discovery_access"
    __table_args__ = (UniqueConstraint("profile_id", "user_id"), TABLE_OPTIONS)
    id: Mapped[str] = mapped_column(UUID_TYPE, primary_key=True)
    profile_id: Mapped[str] = mapped_column(
        ForeignKey("discovery_profiles.id", ondelete="RESTRICT")
    )
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    is_active: Mapped[bool] = mapped_column(Boolean)


class Material(Base):
    __tablename__ = "discovery_materials"
    __table_args__ = (
        CheckConstraint(
            "purpose IN ('SELLER_CAPABILITY','BUYER_DEMAND')", name="ck_discovery_purpose"
        ),
        UniqueConstraint("profile_id", "purpose", "sha256"),
        Index("ix_discovery_material_profile", "profile_id", "created_at", "id"),
        TABLE_OPTIONS,
    )
    id: Mapped[str] = mapped_column(UUID_TYPE, primary_key=True)
    profile_id: Mapped[str] = mapped_column(
        ForeignKey("discovery_profiles.id", ondelete="RESTRICT")
    )
    uploaded_by: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    title: Mapped[str] = mapped_column(String(200))
    purpose: Mapped[str] = mapped_column(String(32))
    content: Mapped[str] = mapped_column(MEDIUMTEXT)
    original_bytes: Mapped[bytes] = mapped_column(MEDIUMBLOB)
    sha256: Mapped[bytes] = mapped_column(BINARY(32))
    created_at: Mapped[datetime] = mapped_column(DATETIME(fsp=6))


class DiscoveryRun(Versioned, Base):
    __tablename__ = "discovery_runs"
    __table_args__ = (
        UniqueConstraint("created_by", "request_token"),
        CheckConstraint(
            "status IN ('QUEUED','RUNNING','SUCCEEDED','FAILED')", name="ck_discovery_run"
        ),
        CheckConstraint(
            "version >= 1 AND attempts >= 0 AND attempts <= 3", name="ck_discovery_run_version"
        ),
        Index("ix_discovery_run_claim", "status", "lease_until", "created_at", "id"),
        TABLE_OPTIONS,
    )
    id: Mapped[str] = mapped_column(UUID_TYPE, primary_key=True)
    profile_id: Mapped[str] = mapped_column(
        ForeignKey("discovery_profiles.id", ondelete="RESTRICT")
    )
    created_by: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    request_token: Mapped[str] = mapped_column(UUID_TYPE)
    request_hash: Mapped[bytes] = mapped_column(BINARY(32))
    profile_snapshot: Mapped[dict] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(16))
    attempts: Mapped[int] = mapped_column(default=0)
    lease_token: Mapped[str | None] = mapped_column(UUID_TYPE)
    lease_until: Mapped[datetime | None] = mapped_column(DATETIME(fsp=6))
    error_code: Mapped[str | None] = mapped_column(String(64))
    result_count: Mapped[int] = mapped_column(default=0)


class RunMaterial(Base):
    __tablename__ = "discovery_run_materials"
    __table_args__ = (TABLE_OPTIONS,)
    run_id: Mapped[str] = mapped_column(
        ForeignKey("discovery_runs.id", ondelete="RESTRICT"), primary_key=True
    )
    material_id: Mapped[str] = mapped_column(
        ForeignKey("discovery_materials.id", ondelete="RESTRICT"), primary_key=True
    )


class DiscoveryLead(Versioned, Base):
    __tablename__ = "discovery_leads"
    __table_args__ = (
        UniqueConstraint("material_id"),
        CheckConstraint(
            "status IN ('NEW','IN_REVIEW','QUALIFIED','DISQUALIFIED')", name="ck_discovery_lead"
        ),
        CheckConstraint("version >= 1", name="ck_discovery_lead_version"),
        Index("ix_discovery_lead_profile", "profile_id", "status", "created_at", "id"),
        TABLE_OPTIONS,
    )
    id: Mapped[str] = mapped_column(UUID_TYPE, primary_key=True)
    profile_id: Mapped[str] = mapped_column(
        ForeignKey("discovery_profiles.id", ondelete="RESTRICT")
    )
    run_id: Mapped[str] = mapped_column(ForeignKey("discovery_runs.id", ondelete="RESTRICT"))
    material_id: Mapped[str] = mapped_column(
        ForeignKey("discovery_materials.id", ondelete="RESTRICT")
    )
    owner_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    buyer_name: Mapped[str] = mapped_column(String(200))
    project_name: Mapped[str] = mapped_column(String(200))
    notice_type: Mapped[str] = mapped_column(String(32))
    analysis: Mapped[dict] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(24))
    summary_shared: Mapped[bool] = mapped_column(Boolean, default=False)
    review_note: Mapped[str | None] = mapped_column(String(1000))
    account_id: Mapped[str | None] = mapped_column(ForeignKey("accounts.id", ondelete="RESTRICT"))


class AccountLink(Base):
    __tablename__ = "discovery_account_links"
    __table_args__ = (UniqueConstraint("lead_id"), TABLE_OPTIONS)
    id: Mapped[str] = mapped_column(UUID_TYPE, primary_key=True)
    lead_id: Mapped[str] = mapped_column(ForeignKey("discovery_leads.id", ondelete="RESTRICT"))
    account_id: Mapped[str] = mapped_column(ForeignKey("accounts.id", ondelete="RESTRICT"))
    actor_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    request_key: Mapped[str] = mapped_column(String(128))
    request_hash: Mapped[bytes] = mapped_column(BINARY(32))
    result: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DATETIME(fsp=6))


class SearchGuard(Base):
    __tablename__ = "discovery_search_guard"
    __table_args__ = (CheckConstraint("id = 1", name="ck_search_guard_singleton"), TABLE_OPTIONS)
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)
    version: Mapped[int] = mapped_column(Integer)


class SearchRun(Versioned, Base):
    __tablename__ = "discovery_search_runs"
    __table_args__ = (
        UniqueConstraint("created_by", "request_token", name="uq_search_actor_token"),
        CheckConstraint(
            "status IN ('QUEUED','RUNNING','SUCCEEDED','FAILED','OUTCOME_UNKNOWN')",
            name="ck_search_status",
        ),
        CheckConstraint("version >= 1 AND profile_version >= 1", name="ck_search_versions"),
        Index("ix_search_claim", "status", "lease_until", "created_at"),
        Index("ix_search_profile", "profile_id", "created_at", "id"),
        Index("ix_search_user_quota", "created_by", "created_at"),
        Index("ix_search_global_quota", "created_at"),
        TABLE_OPTIONS,
    )
    id: Mapped[str] = mapped_column(UUID_TYPE, primary_key=True)
    profile_id: Mapped[str] = mapped_column(
        ForeignKey("discovery_profiles.id", ondelete="RESTRICT")
    )
    created_by: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    request_token: Mapped[str] = mapped_column(UUID_TYPE)
    request_hash: Mapped[bytes] = mapped_column(BINARY(32))
    profile_version: Mapped[int] = mapped_column(Integer)
    public_query: Mapped[str] = mapped_column(String(200))
    endpoint: Mapped[str] = mapped_column(String(100))
    status: Mapped[str] = mapped_column(String(24))
    provider_attempted: Mapped[bool] = mapped_column(Boolean, default=False)
    lease_token: Mapped[str | None] = mapped_column(UUID_TYPE)
    lease_until: Mapped[datetime | None] = mapped_column(DATETIME(fsp=6))
    started_at: Mapped[datetime | None] = mapped_column(DATETIME(fsp=6))
    completed_at: Mapped[datetime | None] = mapped_column(DATETIME(fsp=6))
    error_code: Mapped[str | None] = mapped_column(String(64))
    result: Mapped[dict | None] = mapped_column(JSON)
