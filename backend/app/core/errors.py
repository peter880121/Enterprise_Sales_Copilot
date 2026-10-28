from fastapi import Request
from fastapi.responses import JSONResponse


class AppError(Exception):
    def __init__(self, status: int, code: str, message: str, retryable: bool = False, details=None):
        self.status, self.code, self.message, self.retryable = status, code, message, retryable
        self.details = details


def error_response(
    request: Request, status: int, code: str, message: str, retryable=False, details=None
):
    return JSONResponse(
        status_code=status,
        content={
            "error": {
                "code": code,
                "message": message,
                "retryable": retryable,
                **({"details": details} if details is not None else {}),
            },
            "request_id": getattr(request.state, "request_id", "unknown"),
        },
    )
