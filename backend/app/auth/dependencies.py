from fastapi import Depends, Request

from app.auth.models import Role
from app.core.errors import AppError


def current_identity(request: Request):
    return request.app.state.auth.authenticate(
        request.cookies.get(request.app.state.settings.cookie_name)
    )


def require_roles(*roles: Role):
    def check(identity=Depends(current_identity)):
        if identity.user.role not in roles:
            raise AppError(403, "FORBIDDEN", "当前角色没有此操作权限。")
        return identity

    return check
