from datetime import datetime
from enum import StrEnum

from sqlalchemy import BigInteger, Boolean, CheckConstraint, ForeignKey, Index, String
from sqlalchemy.dialects.mysql import BINARY, DATETIME
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class Role(StrEnum):
    ADMIN = "ADMIN"
    SALES_MANAGER = "SALES_MANAGER"
    SALES_REP = "SALES_REP"
    READ_ONLY = "READ_ONLY"


class User(Base):
    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint(
            "role IN ('ADMIN','SALES_MANAGER','SALES_REP','READ_ONLY')", name="ck_users_role"
        ),
        Index("ix_users_role_active", "role", "is_active", "id"),
        {"mysql_engine": "InnoDB", "mysql_charset": "utf8mb4"},
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    name: Mapped[str] = mapped_column(String(100))
    email: Mapped[str] = mapped_column(String(254))
    email_normalized: Mapped[str] = mapped_column(String(254), unique=True)
    password_hash: Mapped[str] = mapped_column(String(512))
    role: Mapped[str] = mapped_column(String(24))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    password_changed_at: Mapped[datetime] = mapped_column(DATETIME(fsp=6))
    version: Mapped[int] = mapped_column(BigInteger, default=1)
    created_at: Mapped[datetime] = mapped_column(DATETIME(fsp=6))
    updated_at: Mapped[datetime] = mapped_column(DATETIME(fsp=6))


class AuthSession(Base):
    __tablename__ = "sessions"
    __table_args__ = (
        Index("ix_sessions_user_revoked", "user_id", "revoked_at"),
        Index("ix_sessions_expiry", "absolute_expires_at"),
        {"mysql_engine": "InnoDB", "mysql_charset": "utf8mb4"},
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    token_hash: Mapped[bytes] = mapped_column(BINARY(32), unique=True)
    csrf_nonce: Mapped[bytes] = mapped_column(BINARY(32))
    created_at: Mapped[datetime] = mapped_column(DATETIME(fsp=6))
    last_seen_at: Mapped[datetime] = mapped_column(DATETIME(fsp=6))
    idle_expires_at: Mapped[datetime] = mapped_column(DATETIME(fsp=6))
    absolute_expires_at: Mapped[datetime] = mapped_column(DATETIME(fsp=6))
    revoked_at: Mapped[datetime | None] = mapped_column(DATETIME(fsp=6), nullable=True)


class AuthThrottle(Base):
    __tablename__ = "auth_throttles"
    __table_args__ = (
        Index("ix_throttle_expiry", "expires_at"),
        {"mysql_engine": "InnoDB", "mysql_charset": "utf8mb4"},
    )
    key_hash: Mapped[bytes] = mapped_column(BINARY(32), primary_key=True)
    window_start: Mapped[datetime] = mapped_column(DATETIME(fsp=6))
    failed_count: Mapped[int]
    blocked_until: Mapped[datetime | None] = mapped_column(DATETIME(fsp=6), nullable=True)
    expires_at: Mapped[datetime] = mapped_column(DATETIME(fsp=6))
