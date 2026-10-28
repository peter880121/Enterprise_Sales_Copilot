from sqlalchemy import func, or_, select, update

from app.auth.models import AuthSession, Role, SystemGuard, User
from app.core.errors import AppError


class UserRepository:
    def __init__(self, session):
        self.session = session

    def guard(self):
        guard = self.session.scalar(
            select(SystemGuard).where(SystemGuard.key == "active_admin").with_for_update()
        )
        if guard is None:
            raise AppError(503, "SCHEMA_NOT_READY", "用户管理尚未完成数据库升级。")

    def lock_users(self, *ids):
        return {
            user.id: user
            for user in self.session.scalars(
                select(User)
                .where(User.id.in_(sorted(set(ids))))
                .order_by(User.id)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
        }

    def active_admins_except(self, target_id):
        return self.session.scalar(
            select(func.count())
            .select_from(User)
            .where(
                User.id != target_id,
                User.role == Role.ADMIN,
                User.is_active.is_(True),
                User.deleted_at.is_(None),
                User.registration_status == "APPROVED",
            )
        )

    def revoke(self, user_id, current):
        self.session.execute(
            update(AuthSession)
            .where(AuthSession.user_id == user_id, AuthSession.revoked_at.is_(None))
            .values(revoked_at=current)
        )

    def cas(self, user, expected, changes):
        if user.version != expected:
            raise AppError(
                409,
                "VERSION_CONFLICT",
                "用户已变化，请重新读取并确认。",
                details={"expected_version": expected, "current_version": user.version},
            )
        if (
            self.session.execute(
                update(User)
                .where(User.id == user.id, User.version == expected)
                .values(**changes, version=expected + 1)
                .execution_options(synchronize_session=False)
            ).rowcount
            != 1
        ):
            raise AppError(409, "VERSION_CONFLICT", "用户已变化，请重新读取并确认。")
        self.session.refresh(user)

    def listing(self, query):
        filters = []
        if query.q:
            filters.append(
                or_(
                    User.name.contains(query.q, autoescape=True),
                    User.email.contains(query.q, autoescape=True),
                )
            )
        if query.role:
            filters.append(User.role == query.role)
        if query.is_active is not None:
            filters.append(User.is_active == query.is_active)
        if query.status == "DELETED":
            filters.append(User.deleted_at.is_not(None))
        else:
            filters.append(User.deleted_at.is_(None))
            if query.status == "PENDING":
                filters.append(User.registration_status == "PENDING")
            elif query.status in {"ACTIVE", "DISABLED"}:
                filters += [
                    User.registration_status == "APPROVED",
                    User.is_active == (query.status == "ACTIVE"),
                ]
        total = self.session.scalar(select(func.count()).select_from(User).where(*filters))
        users = self.session.scalars(
            select(User)
            .where(*filters)
            .order_by(User.created_at.desc(), User.id)
            .offset((query.page - 1) * query.page_size)
            .limit(query.page_size)
        ).all()
        return users, total
