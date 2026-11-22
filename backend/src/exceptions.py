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


class ClientUpgradeRequired(Exception):
    """A /v2 client below the published ``min_supported_version_code`` (T6.3, spec §3.4)."""

    def __init__(self, min_supported_version_code: int):
        self.min_supported_version_code = min_supported_version_code


async def client_upgrade_required_handler(request: Request, exc: Exception):
    minimum = exc.min_supported_version_code if isinstance(exc, ClientUpgradeRequired) else 0
    return JSONResponse(
        status_code=426,
        content={
            "detail": "Client update required",
            "min_supported_version_code": minimum,
        },
    )
