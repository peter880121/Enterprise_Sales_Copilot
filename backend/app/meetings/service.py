import hashlib
import json
from uuid import uuid4

from sqlalchemy import func, select

from app.auth.models import Role, User
from app.auth.service import now
from app.core.errors import AppError
from app.crm.models import AuditEvent
from app.crm.service import can_write
from app.meetings.context import context_digest
from app.meetings.context import snapshot as context_snapshot
from app.meetings.models import Job, MeetingAnalysis, Suggestion
from app.meetings.schemas import MeetingCreate
from app.sales.models import IdempotencyRecord, Opportunity
from app.sales.service import encode
from app.users.service import UserService


def audit(
    session,
    entity,
    actor_id,
    action,
    request_id,
    before=None,
    *,
    related_suggestion_id=None,
    replacement_analysis_id=None,
):
    # Never include the original note, extraction, quote, or rejection reason in audit.
    after = {
        "id": entity.id,
        "status": entity.status,
        "mode": "MOCK",
        "base_opportunity_version": entity.base_opportunity_version,
    }
    if related_suggestion_id is not None:
        after["related_suggestion_id"] = related_suggestion_id
    if replacement_analysis_id is not None:
        after["replacement_analysis_id"] = replacement_analysis_id
    if isinstance(entity, MeetingAnalysis):
        after.update(input_sha256=entity.input_sha256.hex(), input_length=len(entity.input_text))
    else:
        after.update(version=entity.version)
        if entity.status == "EXECUTED":
            after.update(
                execution_id=entity.execution_id, selected_change_ids=entity.selected_change_ids
            )
    session.add(
        AuditEvent(
            id=str(uuid4()),
            entity_type="MEETINGANALYSIS"
            if isinstance(entity, MeetingAnalysis)
            else "AISUGGESTION",
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
            mutation_event_key=f"meeting:{entity.id}:{action}:{getattr(entity, 'version', 1)}",
            created_at=now(),
        )
    )
    session.flush()


