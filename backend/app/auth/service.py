import hmac
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from sqlalchemy import select, update
from sqlalchemy.dialects.mysql import insert

from app.auth.models import AuthSession, AuthThrottle, User
from app.auth.schemas import UserPublic
from app.auth.security import csrf_token, dummy_hash, hasher, token_hash, verify_password
from app.core.errors import AppError


def now():
    return datetime.now(UTC).replace(tzinfo=None)


@dataclass
class Identity:
    user: UserPublic
    session_id: str
    csrf: str
    expires_at: datetime
    absolute_expires_at: datetime


class AuthService:
    def __init__(self, db, settings):
        self.db, self.settings = db, settings

    def origin(self, origin: str | None):
        if origin != self.settings.allowed_origin:
            raise AppError(403, "CSRF_INVALID", "请求来源不受信任。")

    def login(self, credentials, source: str, old_token: str | None = None):
        current = now()
        key = hmac.digest(
            self.settings.csrf_signing_key.get_secret_value().encode(),
            (credentials.email + "|" + source).encode(),
            "sha256",
        )
        # Shared pre-auth attempt budget, separately committed even when login is rejected.
        with self.db.transaction() as session:
            session.execute(
                insert(AuthThrottle)
                .values(
                    key_hash=key,
                    window_start=current,
                    failed_count=0,
                    expires_at=current + timedelta(minutes=15),
                )
                .on_duplicate_key_update(key_hash=key)
            )
            throttle = session.get(AuthThrottle, key, with_for_update=True)
            if throttle.expires_at <= current:
                throttle.window_start, throttle.failed_count = current, 0
                throttle.blocked_until = None
                throttle.expires_at = current + timedelta(minutes=15)
            if throttle.failed_count >= 10:
                raise AppError(429, "RATE_LIMITED", "登录请求过多，请稍后重试。")
            throttle.failed_count += 1

        with self.db.transaction() as session:
            user = session.scalar(
                select(User).where(User.email_normalized == credentials.email).with_for_update()
            )
            valid = verify_password(
                user.password_hash if user else dummy_hash, credentials.password
            )
            if not valid or not user or not user.is_active:
                raise AppError(401, "INVALID_CREDENTIALS", "邮箱或密码不正确。")
            if hasher.check_needs_rehash(user.password_hash):
                user.password_hash = hasher.hash(credentials.password)
            if old_token:
                session.execute(
                    update(AuthSession)
                    .where(AuthSession.token_hash == token_hash(old_token))
                    .values(revoked_at=current)
                )
            token = secrets.token_urlsafe(32)
            auth = AuthSession(
                id=str(uuid4()),
                user_id=user.id,
                token_hash=token_hash(token),
                csrf_nonce=secrets.token_bytes(32),
                created_at=current,
                last_seen_at=current,
                idle_expires_at=current + timedelta(minutes=self.settings.session_idle_minutes),
                absolute_expires_at=current + timedelta(hours=self.settings.session_absolute_hours),
            )
            session.add(auth)
            session.flush()
            identity = self._identity(user, auth)
        return identity, token

    def authenticate(self, token: str | None) -> Identity:
        if not token or len(token) > 200:
            raise AppError(401, "SESSION_EXPIRED", "请先登录。")
        current = now()
        with self.db.transaction() as session:
            auth = session.scalar(
                select(AuthSession)
                .where(AuthSession.token_hash == token_hash(token))
                .with_for_update()
            )
            if (
                not auth
                or auth.revoked_at
                or min(auth.idle_expires_at, auth.absolute_expires_at) <= current
            ):
                raise AppError(401, "SESSION_EXPIRED", "会话已失效，请重新登录。")
            user = session.get(User, auth.user_id)
            if not user or not user.is_active or user.password_changed_at > auth.created_at:
                raise AppError(401, "SESSION_EXPIRED", "会话已失效，请重新登录。")
            if current - auth.last_seen_at >= timedelta(minutes=1):
                auth.last_seen_at = current
                auth.idle_expires_at = min(
                    current + timedelta(minutes=self.settings.session_idle_minutes),
                    auth.absolute_expires_at,
                )
            return self._identity(user, auth)

    def check_csrf(self, identity: Identity, supplied: str | None):
        if (
            not supplied
            or not supplied.isascii()
            or not hmac.compare_digest(identity.csrf, supplied)
        ):
            raise AppError(403, "CSRF_INVALID", "请求校验失败，请刷新页面后重试。")

    def logout(self, identity: Identity):
        with self.db.transaction() as session:
            session.execute(
                update(AuthSession)
                .where(AuthSession.id == identity.session_id)
                .values(revoked_at=now())
            )

    def _identity(self, user, auth):
        return Identity(
            UserPublic.model_validate(user),
            auth.id,
            csrf_token(self.settings.csrf_signing_key.get_secret_value(), auth.id, auth.csrf_nonce),
            min(auth.idle_expires_at, auth.absolute_expires_at),
            auth.absolute_expires_at,
        )
