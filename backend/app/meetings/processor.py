import time
from datetime import timedelta
from uuid import uuid4

from sqlalchemy import and_, or_, select

from app.ai import MockProvider
from app.auth.service import now
from app.core.errors import AppError
from app.meetings.models import AIRun, Job, MeetingAnalysis, Suggestion
from app.meetings.proposals import propose
from app.meetings.schemas import Extraction
from app.meetings.service import MeetingService, audit


class MeetingProcessor:
    def __init__(self, db, settings, provider=None):
        self.db, self.settings = db, settings
        self.provider = provider or MockProvider()

    def claim(self):
        with self.db.transaction() as session:
            current = now()
            row = session.scalar(
                select(Job)
                .where(
                    or_(
                        and_(Job.status == "QUEUED", Job.available_at <= current),
                        and_(Job.status == "RUNNING", Job.lease_until <= current),
                    )
                )
                .order_by(Job.available_at, Job.id)
                .with_for_update(skip_locked=True)
                .limit(1)
            )
            if row is None:
                return None
            # Recovered attempts must not remain RUNNING after their worker disappeared.
            # Preserve every terminal run, including earlier failed retries.
            for abandoned in session.scalars(
                select(AIRun)
                .where(AIRun.job_id == row.id, AIRun.status == "RUNNING")
                .with_for_update()
            ):
                abandoned.status = "DISCARDED"
                abandoned.error_code = "LEASE_EXPIRED"
                abandoned.ended_at = current
            analysis = session.scalar(
                select(MeetingAnalysis)
                .where(MeetingAnalysis.source_job_id == row.id)
                .with_for_update()
            )
            suggestion = session.scalar(
                select(Suggestion).where(Suggestion.source_job_id == row.id).with_for_update()
            )
            if row.attempts >= 3:
                row.status = analysis.status = "FAILED"
                row.error_code = "AI_RETRY_EXHAUSTED"
                row.lease_token = None
                row.lease_until = None
                suggestion.status = "FAILED"
                suggestion.version += 1
                suggestion.updated_at = analysis.updated_at = row.updated_at = current
                audit(session, analysis, None, "MEETING_FAILED", row.id)
                return None
            row.attempts += 1
            row.status = analysis.status = "RUNNING"
            row.lease_token = str(uuid4())
            row.lease_until = current + timedelta(seconds=60)
            row.updated_at = analysis.updated_at = current
            run = AIRun(
                id=str(uuid4()),
                job_id=row.id,
                attempt=row.attempts,
                mode="MOCK",
                provider="deterministic-labelled-synthetic",
                schema_version=analysis.schema_version,
                prompt_version=analysis.prompt_version,
                input_hash=analysis.input_sha256,
                status="RUNNING",
                started_at=current,
            )
            session.add(run)
            return {
                "job_id": row.id,
                "token": row.lease_token,
                "analysis_id": analysis.id,
                "opportunity_id": row.opportunity_id,
                "actor_id": row.created_by,
                "run_id": run.id,
            }

    def process_one(self):
        claim = self.claim()
        if claim is None:
            return False
        start = time.monotonic()
        error, result, retry = None, None, False
        with self.db.transaction() as session:
            text = session.get(MeetingAnalysis, claim["analysis_id"]).input_text
        try:
            if self.settings.ai_mode != "mock" or self.provider.mode != "MOCK":
                raise AppError(503, "AI_PROVIDER_UNAVAILABLE", "Real provider is not authorized")
            raw = self.provider.structured_generate(text)
            extraction = (
                Extraction.model_validate_json(raw)
                if isinstance(raw, str)
                else Extraction.model_validate(raw)
            )
            result = extraction.verify_source(text).model_dump(mode="json")
        except (TimeoutError, ConnectionError):
            error, retry = "AI_TIMEOUT", True
        except AppError as exc:
            error = exc.code
        except (ValueError, TypeError):
            error = "AI_OUTPUT_INVALID"
        except Exception:
            # No provider error text or original input in logs/database error payloads.
            error = "AI_PROVIDER_ERROR"
        self.publish(claim, result, error, retry, round((time.monotonic() - start) * 1000))
        return True

    def publish(self, claim, result, error, retry, latency):
        with self.db.transaction() as session:
            service = MeetingService(self.db, self.settings)
            try:
                service.access(session, claim["actor_id"], claim["opportunity_id"], write=True)
            except AppError:
                error, retry, result = "AI_PERMISSION_CHANGED", False, None
            job = session.get(Job, claim["job_id"], with_for_update=True)
            run = session.get(AIRun, claim["run_id"], with_for_update=True)
            if run.status != "RUNNING":
                # A duplicate or late callback cannot rewrite a recorded terminal outcome.
                return False
            current = now()
            run.ended_at, run.latency_ms = current, latency
            if (
                job.status != "RUNNING"
                or job.lease_token != claim["token"]
                or job.lease_until <= current
            ):
                run.status, run.error_code = "DISCARDED", "LEASE_LOST"
                return False
            run.status, run.error_code = ("FAILED" if error else "SUCCEEDED"), error
            analysis = session.get(MeetingAnalysis, claim["analysis_id"], with_for_update=True)
            suggestion = session.scalar(
                select(Suggestion).where(Suggestion.analysis_id == analysis.id).with_for_update()
            )
            job.error_code = error
            job.lease_token = None
            job.lease_until = None
            job.updated_at = analysis.updated_at = suggestion.updated_at = current
            if error and retry and job.attempts < 3:
                job.status = analysis.status = "QUEUED"
                job.available_at = current + timedelta(seconds=2**job.attempts)
                return False
            job.status = analysis.status = "FAILED" if error else "SUCCEEDED"
            analysis.result = result if not error else None
            if not error and suggestion.base_snapshot:
                suggestion.proposed_changes, limitations = propose(
                    analysis.input_text,
                    suggestion.base_snapshot,
                    analysis.meeting_date,
                    analysis.timezone,
                )
                analysis.result = {**result, "limitations": limitations}
            suggestion.status = "FAILED" if error else "DRAFT"
            suggestion.version += 1
            audit(
                session, analysis, None, "MEETING_FAILED" if error else "MEETING_GENERATED", job.id
            )
            return True
