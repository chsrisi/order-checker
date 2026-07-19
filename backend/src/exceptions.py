import logging

from fastapi import Request
from fastapi.responses import JSONResponse

logger = logging.getLogger("backend.exceptions")


class DomainException(Exception):
    def __init__(self, status_code: int, detail: str):
        self.status_code = status_code
        self.detail = detail


async def domain_exception_handler(request: Request, exc: Exception):
    status_code = exc.status_code if isinstance(exc, DomainException) else 500
    detail = exc.detail if isinstance(exc, DomainException) else "Internal server error"
    logger.warning(
        "domain_error",
        extra={
            "event": "domain.error",
            "http_method": request.method,
            "http_path": request.url.path,
            "http_status": status_code,
            "detail": detail,
        },
    )
    return JSONResponse(
        status_code=status_code,
        content={"detail": detail},
    )
