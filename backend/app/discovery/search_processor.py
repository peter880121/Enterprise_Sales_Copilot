"""At-most-one dispatch per accepted search; unknown outcomes are never replayed."""

from datetime import timedelta
from uuid import uuid4

from sqlalchemy import and_, or_, select

from app.auth.models import User
from app.auth.service import now
from app.core.errors import AppError
from app.crm.service import SELLERS
from app.discovery.models import SearchRun
from app.discovery.search_service import SearchService
from app.discovery.service import audit
from app.discovery.tavily import TavilySearch
from app.users.service import UserService


class SearchProcessor:
    def __init__(self, db, settings, *, provider_factory=TavilySearch):
        self.db, self.settings, self.provider_factory = db, settings, provider_factory

    def claim(self):
        with self.db.transaction() as s:
            row = s.scalar(
                select(SearchRun)
                .where(
                    or_(
                        SearchRun.status == "QUEUED",
                        and_(SearchRun.status == "RUNNING", SearchRun.lease_until <= now()),
                    )
                )
                .order_by(SearchRun.created_at, SearchRun.id)
                .with_for_update(skip_locked=True)
                .limit(1)
            )
            if row is None:
                return None
            if row.status == "RUNNING":
                row.status = "OUTCOME_UNKNOWN" if row.provider_attempted else "FAILED"
                row.error_code = (
                    "SEARCH_OUTCOME_UNKNOWN"
                    if row.provider_attempted
                    else "SEARCH_DISPATCH_EXPIRED"
                )
                row.completed_at = now()
                row.lease_token = row.lease_until = None
                row.version += 1
                row.updated_at = now()
                audit(s, row, None, "SEARCH_EXPIRED", row.id)
                return {"expired": True}
            row.status = "RUNNING"
            row.lease_token = str(uuid4())
            row.lease_until = now() + timedelta(seconds=180)
            row.started_at = now()
            row.updated_at = now()
            row.version += 1
            return {
                "id": row.id,
                "token": row.lease_token,
                "creator": row.created_by,
                "profile_id": row.profile_id,
            }

    def permitted(self, session, claim):
        actor = session.get(User, claim["creator"], with_for_update=True)
        if actor is None or actor.role not in SELLERS:
            raise AppError(403, "SOURCE_ACCESS_REVOKED", "Search access revoked")
        UserService(self.db, self.settings).active(actor)
        profile = SearchService(self.db, self.settings).access(
            session, actor, claim["profile_id"], write=True
        )
        return profile

    @staticmethod
    def valid(row, claim):
        return (
            row.status == "RUNNING"
            and row.lease_token == claim["token"]
            and row.lease_until > now()
        )

    def dispatch(self, claim):
        with self.db.transaction() as s:
            profile = self.permitted(s, claim)
            row = s.get(SearchRun, claim["id"], with_for_update=True)
            if not self.valid(row, claim) or row.provider_attempted:
                return None
            if not self.settings.discovery_search_enabled:
                raise AppError(503, "SEARCH_NOT_ENABLED", "Search disabled")
            if profile.version != row.profile_version:
                raise AppError(409, "SEARCH_PROFILE_CHANGED", "Profile changed before dispatch")
            # Durable fence before crossing the network. A crash after this never replays the call.
            row.provider_attempted = True
            row.version += 1
            row.updated_at = now()
            audit(s, row, None, "SEARCH_DISPATCHED", row.id)
            return row.endpoint, row.public_query

    def publish(self, claim, result=None, error=None):
        with self.db.transaction() as s:
            try:
                profile = self.permitted(s, claim)
            except AppError:
                profile = None
                error = "SOURCE_ACCESS_REVOKED"
            row = s.get(SearchRun, claim["id"], with_for_update=True)
            if not self.valid(row, claim):
                return False
            if profile is not None and profile.version != row.profile_version:
                error = "SEARCH_PROFILE_CHANGED"
            row.status = (
                "OUTCOME_UNKNOWN"
                if error == "SEARCH_OUTCOME_UNKNOWN"
                else "FAILED"
                if error
                else "SUCCEEDED"
            )
            row.result = None if error else result
            row.error_code = error
            row.completed_at = now()
            row.lease_token = row.lease_until = None
            row.version += 1
            row.updated_at = now()
            audit(s, row, None, "SEARCH_COMPLETED" if not error else "SEARCH_FAILED", row.id)
            return True

    def process_one(self):
        claim = self.claim()
        if claim is None:
            return False
        if claim.get("expired"):
            return True
        result, error = None, None
        try:
            payload = self.dispatch(claim)
            if payload is None:
                return True
            endpoint, query = payload
            # No transaction held across any external request.
            result = self.provider_factory(endpoint, self.settings.tavily_api_key).search(query)
        except AppError as exc:
            error = exc.code
        except Exception:
            error = "SEARCH_OUTCOME_UNKNOWN"
        self.publish(claim, result, error)
        return True
