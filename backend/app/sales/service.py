import hashlib
import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

from fastapi.encoders import jsonable_encoder
from sqlalchemy import and_, case, func, select

from app.auth.models import Role, User
from app.auth.service import now
from app.core.errors import AppError
from app.crm.models import Account, AuditEvent, Contact
from app.crm.repository import CRMRepository
from app.crm.service import MANAGERS, CRMService, can_write
from app.sales.audit import audit_values
from app.sales.domain import OPEN, PROBABILITY, transition, validate_evidence
from app.sales.models import Activity, CloseEvidence, IdempotencyRecord, Opportunity, StoredObject


def encode(value):
    return jsonable_encoder(
        value,
        custom_encoder={
            Decimal: lambda n: format(n, ".2f"),
            datetime: lambda d: d.replace(tzinfo=UTC).isoformat().replace("+00:00", "Z"),
        },
    )


def snapshot(entity):
    return encode({column.key: getattr(entity, column.key) for column in entity.__table__.columns})


def audit_snapshot(entity):
    return encode(audit_values(entity))


def values(body, *, patch=False):
    result = body.model_dump(exclude_unset=patch)
    for key, value in result.items():
        if isinstance(value, UUID):
            result[key] = str(value)
        elif isinstance(value, datetime):
            result[key] = value.astimezone(UTC).replace(tzinfo=None)
    return result


