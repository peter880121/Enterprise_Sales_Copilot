from uuid import uuid4

from app.auth.models import Role, User
from app.auth.service import now
from app.core.errors import AppError
from app.crm.models import Account, AuditEvent
from app.crm.repository import CRMRepository
from app.crm.schemas import AccountView, ContactView, OwnerView

MANAGERS = {Role.ADMIN, Role.SALES_MANAGER}
SELLERS = MANAGERS | {Role.SALES_REP}
ACCOUNT_FIELDS = (
    "id",
    "owner_id",
    "name",
    "industry",
    "website",
    "company_size",
    "description",
    "is_active",
    "version",
)
CONTACT_FIELDS = (
    "id",
    "account_id",
    "name",
    "title",
    "email",
    "phone",
    "decision_role",
    "is_active",
    "version",
)


def can_write(role, actor_id, owner_id):
    return role in MANAGERS or (role == Role.SALES_REP and actor_id == owner_id)


class CRMService:
    def __init__(self, db):
        self.db = db

    def actor(self, repository, identity):
        # Recheck current user under a lock within the same write transaction.
        user = repository.get(User, identity.user.id, lock=True)
        if not user or not user.is_active:
            raise AppError(401, "SESSION_EXPIRED", "会话已失效。")
        if user.role not in SELLERS:
            raise AppError(403, "FORBIDDEN", "当前角色没有写入权限。")
        return user

    def required(self, repository, model, entity_id, *, lock=False):
        entity = repository.get(model, entity_id, lock=lock)
        if entity is None:
            raise AppError(404, "NOT_FOUND", "对象不存在。")
        return entity

    def permit(self, actor, account):
        if not can_write(actor.role, actor.id, account.owner_id):
            raise AppError(403, "FORBIDDEN", "只有客户负责人或经理可修改。")

    def owner(self, repository, owner_id):
        owner = repository.owner(owner_id)
        if not owner or not owner.is_active or owner.role not in SELLERS:
            raise AppError(422, "OWNER_INVALID", "负责人必须是有效销售角色。")
        return owner

    def view(self, repository, entity):
        if isinstance(entity, Account):
            owner = repository.get(User, entity.owner_id)
            return AccountView.model_validate(
                {
                    **{key: getattr(entity, key) for key in ACCOUNT_FIELDS},
                    "created_at": entity.created_at,
                    "updated_at": entity.updated_at,
                    "owner": OwnerView.model_validate(owner),
                }
            )
        return ContactView.model_validate(entity)

    def audit(self, session, entity, actor_id, before, expected_version, request_id):
        kind = "ACCOUNT" if isinstance(entity, Account) else "CONTACT"
        fields = ACCOUNT_FIELDS if kind == "ACCOUNT" else CONTACT_FIELDS
        session.add(
            AuditEvent(
                id=str(uuid4()),
                entity_type=kind,
                entity_id=entity.id,
                actor_kind="USER",
                actor_id=actor_id,
                action=f"{kind}_{'UPDATED' if before else 'CREATED'}",
                before_state=before,
                after_state={key: getattr(entity, key) for key in fields},
                reason=None,
                expected_version=expected_version,
                resulting_version=entity.version,
                request_id=request_id,
                mutation_event_key=f"{kind.lower()}:{entity.id}:{entity.version}",
                created_at=now(),
            )
        )
        session.flush()

    def detail(self, model, entity_id):
        with self.db.transaction() as session:
            repository = CRMRepository(session)
            return self.view(repository, self.required(repository, model, entity_id))

    def listing(self, model, query, account_id=None):
        with self.db.transaction() as session:
            repository = CRMRepository(session)
            if account_id:
                self.required(repository, Account, account_id)
                query = query.model_copy(update={"account_id": account_id})
            rows, total = repository.list(model, query)
            return [self.view(repository, row) for row in rows], total

    def create(self, model, body, identity, request_id):
        with self.db.transaction() as session:
            repository = CRMRepository(session)
            actor = self.actor(repository, identity)
            values = body.model_dump(mode="json")
            if model is Account:
                owner_id = values.get("owner_id") or actor.id
                if actor.role == Role.SALES_REP and owner_id != actor.id:
                    raise AppError(403, "FORBIDDEN", "销售人员只能创建本人负责的客户。")
                self.owner(repository, owner_id)
                values["owner_id"] = owner_id
            else:
                account = self.required(repository, Account, values["account_id"], lock=True)
                self.permit(actor, account)
                if not account.is_active:
                    raise AppError(422, "ACCOUNT_INACTIVE", "不能向停用客户新增联系人。")
            current = now()
            entity = model(
                id=str(uuid4()),
                **values,
                is_active=True,
                version=1,
                created_at=current,
                updated_at=current,
            )
            session.add(entity)
            session.flush()
            self.audit(session, entity, actor.id, None, None, request_id)
            return self.view(repository, entity)

    def patch(self, model, entity_id, body, identity, request_id):
        with self.db.transaction() as session:
            repository = CRMRepository(session)
            actor = self.actor(repository, identity)
            # All contact writes lock the account before the contact. Account IDs are immutable.
            entity = self.required(repository, model, entity_id)
            account_id = entity.id if model is Account else entity.account_id
            account = self.required(repository, Account, account_id, lock=True)
            self.permit(actor, account)
            session.refresh(entity)
            values = body.model_dump(mode="json", exclude_unset=True)
            version = values.pop("expected_version")
            if model is Account and "owner_id" in values:
                if actor.role not in MANAGERS:
                    raise AppError(403, "FORBIDDEN", "仅经理或管理员可更换负责人。")
                self.owner(repository, values["owner_id"])
            fields = ACCOUNT_FIELDS if model is Account else CONTACT_FIELDS
            before = {key: getattr(entity, key) for key in fields}
            if not repository.cas(model, entity_id, version, {**values, "updated_at": now()}):
                raise AppError(
                    409,
                    "VERSION_CONFLICT",
                    "数据已更新，请重新读取并确认。",
                    details={"expected_version": version, "current_version": entity.version},
                )
            session.refresh(entity)
            self.audit(session, entity, actor.id, before, version, request_id)
            return self.view(repository, entity)
