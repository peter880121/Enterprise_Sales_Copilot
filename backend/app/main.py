import logging
import time
from contextlib import asynccontextmanager
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from sqlalchemy.exc import SQLAlchemyError
from starlette.exceptions import HTTPException

from app.ai import MockProvider
from app.auth.router import router as auth_router
from app.auth.service import AuthService
from app.core.config import get_settings
from app.core.errors import AppError, error_response
from app.core.logging import configure_logging
from app.db import Database
from app.storage import ObjectStorage


def create_app(settings=None, database=None, storage=None):
    settings = settings or get_settings()
    configure_logging()
    db = database or Database(settings)

    @asynccontextmanager
    async def lifespan(_app):
        try:
            yield
        finally:
            db.close()

    app = FastAPI(title="Enterprise Sales Copilot", version="0.1.0", lifespan=lifespan)
    app.state.settings, app.state.db = settings, db
    app.state.storage = storage or ObjectStorage(settings)
    app.state.auth = AuthService(db, settings)

    @app.middleware("http")
    async def operational_context(request, call_next):
        request.state.request_id = str(uuid4())
        started = time.monotonic()
        try:
            response = await call_next(request)
        except Exception:
            response = error_response(request, 500, "INTERNAL_ERROR", "请求处理失败。")
        response.headers["X-Request-ID"] = request.state.request_id
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        logging.getLogger("esc").info(
            "http_request",
            extra={
                "request_id": request.state.request_id,
                "method": request.method,
                "status": response.status_code,
                "duration_ms": round((time.monotonic() - started) * 1000),
            },
        )
        return response

    @app.exception_handler(AppError)
    async def app_error(request, exc):
        return error_response(request, exc.status, exc.code, exc.message, exc.retryable)

    @app.exception_handler(RequestValidationError)
    async def validation_error(request, _exc):
        # Do not reflect submitted passwords/tokens or Pydantic input payloads.
        return error_response(request, 422, "VALIDATION_ERROR", "请求字段无效。")

    @app.exception_handler(SQLAlchemyError)
    async def database_error(request, _exc):
        return error_response(request, 503, "DEPENDENCY_UNAVAILABLE", "数据库暂不可用。", True)

    @app.exception_handler(HTTPException)
    async def http_error(request, exc):
        return error_response(
            request,
            exc.status_code,
            "NOT_FOUND" if exc.status_code == 404 else "HTTP_ERROR",
            "请求不可用。",
        )

    app.include_router(auth_router, prefix="/api/v1")

    @app.get("/api/v1/health/live")
    def live():
        return {"status": "alive"}

    @app.get("/api/v1/health/ready")
    def ready():
        if not db.ready():
            raise AppError(503, "DEPENDENCY_UNAVAILABLE", "数据库或迁移未就绪。", True)
        return {"status": "ready"}

    from fastapi import Depends

    from app.auth.dependencies import current_identity

    @app.get("/api/v1/capabilities")
    def capabilities(request: Request, _identity=Depends(current_identity)):
        crm = db.ready()
        store = app.state.storage.ready()
        return {
            "data": {
                "crm": {
                    "available": crm,
                    "reason": "foundation_only" if crm else "database_unavailable",
                },
                "storage": {"available": store, "reason": None if store else "storage_unavailable"},
                "ai": MockProvider().status()
                if settings.ai_mode == "mock"
                else {
                    "mode": "REAL",
                    "available": False,
                    "reason": "real_provider_not_implemented_m1",
                },
                "knowledge": {
                    "enabled": settings.knowledge_enabled,
                    "available": False,
                    "reason": "not_implemented_m1",
                },
                "worker": {"available": False, "reason": "skeleton_only_no_business_handlers"},
            },
            "request_id": request.state.request_id,
        }

    return app
