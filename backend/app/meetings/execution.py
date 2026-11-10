import hashlib
import json
from datetime import UTC
from uuid import UUID, uuid4

from pydantic import Field, field_validator
from sqlalchemy import select

from app.auth.service import now
from app.core.errors import AppError
from app.crm.models import Contact
from app.crm.repository import CRMRepository
from app.meetings.context import context_digest
from app.meetings.models import MeetingAnalysis, Suggestion, SuggestionExecution
from app.meetings.proposals import FrozenChange, propose
from app.meetings.schemas import Input
from app.meetings.service import MeetingService, audit
from app.sales.models import Activity, IdempotencyRecord, Opportunity
from app.sales.schemas import ActivityCreate, OpportunityPatch
from app.sales.service import SalesService, audit_snapshot, values
from app.users.service import UserService


class Apply(Input):
    expected_version: int = Field(ge=1, strict=True)
    expected_opportunity_version: int = Field(ge=1, strict=True)
    selected_change_ids: list[UUID] = Field(min_length=1, max_length=20)
    confirmed: bool = Field(strict=True)

    @field_validator("confirmed")
    @classmethod
    def explicit_confirmation(cls, value):
        if value is not True:
            raise ValueError("explicit confirmation required")
        return value

    @field_validator("selected_change_ids")
    @classmethod
    def unique(cls, selected):
        if len(set(selected)) != len(selected):
            raise ValueError("duplicate selection")
        return selected


