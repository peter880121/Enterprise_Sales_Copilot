from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, Query, Request, UploadFile
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from app.auth.dependencies import current_identity
from app.core.errors import AppError
from app.crm.router import result, writer
from app.discovery.schemas import (
    AccountConfirm,
    AccountPreview,
    MaterialCreate,
    ProfileCreate,
    ProfilePatch,
    PublicSearchPreview,
    Review,
    RunCreate,
    SearchAccept,
)
from app.discovery.search_service import SearchService
from app.discovery.service import DiscoveryService
from app.sales.router import Key

router = APIRouter(prefix="/discovery", tags=["Discovery D1 / local rules only"])


def service(request):
    return DiscoveryService(request.app.state.db, request.app.state.settings)


def paged(request, rows, total, page):
    return {**result(request, rows), "page": {"number": page, "size": 20, "total": total}}


@router.get("/reviewers")
def reviewers(
    request: Request,
    q: str = Query("", max_length=100),
    page: int = Query(1, ge=1, le=100000),
    identity=Depends(current_identity),
):
    rows, total = service(request).reviewers(identity, q, page)
    return paged(request, rows, total, page)


@router.get("/profiles")
def profiles(
    request: Request, page: int = Query(1, ge=1, le=100000), identity=Depends(current_identity)
):
    rows, total = service(request).profiles(identity, page)
    return paged(request, rows, total, page)


@router.get("/profiles/{profile_id}")
def profile(profile_id: UUID, request: Request, identity=Depends(current_identity)):
    return result(request, service(request).profile(identity, str(profile_id)))


@router.post("/profiles", status_code=201)
def create_profile(body: ProfileCreate, request: Request, identity=Depends(writer)):
    return result(request, service(request).save_profile(identity, body, request.state.request_id))


@router.post("/profiles/{profile_id}/search-preview")
def search_preview(
    profile_id: UUID,
    body: PublicSearchPreview,
    request: Request,
    identity=Depends(writer),
):
    return result(
        request,
        SearchService(request.app.state.db, request.app.state.settings).preview(
            identity, str(profile_id), body
        ),
    )


@router.post("/profiles/{profile_id}/search-runs", status_code=202)
def accept_search(profile_id: UUID, body: SearchAccept, request: Request, identity=Depends(writer)):
    return result(
        request,
        SearchService(request.app.state.db, request.app.state.settings).accept(
            identity, str(profile_id), body, request.state.request_id
        ),
    )


@router.get("/profiles/{profile_id}/search-runs")
def search_history(
    profile_id: UUID,
    request: Request,
    page: int = Query(1, ge=1, le=100000),
    identity=Depends(current_identity),
):
    rows, total = SearchService(request.app.state.db, request.app.state.settings).history(
        identity, str(profile_id), page
    )
    return paged(request, rows, total, page)


@router.get("/search-runs/{run_id}")
def search_detail(run_id: UUID, request: Request, identity=Depends(current_identity)):
    return result(
        request,
        SearchService(request.app.state.db, request.app.state.settings).detail(
            identity, str(run_id)
        ),
    )


@router.patch("/profiles/{profile_id}")
def patch_profile(profile_id: UUID, body: ProfilePatch, request: Request, identity=Depends(writer)):
    return result(
        request,
        service(request).save_profile(identity, body, request.state.request_id, str(profile_id)),
    )


@router.get("/profiles/{profile_id}/materials")
def materials(
    profile_id: UUID,
    request: Request,
    page: int = Query(1, ge=1, le=100000),
    identity=Depends(current_identity),
):
    rows, total = service(request).materials(identity, str(profile_id), page)
    return paged(request, rows, total, page)


@router.post("/profiles/{profile_id}/materials", status_code=201)
def paste_material(
    profile_id: UUID, body: MaterialCreate, request: Request, identity=Depends(writer)
):
    return result(
        request,
        service(request).add_material(identity, str(profile_id), body, request.state.request_id),
    )


