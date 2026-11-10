"""Public search intent/receipts; quota reservations serialize in the same transaction."""

import hashlib
import hmac
import time
from datetime import timedelta
from uuid import uuid4

from sqlalchemy import func, select

from app.auth.service import now
from app.core.errors import AppError
from app.discovery.models import SearchGuard, SearchRun
from app.discovery.service import DiscoveryService, audit, digest
from app.discovery.tavily import PARAMETERS, TavilySearch
from app.sales.service import encode


def preview_signature(settings, actor_id, profile_id, version, query, timestamp):
    payload = digest(
        {
            "purpose": "TAVILY_SEARCH_V1",
            "actor": actor_id,
            "profile": profile_id,
            "version": version,
            "query": query,
            "endpoint": settings.tavily_base_url.rstrip("/"),
            "parameters": PARAMETERS,
            "timestamp": timestamp,
        }
    )
    return hmac.new(
        settings.csrf_signing_key.get_secret_value().encode(), payload.encode(), hashlib.sha256
    ).hexdigest()


def verify_preview(settings, actor_id, profile_id, body, *, clock=None):
    timestamp, signature = body.preview_token.split(":", 1)
    timestamp = int(timestamp)
    current = int(time.time()) if clock is None else clock
    expected = preview_signature(
        settings, actor_id, profile_id, body.expected_profile_version, body.public_query, timestamp
    )
    if not current - 600 <= timestamp <= current + 10 or not hmac.compare_digest(
        signature, expected
    ):
        raise AppError(409, "SEARCH_PREVIEW_STALE", "公开查询预览已失效，请重新核对和确认。")


class SearchService(DiscoveryService):
    def configured(self):
        try:
            TavilySearch(self.settings.tavily_base_url, self.settings.tavily_api_key)
            return True
        except AppError:
            return False

    def quota(self, session, actor_id):
        start = now().replace(hour=0, minute=0, second=0, microsecond=0)
        window = [SearchRun.created_at >= start, SearchRun.created_at < start + timedelta(days=1)]
        total = session.scalar(select(func.count()).select_from(SearchRun).where(*window))
        own = session.scalar(
            select(func.count())
            .select_from(SearchRun)
            .where(*window, SearchRun.created_by == actor_id)
        )
        return {
            "timezone": "UTC",
            "user_used": own,
            "user_limit": self.settings.discovery_search_user_daily_limit,
            "global_used": total,
            "global_limit": self.settings.discovery_search_global_daily_limit,
        }

    def preview(self, identity, profile_id, body):
        data = super().search_preview(identity, profile_id, body)
        with self.db.transaction() as s:
            actor = self.actor(s, identity)
            allowed = True
            try:
                self.access(s, actor, profile_id, write=True)
            except AppError as exc:
                if exc.status != 403:
                    raise
                allowed = False
            quota = self.quota(s, actor.id)
            configured = self.configured()
            available = (
                allowed
                and configured
                and self.settings.discovery_search_enabled
                and quota["user_used"] < quota["user_limit"]
                and quota["global_used"] < quota["global_limit"]
            )
            timestamp = int(time.time())
            signature = preview_signature(
                self.settings,
                actor.id,
                profile_id,
                body.expected_profile_version,
                body.public_query,
                timestamp,
            )
            token = f"{timestamp}:{signature}" if available else None
            return data | {
                "configured": configured,
                "web_execution_available": available,
                "preview_token": token,
                "quota": quota,
                "notice": (
                    "确认后将公开查询发送给Tavily；一次最多5条，可能产生费用。"
                    "失败或结果未知不自动重试；额度按UTC日统计受理次数，不自动退回。"
                )
                if available
                else "搜索未启用、无写权限、配置缺失或当日额度不足；本次只生成预览。",
            }

    def view(self, row, *, detail=True):
        fields = (
            "id",
            "profile_id",
            "created_by",
            "profile_version",
            "public_query",
            "status",
            "provider_attempted",
            "error_code",
            "started_at",
            "completed_at",
            "version",
            "created_at",
            "updated_at",
        )
        data = encode({key: getattr(row, key) for key in fields})
        data.update(provider="TAVILY", mode="REAL", may_have_been_charged=row.provider_attempted)
        if detail:
            data["result"] = row.result if row.status == "SUCCEEDED" else None
        return data

    def accept(self, identity, profile_id, body, request_id):
        intent_hash = bytes.fromhex(
            digest(
                {
                    "profile_id": profile_id,
                    "version": body.expected_profile_version,
                    "query": body.public_query,
                }
            )
        )
        with self.db.transaction() as s:
            actor = self.actor(s, identity, write=True)
            profile = self.access(s, actor, profile_id, write=True)
            # Reauthenticate every retry, but do not require an unexpired preview to read a receipt.
            prior = s.scalar(
                select(SearchRun).where(
                    SearchRun.created_by == actor.id,
                    SearchRun.request_token == str(body.request_token),
                )
            )
            if prior:
                if prior.request_hash != intent_hash:
                    raise AppError(409, "IDEMPOTENCY_KEY_REUSED", "原请求标识不能用于其他查询。")
                return self.view(prior)
            if not self.settings.discovery_search_enabled or not self.configured():
                raise AppError(503, "SEARCH_NOT_ENABLED", "网页搜索尚未启用或配置不可用。")
            if profile.version != body.expected_profile_version:
                raise AppError(409, "VERSION_CONFLICT", "画像已变化，请重新核对公开查询。")
            verify_preview(self.settings, actor.id, profile.id, body)
            guard = s.get(SearchGuard, 1, with_for_update=True)
            if guard is None:
                raise AppError(503, "SEARCH_NOT_READY", "搜索额度门禁尚未初始化。")
            quota = self.quota(s, actor.id)
            if (
                quota["user_used"] >= quota["user_limit"]
                or quota["global_used"] >= quota["global_limit"]
            ):
                raise AppError(429, "SEARCH_DAILY_LIMIT", "当日搜索受理额度已用完。")
            guard.version += 1
            row = SearchRun(
                id=str(uuid4()),
                profile_id=profile.id,
                created_by=actor.id,
                request_token=str(body.request_token),
                request_hash=intent_hash,
                profile_version=profile.version,
                public_query=body.public_query,
                endpoint=self.settings.tavily_base_url.rstrip("/"),
                status="QUEUED",
                provider_attempted=False,
                version=1,
                created_at=now(),
                updated_at=now(),
            )
            s.add(row)
            s.flush()
            audit(s, row, actor.id, "SEARCH_ACCEPTED", request_id)
            return self.view(row)

    def history(self, identity, profile_id, page=1):
        with self.db.transaction() as s:
            actor = self.actor(s, identity)
            self.access(s, actor, profile_id)
            query = select(SearchRun).where(SearchRun.profile_id == profile_id)
            total = s.scalar(select(func.count()).select_from(query.subquery()))
            rows = s.scalars(
                query.order_by(SearchRun.created_at.desc(), SearchRun.id)
                .offset((page - 1) * 20)
                .limit(20)
            )
            return [self.view(row, detail=False) for row in rows], total

    def detail(self, identity, run_id):
        with self.db.transaction() as s:
            actor = self.actor(s, identity)
            row = self.required(s, SearchRun, run_id)
            self.access(s, actor, row.profile_id)
            return self.view(row)
