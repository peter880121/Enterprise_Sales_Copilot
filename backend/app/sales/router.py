from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, Header, Query, Request, Response, UploadFile

from app.auth.dependencies import current_identity
from app.core.errors import AppError
from app.crm.models import AuditEvent
from app.crm.router import result, writer
from app.sales.files import MAX_BYTES, EvidenceFiles
from app.sales.models import Activity, CloseEvidence
from app.sales.schemas import (
    ActivityCreate,
    ActivityPatch,
    Archive,
    Assignment,
    Command,
    Completion,
    EvidenceCreate,
    OpportunityCreate,
    OpportunityPatch,
    OpportunityQuery,
    Review,
    Transition,
)
from app.sales.service import SalesService
from app.sales.views import (
    ActivityView,
    AuditView,
    Envelope,
    EvidenceView,
    OpportunityView,
    Paged,
    UploadedView,
)

router = APIRouter(tags=["M2 sales"])
Page = Annotated[int, Query(ge=1)]
PageSize = Annotated[int, Query(ge=1, le=100)]
Key = Annotated[
    str,
    Header(alias="Idempotency-Key", min_length=1, max_length=100, pattern=r"^[A-Za-z0-9_.:-]+$"),
]


def service(request):
    return SalesService(request.app.state.db)


def date_range(start, end):
    if any(value and value.tzinfo is None for value in (start, end)) or (
        start and end and start > end
    ):
        raise AppError(422, "DATE_RANGE_INVALID", "请提供含时区且顺序正确的时间范围。")


def collection(request, model, page, page_size, **filters):
    data, total = service(request).collection(model, page, page_size, **filters)
    return {**result(request, data), "page": {"number": page, "size": page_size, "total": total}}


@router.get("/opportunities", response_model=Paged[OpportunityView])
def opportunities(
    request: Request,
    query: Annotated[OpportunityQuery, Query()],
    _identity=Depends(current_identity),
):
    data, total = service(request).list_opportunities(query)
    return {
        **result(request, data),
        "page": {"number": query.page, "size": query.page_size, "total": total},
    }


@router.get("/pipeline/summary")
def pipeline(
    request: Request,
    query: Annotated[OpportunityQuery, Query()],
    _identity=Depends(current_identity),
):
    return result(request, service(request).pipeline(query))


@router.post("/opportunities", response_model=Envelope[OpportunityView], status_code=201)
def create_opportunity(body: OpportunityCreate, request: Request, identity=Depends(writer)):
    return result(
        request, service(request).create_opportunity(body, identity, request.state.request_id)
    )


@router.get("/opportunities/{entity_id}", response_model=Envelope[OpportunityView])
def opportunity(entity_id: UUID, request: Request, identity=Depends(current_identity)):
    return result(request, service(request).detail_opportunity(str(entity_id), identity))


@router.patch("/opportunities/{entity_id}", response_model=Envelope[OpportunityView])
def patch_opportunity(
    entity_id: UUID, body: OpportunityPatch, request: Request, identity=Depends(writer)
):
    return result(
        request,
        service(request).patch_opportunity(
            str(entity_id), body, identity, request.state.request_id
        ),
    )


def command(request, entity_id, action, body, key, identity):
    return result(
        request,
        service(request).command(
            str(entity_id), action, body, key, identity, request.state.request_id
        ),
    )


@router.post("/opportunities/{entity_id}/transitions", response_model=Envelope[OpportunityView])
def change_stage(
    entity_id: UUID,
    body: Transition,
    request: Request,
    idempotency_key: Key,
    identity=Depends(writer),
):
    return command(request, entity_id, "transitions", body, idempotency_key, identity)


@router.post("/opportunities/{entity_id}/reopen", response_model=Envelope[OpportunityView])
def reopen(
    entity_id: UUID, body: Command, request: Request, idempotency_key: Key, identity=Depends(writer)
):
    return command(request, entity_id, "reopen", body, idempotency_key, identity)


@router.post("/opportunities/{entity_id}/assign-owner", response_model=Envelope[OpportunityView])
def assign(
    entity_id: UUID,
    body: Assignment,
    request: Request,
    idempotency_key: Key,
    identity=Depends(writer),
):
    return command(request, entity_id, "assign-owner", body, idempotency_key, identity)


@router.post("/opportunities/{entity_id}/archive", response_model=Envelope[OpportunityView])
def archive(
    entity_id: UUID, body: Archive, request: Request, idempotency_key: Key, identity=Depends(writer)
):
    return command(request, entity_id, "archive", body, idempotency_key, identity)


@router.get("/opportunities/{entity_id}/history", response_model=Paged[AuditView])
def history(
    entity_id: UUID,
    request: Request,
    page: Page = 1,
    page_size: PageSize = 20,
    _identity=Depends(current_identity),
):
    return collection(
        request, AuditEvent, page, page_size, entity_id=str(entity_id), entity_type="OPPORTUNITY"
    )


@router.get("/opportunities/{entity_id}/activities", response_model=Paged[ActivityView])
def opportunity_activities(
    entity_id: UUID,
    request: Request,
    page: Page = 1,
    page_size: PageSize = 20,
    _identity=Depends(current_identity),
):
    return collection(request, Activity, page, page_size, opportunity_id=str(entity_id))


