"""Q10 policy preview only. No update/delete/export or filesystem cleanup operations."""

from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import case, func, null, select

from app.auth.dependencies import current_identity
from app.auth.models import Role, User
from app.auth.service import now
from app.core.errors import AppError
from app.crm.models import AuditEvent
from app.crm.router import result
from app.meetings.models import AIRun, Job, MeetingAnalysis, Suggestion, SuggestionExecution
from app.sales.models import CloseEvidence, IdempotencyRecord
from app.users.service import UserService

router = APIRouter(tags=["Q10 retention preview only"])


class RetentionService:
    def __init__(self, db, settings):
        self.db, self.settings = db, settings

    def preview(self, identity, as_of=None):
        if as_of is not None and as_of.tzinfo is None:
            raise AppError(422, "TIMEZONE_REQUIRED", "预览时间必须包含时区。")
        current = as_of.astimezone(UTC).replace(tzinfo=None) if as_of else now()
        with self.db.transaction() as session:
            actor = session.get(User, identity.user.id)
            UserService(self.db, self.settings).active(actor)
            if actor.role != Role.ADMIN:
                raise AppError(403, "FORBIDDEN", "仅管理员可查看保留策略预览。")

            def counts(query):
                sub = query.subquery()
                total = session.scalar(select(func.count()).select_from(sub))
                blocked = dict(
                    session.execute(
                        select(sub.c.reason, func.count())
                        .where(sub.c.reason.is_not(None))
                        .group_by(sub.c.reason)
                    ).all()
                )
                ids = list(
                    session.scalars(
                        select(sub.c.id).where(sub.c.reason.is_(None)).order_by(sub.c.id).limit(20)
                    )
                )
                return {
                    "due_count": total,
                    "candidate_count": total - sum(blocked.values()),
                    "blocked_by_reason": blocked,
                    "sample_ids": ids,
                    "sample_limit": 20,
                }

            reason = case(
                (Job.status.in_(["QUEUED", "RUNNING"]), "ACTIVE_JOB"),
                (Suggestion.status.in_(["GENERATING", "DRAFT"]), "PENDING_REVIEW"),
                (SuggestionExecution.id.is_not(None), "EXECUTION_REFERENCE"),
                (Suggestion.id.is_(None), "REFERENCE_INCOMPLETE"),
                else_=None,
            )
            analyses = (
                select(MeetingAnalysis.id, reason.label("reason"))
                .join(Job, Job.id == MeetingAnalysis.source_job_id)
                .outerjoin(Suggestion, Suggestion.analysis_id == MeetingAnalysis.id)
                .outerjoin(SuggestionExecution, SuggestionExecution.suggestion_id == Suggestion.id)
                .where(MeetingAnalysis.created_at <= current - timedelta(days=90))
            )
            jobs = (
                select(Job.id, reason.label("reason"))
                .outerjoin(Suggestion, Suggestion.source_job_id == Job.id)
                .outerjoin(SuggestionExecution, SuggestionExecution.suggestion_id == Suggestion.id)
                .where(Job.updated_at <= current - timedelta(days=30))
            )
            run_reason = case(
                (AIRun.status == "RUNNING", "ACTIVE_RUN"),
                (Job.status.in_(["QUEUED", "RUNNING"]), "ACTIVE_JOB"),
                (Suggestion.status.in_(["GENERATING", "DRAFT"]), "PENDING_REVIEW"),
                (SuggestionExecution.id.is_not(None), "EXECUTION_REFERENCE"),
                (Suggestion.id.is_(None), "REFERENCE_INCOMPLETE"),
                else_=None,
            )
            runs = (
                select(AIRun.id, run_reason.label("reason"))
                .join(Job, Job.id == AIRun.job_id)
                .outerjoin(Suggestion, Suggestion.source_job_id == Job.id)
                .outerjoin(SuggestionExecution, SuggestionExecution.suggestion_id == Suggestion.id)
                .where(
                    func.coalesce(AIRun.ended_at, AIRun.started_at) <= current - timedelta(days=30)
                )
            )
            cache = select(
                IdempotencyRecord.id,
                null().label("reason"),
            ).where(IdempotencyRecord.created_at <= current - timedelta(days=7))
            groups = [
                {
                    "scope": "meeting_source_and_quotes",
                    "days": 90,
                    "target": "source_and_derived_copies_only",
                    "keep_identity": True,
                    **counts(analyses),
                },
                {
                    "scope": "job_details",
                    "days": 30,
                    "target": "details_only_keep_status_and_references",
                    "keep_identity": True,
                    **counts(jobs),
                },
                {
                    "scope": "ai_run_details",
                    "days": 30,
                    "target": "details_only_keep_minimal_run_metadata",
                    "keep_identity": True,
                    **counts(runs),
                },
                {
                    "scope": "idempotency_response_cache",
                    "days": 7,
                    "target": "response_only_keep_permanent_dedupe",
                    "keep_identity": True,
                    **counts(cache),
                },
            ]
            return {
                "mode": "DRY_RUN",
                "writes_enabled": False,
                "as_of": current.replace(tzinfo=UTC).isoformat().replace("+00:00", "Z"),
                "groups": groups,
                "protected": {
                    "audit_events": session.scalar(select(func.count()).select_from(AuditEvent)),
                    "close_evidence": session.scalar(
                        select(func.count()).select_from(CloseEvidence)
                    ),
                    "suggestion_executions": session.scalar(
                        select(func.count()).select_from(SuggestionExecution)
                    ),
                },
                "limitations": [
                    "仅预览，不可按候选 ID 删除整行。",
                    "待审核/运行中/执行引用阻断清理；Q11 草稿有效期仍待确认。",
                    "不扫描本地文件、报告、备份或对象存储。",
                ],
            }


@router.get("/admin/retention/preview")
def preview(
    request: Request,
    as_of: datetime | None = Query(default=None),
    identity=Depends(current_identity),
):
    return result(
        request,
        RetentionService(request.app.state.db, request.app.state.settings).preview(identity, as_of),
    )