class ExecutionService:
    def __init__(self, db, settings):
        self.db, self.settings = db, settings

    def result(self, identity, suggestion_id):
        with self.db.transaction() as session:
            meetings = MeetingService(self.db, self.settings)
            row = meetings.required(session, Suggestion, suggestion_id)
            meetings.access(session, identity.user.id, row.opportunity_id)
            execution = session.scalar(
                select(SuggestionExecution).where(SuggestionExecution.suggestion_id == row.id)
            )
            if not execution:
                raise AppError(409, "SUGGESTION_NOT_EXECUTED", "该草稿尚未执行。")
            return execution.result

    def apply(self, identity, suggestion_id, body, key, request_id):
        chosen = sorted(str(item) for item in body.selected_change_ids)
        request_hash = hashlib.sha256(
            json.dumps(body.model_dump(mode="json"), sort_keys=True).encode()
        ).hexdigest()
        with self.db.transaction() as session:
            meetings = MeetingService(self.db, self.settings)
            preview = meetings.required(session, Suggestion, suggestion_id)
            meetings.access(session, identity.user.id, preview.opportunity_id)
            all_changes = [
                FrozenChange.model_validate(change) for change in (preview.proposed_changes or [])
            ]
            assignees = [
                change.values["assignee_id"]
                for change in all_changes
                if change.kind == "TASK" and str(change.id) in chosen
            ]
            repo = CRMRepository(session)
            sales = SalesService(self.db)
            actor = sales.users(repo, identity, *assignees)
            UserService(self.db, self.settings).active(actor)
            account, opportunity = sales.locked(repo, preview.opportunity_id)
            sales.authorize(actor, opportunity)
            UserService(self.db, self.settings).session_live(session, identity)
            row = meetings.required(session, Suggestion, suggestion_id, lock=True)
            scope = f"suggestion:{row.id}:apply"
            prior = session.scalar(
                select(IdempotencyRecord).where(
                    IdempotencyRecord.actor_id == actor.id,
                    IdempotencyRecord.scope == scope,
                    IdempotencyRecord.request_key == key,
                )
            )
            if prior:
                if prior.request_hash != request_hash:
                    raise AppError(409, "IDEMPOTENCY_KEY_REUSED", "幂等键已用于不同请求。")
                return prior.response
            existing = session.scalar(
                select(SuggestionExecution).where(SuggestionExecution.suggestion_id == row.id)
            )
            if existing:
                if sorted(existing.selected_change_ids) != chosen:
                    raise AppError(
                        409, "SUGGESTION_ALREADY_EXECUTED", "该草稿已执行，不能改变选择或补执行。"
                    )
                return existing.result
            if row.status != "DRAFT":
                raise AppError(409, "INVALID_SUGGESTION_STATUS", "只有未审核草稿可执行。")
            if row.version != body.expected_version:
                raise AppError(409, "VERSION_CONFLICT", "草稿已变化，请重新读取。")
            if not row.base_snapshot or not row.context_digest:
                raise AppError(
                    409, "SUGGESTION_REGENERATE_REQUIRED", "旧草稿缺少冻结上下文，请生成新草稿。"
                )
            if not all_changes:
                raise AppError(422, "NO_EXECUTABLE_CHANGES", "该草稿没有可执行变更。")
            lookup = {str(change.id): change for change in all_changes}
            if not set(chosen) <= lookup.keys():
                raise AppError(422, "INVALID_CHANGE_SELECTION", "只能执行本草稿已冻结的变更 ID。")
            if (
                opportunity.version != row.base_opportunity_version
                or opportunity.version != body.expected_opportunity_version
                or context_digest(session, opportunity) != row.context_digest
            ):
                raise AppError(409, "SUGGESTION_STALE", "商机或活动上下文已变化，请生成新草稿。")
            sales.open(opportunity)
            if not account.is_active:
                raise AppError(422, "ACCOUNT_INACTIVE", "客户已停用，不能应用草稿。")
            analysis = meetings.required(session, MeetingAnalysis, row.analysis_id)
            selected = [lookup[item].verify_source(analysis.input_text) for item in chosen]
            # Previously published drafts are never rewritten. Revalidate their selected
            # semantics against the current deterministic policy before any business write.
            current_changes, _ = propose(
                analysis.input_text, row.base_snapshot, analysis.meeting_date, analysis.timezone
            )
            permitted = [
                {key: value for key, value in change.items() if key != "id"}
                for change in current_changes
            ]
            if any(
                change.model_dump(mode="json", exclude={"id"}) not in permitted
                for change in selected
            ):
                raise AppError(
                    409,
                    "SUGGESTION_REGENERATE_REQUIRED",
                    "所选冻结提议不再符合当前解析规则，请生成新草稿；历史资料保持不变。",
                )
            patch = {}
            activities = []
            current = now()
            execution_id = str(uuid4())
            for change in selected:
                if change.kind == "FIELD":
                    for field, value in change.before.items():
                        if row.base_snapshot.get(field) != value:
                            raise AppError(409, "SUGGESTION_STALE", "冻结前值不一致。")
                    if set(patch) & set(change.values):
                        raise AppError(422, "CHANGE_DEPENDENCY_INVALID", "变更字段不能重复。")
                    patch.update(change.values)
                else:
                    payload = {
                        **change.values,
                        "account_id": account.id,
                        "opportunity_id": opportunity.id,
                        "type": change.kind,
                    }
                    if change.kind == "NOTE":
                        payload["occurred_at"] = current.replace(tzinfo=UTC)
                    activity = ActivityCreate.model_validate(payload)
                    if activity.assignee_id:
                        sales.owner(repo, str(activity.assignee_id))
                    activities.append((change, activity))
            if patch:
                patch = values(
                    OpportunityPatch(expected_version=opportunity.version, **patch), patch=True
                )
                patch.pop("expected_version")
                if patch.get("primary_contact_id"):
                    contact = repo.get(Contact, patch["primary_contact_id"], lock=True)
                    if not contact or not contact.is_active or contact.account_id != account.id:
                        raise AppError(
                            422, "RELATIONSHIP_MISMATCH", "主要联系人须属于同一客户且有效。"
                        )
            before = audit_snapshot(opportunity)
            if not repo.cas(
                Opportunity, opportunity.id, opportunity.version, {**patch, "updated_at": current}
            ):
                raise AppError(409, "SUGGESTION_STALE", "商机版本冲突，操作已回滚。")
            session.refresh(opportunity)
            sales.audit_sales(
                session, opportunity, actor, before, request_id, "AI_SUGGESTION_APPLIED"
            )
            activity_ids = []
            for change, body_activity in activities:
                activity = Activity(
                    id=str(uuid4()),
                    **values(body_activity),
                    created_by=actor.id,
                    status="OPEN" if change.kind == "TASK" else "RECORDED",
                    version=1,
                    created_at=current,
                    updated_at=current,
                    ai_execution_key=f"{execution_id}:{change.id}",
                )
                session.add(activity)
                session.flush()
                activity_ids.append(activity.id)
                sales.audit_sales(session, activity, actor, None, request_id, "AI_ACTIVITY_CREATED")
            before_draft = {"status": row.status, "version": row.version}
            row.status = "EXECUTED"
            row.version += 1
            row.reviewed_by = actor.id
            row.reviewed_at = row.executed_at = row.updated_at = current
            row.execution_id = execution_id
            row.result_version = opportunity.version
            row.selected_change_ids = chosen
            audit(session, row, actor.id, "SUGGESTION_EXECUTED", request_id, before_draft)
            result = {
                "execution_id": execution_id,
                "suggestion_id": row.id,
                "opportunity_id": opportunity.id,
                "selected_change_ids": chosen,
                "activity_ids": activity_ids,
                "result_version": opportunity.version,
                "executed_by": actor.id,
                "executed_at": current.replace(tzinfo=UTC).isoformat().replace("+00:00", "Z"),
            }
            session.add(
                SuggestionExecution(
                    id=execution_id,
                    suggestion_id=row.id,
                    opportunity_id=opportunity.id,
                    actor_id=actor.id,
                    selected_change_ids=chosen,
                    result_version=opportunity.version,
                    result=result,
                    created_at=current,
                )
            )
            session.add(
                IdempotencyRecord(
                    id=str(uuid4()),
                    actor_id=actor.id,
                    scope=scope,
                    request_key=key,
                    request_hash=request_hash,
                    response=result,
                    created_at=current,
                )
            )
            session.flush()
            return result
