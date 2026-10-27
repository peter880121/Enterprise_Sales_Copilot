from datetime import UTC

from fastapi import APIRouter, Depends, Request, Response

from app.auth.dependencies import current_identity, require_roles
from app.auth.models import Role
from app.auth.schemas import LoginRequest

router = APIRouter()


def envelope(request, data):
    return {"data": data, "request_id": request.state.request_id}


@router.post("/auth/login")
def login(body: LoginRequest, request: Request, response: Response):
    auth, settings = request.app.state.auth, request.app.state.settings
    auth.origin(request.headers.get("origin"))
    identity, token = auth.login(
        body,
        request.client.host if request.client else "unknown",
        request.cookies.get(settings.cookie_name),
    )
    response.set_cookie(
        settings.cookie_name,
        token,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
        path="/api",
        max_age=settings.session_absolute_hours * 3600,
    )
    return envelope(
        request,
        {
            "user": identity.user,
            "csrf_token": identity.csrf,
            "absolute_expires_at": identity.absolute_expires_at.replace(tzinfo=UTC),
        },
    )


@router.get("/auth/me")
def me(request: Request, identity=Depends(current_identity)):
    return envelope(
        request,
        {
            "user": identity.user,
            "csrf_token": identity.csrf,
            "expires_at": identity.expires_at.replace(tzinfo=UTC),
            "capabilities": {"manage_users": identity.user.role == Role.ADMIN},
        },
    )


@router.post("/auth/logout", status_code=204)
def logout(request: Request, identity=Depends(current_identity)):
    request.app.state.auth.origin(request.headers.get("origin"))
    request.app.state.auth.check_csrf(identity, request.headers.get("x-csrf-token"))
    request.app.state.auth.logout(identity)
    response = Response(status_code=204)
    response.delete_cookie(
        request.app.state.settings.cookie_name,
        path="/api",
        secure=request.app.state.settings.cookie_secure,
        httponly=True,
        samesite="lax",
    )
    return response


@router.get("/admin/access-check")
def admin_check(request: Request, identity=Depends(require_roles(Role.ADMIN))):
    # Authorization probe only. User management is deliberately deferred.
    return envelope(request, {"authorized": True, "role": identity.user.role})
