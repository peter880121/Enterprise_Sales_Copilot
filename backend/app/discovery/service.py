import hashlib
import json
from uuid import uuid4

from sqlalchemy import exists, func, or_, select

from app.auth.models import Role, User
from app.auth.service import now
from app.core.errors import AppError
from app.crm.models import Account, AuditEvent
from app.crm.repository import CRMRepository
from app.crm.schemas import AccountCreate
from app.crm.service import MANAGERS, SELLERS, CRMService
from app.discovery.models import (
    AccountLink,
    DiscoveryLead,
    DiscoveryRun,
    Material,
    ProfileAccess,
    RunMaterial,
    SalesProfile,
)
from app.discovery.tavily import destination
from app.sales.service import encode
from app.users.service import UserService


def digest(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def audit(session, entity, actor_id, action, request_id, before=None):
    # Global audit readers must never receive private filenames, notes or profile terms.
    after = {
        "id": entity.id,
        "version": getattr(entity, "version", None),
        "status": getattr(entity, "status", None),
    }
    session.add(
        AuditEvent(
            id=str(uuid4()),
            entity_type="DISCOVERY",
            entity_id=entity.id,
            actor_kind="USER" if actor_id else "SYSTEM",
            actor_id=actor_id,
            action=action,
            before_state=before,
            after_state=after,
            reason=None,
            expected_version=before.get("version") if before else None,
            resulting_version=getattr(entity, "version", None),
            request_id=request_id,
            mutation_event_key=f"discovery:{entity.id}:{action}:{getattr(entity, 'version', 1)}",
            created_at=now(),
        )
    )
    session.flush()


class DiscoveryService:
    def __init__(self, db, settings):
        self.db, self.settings = db, settings

    def actor(self, session, identity, *, write=False, extra_ids=()):
        repo = CRMRepository(session)
        if write:
            for uid in sorted({identity.user.id, *(str(uid) for uid in extra_ids)}):
                repo.get(User, uid, lock=True)
        actor = repo.get(User, identity.user.id)
        users = UserService(self.db, self.settings)
        users.active(actor)
        if write:
            users.session_live(session, identity)
            if actor.role not in SELLERS:
                raise AppError(403, "FORBIDDEN", "只读账号不能修改发现资料或触发任务。")
        return actor

    def required(self, session, model, entity_id, lock=False):
        value = CRMRepository(session).get(model, entity_id, lock=lock)
        if value is None:
            raise AppError(404, "NOT_FOUND", "发现对象不存在。")
        return value

    def mutate(self, session, row, fields):
        if not CRMRepository(session).cas(type(row), row.id, row.version, fields):
            raise AppError(409, "VERSION_CONFLICT", "数据已变化，操作已回滚。")
        session.refresh(row)

    def reviewers(self, identity, q, page):
        with self.db.transaction() as s:
            actor = self.actor(s, identity)
            if actor.role not in SELLERS:
                raise AppError(403, "FORBIDDEN", "只读账号不能配置评审者。")
            query = select(User).where(
                User.role.in_(MANAGERS),
                User.is_active.is_(True),
                User.registration_status == "APPROVED",
                User.deleted_at.is_(None),
            )
            if q:
                query = query.where(User.name.contains(q, autoescape=True))
            total = s.scalar(select(func.count()).select_from(query.subquery()))
            return [
                {"id": row.id, "name": row.name, "role": row.role}
                for row in s.scalars(
                    query.order_by(User.name, User.id).offset((page - 1) * 20).limit(20)
                )
            ], total

    def visible(self, actor):
        grants = exists(
            select(ProfileAccess.id).where(
                ProfileAccess.profile_id == SalesProfile.id,
                ProfileAccess.user_id == actor.id,
                ProfileAccess.is_active.is_(True),
            )
        )
        return or_(
            SalesProfile.owner_id == actor.id,
            SalesProfile.visibility == "TEAM",
            grants if actor.role in MANAGERS else False,
        )

    def access(self, session, actor, profile_id, *, write=False):
        profile = self.required(session, SalesProfile, profile_id, lock=write)
        granted = (
            actor.role in MANAGERS
            and session.scalar(
                select(ProfileAccess.id).where(
                    ProfileAccess.profile_id == profile.id,
                    ProfileAccess.user_id == actor.id,
                    ProfileAccess.is_active.is_(True),
                )
            )
            is not None
        )
        if actor.role == Role.READ_ONLY or not (
            profile.owner_id == actor.id or granted or (not write and profile.visibility == "TEAM")
        ):
            raise AppError(403, "FORBIDDEN", "没有此发现空间及原始资料的权限。")
        return profile

    def profile_view(self, session, row):
        reviewers = [
            {"id": user.id, "name": user.name, "role": user.role}
            for user in session.scalars(
                select(User)
                .join(ProfileAccess, ProfileAccess.user_id == User.id)
                .where(ProfileAccess.profile_id == row.id, ProfileAccess.is_active.is_(True))
                .order_by(User.id)
            )
        ]
        return encode(
            {
                name: getattr(row, name)
                for name in (
                    "id",
                    "owner_id",
                    "name",
                    "product",
                    "keywords",
                    "regions",
                    "visibility",
                    "version",
                    "created_at",
                    "updated_at",
                )
            }
            | {"reviewer_ids": [user["id"] for user in reviewers], "reviewers": reviewers}
        )

    def profiles(self, identity, page=1):
        with self.db.transaction() as s:
            actor = self.actor(s, identity)
            if actor.role == Role.READ_ONLY:
                return [], 0
            query = select(SalesProfile).where(self.visible(actor))
            total = s.scalar(select(func.count()).select_from(query.subquery()))
            rows = s.scalars(
                query.order_by(SalesProfile.created_at.desc(), SalesProfile.id)
                .offset((page - 1) * 20)
                .limit(20)
            )
            return [self.profile_view(s, row) for row in rows], total

    def search_preview(self, identity, profile_id, body):
        with self.db.transaction() as s:
            actor = self.actor(s, identity)
            profile = self.access(s, actor, profile_id)
            if profile.version != body.expected_profile_version:
                raise AppError(409, "VERSION_CONFLICT", "画像已变化，请重新读取后核对公开查询。")
            configured = False
            try:
                destination(self.settings.tavily_base_url)
                configured = bool(self.settings.tavily_api_key)
            except AppError:
                pass
            # Explicit public input only. Never derive query text from private profile/materials.
            return {
                "provider": "TAVILY",
                "public_query": body.public_query,
                "profile_id": profile.id,
                "profile_version": profile.version,
                "max_results": 5,
                "search_depth": "basic",
                "configured": configured,
                "external_request_sent": False,
                "web_execution_available": False,
                "notice": "当前仅预览公开查询；网页搜索执行须待持久化请求去重与额度门禁接入。",
            }

    def profile(self, identity, entity_id):
        with self.db.transaction() as s:
            actor = self.actor(s, identity)
            return self.profile_view(s, self.access(s, actor, entity_id))

    def save_profile(self, identity, body, request_id, entity_id=None):
        with self.db.transaction() as s:
            actor = self.actor(s, identity, write=True, extra_ids=body.reviewer_ids)
            row = self.access(s, actor, entity_id, write=True) if entity_id else None
            if row and (row.version != body.expected_version or row.visibility != body.visibility):
                raise AppError(
                    409, "VERSION_CONFLICT", "画像已变化或可见性不同；共享范围需新建空间。"
                )
            prior = (
                list(s.scalars(select(ProfileAccess).where(ProfileAccess.profile_id == row.id)))
                if row
                else []
            )
            requested = {str(uid) for uid in body.reviewer_ids}
            if (
                row
                and actor.id != row.owner_id
                and requested != {g.user_id for g in prior if g.is_active}
            ):
                raise AppError(403, "FORBIDDEN", "只有创建者可以更改评审者授权。")
            for uid in requested:
                reviewer = s.get(User, uid)
                if not reviewer or not reviewer.is_active or reviewer.role not in MANAGERS:
                    raise AppError(422, "REVIEWER_INVALID", "评审者必须是有效经理或管理员。")
            before = {"version": row.version} if row else None
            if row is None:
                row = SalesProfile(
                    id=str(uuid4()),
                    owner_id=actor.id,
                    version=1,
                    created_at=now(),
                    updated_at=now(),
                )
                for name in ("name", "product", "keywords", "regions", "visibility"):
                    setattr(row, name, getattr(body, name))
                s.add(row)
                s.flush()
            else:
                self.mutate(
                    s,
                    row,
                    {
                        name: getattr(body, name)
                        for name in ("name", "product", "keywords", "regions")
                    }
                    | {"updated_at": now()},
                )
            for grant in prior:
                grant.is_active = grant.user_id in requested
            for uid in requested - {g.user_id for g in prior}:
                s.add(
                    ProfileAccess(id=str(uuid4()), profile_id=row.id, user_id=uid, is_active=True)
                )
            audit(s, row, actor.id, "DISCOVERY_PROFILE_SAVED", request_id, before)
            return self.profile_view(s, row)

    def add_material(self, identity, profile_id, body, request_id, original_bytes=None):
        raw = original_bytes if original_bytes is not None else body.content.encode("utf8")
        if len(raw) > 65536:
            raise AppError(413, "MATERIAL_TOO_LARGE", "D1文本资料上限64 KiB。")
        with self.db.transaction() as s:
            actor = self.actor(s, identity, write=True)
            profile = self.access(s, actor, profile_id, write=True)
            if profile.visibility == "TEAM" and not body.confirm_team_visibility:
                raise AppError(
                    422, "SHARING_CONFIRMATION_REQUIRED", "请明确确认资料在团队空间共享。"
                )
            sha = hashlib.sha256(raw).digest()
            prior = s.scalar(
                select(Material).where(
                    Material.profile_id == profile.id,
                    Material.purpose == body.purpose,
                    Material.sha256 == sha,
                )
            )
            if prior:
                return self.material_view(prior)
            row = Material(
                id=str(uuid4()),
                profile_id=profile.id,
                uploaded_by=actor.id,
                title=body.title,
                purpose=body.purpose,
                content=body.content,
                original_bytes=raw,
                sha256=sha,
                created_at=now(),
            )
            s.add(row)
            s.flush()
            audit(s, row, actor.id, "DISCOVERY_MATERIAL_ADDED", request_id)
            return self.material_view(row)

    def material_view(self, row, detail=False):
        data = encode(
            {
                key: getattr(row, key)
                for key in ("id", "profile_id", "title", "purpose", "created_at")
            }
        )
        return (
            data
            | {"sha256": row.sha256.hex()}
            | (
                {
                    "content": row.content,
                    "text_sha256": hashlib.sha256(row.content.encode()).hexdigest(),
                }
                if detail
                else {}
            )
        )

    def materials(self, identity, profile_id, page=1):
        with self.db.transaction() as s:
            actor = self.actor(s, identity)
            self.access(s, actor, profile_id)
            query = select(Material).where(Material.profile_id == profile_id)
            total = s.scalar(select(func.count()).select_from(query.subquery()))
            return [
                self.material_view(row)
                for row in s.scalars(
                    query.order_by(Material.created_at.desc(), Material.id)
                    .offset((page - 1) * 20)
                    .limit(20)
                )
            ], total

    def material(self, identity, material_id):
        with self.db.transaction() as s:
            actor = self.actor(s, identity)
            row = self.required(s, Material, material_id)
            self.access(s, actor, row.profile_id)
            return self.material_view(row, True)

    def start(self, identity, profile_id, body, request_id):
        with self.db.transaction() as s:
            actor = self.actor(s, identity, write=True)
            profile = self.access(s, actor, profile_id, write=True)
            hashed = bytes.fromhex(
                digest({"profile_id": profile_id, **body.model_dump(mode="json")})
            )
            prior = s.scalar(
                select(DiscoveryRun).where(
                    DiscoveryRun.created_by == actor.id,
                    DiscoveryRun.request_token == str(body.request_token),
                )
            )
            if prior:
                if prior.request_hash != hashed:
                    raise AppError(409, "IDEMPOTENCY_KEY_REUSED", "请求标识已用于其他内容。")
                return self.run_view(prior)
            if profile.version != body.expected_profile_version:
                raise AppError(409, "VERSION_CONFLICT", "画像已变化，请重新读取。")
            for uid in body.material_ids:
                material = self.required(s, Material, str(uid))
                if material.profile_id != profile.id or material.purpose != "BUYER_DEMAND":
                    raise AppError(422, "MATERIAL_SCOPE_INVALID", "只能选择本空间的采购需求资料。")
            row = DiscoveryRun(
                id=str(uuid4()),
                profile_id=profile.id,
                created_by=actor.id,
                request_token=str(body.request_token),
                request_hash=hashed,
                profile_snapshot=self.profile_view(s, profile),
                status="QUEUED",
                attempts=0,
                result_count=0,
                version=1,
                created_at=now(),
                updated_at=now(),
            )
            s.add(row)
            s.flush()
            for uid in body.material_ids:
                s.add(RunMaterial(run_id=row.id, material_id=str(uid)))
            audit(s, row, actor.id, "DISCOVERY_RUN_QUEUED", request_id)
            return self.run_view(row)

    def run_view(self, row):
        return encode(
            {
                key: getattr(row, key)
                for key in (
                    "id",
                    "profile_id",
                    "status",
                    "result_count",
                    "error_code",
                    "created_at",
                    "updated_at",
                )
            }
            | {"mode": "RULES", "provider_called": False}
        )

    def run(self, identity, entity_id):
        with self.db.transaction() as s:
            actor = self.actor(s, identity)
            row = self.required(s, DiscoveryRun, entity_id)
            self.access(s, actor, row.profile_id)
            return self.run_view(row)

    def lead_view(self, row, summary=False):
        data = encode(
            {
                key: getattr(row, key)
                for key in (
                    "id",
                    "buyer_name",
                    "project_name",
                    "notice_type",
                    "status",
                    "version",
                    "account_id",
                    "created_at",
                    "updated_at",
                )
            }
        )
        return (
            data
            | {"summary_only": summary}
            | (
                {}
                if summary
                else {
                    "profile_id": row.profile_id,
                    "owner_id": row.owner_id,
                    "material_id": row.material_id,
                    "analysis": row.analysis,
                    "review_note": row.review_note,
                }
            )
        )

    def leads(self, identity, page, q, status=None):
        with self.db.transaction() as s:
            actor = self.actor(s, identity)
            filters = [self.visible(actor)]
            if actor.role == Role.READ_ONLY:
                filters += [
                    SalesProfile.visibility == "TEAM",
                    DiscoveryLead.status == "QUALIFIED",
                    DiscoveryLead.summary_shared.is_(True),
                ]
            if q:
                filters.append(
                    or_(
                        DiscoveryLead.buyer_name.contains(q, autoescape=True),
                        DiscoveryLead.project_name.contains(q, autoescape=True),
                    )
                )
            if status:
                filters.append(DiscoveryLead.status == status)
            query = (
                select(DiscoveryLead)
                .join(SalesProfile, SalesProfile.id == DiscoveryLead.profile_id)
                .where(*filters)
            )
            total = s.scalar(select(func.count()).select_from(query.subquery()))
            rows = s.scalars(
                query.order_by(DiscoveryLead.created_at.desc(), DiscoveryLead.id)
                .offset((page - 1) * 20)
                .limit(20)
            )
            return [self.lead_view(row, actor.role == Role.READ_ONLY) for row in rows], total

    def lead(self, identity, entity_id):
        with self.db.transaction() as s:
            actor = self.actor(s, identity)
            row = self.required(s, DiscoveryLead, entity_id)
            if actor.role == Role.READ_ONLY:
                profile = self.required(s, SalesProfile, row.profile_id)
                if (
                    profile.visibility != "TEAM"
                    or row.status != "QUALIFIED"
                    or not row.summary_shared
                ):
                    raise AppError(403, "FORBIDDEN", "此线索未共享审核后的摘要。")
            else:
                profile = self.access(s, actor, row.profile_id)
            return self.lead_view(row, actor.role == Role.READ_ONLY) | {
                "can_share_summary": actor.role != Role.READ_ONLY and profile.visibility == "TEAM"
            }

    def review(self, identity, entity_id, body, request_id):
        with self.db.transaction() as s:
            actor = self.actor(s, identity, write=True)
            preview = self.required(s, DiscoveryLead, entity_id)
            profile = self.access(s, actor, preview.profile_id, write=True)
            row = self.required(s, DiscoveryLead, entity_id, True)
            if row.version != body.expected_version:
                raise AppError(409, "VERSION_CONFLICT", "线索已变化，输入未自动覆盖。")
            allowed = {
                "NEW": {"IN_REVIEW", "DISQUALIFIED"},
                "IN_REVIEW": {"QUALIFIED", "DISQUALIFIED"},
                "QUALIFIED": {"DISQUALIFIED"},
                "DISQUALIFIED": {"IN_REVIEW"},
            }
            if body.status not in allowed[row.status]:
                raise AppError(409, "INVALID_LEAD_TRANSITION", "请按线索评审流程操作。")
            if body.publish_summary and (
                profile.visibility != "TEAM" or body.status != "QUALIFIED"
            ):
                raise AppError(
                    422, "SHARING_SCOPE_INVALID", "仅团队空间的已认可线索可明确共享摘要。"
                )
            before = {"status": row.status, "version": row.version}
            self.mutate(
                s,
                row,
                {
                    "status": body.status,
                    "summary_shared": body.publish_summary,
                    "review_note": body.reason,
                    "updated_at": now(),
                },
            )
            audit(s, row, actor.id, "DISCOVERY_LEAD_REVIEWED", request_id, before)
            return self.lead_view(row) | {"can_share_summary": profile.visibility == "TEAM"}

    def link_plan(self, session, actor, row, body):
        if row.status != "QUALIFIED":
            raise AppError(409, "LEAD_NOT_QUALIFIED", "请先人工认可此线索。")
        if row.version != body.expected_version:
            raise AppError(409, "VERSION_CONFLICT", "线索已变化，请重新预览。")
        target = None
        if body.existing_account_id:
            target = self.required(session, Account, str(body.existing_account_id), True)
            if not target.is_active:
                raise AppError(422, "ACCOUNT_INACTIVE", "不能关联已停用客户。")
        fields = {
            "account_id": target.id if target else None,
            "account_name": target.name if target else body.new_account_name,
            "account_version": target.version if target else None,
            "owner_id": target.owner_id if target else actor.id,
            "owner_name": session.get(User, target.owner_id).name if target else actor.name,
        }
        plan = {"lead_id": row.id, "lead_version": row.version, "actor_id": actor.id, **fields}
        return plan | {
            "preview_hash": digest(plan),
            "shared_crm": True,
            "notice": "新建客户基础字段对全企业CRM用户可读；原始资料不会复制。",
        }

    def account_preview(self, identity, entity_id, body):
        with self.db.transaction() as s:
            actor = self.actor(s, identity, write=True)
            preview = self.required(s, DiscoveryLead, entity_id)
            self.access(s, actor, preview.profile_id, write=True)
            row = self.required(s, DiscoveryLead, entity_id, True)
            return self.link_plan(s, actor, row, body)

    def link_account(self, identity, entity_id, body, key, request_id):
        hashed = bytes.fromhex(digest(body.model_dump(mode="json")))
        with self.db.transaction() as s:
            actor = self.actor(s, identity, write=True)
            preview = self.required(s, DiscoveryLead, entity_id)
            self.access(s, actor, preview.profile_id, write=True)
            row = self.required(s, DiscoveryLead, entity_id, True)
            prior = s.scalar(select(AccountLink).where(AccountLink.lead_id == row.id))
            if prior:
                if prior.request_hash == hashed and prior.actor_id == actor.id:
                    return prior.result
                if prior.actor_id == actor.id and prior.request_key == key:
                    raise AppError(409, "IDEMPOTENCY_KEY_REUSED", "幂等键已用于其他客户映射。")
                raise AppError(409, "ALREADY_LINKED", "此线索已绑定客户，不能重复创建或隐式替换。")
            plan = self.link_plan(s, actor, row, body)
            if body.preview_hash != plan["preview_hash"]:
                raise AppError(409, "PREVIEW_STALE", "预览已变化，请重新核对。")
            if body.existing_account_id:
                account = self.required(s, Account, str(body.existing_account_id))
            else:
                validated = AccountCreate(name=body.new_account_name)
                account = Account(
                    id=str(uuid4()),
                    owner_id=actor.id,
                    name=validated.name,
                    industry=None,
                    website=None,
                    company_size=None,
                    description=None,
                    is_active=True,
                    version=1,
                    created_at=now(),
                    updated_at=now(),
                )
                s.add(account)
                s.flush()
                CRMService(self.db).audit(s, account, actor.id, None, None, request_id)
            before = {"status": row.status, "version": row.version}
            self.mutate(s, row, {"account_id": account.id, "updated_at": now()})
            audit(s, row, actor.id, "DISCOVERY_ACCOUNT_LINKED", request_id, before)
            result = {
                "lead_id": row.id,
                "account_id": account.id,
                "result_version": row.version,
                "opportunity_created": False,
            }
            s.add(
                AccountLink(
                    id=str(uuid4()),
                    lead_id=row.id,
                    account_id=account.id,
                    actor_id=actor.id,
                    request_key=key,
                    request_hash=hashed,
                    result=result,
                    created_at=now(),
                )
            )
            s.flush()
            return result
