from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request

from app.auth.dependencies import current_identity
from app.crm.router import result, writer
from app.meetings.execution import Apply, ExecutionService
from app.meetings.schemas import MeetingCreate, Regenerate, Review
from app.meetings.service import MeetingService
from app.sales.router import Key

router = APIRouter(tags=["M3 meeting drafts and controlled execution (MOCK)"])


@router.post("/suggestions/{suggestion_id}/regenerate", status_code=202)
def regenerate(
    suggestion_id: UUID,
    body: Regenerate,
    request: Request,
    identity=Depends(writer),
):
    return result(
        request,
        service(request).regenerate(identity, str(suggestion_id), body, request.state.request_id),
    )


@router.post("/suggestions/{suggestion_id}/apply")
def apply(
    suggestion_id: UUID,
    body: Apply,
    request: Request,
    idempotency_key: Key,
    identity=Depends(writer),
):
    return result(
        request,
        ExecutionService(request.app.state.db, request.app.state.settings).apply(
            identity, str(suggestion_id), body, idempotency_key, request.state.request_id
        ),
    )


@router.get("/suggestions/{suggestion_id}/execution")
def execution(suggestion_id: UUID, request: Request, identity=Depends(current_identity)):
    return result(
        request,
        ExecutionService(request.app.state.db, request.app.state.settings).result(
            identity, str(suggestion_id)
        ),
    )


def service(request):
    return MeetingService(request.app.state.db, request.app.state.settings)


@router.post("/opportunities/{opportunity_id}/meeting-analyses", status_code=202)
def submit(opportunity_id: UUID, body: MeetingCreate, request: Request, identity=Depends(writer)):
    return result(
        request,
        service(request).submit(identity, str(opportunity_id), body, request.state.request_id),
    )


@router.get("/opportunities/{opportunity_id}/meeting-analyses")
def listing(
    opportunity_id: UUID,
    request: Request,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    identity=Depends(current_identity),
):
    rows, total = service(request).listing(identity, str(opportunity_id), page, page_size)
    return {**result(request, rows), "page": {"number": page, "size": page_size, "total": total}}


@router.get("/meeting-analyses/{analysis_id}")
def detail(analysis_id: UUID, request: Request, identity=Depends(current_identity)):
    return result(request, service(request).analysis(identity, str(analysis_id)))


@router.get("/jobs/{job_id}")
def job(job_id: UUID, request: Request, identity=Depends(current_identity)):
    return result(request, service(request).job(identity, str(job_id)))


@router.get("/suggestions/{suggestion_id}")
def suggestion(suggestion_id: UUID, request: Request, identity=Depends(current_identity)):
    return result(request, service(request).suggestion(identity, str(suggestion_id)))


@router.post("/suggestions/{suggestion_id}/reject")
def reject(
    suggestion_id: UUID,
    body: Review,
    request: Request,
    idempotency_key: Key,
    identity=Depends(writer),
):
    return result(
        request,
        service(request).review(
            identity, str(suggestion_id), "reject", body, idempotency_key, request.state.request_id
        ),
    )


@router.post("/suggestions/{suggestion_id}/abandon")
def abandon(
    suggestion_id: UUID,
    body: Review,
    request: Request,
    idempotency_key: Key,
    identity=Depends(writer),
):
    return result(
        request,
        service(request).review(
            identity, str(suggestion_id), "abandon", body, idempotency_key, request.state.request_id
        ),
    )