@router.post("/profiles/{profile_id}/material-files", status_code=201)
def upload_material(
    profile_id: UUID,
    request: Request,
    purpose: Annotated[str, Form()],
    confirm_team_visibility: Annotated[bool, Form()],
    confirm_no_patient_data: Annotated[bool, Form()],
    file: Annotated[UploadFile, File()],
    identity=Depends(writer),
):
    name = (file.filename or "").replace("\\", "/").rsplit("/", 1)[-1]
    if not name.lower().endswith((".txt", ".md")) or file.content_type not in {
        "text/plain",
        "text/markdown",
        "application/octet-stream",
    }:
        raise AppError(
            422, "FILE_TYPE_UNSUPPORTED", "D1仅支持UTF-8 TXT/Markdown；PDF/知识库待接入。"
        )
    payload = file.file.read(65537)
    if len(payload) > 65536:
        raise AppError(413, "MATERIAL_TOO_LARGE", "D1文本资料上限64 KiB。")
    try:
        content = payload.decode("utf-8-sig")
    except UnicodeError:
        raise AppError(422, "INVALID_TEXT_ENCODING", "资料必须使用UTF-8编码。") from None
    if "\x00" in content:
        raise AppError(422, "INVALID_TEXT_ENCODING", "不接受二进制内容。")
    try:
        body = MaterialCreate(
            title=name,
            content=content,
            purpose=purpose,
            confirm_team_visibility=confirm_team_visibility,
            confirm_no_patient_data=confirm_no_patient_data,
        )
    except ValidationError:
        raise AppError(422, "INVALID_MATERIAL", "请检查文本内容、文件名和资料用途。") from None
    return result(
        request,
        service(request).add_material(
            identity, str(profile_id), body, request.state.request_id, payload
        ),
    )


@router.get("/materials/{material_id}")
def material(material_id: UUID, request: Request, identity=Depends(current_identity)):
    return result(request, service(request).material(identity, str(material_id)))


@router.post("/profiles/{profile_id}/runs", status_code=202)
def start(profile_id: UUID, body: RunCreate, request: Request, identity=Depends(writer)):
    return result(
        request, service(request).start(identity, str(profile_id), body, request.state.request_id)
    )


@router.get("/runs/{entity_id}")
def run(entity_id: UUID, request: Request, identity=Depends(current_identity)):
    return result(request, service(request).run(identity, str(entity_id)))


@router.get("/leads")
def leads(
    request: Request,
    page: int = Query(1, ge=1, le=100000),
    q: str = Query("", max_length=100),
    status: str | None = Query(None, pattern="^(NEW|IN_REVIEW|QUALIFIED|DISQUALIFIED)$"),
    identity=Depends(current_identity),
):
    rows, total = service(request).leads(identity, page, q, status)
    return paged(request, rows, total, page)


@router.get("/leads/{entity_id}")
def lead(entity_id: UUID, request: Request, identity=Depends(current_identity)):
    return result(request, service(request).lead(identity, str(entity_id)))


@router.patch("/leads/{entity_id}")
def review(entity_id: UUID, body: Review, request: Request, identity=Depends(writer)):
    return result(
        request, service(request).review(identity, str(entity_id), body, request.state.request_id)
    )


@router.post("/leads/{entity_id}/account-preview")
def preview(entity_id: UUID, body: AccountPreview, request: Request, identity=Depends(writer)):
    return result(request, service(request).account_preview(identity, str(entity_id), body))


@router.post("/leads/{entity_id}/link-account")
def link(
    entity_id: UUID,
    body: AccountConfirm,
    request: Request,
    idempotency_key: Key,
    identity=Depends(writer),
):
    return result(
        request,
        service(request).link_account(
            identity, str(entity_id), body, idempotency_key, request.state.request_id
        ),
    )


class DiscoveryBodyLimit:
    """Bound discovery JSON/multipart bytes before parsing or disk spooling."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or not scope.get("path", "").startswith("/api/v1/discovery/"):
            return await self.app(scope, receive, send)
        messages, total = [], 0
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            total += len(message.get("body", b""))
            if total > 131072:
                return await JSONResponse(
                    {
                        "error": {
                            "code": "REQUEST_TOO_LARGE",
                            "message": "发现模块请求超过128 KiB。",
                            "retryable": False,
                        },
                        "request_id": scope.get("state", {}).get("request_id", "unavailable"),
                    },
                    status_code=413,
                )(scope, receive, send)
            messages.append(message)
            if not message.get("more_body", False):
                break
        index = 0

        async def replay():
            nonlocal index
            if index < len(messages):
                item = messages[index]
                index += 1
                return item
            return await receive()

        return await self.app(scope, replay, send)