@router.get("/opportunities/{entity_id}/evidence", response_model=Paged[EvidenceView])
def evidence(
    entity_id: UUID,
    request: Request,
    page: Page = 1,
    page_size: PageSize = 20,
    _identity=Depends(current_identity),
):
    return collection(request, CloseEvidence, page, page_size, opportunity_id=str(entity_id))


@router.post(
    "/opportunities/{entity_id}/evidence", response_model=Envelope[EvidenceView], status_code=201
)
def submit_evidence(
    entity_id: UUID, body: EvidenceCreate, request: Request, identity=Depends(writer)
):
    return result(
        request,
        service(request).create_evidence(str(entity_id), body, identity, request.state.request_id),
    )


@router.post(
    "/opportunities/{entity_id}/evidence-files",
    response_model=Envelope[UploadedView],
    status_code=201,
)
def upload(
    entity_id: UUID,
    request: Request,
    request_token: Annotated[UUID, Form()],
    file: Annotated[UploadFile, File()],
    identity=Depends(writer),
):
    if file.content_type != "application/pdf":
        raise AppError(422, "FILE_TYPE_INVALID", "仅接受PDF。")
    payload = file.file.read(MAX_BYTES + 1)
    data = EvidenceFiles(request.app.state.db).upload(
        str(entity_id),
        payload,
        file.filename or "evidence.pdf",
        str(request_token),
        identity,
        request.app.state.storage,
    )
    return result(request, data)


@router.post("/evidence/{entity_id}/review", response_model=Envelope[EvidenceView])
def review(
    entity_id: UUID, body: Review, request: Request, idempotency_key: Key, identity=Depends(writer)
):
    return result(
        request,
        service(request).review(
            str(entity_id), body, idempotency_key, identity, request.state.request_id
        ),
    )


@router.get(
    "/evidence/{entity_id}/download",
    response_class=Response,
    responses={
        200: {"content": {"application/pdf": {"schema": {"type": "string", "format": "binary"}}}}
    },
)
def download(entity_id: UUID, request: Request, identity=Depends(current_identity)):
    payload = EvidenceFiles(request.app.state.db).download(
        str(entity_id), identity, request.app.state.storage
    )
    return Response(
        payload,
        media_type="application/pdf",
        headers={
            "Content-Disposition": 'attachment; filename="evidence.pdf"',
            "Cache-Control": "no-store",
        },
    )


@router.get("/activities", response_model=Paged[ActivityView])
def activities(
    request: Request,
    page: Page = 1,
    page_size: PageSize = 20,
    account_id: UUID | None = None,
    opportunity_id: UUID | None = None,
    assignee_id: UUID | None = None,
    status: Literal["RECORDED", "OPEN", "DONE", "CANCELLED"] | None = None,
    due_from: datetime | None = None,
    due_to: datetime | None = None,
    _identity=Depends(current_identity),
):
    date_range(due_from, due_to)
    return collection(
        request,
        Activity,
        page,
        page_size,
        account_id=str(account_id) if account_id else None,
        opportunity_id=str(opportunity_id) if opportunity_id else None,
        assignee_id=str(assignee_id) if assignee_id else None,
        status=status,
        due_from=due_from,
        due_to=due_to,
    )


@router.post("/activities", response_model=Envelope[ActivityView], status_code=201)
def create_activity(body: ActivityCreate, request: Request, identity=Depends(writer)):
    return result(request, service(request).activity(body, identity, request.state.request_id))


@router.patch("/activities/{entity_id}", response_model=Envelope[ActivityView])
def patch_activity(
    entity_id: UUID, body: ActivityPatch, request: Request, identity=Depends(writer)
):
    return result(
        request, service(request).activity(body, identity, request.state.request_id, str(entity_id))
    )


@router.post("/activities/{entity_id}/complete", response_model=Envelope[ActivityView])
def complete_activity(
    entity_id: UUID,
    body: Completion,
    request: Request,
    idempotency_key: Key,
    identity=Depends(writer),
):
    return result(
        request,
        service(request).complete(
            str(entity_id),
            body,
            idempotency_key,
            identity,
            request.state.request_id,
        ),
    )


@router.get("/audit-events", response_model=Paged[AuditView])
def audit_events(
    request: Request,
    page: Page = 1,
    page_size: PageSize = 20,
    entity_id: UUID | None = None,
    actor_id: UUID | None = None,
    entity_type: str | None = Query(default=None, max_length=64),
    action: str | None = Query(default=None, max_length=64),
    from_time: datetime | None = Query(default=None, alias="from"),
    to_time: datetime | None = Query(default=None, alias="to"),
    identity=Depends(current_identity),
):
    date_range(from_time, to_time)
    data, total = service(request).audits(
        identity,
        page,
        page_size,
        str(entity_id) if entity_id else None,
        str(actor_id) if actor_id else None,
        entity_type=entity_type,
        action=action,
        from_time=from_time,
        to_time=to_time,
    )
    return {**result(request, data), "page": {"number": page, "size": page_size, "total": total}}


@router.get("/audit-events/{event_id}", response_model=Envelope[AuditView])
def audit_detail(event_id: UUID, request: Request, identity=Depends(current_identity)):
    data, _ = service(request).audits(identity, 1, 1, event_id=str(event_id))
    if not data:
        raise AppError(404, "NOT_FOUND", "审计事件不存在或不属于业务审计范围。")
    return result(request, data[0])
