import hashlib
import hmac
import json
from datetime import timedelta
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.dialects.mysql import insert
from sqlalchemy.exc import IntegrityError

from app.auth.models import AuthSession, AuthThrottle, Role, User
from app.auth.schemas import UserPublic
from app.auth.security import hash_password, verify_password
from app.auth.service import now
from app.core.errors import AppError
from app.crm.models import AuditEvent
from app.sales.models import IdempotencyRecord
from app.users.repository import UserRepository
from app.users.schemas import UserAuditView

AUDIT_FIELDS = (
    "id",
    "name",
    "email",
    "role",
    "is_active",
    "registration_status",
    "deleted_at",
    "version",
    "created_at",
    "updated_at",
)


def public(user):
    return UserPublic.model_validate(user).model_dump(mode="json")


def audit_snapshot(user):
    data = public(user)
    return {key: data[key] for key in AUDIT_FIELDS}


class UserService:
    def __init__(self, db, settings):
        self.db, self.settings = db, settings

    def active(self, user):
        if (
            not user
            or not user.is_active
            or user.deleted_at
            or user.registration_status != "APPROVED"
        ):
            raise AppError(401, "SESSION_EXPIRED", "请重新登录。")

    def admin(self, user):
        self.active(user)
        if user.role != Role.ADMIN:
            raise AppError(403, "FORBIDDEN", "仅管理员可管理用户。")

    def session_live(self, session, identity):
        # Writes lock users before sessions. Recheck after waiting for concurrent management.
        auth = session.get(AuthSession, identity.session_id, with_for_update=True)
        if (
            not auth
            or auth.user_id != identity.user.id
            or auth.revoked_at
            or min(auth.idle_expires_at, auth.absolute_expires_at) <= now()
        ):
            raise AppError(401, "SESSION_EXPIRED", "会话已失效，请重新登录。")

    def audit(self, session, user, actor_id, before, request_id, action, reason=None):
        session.add(
            AuditEvent(
                id=str(uuid4()),
                entity_type="USER",
                entity_id=user.id,
                actor_kind="USER" if actor_id else "ANONYMOUS",
                actor_id=actor_id,
                action=action,
                before_state=before,
                after_state=audit_snapshot(user),
                reason=reason,
                expected_version=before["version"] if before else None,
                resulting_version=user.version,
                request_id=request_id,
                mutation_event_key=f"user:{user.id}:{user.version}",
                created_at=now(),
            )
        )
        session.flush()

    def budget(self, scope):
        key = hmac.digest(
            self.settings.csrf_signing_key.get_secret_value().encode(), scope.encode(), "sha256"
        )
        current = now()
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
            budget = session.get(AuthThrottle, key, with_for_update=True)
            if budget.expires_at <= current:
                budget.failed_count, budget.window_start, budget.expires_at = (
                    0,
                    current,
                    current + timedelta(minutes=15),
                )
            if budget.failed_count >= 20:
                raise AppError(429, "RATE_LIMITED", "请求过多，请稍后重试。")
            budget.failed_count += 1

    def register(self, body, source, request_id):
        self.budget("registration:" + source)
        encoded = hash_password(body.password)
        try:
            with self.db.transaction() as session:
                if session.scalar(select(User.id).where(User.email_normalized == body.email)):
                    return
                current = now()
                user = User(
                    id=str(uuid4()),
                    name=body.name,
                    email=body.email,
                    email_normalized=body.email,
                    password_hash=encoded,
                    role=Role.READ_ONLY,
                    is_active=False,
                    registration_status="PENDING",
                    version=1,
                    password_changed_at=current,
                    created_at=current,
                    updated_at=current,
                )
                session.add(user)
                session.flush()
                self.audit(session, user, None, None, request_id, "USER_REGISTERED")
        except IntegrityError as exc:
            if getattr(exc.orig, "args", [None])[0] != 1062 or not self.email_taken(body.email):
                raise
            # Uniform public response for an existing normalized email, including races.

    def email_taken(self, email, exclude_id=None):
        # Called only after the failed unit of work has rolled back. Other unique
        # constraints (especially audit history) must never become email success/errors.
        with self.db.transaction() as session:
            query = select(User.id).where(User.email_normalized == email)
            if exclude_id is not None:
                query = query.where(User.id != exclude_id)
            return session.scalar(query) is not None

    def listing(self, identity, query):
        with self.db.transaction() as session:
            self.admin(session.get(User, identity.user.id))
            rows, total = UserRepository(session).listing(query)
            return [public(row) for row in rows], total

    def detail(self, identity, user_id):
        with self.db.transaction() as session:
            self.admin(session.get(User, identity.user.id))
            user = session.get(User, user_id)
            if user is None:
                raise AppError(404, "NOT_FOUND", "用户不存在。")
            return public(user)

    def history(self, identity, user_id, page, size):
        with self.db.transaction() as session:
            self.admin(session.get(User, identity.user.id))
            if session.get(User, user_id) is None:
                raise AppError(404, "NOT_FOUND", "用户不存在。")
            conditions = [AuditEvent.entity_type == "USER", AuditEvent.entity_id == user_id]
            total = session.scalar(select(func.count()).select_from(AuditEvent).where(*conditions))
            rows = session.scalars(
                select(AuditEvent)
                .where(*conditions)
                .order_by(AuditEvent.created_at.desc(), AuditEvent.id)
                .offset((page - 1) * size)
                .limit(size)
            )
            return [
                UserAuditView.model_validate(row).model_dump(mode="json") for row in rows
            ], total

    def create(self, identity, body, request_id):
        encoded = hash_password(body.password)
        try:
            with self.db.transaction() as session:
                repository = UserRepository(session)
                repository.guard()
                actor = repository.lock_users(identity.user.id).get(identity.user.id)
                self.admin(actor)
                self.session_live(session, identity)
                current = now()
                user = User(
                    id=str(uuid4()),
                    name=body.name,
                    email=body.email,
                    email_normalized=body.email,
                    password_hash=encoded,
                    role=body.role,
                    is_active=body.is_active,
                    registration_status="APPROVED",
                    version=1,
                    password_changed_at=current,
                    created_at=current,
                    updated_at=current,
                )
                session.add(user)
                session.flush()
                self.audit(session, user, actor.id, None, request_id, "USER_CREATED")
                return public(user)
        except IntegrityError as exc:
            if getattr(exc.orig, "args", [None])[0] == 1062 and self.email_taken(body.email):
                raise AppError(409, "EMAIL_EXISTS", "邮箱已被占用。") from None
            raise

    def mutate(self, identity, user_id, action, body, request_id, key=None):
        try:
            with self.db.transaction() as session:
                repository = UserRepository(session)
                repository.guard()
                users = repository.lock_users(identity.user.id, user_id)
                actor, user = users.get(identity.user.id), users.get(user_id)
                self.admin(actor)
                self.session_live(session, identity)
                if user is None:
                    raise AppError(404, "NOT_FOUND", "用户不存在。")
                digest, scope = None, f"user:{user_id}:reset-password"
                if action == "reset-password":
                    digest = hmac.new(
                        self.settings.csrf_signing_key.get_secret_value().encode(),
                        json.dumps(body.model_dump(mode="json"), sort_keys=True).encode(),
                        hashlib.sha256,
                    ).hexdigest()
                    prior = session.scalar(
                        select(IdempotencyRecord).where(
                            IdempotencyRecord.actor_id == actor.id,
                            IdempotencyRecord.scope == scope,
                            IdempotencyRecord.request_key == key,
                        )
                    )
                    if prior:
                        if prior.request_hash != digest:
                            raise AppError(409, "IDEMPOTENCY_KEY_REUSED", "幂等键已用于其他内容。")
                        return prior.response
                before = audit_snapshot(user)
                changes = {"updated_at": now()}
                if action != "restore" and user.deleted_at:
                    raise AppError(409, "USER_DELETED", "请先恢复已删除用户。")
                if action == "update":
                    changes.update(
                        body.model_dump(exclude_unset=True, exclude={"expected_version", "reason"})
                    )
                    if "email" in changes:
                        changes["email_normalized"] = changes["email"]
                    if changes.get("is_active") and user.registration_status != "APPROVED":
                        raise AppError(409, "REGISTRATION_PENDING", "请通过注册审批分配角色。")
                elif action == "approve":
                    if user.registration_status != "PENDING":
                        raise AppError(409, "REGISTRATION_NOT_PENDING", "该用户无需审批。")
                    changes.update(registration_status="APPROVED", is_active=True, role=body.role)
                elif action == "delete":
                    changes.update(is_active=False, deleted_at=now())
                elif action == "restore":
                    if not user.deleted_at:
                        raise AppError(409, "USER_NOT_DELETED", "用户未被删除。")
                    changes.update(
                        deleted_at=None, is_active=user.registration_status == "APPROVED"
                    )
                elif action == "reset-password":
                    changes.update(
                        password_hash=hash_password(body.new_password), password_changed_at=now()
                    )
                else:
                    raise AppError(422, "INVALID_ACTION", "不支持的用户操作。")
                resulting_admin = (
                    changes.get("role", user.role) == Role.ADMIN
                    and changes.get("is_active", user.is_active)
                    and changes.get("deleted_at", user.deleted_at) is None
                )
                if (
                    user.role == Role.ADMIN
                    and user.is_active
                    and not resulting_admin
                    and not repository.active_admins_except(user.id)
                ):
                    raise AppError(409, "LAST_ADMIN_REQUIRED", "必须保留至少一名有效管理员。")
                repository.cas(user, body.expected_version, changes)
                repository.revoke(user.id, now())
                self.audit(
                    session,
                    user,
                    actor.id,
                    before,
                    request_id,
                    "USER_" + action.upper().replace("-", "_"),
                    body.reason,
                )
                result = public(user)
                if action == "reset-password":
                    session.add(
                        IdempotencyRecord(
                            id=str(uuid4()),
                            actor_id=actor.id,
                            scope=scope,
                            request_key=key,
                            request_hash=digest,
                            response=result,
                            created_at=now(),
                        )
                    )
                    session.flush()
                return result
        except IntegrityError as exc:
            email = getattr(body, "email", None)
            if (
                getattr(exc.orig, "args", [None])[0] == 1062
                and email is not None
                and self.email_taken(email, exclude_id=user_id)
            ):
                raise AppError(409, "EMAIL_EXISTS", "邮箱已被占用。") from None
            raise

    def profile(self, identity, body, request_id, password_change=False):
        self.budget("credential-change:" + identity.user.id)
        with self.db.transaction() as session:
            repository = UserRepository(session)
            user = repository.lock_users(identity.user.id).get(identity.user.id)
            self.active(user)
            self.session_live(session, identity)
            if not verify_password(user.password_hash, body.current_password):
                raise AppError(401, "WRONG_PASSWORD", "当前密码不正确。")
            before = audit_snapshot(user)
            current = now()
            changes = {"updated_at": current}
            if password_change:
                if verify_password(user.password_hash, body.new_password):
                    raise AppError(422, "PASSWORD_UNCHANGED", "新密码不能与当前密码相同。")
                changes.update(
                    password_hash=hash_password(body.new_password), password_changed_at=current
                )
                expected = user.version
            else:
                changes.update(name=body.name, email=body.email, email_normalized=body.email)
                expected = body.expected_version
            try:
                repository.cas(user, expected, changes)
            except IntegrityError as exc:
                if getattr(exc.orig, "args", [None])[0] == 1062:
                    raise AppError(409, "EMAIL_EXISTS", "邮箱已被占用。") from None
                raise
            repository.revoke(user.id, current)
            self.audit(
                session,
                user,
                user.id,
                before,
                request_id,
                "USER_PASSWORD_CHANGED" if password_change else "USER_PROFILE_UPDATED",
            )
            return public(user)