class SalesService(CRMService):
    def manager(self, actor):
        if actor.role not in MANAGERS:
            raise AppError(403, "FORBIDDEN", "该操作需要经理或管理员权限。")

    def authorize(self, actor, opportunity):
        if not can_write(actor.role, actor.id, opportunity.owner_id):
            raise AppError(403, "FORBIDDEN", "只有商机负责人或经理可修改。")

    def open(self, opportunity):
        if opportunity.stage not in OPEN:
            raise AppError(422, "TERMINAL_OPPORTUNITY", "已关闭商机不能普通编辑或再次关闭。")

    def version(self, entity, expected):
        if entity.version != expected:
            raise AppError(
                409,
                "VERSION_CONFLICT",
                "数据已变化，请重新读取后确认。",
                details={
                    "expected_version": expected,
                    "current_version": entity.version,
                },
            )

    def users(self, repository, identity, *extra_ids):
        # Lock users in stable order before any Account/Opportunity lock.
        for entity_id in sorted({identity.user.id, *(str(i) for i in extra_ids if i)}):
            repository.get(User, entity_id, lock=True)
        return self.actor(repository, identity)

    def locked(self, repository, opportunity_id):
        preview = self.required(repository, Opportunity, opportunity_id)
        account = self.required(repository, Account, preview.account_id, lock=True)
        opportunity = self.required(repository, Opportunity, opportunity_id, lock=True)
        return account, opportunity

    def contact(self, repository, account_id, contact_id):
        if contact_id:
            contact = repository.get(Contact, contact_id)
            if not contact or contact.account_id != account_id or not contact.is_active:
                raise AppError(422, "RELATIONSHIP_MISMATCH", "联系人须为该客户的有效联系人。")

    def audit_sales(self, session, entity, actor, before, request_id, action, reason=None):
        session.add(
            AuditEvent(
                id=str(uuid4()),
                entity_type=entity.__class__.__name__.upper(),
                entity_id=entity.id,
                actor_kind="USER",
                actor_id=actor.id,
                action=action,
                before_state=before,
                after_state=audit_snapshot(entity),
                reason=reason,
                expected_version=before["version"] if before and "version" in before else None,
                resulting_version=getattr(entity, "version", None),
                request_id=request_id,
                mutation_event_key=(
                    f"{entity.__tablename__}:{entity.id}:{getattr(entity, 'version', 1)}"
                ),
                created_at=now(),
            )
        )
        session.flush()

    def view_opportunity(self, repository, opportunity, references=None):
        data = snapshot(opportunity)
        account = (
            references["accounts"][opportunity.account_id]
            if references
            else repository.get(Account, opportunity.account_id)
        )
        owner = (
            references["owners"][opportunity.owner_id]
            if references
            else repository.get(User, opportunity.owner_id)
        )
        evidence = (
            (
                references["evidence"].get(opportunity.close_evidence_id)
                if references
                else repository.get(CloseEvidence, opportunity.close_evidence_id)
            )
            if opportunity.close_evidence_id
            else None
        )
        data.update(
            account={"id": account.id, "name": account.name},
            owner={"id": owner.id, "name": owner.name},
            actual_amount=format(evidence.amount, ".2f")
            if evidence and evidence.status == "VERIFIED" and opportunity.stage == "WON"
            else None,
            actual_currency=evidence.currency
            if evidence and evidence.status == "VERIFIED" and opportunity.stage == "WON"
            else None,
            close_evidence_type=evidence.type if evidence else None,
            close_evidence_reference=evidence.reference_number if evidence else None,
            last_activity_at=encode(
                references["activity"].get(opportunity.id)
                if references
                else repository.session.scalar(
                    select(func.max(Activity.occurred_at)).where(
                        Activity.opportunity_id == opportunity.id
                    )
                )
            ),
        )
        return data

    def detail_opportunity(self, entity_id, identity):
        with self.db.transaction() as session:
            repository = CRMRepository(session)
            entity = self.required(repository, Opportunity, entity_id)
            data = self.view_opportunity(repository, entity)
            writable = can_write(identity.user.role, identity.user.id, entity.owner_id)
            data["capabilities"] = {
                "can_edit": writable and entity.stage in OPEN,
                "can_close": identity.user.role in MANAGERS
                and entity.stage in {"NEGOTIATION", "FOLLOW_UP"},
                "can_reopen": identity.user.role in MANAGERS
                and entity.stage == "LOST"
                and not entity.is_archived,
                "can_submit_evidence": writable and entity.stage in OPEN,
            }
            return data

    def filters(self, query):
        filters = [Opportunity.is_archived == query.is_archived]
        for key in ("stage", "owner_id", "account_id", "currency", "priority"):
            value = getattr(query, key)
            if value is not None:
                filters.append(getattr(Opportunity, key) == str(value))
        if query.q:
            filters.append(Opportunity.name.contains(query.q, autoescape=True))
        return filters

    def list_opportunities(self, query):
        with self.db.transaction() as session:
            repository = CRMRepository(session)
            filters = self.filters(query)
            count = session.scalar(select(func.count()).select_from(Opportunity).where(*filters))
            rows = session.scalars(
                select(Opportunity)
                .where(*filters)
                .order_by(
                    getattr(Opportunity, query.sort),
                    Opportunity.id,
                )
                .offset((query.page - 1) * query.page_size)
                .limit(query.page_size)
            ).all()
            references = {}
            for name, model, ids in [
                ("accounts", Account, {row.account_id for row in rows}),
                ("owners", User, {row.owner_id for row in rows}),
                (
                    "evidence",
                    CloseEvidence,
                    {row.close_evidence_id for row in rows if row.close_evidence_id},
                ),
            ]:
                references[name] = (
                    {
                        entity.id: entity
                        for entity in session.scalars(select(model).where(model.id.in_(ids)))
                    }
                    if ids
                    else {}
                )
            references["activity"] = (
                dict(
                    session.execute(
                        select(Activity.opportunity_id, func.max(Activity.occurred_at))
                        .where(Activity.opportunity_id.in_([row.id for row in rows]))
                        .group_by(Activity.opportunity_id)
                    ).all()
                )
                if rows
                else {}
            )
            return [self.view_opportunity(repository, row, references) for row in rows], count

    def create_opportunity(self, body, identity, request_id):
        with self.db.transaction() as session:
            repository = CRMRepository(session)
            actor = self.users(repository, identity, body.owner_id)
            owner_id = str(body.owner_id or actor.id)
            if actor.role == Role.SALES_REP and owner_id != actor.id:
                raise AppError(403, "FORBIDDEN", "销售人员只能创建本人商机。")
            self.owner(repository, owner_id)
            account = self.required(repository, Account, str(body.account_id), lock=True)
            if not account.is_active:
                raise AppError(422, "ACCOUNT_INACTIVE", "不能在停用客户下创建商机。")
            self.contact(
                repository,
                account.id,
                str(body.primary_contact_id) if body.primary_contact_id else None,
            )
            data = values(body)
            data["owner_id"] = owner_id
            current = now()
            entity = Opportunity(
                id=str(uuid4()),
                **data,
                stage="PROPOSAL_SUBMITTED",
                probability=20,
                version=1,
                is_archived=False,
                created_at=current,
                updated_at=current,
            )
            session.add(entity)
            session.flush()
            session.refresh(entity)
            self.audit_sales(session, entity, actor, None, request_id, "OPPORTUNITY_CREATED")
            return self.view_opportunity(repository, entity)

    def patch_opportunity(self, entity_id, body, identity, request_id):
        with self.db.transaction() as session:
            repository = CRMRepository(session)
            actor = self.users(repository, identity)
            _, entity = self.locked(repository, entity_id)
            self.authorize(actor, entity)
            self.version(entity, body.expected_version)
            self.open(entity)
            data = values(body, patch=True)
            data.pop("expected_version")
            self.contact(repository, entity.account_id, data.get("primary_contact_id"))
            before = audit_snapshot(entity)
            if not repository.cas(
                Opportunity, entity.id, entity.version, {**data, "updated_at": now()}
            ):
                raise AppError(409, "VERSION_CONFLICT", "商机已变化。")
            session.refresh(entity)
            self.audit_sales(session, entity, actor, before, request_id, "OPPORTUNITY_UPDATED")
            return self.view_opportunity(repository, entity)

    def replay(self, repository, actor, scope, key, body):
        digest = hashlib.sha256(
            json.dumps(body.model_dump(mode="json"), sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        # The already-held actor lock serializes same-key calls. Results are immutable:
        # a plain SELECT avoids granting UPDATE just to permit MySQL FOR UPDATE reads.
        record = repository.session.scalar(
            select(IdempotencyRecord).where(
                IdempotencyRecord.actor_id == actor.id,
                IdempotencyRecord.scope == scope,
                IdempotencyRecord.request_key == key,
            )
        )
        if record and record.request_hash != digest:
            raise AppError(409, "IDEMPOTENCY_KEY_REUSED", "该幂等键已用于不同操作内容。")
        return record, digest

    def remember(self, session, actor, scope, key, digest, data):
        session.add(
            IdempotencyRecord(
                id=str(uuid4()),
                actor_id=actor.id,
                scope=scope,
                request_key=key,
                request_hash=digest,
                response=data,
                created_at=now(),
            )
        )
        # No expiry or cleanup policy is inferred while Q10 remains unapproved.
        session.flush()

    def command(self, entity_id, action, body, key, identity, request_id):
        with self.db.transaction() as session:
            repository = CRMRepository(session)
            actor = self.users(repository, identity, getattr(body, "owner_id", None))
            account, entity = self.locked(repository, entity_id)
            self.authorize(actor, entity)
            if action != "transitions" or body.target_stage in {"WON", "LOST"}:
                self.manager(actor)
            scope = f"opportunity:{entity_id}:{action}"
            previous, digest = self.replay(repository, actor, scope, key, body)
            if previous:
                return previous.response
            self.version(entity, body.expected_version)
            before = audit_snapshot(entity)
            data = {"updated_at": now()}
            if action == "reopen":
                if entity.stage == "WON":
                    raise AppError(422, "WON_REOPEN_NOT_ALLOWED", "MVP不允许重新打开已成交商机。")
                if entity.stage != "LOST" or entity.is_archived:
                    raise AppError(422, "NOT_LOST", "仅未归档丢单商机可重新打开。")
                data.update(
                    stage="NEGOTIATION",
                    probability=60,
                    closed_at=None,
                    closed_by=None,
                    close_reason=None,
                    close_reason_code=None,
                    close_evidence_id=None,
                )
            elif action == "archive":
                if entity.stage in OPEN:
                    raise AppError(422, "OPEN_OPPORTUNITY_CANNOT_ARCHIVE", "只能归档终态商机。")
                data.update(
                    is_archived=body.is_archived,
                    archived_at=now() if body.is_archived else None,
                    archived_by=actor.id if body.is_archived else None,
                )
            elif action == "assign-owner":
                self.open(entity)
                self.owner(repository, str(body.owner_id))
                data["owner_id"] = str(body.owner_id)
            else:
                transition(entity.stage, body.target_stage)
                if not account.is_active:
                    raise AppError(422, "ACCOUNT_INACTIVE", "停用客户的商机不能推进。")
                data.update(stage=body.target_stage, probability=PROBABILITY[body.target_stage])
                if body.target_stage == "WON":
                    evidence = (
                        repository.get(CloseEvidence, str(body.evidence_id), lock=True)
                        if body.evidence_id
                        else None
                    )
                    validate_evidence(evidence, entity)
                    stored = repository.get(StoredObject, evidence.stored_object_id)
                    if not stored or stored.status != "AVAILABLE":
                        raise AppError(422, "EVIDENCE_INVALID", "证据原件未持久化。")
                    data.update(close_evidence_id=evidence.id, closed_at=now(), closed_by=actor.id)
                elif body.target_stage == "LOST":
                    if not body.close_reason or not body.close_reason_code:
                        raise AppError(422, "CLOSE_REASON_REQUIRED", "丢单需要分类和原因。")
                    data.update(
                        close_reason=body.close_reason,
                        close_reason_code=body.close_reason_code,
                        closed_at=now(),
                        closed_by=actor.id,
                    )
            if not repository.cas(Opportunity, entity.id, entity.version, data):
                raise AppError(409, "VERSION_CONFLICT", "商机已变化。")
            session.refresh(entity)
            self.audit_sales(
                session,
                entity,
                actor,
                before,
                request_id,
                "OPPORTUNITY_" + action.upper(),
                body.reason,
            )
            result = self.view_opportunity(repository, entity)
            self.remember(session, actor, scope, key, digest, result)
            return result

    def create_evidence(self, entity_id, body, identity, request_id):
        with self.db.transaction() as session:
            repository = CRMRepository(session)
            actor = self.users(repository, identity)
            _, opportunity = self.locked(repository, entity_id)
            self.authorize(actor, opportunity)
            self.open(opportunity)
            stored = self.required(repository, StoredObject, str(body.stored_object_id), lock=True)
            if stored.opportunity_id != entity_id or stored.uploaded_by != actor.id:
                raise AppError(
                    422, "EVIDENCE_RELATIONSHIP_INVALID", "不能引用其他用户或商机的文件。"
                )
            if stored.status != "AVAILABLE":
                raise AppError(422, "OBJECT_NOT_AVAILABLE", "原件尚未完成存储。")
            if session.scalar(
                select(CloseEvidence.id).where(CloseEvidence.stored_object_id == stored.id)
            ):
                raise AppError(422, "EVIDENCE_RELATIONSHIP_INVALID", "该文件已提交为成交证据。")
            if body.currency != opportunity.currency:
                raise AppError(422, "EVIDENCE_CURRENCY_MISMATCH", "证据与商机币种必须一致。")
            if body.type == "OTHER_APPROVED" and not (body.approval_basis or "").strip():
                raise AppError(422, "APPROVAL_BASIS_REQUIRED", "其他依据必须附明确批准说明。")
            current = now()
            entity = CloseEvidence(
                id=str(uuid4()),
                opportunity_id=entity_id,
                **values(body),
                submitted_by=actor.id,
                status="PENDING",
                version=1,
                created_at=current,
                updated_at=current,
            )
            session.add(entity)
            session.flush()
            self.audit_sales(session, entity, actor, None, request_id, "EVIDENCE_SUBMITTED")
            return snapshot(entity)

    def review(self, entity_id, body, key, identity, request_id):
        with self.db.transaction() as session:
            repository = CRMRepository(session)
            actor = self.users(repository, identity)
            self.manager(actor)
            preview = self.required(repository, CloseEvidence, entity_id)
            _, opportunity = self.locked(repository, preview.opportunity_id)
            self.authorize(actor, opportunity)
            entity = self.required(repository, CloseEvidence, entity_id, lock=True)
            if entity.submitted_by == actor.id:
                raise AppError(
                    403, "EVIDENCE_REVIEWER_CONFLICT", "请更换另一位有权限的经理或管理员核验。"
                )
            scope = f"evidence:{entity_id}:review"
            previous, digest = self.replay(repository, actor, scope, key, body)
            if previous:
                return previous.response
            self.version(entity, body.expected_version)
            if entity.status != "PENDING":
                raise AppError(422, "EVIDENCE_IMMUTABLE", "审核结果不可覆盖，请提交新证据。")
            if entity.currency != opportunity.currency:
                raise AppError(422, "EVIDENCE_CURRENCY_MISMATCH", "证据与商机币种必须一致。")
            if entity.type == "OTHER_APPROVED" and body.decision == "VERIFY":
                raise AppError(
                    409, "OTHER_APPROVAL_POLICY_PENDING", "其他依据审批责任待确认，不能核验通过。"
                )
            stored = self.required(repository, StoredObject, entity.stored_object_id)
            if stored.status != "AVAILABLE":
                raise AppError(422, "EVIDENCE_INVALID", "原件未完成持久化。")
            before = audit_snapshot(entity)
            data = {
                "status": "VERIFIED" if body.decision == "VERIFY" else "REJECTED",
                "reviewed_by": actor.id,
                "reviewed_at": now(),
                "verification_note": body.note,
                "updated_at": now(),
            }
            if body.approval_basis is not None:
                data["approval_basis"] = body.approval_basis
            if not repository.cas(CloseEvidence, entity.id, entity.version, data):
                raise AppError(409, "VERSION_CONFLICT", "证据已变化。")
            session.refresh(entity)
            self.audit_sales(
                session, entity, actor, before, request_id, "EVIDENCE_REVIEWED", body.note
            )
            result = snapshot(entity)
            self.remember(session, actor, scope, key, digest, result)
            return result

    def pipeline(self, query):
        end = query.win_to or datetime.now(UTC)
        start = query.win_from or end - timedelta(days=90)
        start, end = (
            start.astimezone(UTC).replace(tzinfo=None),
            end.astimezone(UTC).replace(tzinfo=None),
        )
        if start > end:
            raise AppError(422, "DATE_RANGE_INVALID", "关闭日期区间无效。")
        in_window = Opportunity.closed_at.between(start, end)
        won = and_(Opportunity.stage == "WON", in_window)
        lost = and_(Opportunity.stage == "LOST", in_window)
        with self.db.transaction() as session:
            # Aggregate bounded currency/stage groups in MySQL instead of materializing every
            # Opportunity/evidence pair. Sum the per-row generated weighted amount (already
            # rounded), and join only the explicitly selected evidence for actual revenue.
            rows = (
                session.execute(
                    select(
                        Opportunity.currency,
                        Opportunity.stage,
                        func.count().label("count"),
                        func.count(Opportunity.amount).label("known"),
                        func.sum(Opportunity.amount).label("amount"),
                        func.sum(Opportunity.weighted_amount).label("weighted"),
                        func.sum(case((won, 1), else_=0)).label("won_count"),
                        func.sum(case((lost, 1), else_=0)).label("lost_count"),
                        func.sum(
                            case(
                                (
                                    and_(won, CloseEvidence.status == "VERIFIED"),
                                    CloseEvidence.amount,
                                ),
                                else_=0,
                            )
                        ).label("actual"),
                    )
                    .outerjoin(
                        CloseEvidence,
                        Opportunity.close_evidence_id == CloseEvidence.id,
                    )
                    .where(*self.filters(query))
                    .group_by(Opportunity.currency, Opportunity.stage)
                )
                .mappings()
                .all()
            )
            groups = {}
            for row in rows:
                groups.setdefault(row["currency"], []).append(row)
            for currency in [query.currency] if query.currency else ["CNY", "USD", "EUR", "HKD"]:
                groups.setdefault(currency, [])
            result = []

            def totals(items):
                known = sum(row["known"] for row in items)
                count = sum(row["count"] for row in items)
                return {
                    "known_amount_count": known,
                    "unknown_amount_count": count - known,
                    "total_amount": format(
                        sum((row["amount"] or Decimal(0) for row in items), Decimal(0)), ".2f"
                    )
                    if known or not count
                    else None,
                    "weighted_amount": format(
                        sum((row["weighted"] or Decimal(0) for row in items), Decimal(0)), ".2f"
                    )
                    if known or not count
                    else None,
                }

            for currency, pairs in sorted(groups.items()):
                opened = [row for row in pairs if row["stage"] in OPEN]
                totals_open = totals(opened)
                won_count = int(sum(row["won_count"] for row in pairs))
                lost_count = int(sum(row["lost_count"] for row in pairs))
                result.append(
                    {
                        "currency": currency,
                        "open_count": sum(row["count"] for row in opened),
                        "known_amount_count": totals_open["known_amount_count"],
                        "unknown_amount_count": totals_open["unknown_amount_count"],
                        "pipeline_value": totals_open["total_amount"],
                        "weighted_forecast": totals_open["weighted_amount"],
                        "closed_won_actual_amount": format(
                            sum(
                                (row["actual"] or Decimal(0) for row in pairs),
                                Decimal(0),
                            ),
                            ".2f",
                        ),
                        "closed_won_count": won_count,
                        "closed_lost_count": lost_count,
                        "win_rate": str(Decimal(won_count) / Decimal(won_count + lost_count))
                        if won_count or lost_count
                        else None,
                        "stages": [
                            {
                                "stage": stage,
                                "count": sum(
                                    row["count"] for row in pairs if row["stage"] == stage
                                ),
                                **totals([row for row in pairs if row["stage"] == stage]),
                            }
                            for stage in PROBABILITY
                        ],
                    }
                )
            return {
                "currency_groups": result,
                "window": encode({"from": start, "to": end}),
                "filters": query.model_dump(mode="json"),
            }

    def activity(self, body, identity, request_id, entity_id=None):
        with self.db.transaction() as session:
            repository = CRMRepository(session)
            actor = self.users(repository, identity, getattr(body, "assignee_id", None))
            entity = self.required(repository, Activity, entity_id) if entity_id else None
            account_id = entity.account_id if entity else str(body.account_id)
            opportunity_id = (
                entity.opportunity_id
                if entity
                else (str(body.opportunity_id) if body.opportunity_id else None)
            )
            account = self.required(repository, Account, account_id, lock=True)
            if opportunity_id:
                opportunity = self.required(repository, Opportunity, opportunity_id, lock=True)
                self.authorize(actor, opportunity)
                if opportunity.account_id != account.id:
                    raise AppError(422, "RELATIONSHIP_MISMATCH", "活动与商机必须属于同一客户。")
            else:
                self.permit(actor, account)
            if entity:
                session.refresh(entity, with_for_update=True)
                self.version(entity, body.expected_version)
                before = audit_snapshot(entity)
                data = values(body, patch=True)
                data.pop("expected_version")
                reason = data.pop("reason")
                if not repository.cas(
                    Activity, entity.id, entity.version, {**data, "updated_at": now()}
                ):
                    raise AppError(409, "VERSION_CONFLICT", "活动已变化。")
                session.refresh(entity)
            else:
                self.contact(
                    repository, account.id, str(body.contact_id) if body.contact_id else None
                )
                if body.assignee_id:
                    self.owner(repository, str(body.assignee_id))
                current = now()
                entity = Activity(
                    id=str(uuid4()),
                    **values(body),
                    created_by=actor.id,
                    status="OPEN" if body.type == "TASK" else "RECORDED",
                    version=1,
                    created_at=current,
                    updated_at=current,
                )
                session.add(entity)
                session.flush()
                before, reason = None, None
            self.audit_sales(
                session,
                entity,
                actor,
                before,
                request_id,
                "ACTIVITY_UPDATED" if before else "ACTIVITY_CREATED",
                reason,
            )
            return snapshot(entity)

    def collection(self, model, page, page_size, **filters):
        with self.db.transaction() as session:
            repository = CRMRepository(session)
            opportunity_id = filters.get("opportunity_id")
            if model is AuditEvent and filters.get("entity_type") == "OPPORTUNITY":
                opportunity_id = filters.get("entity_id")
            if opportunity_id:
                self.required(repository, Opportunity, opportunity_id)
            due_from, due_to = filters.pop("due_from", None), filters.pop("due_to", None)
            conditions = [
                getattr(model, key) == value for key, value in filters.items() if value is not None
            ]
            if due_from:
                conditions.append(Activity.due_at >= due_from.astimezone(UTC).replace(tzinfo=None))
            if due_to:
                conditions.append(Activity.due_at <= due_to.astimezone(UTC).replace(tzinfo=None))
            total = session.scalar(select(func.count()).select_from(model).where(*conditions))
            rows = session.scalars(
                select(model)
                .where(*conditions)
                .order_by(model.created_at.desc(), model.id)
                .offset((page - 1) * page_size)
                .limit(page_size)
            ).all()
            return [snapshot(row) for row in rows], total

    def complete(self, entity_id, body, key, identity, request_id):
        with self.db.transaction() as session:
            repository = CRMRepository(session)
            actor = self.users(repository, identity)
            preview = self.required(repository, Activity, entity_id)
            account = self.required(repository, Account, preview.account_id, lock=True)
            if preview.opportunity_id:
                opportunity = self.required(
                    repository, Opportunity, preview.opportunity_id, lock=True
                )
                self.authorize(actor, opportunity)
            else:
                self.permit(actor, account)
            entity = self.required(repository, Activity, entity_id, lock=True)
            scope = f"activity:{entity_id}:complete"
            previous, digest = self.replay(repository, actor, scope, key, body)
            if previous:
                return previous.response
            self.version(entity, body.expected_version)
            if entity.type != "TASK":
                raise AppError(422, "NOT_A_TASK", "只有任务可以完成。")
            if entity.status != "OPEN":
                raise AppError(409, "ACTIVITY_ALREADY_COMPLETED", "任务已完成或取消。")
            before = audit_snapshot(entity)
            if not repository.cas(
                Activity,
                entity.id,
                entity.version,
                {
                    "status": "DONE",
                    "completed_at": now(),
                    "updated_at": now(),
                },
            ):
                raise AppError(409, "VERSION_CONFLICT", "任务已变化。")
            session.refresh(entity)
            self.audit_sales(
                session, entity, actor, before, request_id, "ACTIVITY_COMPLETED", body.reason
            )
            result = snapshot(entity)
            self.remember(session, actor, scope, key, digest, result)
            return result

    def audits(
        self,
        identity,
        page,
        page_size,
        entity_id=None,
        actor_id=None,
        entity_type=None,
        action=None,
        from_time=None,
        to_time=None,
        event_id=None,
    ):
        with self.db.transaction() as session:
            actor = session.get(User, identity.user.id)
            if not actor or not actor.is_active:
                raise AppError(401, "SESSION_EXPIRED", "会话已失效。")
            if actor.role not in MANAGERS:
                raise AppError(403, "FORBIDDEN", "全局业务审计仅向经理或管理员开放。")
            conditions = [
                AuditEvent.entity_type.in_(
                    ["ACCOUNT", "CONTACT", "OPPORTUNITY", "ACTIVITY", "CLOSEEVIDENCE"]
                )
            ]
            if entity_id:
                conditions.append(AuditEvent.entity_id == entity_id)
            if actor_id:
                conditions.append(AuditEvent.actor_id == actor_id)
            if event_id:
                conditions.append(AuditEvent.id == event_id)
            if entity_type:
                conditions.append(AuditEvent.entity_type == entity_type)
            if action:
                conditions.append(AuditEvent.action == action)
            if from_time:
                conditions.append(
                    AuditEvent.created_at >= from_time.astimezone(UTC).replace(tzinfo=None)
                )
            if to_time:
                conditions.append(
                    AuditEvent.created_at <= to_time.astimezone(UTC).replace(tzinfo=None)
                )
            total = session.scalar(select(func.count()).select_from(AuditEvent).where(*conditions))
            events = session.scalars(
                select(AuditEvent)
                .where(*conditions)
                .order_by(
                    AuditEvent.created_at.desc(),
                    AuditEvent.id,
                )
                .offset((page - 1) * page_size)
                .limit(page_size)
            ).all()
            return [snapshot(event) for event in events], total
