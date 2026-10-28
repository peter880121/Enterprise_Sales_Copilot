from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, Response

from app.auth.dependencies import require_roles
from app.auth.models import Role
from app.auth.schemas import UserPublic
from app.core.errors import AppError
from app.crm.router import result, writer
from app.sales.router import Key
from app.sales.views import Envelope, Paged
from app.users.schemas import (
    Approval,
    PasswordChange,
    PasswordReset,
    ProfilePatch,
    Registration,
    UserAuditView,
    UserCommand,
    UserCreate,
    UserPatch,
    UserQuery,
)
from app.users.service import UserService

router = APIRouter(tags=["M2.1 users"])


def service(request):
    return UserService(request.app.state.db, request.app.state.settings)


def admin_writer(identity=Depends(writer)):
    if identity.user.role != Role.ADMIN:
        raise AppError(403, "FORBIDDEN", "仅管理员可管理用户。")
    return identity


@router.post("/auth/register", status_code=202)
def register(body: Registration, request: Request):
    request.app.state.auth.origin(request.headers.get("origin"))
    service(request).register(
        body, request.client.host if request.client else "unknown", request.state.request_id
    )
    return result(
        request, {"message": "若注册资料可用，申请已提交。请等待管理员批准并分配角色后登录。"}
    )


@router.get("/users/roles")
def roles(request: Request, _identity=Depends(require_roles(Role.ADMIN))):
    return result(
        request,
        [
            {"role": "ADMIN", "description": "管理用户；全企业 CRM 读写；业务及用户安全审计"},
            {"role": "SALES_MANAGER", "description": "全企业 CRM 读写；独立核验证据；仅业务审计"},
            {
                "role": "SALES_REP",
                "description": "全企业 CRM 可读；仅本人负责对象可写；不能核验证据",
            },
            {"role": "READ_ONLY", "description": "全企业 CRM 只读；不能写入或核验证据"},
        ],
    )


@router.get("/users", response_model=Paged[UserPublic])
def users(
    request: Request,
    query: Annotated[UserQuery, Query()],
    identity=Depends(require_roles(Role.ADMIN)),
):
    rows, total = service(request).listing(identity, query)
    return {
        **result(request, rows),
        "page": {"number": query.page, "size": query.page_size, "total": total},
    }


@router.post("/users", response_model=Envelope[UserPublic], status_code=201)
def create(body: UserCreate, request: Request, identity=Depends(admin_writer)):
    return result(request, service(request).create(identity, body, request.state.request_id))


@router.get("/users/{user_id}", response_model=Envelope[UserPublic])
def detail(user_id: UUID, request: Request, identity=Depends(require_roles(Role.ADMIN))):
    return result(request, service(request).detail(identity, str(user_id)))


@router.get("/users/{user_id}/history", response_model=Paged[UserAuditView])
def history(
    user_id: UUID,
    request: Request,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    identity=Depends(require_roles(Role.ADMIN)),
):
    rows, total = service(request).history(identity, str(user_id), page, page_size)
    return {**result(request, rows), "page": {"number": page, "size": page_size, "total": total}}


@router.patch("/users/{user_id}", response_model=Envelope[UserPublic])
def patch(user_id: UUID, body: UserPatch, request: Request, identity=Depends(admin_writer)):
    return result(
        request,
        service(request).mutate(identity, str(user_id), "update", body, request.state.request_id),
    )


@router.delete("/users/{user_id}", response_model=Envelope[UserPublic])
def delete(user_id: UUID, body: UserCommand, request: Request, identity=Depends(admin_writer)):
    return result(
        request,
        service(request).mutate(identity, str(user_id), "delete", body, request.state.request_id),
    )


@router.post("/users/{user_id}/restore", response_model=Envelope[UserPublic])
def restore(user_id: UUID, body: UserCommand, request: Request, identity=Depends(admin_writer)):
    return result(
        request,
        service(request).mutate(identity, str(user_id), "restore", body, request.state.request_id),
    )


@router.post("/users/{user_id}/approve", response_model=Envelope[UserPublic])
def approve(user_id: UUID, body: Approval, request: Request, identity=Depends(admin_writer)):
    return result(
        request,
        service(request).mutate(identity, str(user_id), "approve", body, request.state.request_id),
    )


@router.post("/users/{user_id}/reset-password", response_model=Envelope[UserPublic])
def reset(
    user_id: UUID,
    body: PasswordReset,
    request: Request,
    idempotency_key: Key,
    identity=Depends(admin_writer),
):
    return result(
        request,
        service(request).mutate(
            identity,
            str(user_id),
            "reset-password",
            body,
            request.state.request_id,
            idempotency_key,
        ),
    )


def clear_cookie(response, request):
    response.delete_cookie(
        request.app.state.settings.cookie_name,
        path="/api",
        httponly=True,
        secure=request.app.state.settings.cookie_secure,
        samesite="lax",
    )


@router.post("/auth/change-password", status_code=204)
def password(body: PasswordChange, request: Request, identity=Depends(writer)):
    service(request).profile(identity, body, request.state.request_id, password_change=True)
    response = Response(status_code=204)
    clear_cookie(response, request)
    return response


@router.patch("/auth/profile", response_model=Envelope[UserPublic])
def profile(body: ProfilePatch, request: Request, response: Response, identity=Depends(writer)):
    user = service(request).profile(identity, body, request.state.request_id)
    clear_cookie(response, request)
    return result(request, user)