class MeetingService:
    def __init__(self, db, settings):
        self.db, self.settings = db, settings

    def access(self, session, user_id, opportunity_id, *, write=False, identity=None):
        user = session.get(User, user_id, with_for_update=write)
        UserService(self.db, self.settings).active(user)
        opportunity = session.get(Opportunity, opportunity_id, with_for_update=write)
        if opportunity is None:
            raise AppError(404, "NOT_FOUND", "商机不存在。")
        if not can_write(user.role, user.id, opportunity.owner_id):
            raise AppError(403, "FORBIDDEN", "纪要与草稿仅对有该商机 AI 权限的用户开放。")
        if write and identity:
            UserService(self.db, self.settings).session_live(session, identity)
        return user, opportunity

    def required(self, session, model, entity_id, lock=False):
        obj = session.get(model, entity_id, with_for_update=lock, populate_existing=lock)
        if obj is None:
            raise AppError(404, "NOT_FOUND", "对象不存在。")
        return obj

    def submit(self, identity, opportunity_id, body, request_id):
        if self.settings.ai_mode != "mock":
            raise AppError(
                503, "AI_PROVIDER_UNAVAILABLE", "本轮未启用真实 Provider，不会自动回退 Mock。"
            )
        digest = hashlib.sha256(
            json.dumps(body.model_dump(mode="json"), sort_keys=True).encode()
        ).digest()
        key = f"meeting:{identity.user.id}:{opportunity_id}:{body.request_token}"
        with self.db.transaction() as session:
            actor, opportunity = self.access(
                session, identity.user.id, opportunity_id, write=True, identity=identity
            )
            job = session.scalar(select(Job).where(Job.dedupe_key == key))
            if job:
                if job.request_hash != digest:
                    raise AppError(409, "IDEMPOTENCY_KEY_REUSED", "请求标识已用于其他内容。")
                return self.accepted(session, job)
            if opportunity.version != body.expected_opportunity_version:
                raise AppError(409, "VERSION_CONFLICT", "商机已变化，请重新读取后确认。")
            if opportunity.stage in {"WON", "LOST"}:
                raise AppError(422, "TERMINAL_OPPORTUNITY", "本轮只接受开放商机的会议解析。")
            return self.queue(session, actor, opportunity, body, request_id, key, digest)

    def regenerate(self, identity, suggestion_id, body, request_id):
        if self.settings.ai_mode != "mock":
            raise AppError(503, "AI_PROVIDER_UNAVAILABLE", "本轮未启用真实 Provider。")
        digest = hashlib.sha256(
            json.dumps(body.model_dump(mode="json"), sort_keys=True).encode()
        ).digest()
        with self.db.transaction() as session:
            preview = self.required(session, Suggestion, suggestion_id)
            actor, opportunity = self.access(
                session, identity.user.id, preview.opportunity_id, write=True, identity=identity
            )
            source = self.required(session, Suggestion, suggestion_id, lock=True)
            key = f"regenerate:{actor.id}:{source.id}:{body.request_token}"
            prior = session.scalar(select(Job).where(Job.dedupe_key == key))
            if prior:
                if prior.request_hash != digest:
                    raise AppError(409, "IDEMPOTENCY_KEY_REUSED", "请求标识已用于其他内容。")
                return self.accepted(session, prior)
            if source.version != body.expected_version:
                raise AppError(409, "VERSION_CONFLICT", "草稿已变化，请重新读取后确认。")
            if source.status != "DRAFT":
                raise AppError(409, "INVALID_SUGGESTION_STATUS", "只有未审核草稿可以重新生成。")
            if opportunity.version != body.expected_opportunity_version:
                raise AppError(409, "VERSION_CONFLICT", "商机已变化，请重新读取后确认。")
            if opportunity.stage in {"WON", "LOST"}:
                raise AppError(422, "TERMINAL_OPPORTUNITY", "关闭商机不能重新生成草稿。")
            original = self.required(session, MeetingAnalysis, source.analysis_id)
            copied = MeetingCreate(
                expected_opportunity_version=body.expected_opportunity_version,
                meeting_text=original.input_text,
                meeting_date=original.meeting_date,
                timezone=original.timezone,
                request_token=body.request_token,
            )
            accepted = self.queue(
                session,
                actor,
                opportunity,
                copied,
                request_id,
                key,
                digest,
                source_suggestion_id=source.id,
            )
            before = {"status": source.status, "version": source.version}
            source.status = "SUPERSEDED"
            source.version += 1
            source.reviewed_by = actor.id
            source.reviewed_at = source.updated_at = now()
            audit(
                session,
                source,
                actor.id,
                "SUGGESTION_SUPERSEDED",
                request_id,
                before,
                replacement_analysis_id=accepted["resource_id"],
            )
            return accepted

    def queue(
        self,
        session,
        actor,
        opportunity,
        body,
        request_id,
        key,
        digest,
        *,
        source_suggestion_id=None,
    ):
        current = now()
        job = Job(
            id=str(uuid4()),
            created_by=actor.id,
            opportunity_id=opportunity.id,
            dedupe_key=key,
            request_hash=digest,
            status="QUEUED",
            attempts=0,
            available_at=current,
            created_at=current,
            updated_at=current,
        )
        session.add(job)
        session.flush()
        analysis = MeetingAnalysis(
            id=str(uuid4()),
            opportunity_id=opportunity.id,
            submitted_by=actor.id,
            source_job_id=job.id,
            meeting_date=body.meeting_date,
            timezone=body.timezone,
            input_text=body.meeting_text,
            input_sha256=hashlib.sha256(body.meeting_text.encode()).digest(),
            base_opportunity_version=opportunity.version,
            status="QUEUED",
            mode="MOCK",
            schema_version="meeting-v1",
            prompt_version="labelled-synthetic-v2-q07",
            created_at=current,
            updated_at=current,
        )
        session.add(analysis)
        session.flush()
        suggestion = Suggestion(
            id=str(uuid4()),
            opportunity_id=opportunity.id,
            analysis_id=analysis.id,
            source_job_id=job.id,
            created_by=actor.id,
            base_opportunity_version=opportunity.version,
            status="GENERATING",
            base_snapshot=context_snapshot(opportunity),
            context_digest=context_digest(session, opportunity),
            version=1,
            created_at=current,
            updated_at=current,
        )
        session.add(suggestion)
        session.flush()
        audit(
            session,
            analysis,
            actor.id,
            "MEETING_QUEUED",
            request_id,
            related_suggestion_id=source_suggestion_id,
        )
        return self.accepted(session, job)

    def accepted(self, session, job):
        analysis = session.scalar(
            select(MeetingAnalysis).where(MeetingAnalysis.source_job_id == job.id)
        )
        return {
            "job_id": job.id,
            "status": job.status,
            "resource_id": analysis.id,
            "poll_url": f"/api/v1/jobs/{job.id}",
            "mode": "MOCK",
        }

    def analysis(self, identity, analysis_id):
        with self.db.transaction() as session:
            row = self.required(session, MeetingAnalysis, analysis_id)
            _, opportunity = self.access(session, identity.user.id, row.opportunity_id)
            suggestion = session.scalar(select(Suggestion).where(Suggestion.analysis_id == row.id))
            return self.analysis_view(row, suggestion, opportunity, session)

    def analysis_view(self, row, suggestion, opportunity, session=None):
        suggestion_data = self.suggestion_view(suggestion, opportunity, session)
        return encode(
            {
                key: getattr(row, key)
                for key in (
                    "id",
                    "opportunity_id",
                    "submitted_by",
                    "source_job_id",
                    "meeting_date",
                    "timezone",
                    "input_text",
                    "base_opportunity_version",
                    "status",
                    "result",
                    "mode",
                    "schema_version",
                    "prompt_version",
                    "created_at",
                    "updated_at",
                )
            }
            | {
                "suggestion": suggestion_data,
                "execution_enabled": suggestion_data["execution_enabled"],
            }
        )

    def suggestion_view(self, row, opportunity, session=None):
        replacement_analysis_id = None
        if row.status == "SUPERSEDED" and session is not None:
            event = session.scalar(
                select(AuditEvent.after_state).where(
                    AuditEvent.entity_id == row.id,
                    AuditEvent.entity_type == "AISUGGESTION",
                    AuditEvent.action == "SUGGESTION_SUPERSEDED",
                )
            )
            if event:
                replacement_analysis_id = event.get("replacement_analysis_id")
        stale = row.base_opportunity_version != opportunity.version
        if row.status == "DRAFT" and not stale and session is not None and row.context_digest:
            stale = context_digest(session, opportunity) != row.context_digest
        return encode(
            {
                key: getattr(row, key)
                for key in (
                    "id",
                    "opportunity_id",
                    "analysis_id",
                    "source_job_id",
                    "created_by",
                    "reviewed_by",
                    "reviewed_at",
                    "expires_at",
                    "status",
                    "reason",
                    "base_opportunity_version",
                    "version",
                    "created_at",
                    "updated_at",
                )
            }
            | {
                "mode": "MOCK",
                "proposed_changes": row.proposed_changes or [],
                "execution_enabled": bool(row.proposed_changes)
                and row.status == "DRAFT"
                and row.context_digest is not None
                and not stale,
                "execution_id": row.execution_id,
                "result_version": row.result_version,
                "selected_change_ids": row.selected_change_ids or [],
                "replacement_analysis_id": replacement_analysis_id,
                "effective_status": "STALE" if row.status == "DRAFT" and stale else row.status,
            }
        )

    def suggestion(self, identity, suggestion_id):
        with self.db.transaction() as session:
            row = self.required(session, Suggestion, suggestion_id)
            _, opportunity = self.access(session, identity.user.id, row.opportunity_id)
            return self.suggestion_view(row, opportunity, session)

    def listing(self, identity, opportunity_id, page, size):
        with self.db.transaction() as session:
            _, opportunity = self.access(session, identity.user.id, opportunity_id)
            query = select(MeetingAnalysis).where(MeetingAnalysis.opportunity_id == opportunity_id)
            count = session.scalar(select(func.count()).select_from(query.subquery()))
            rows = session.scalars(
                query.order_by(MeetingAnalysis.created_at.desc(), MeetingAnalysis.id)
                .offset((page - 1) * size)
                .limit(size)
            )
            return [
                {
                    "id": row.id,
                    "status": row.status,
                    "mode": row.mode,
                    "created_at": encode(row.created_at),
                    "base_opportunity_version": row.base_opportunity_version,
                    "current_opportunity_version": opportunity.version,
                }
                for row in rows
            ], count

    def job(self, identity, job_id):
        with self.db.transaction() as session:
            job = self.required(session, Job, job_id)
            actor, _ = self.access(session, identity.user.id, job.opportunity_id)
            if actor.role == Role.SALES_REP and job.created_by != actor.id:
                raise AppError(403, "FORBIDDEN", "不能读取其他用户任务。")
            return self.accepted(session, job) | {
                "attempts": job.attempts,
                "error_code": job.error_code,
                "progress": 100
                if job.status == "SUCCEEDED"
                else 20
                if job.status == "RUNNING"
                else 0,
            }

    def review(self, identity, suggestion_id, action, body, key, request_id):
        with self.db.transaction() as session:
            preview = self.required(session, Suggestion, suggestion_id)
            actor, opportunity = self.access(
                session, identity.user.id, preview.opportunity_id, write=True, identity=identity
            )
            row = self.required(session, Suggestion, suggestion_id, lock=True)
            digest = hashlib.sha256(
                json.dumps(body.model_dump(mode="json"), sort_keys=True).encode()
            ).hexdigest()
            scope = f"suggestion:{row.id}:{action}"
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
            if row.version != body.expected_version:
                raise AppError(409, "VERSION_CONFLICT", "草稿已变化，请重新读取。")
            if row.status != "DRAFT":
                raise AppError(409, "INVALID_SUGGESTION_STATUS", "只有已生成草稿可审核。")
            before = {"status": row.status, "version": row.version}
            row.status = "REJECTED" if action == "reject" else "ABANDONED"
            row.version += 1
            row.reason = body.reason
            row.reviewed_by = actor.id
            row.reviewed_at = row.updated_at = now()
            audit(session, row, actor.id, "SUGGESTION_" + row.status, request_id, before)
            result = self.suggestion_view(row, opportunity, session)
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
